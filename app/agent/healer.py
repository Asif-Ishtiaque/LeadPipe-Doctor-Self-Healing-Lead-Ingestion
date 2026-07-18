"""The self-healing half of the agent loop: given a traceback raised by the
cleaning engine, ask the local LLM to rewrite app/cleaning/transforms.py so
the failure stops happening, then write the patch to disk (with a backup)
so the next pipeline retry picks it up.

This can only work while Ollama is reachable -- rewriting code isn't
something the heuristic fallback used elsewhere in this project can do, so
if the LLM is unavailable we surface that clearly and let the caller route
straight to human review instead of retrying blind.
"""

import ast
import traceback
from dataclasses import dataclass
from pathlib import Path

from app.mapping.llm_client import OllamaUnavailable, generate

TRANSFORMS_PATH = Path(__file__).resolve().parents[2] / "app" / "cleaning" / "transforms.py"


@dataclass
class ErrorInfo:
    exception_type: str
    message: str
    traceback_text: str


def capture_error(exc: Exception) -> ErrorInfo:
    return ErrorInfo(
        exception_type=type(exc).__name__,
        message=str(exc),
        traceback_text="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


class PatchRejected(RuntimeError):
    """Raised when the LLM's proposed fix isn't safe to apply (invalid
    syntax, or it stripped required functions)."""


class NotHealable(RuntimeError):
    """Raised when the exception clearly didn't originate in
    transforms.py -- the only file this agent is scoped to patch.
    Asking the LLM to fix it anyway is a guaranteed-useless ~2-6 minute
    round trip (confirmed by a QA audit: malformed input that broke the
    *ingestion* parser, not the cleaning engine, still burned a full
    360s LLM call before falling back to human review). Skip straight
    there instead."""


def _originates_in_transforms(exc: BaseException) -> bool:
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == str(TRANSFORMS_PATH):
            return True
        tb = tb.tb_next
    return False


REQUIRED_FUNCTIONS = {
    "normalize_phone",
    "normalize_email",
    "parse_datetime_utc",
    "normalize_consent",
    "split_full_name",
}


def _validate_patch(new_source: str) -> None:
    try:
        tree = ast.parse(new_source)
    except SyntaxError as exc:
        raise PatchRejected(f"patched code is not valid Python: {exc}") from exc

    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    missing = REQUIRED_FUNCTIONS - defined
    if missing:
        raise PatchRejected(f"patch dropped required function(s): {sorted(missing)}")


def propose_patch(error: ErrorInfo) -> str:
    """Returns the full replacement source for transforms.py. Raises
    OllamaUnavailable if the LLM can't be reached."""
    current_source = TRANSFORMS_PATH.read_text()

    prompt = f"""You are fixing a bug in a Python data-cleaning module that
raised an uncaught exception while processing a batch of leads.

Current file content (app/cleaning/transforms.py):
```python
{current_source}
```

The exception it raised:
{error.exception_type}: {error.message}

Traceback:
{error.traceback_text}

Rewrite the ENTIRE file to fix this bug, keeping every existing function
name and signature ({', '.join(sorted(REQUIRED_FUNCTIONS))}) and their
overall behavior for valid inputs -- only change what's needed to stop this
exception from being raised, handling the malformed input type gracefully
(returning None rather than raising, where the other functions in this file
already do that for bad input).

Respond with ONLY the complete corrected Python file content, no
explanation, no markdown code fences."""

    # a full-file rewrite is a long generation on CPU-only inference,
    # especially for smaller/quantized models -- observed timings on an
    # 8GB machine ranged from ~106s to ~155s, with real variance run to
    # run, so give it generous headroom rather than tuning to one sample
    response = generate(prompt, timeout=360.0)
    return _strip_code_fences(response)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def apply_patch(new_source: str) -> Path:
    """Validates and writes the patch, backing up the previous version.
    Returns the backup path."""
    _validate_patch(new_source)

    backup_path = TRANSFORMS_PATH.with_suffix(".py.bak")
    backup_path.write_text(TRANSFORMS_PATH.read_text())
    TRANSFORMS_PATH.write_text(new_source)
    return backup_path


def heal(exc: Exception) -> tuple[ErrorInfo, str]:
    """Full heal step: capture the error, ask the LLM for a fix, validate
    and write it. Raises OllamaUnavailable, PatchRejected, or NotHealable
    on failure -- callers should treat any of those as "could not
    self-heal, go to human review"."""
    if not _originates_in_transforms(exc):
        raise NotHealable(
            f"{type(exc).__name__} did not originate in app/cleaning/transforms.py "
            "-- self-healing is scoped to that file only, skipping a doomed LLM attempt"
        )
    error = capture_error(exc)
    new_source = propose_patch(error)
    apply_patch(new_source)
    return error, new_source
