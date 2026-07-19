"""Tests for the self-healing agent's safety guards: the AST-based patch
validator, the backup-before-write apply step, and the NotHealable fast
path that skips a doomed LLM call for exceptions outside its scope. This
is the highest-stakes code in the project -- it rewrites a source file on
disk -- so every test here monkeypatches healer.TRANSFORMS_PATH to a
tmp_path file and never touches the real app/cleaning/transforms.py."""

import pytest

from app.agent import healer
from app.agent.healer import NotHealable, PatchRejected, _originates_in_transforms, _validate_patch, apply_patch

VALID_PATCH = '''def normalize_phone(value, default_region="US"):
    return None


def normalize_email(value):
    return None


def parse_datetime_utc(value):
    return None


def normalize_consent(value):
    return False


def split_full_name(value):
    return None, None
'''


def test_validate_patch_accepts_syntactically_valid_patch_with_all_required_functions():
    _validate_patch(VALID_PATCH)  # must not raise


def test_validate_patch_rejects_invalid_python_syntax():
    with pytest.raises(PatchRejected, match="not valid Python"):
        _validate_patch("def broken(:\n    pass")


def test_validate_patch_rejects_patch_that_drops_one_required_function():
    missing_split_full_name = VALID_PATCH.replace(
        'def split_full_name(value):\n    return None, None\n', ""
    )
    with pytest.raises(PatchRejected, match="split_full_name"):
        _validate_patch(missing_split_full_name)


def test_validate_patch_rejects_patch_that_drops_every_required_function():
    with pytest.raises(PatchRejected, match="dropped required function"):
        _validate_patch("x = 1\n")


def test_apply_patch_backs_up_original_before_overwriting_and_backup_enables_rollback(tmp_path, monkeypatch):
    fake_transforms = tmp_path / "transforms.py"
    original_content = "def normalize_phone(value, default_region='US'):\n    return value\n"
    fake_transforms.write_text(original_content)
    monkeypatch.setattr(healer, "TRANSFORMS_PATH", fake_transforms)

    backup_path = apply_patch(VALID_PATCH)

    assert backup_path.read_text() == original_content
    assert fake_transforms.read_text() == VALID_PATCH

    # Rollback: restoring from the backup must exactly reconstruct the
    # pre-patch file -- this is the guarantee a real self-heal failure
    # (or a bad patch discovered after the fact) depends on.
    fake_transforms.write_text(backup_path.read_text())
    assert fake_transforms.read_text() == original_content


def test_apply_patch_writes_nothing_when_the_patch_is_invalid(tmp_path, monkeypatch):
    fake_transforms = tmp_path / "transforms.py"
    original_content = "def normalize_phone(value, default_region='US'):\n    return value\n"
    fake_transforms.write_text(original_content)
    monkeypatch.setattr(healer, "TRANSFORMS_PATH", fake_transforms)

    with pytest.raises(PatchRejected):
        apply_patch("def broken(:\n")

    # Validation runs before any write -- an invalid patch must leave the
    # real file (and no stray backup) untouched.
    assert fake_transforms.read_text() == original_content
    assert not fake_transforms.with_suffix(".py.bak").exists()


def test_originates_in_transforms_true_when_traceback_frame_matches_transforms_path(tmp_path, monkeypatch):
    fake_path = tmp_path / "transforms.py"
    monkeypatch.setattr(healer, "TRANSFORMS_PATH", fake_path)

    code = compile("raise TypeError('bad')\n", str(fake_path), "exec")
    try:
        exec(code, {})
    except TypeError as exc:
        assert _originates_in_transforms(exc) is True
    else:
        pytest.fail("expected the compiled snippet to raise TypeError")


def test_originates_in_transforms_false_for_an_unrelated_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(healer, "TRANSFORMS_PATH", tmp_path / "transforms.py")
    try:
        raise ValueError("this exception has nothing to do with transforms.py")
    except ValueError as exc:
        assert _originates_in_transforms(exc) is False


def test_heal_raises_not_healable_and_never_calls_the_llm_for_an_unrelated_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(healer, "TRANSFORMS_PATH", tmp_path / "transforms.py")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("propose_patch must not be called when the exception is out of scope")

    monkeypatch.setattr(healer, "propose_patch", _fail_if_called)

    try:
        raise ValueError("came from somewhere else entirely, not transforms.py")
    except ValueError as exc:
        with pytest.raises(NotHealable):
            healer.heal(exc)


def test_heal_success_path_writes_the_llm_proposed_patch(tmp_path, monkeypatch):
    fake_transforms = tmp_path / "transforms.py"
    fake_transforms.write_text("def normalize_phone(value, default_region='US'):\n    return value\n")
    monkeypatch.setattr(healer, "TRANSFORMS_PATH", fake_transforms)
    monkeypatch.setattr(healer, "generate", lambda *a, **k: VALID_PATCH)

    code = compile("raise TypeError('boom')\n", str(fake_transforms), "exec")
    try:
        exec(code, {})
    except TypeError as exc:
        error, new_source = healer.heal(exc)

    assert error.exception_type == "TypeError"
    # _strip_code_fences() (correctly) strips surrounding whitespace from
    # the raw LLM response, so compare content rather than exact bytes.
    assert new_source.strip() == VALID_PATCH.strip()
    assert fake_transforms.read_text().strip() == VALID_PATCH.strip()
