"""Tests for the canonical Lead schema's "flag, never drop" contract.

An external review found the schema making first_name/last_name/email/
phone_e164/consent hard-required was silently rejecting ~60% of a real
sample batch to invalid_leads instead of flagging it -- the brief is
explicit that a lead a business paid for is never deleted for having
dirty data. These tests lock in the fix: every field below must degrade
gracefully (to None or a safe default) rather than raise, no matter how
dirty the input."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schema.canonical import Lead, LeadSource


def _lead(**overrides) -> Lead:
    defaults = dict(
        source=LeadSource.FACEBOOK,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone_e164="+14155550123",
        consent=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Lead(**defaults)


def test_lead_with_every_dirty_field_at_once_constructs_without_raising():
    """The exact combination the reviewer's failing rows had: no name, no
    email, no phone, no consent, no timestamp."""
    lead = _lead(first_name=None, last_name=None, email=None, phone_e164=None, consent=None, created_at=None)
    assert lead.first_name is None
    assert lead.last_name is None
    assert lead.email is None
    assert lead.phone_e164 is None
    assert lead.consent is False  # TCPA-safe default, not None
    assert lead.created_at.tzinfo is not None  # defaulted to now(), still a real datetime


def test_missing_name_email_phone_never_raises_validation_error():
    try:
        _lead(first_name=None, last_name=None, email=None, phone_e164=None)
    except ValidationError as exc:
        pytest.fail(f"a lead missing name/email/phone must not raise ValidationError, got: {exc}")


def test_consent_omitted_entirely_defaults_to_false():
    lead = Lead(
        source=LeadSource.FACEBOOK,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        # consent key not passed at all
    )
    assert lead.consent is False


def test_missing_created_at_defaults_to_a_real_utc_datetime_not_none():
    lead = _lead(created_at=None)
    assert isinstance(lead.created_at, datetime)
    assert lead.created_at.tzinfo == timezone.utc


def test_created_at_key_absent_entirely_does_not_reject_the_lead():
    """Regression: a Pydantic v2 mode='before' validator does NOT fire for
    a field whose key is absent from the input -- only when a value is
    explicitly passed. A QA pass found this silently dropping any lead
    whose source omits a timestamp (or whose 'ts' field the mapper didn't
    resolve) to invalid_leads, violating the never-drop contract. The
    default_factory on created_at is what actually covers the absent-key
    case."""
    lead = Lead(
        source=LeadSource.FACEBOOK,
        first_name="Grace",
        last_name="Hopper",
        email="grace@navy.mil",
        phone_e164="+12026750143",
        consent=True,
        # created_at deliberately not passed at all
    )
    assert isinstance(lead.created_at, datetime)
    assert lead.created_at.tzinfo == timezone.utc


def test_over_long_name_is_truncated_not_rejected():
    lead = _lead(first_name="A" * 5000, last_name="Hamilton")
    assert lead.first_name == "A" * 100
    assert lead.last_name == "Hamilton"


def test_junk_unicode_name_is_nulled_out_not_rejected():
    lead = _lead(first_name="\U0001F602\U0001F602\U0001F602", last_name="normal")
    assert lead.first_name is None
    assert lead.last_name == "normal"


def test_legitimate_name_with_apostrophe_and_hyphen_passes_through_unchanged():
    lead = _lead(first_name="Anne-Marie", last_name="O'Brien")
    assert lead.first_name == "Anne-Marie"
    assert lead.last_name == "O'Brien"


def test_malformed_email_is_nulled_out_not_rejected():
    lead = _lead(email="not-an-email-at-all")
    assert lead.email is None


def test_valid_email_is_normalized_and_lowercased():
    lead = _lead(email="Ada.Lovelace@EXAMPLE.com")
    assert lead.email == "ada.lovelace@example.com"


def test_status_defaults_to_clean():
    assert _lead().status == "clean"
