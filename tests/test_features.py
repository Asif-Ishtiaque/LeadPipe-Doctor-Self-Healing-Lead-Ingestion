"""Tests for the quality-signal features that replace outright rejection:
a lead with a missing/placeholder field is scored down and flagged, never
dropped. Covers the new phone_is_placeholder feature and the
no-contact-info flagging path added alongside the schema fix."""

from datetime import datetime, timezone

from app.agent.pipeline import _flag_quality_concerns
from app.cleaning.transforms import normalize_phone
from app.schema.canonical import Lead, LeadSource
from app.scoring.features import build_features


def _lead(**overrides) -> Lead:
    defaults = dict(
        source=LeadSource.FACEBOOK,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        # NOT a 555 exchange -- this fixture is the "ordinary, ought to
        # be clean" baseline, and +1415555xxxx would accidentally trip
        # phone_is_placeholder itself (indices [5:8] == "555").
        phone_e164="+14152340123",
        consent=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Lead(**defaults)


def test_555_exchange_phone_is_flagged_as_placeholder():
    phone = normalize_phone("(415) 555-0199")
    lead = _lead(phone_e164=phone)
    assert build_features(lead)["phone_is_placeholder"] == 1.0


def test_ordinary_phone_is_not_flagged_as_placeholder():
    lead = _lead(phone_e164="+14152340199")
    assert build_features(lead)["phone_is_placeholder"] == 0.0


def test_missing_phone_is_not_flagged_as_placeholder():
    lead = _lead(phone_e164=None)
    assert build_features(lead)["phone_is_placeholder"] == 0.0


def test_has_x_features_are_false_for_missing_fields_not_crashes():
    lead = _lead(first_name=None, last_name=None, email=None, phone_e164=None)
    features = build_features(lead)
    assert features["has_first_name"] == 0.0
    assert features["has_last_name"] == 0.0
    assert features["has_email"] == 0.0
    assert features["has_phone"] == 0.0


def test_lead_with_no_contact_info_at_all_gets_flagged():
    lead = _lead(email=None, phone_e164=None)
    _flag_quality_concerns([lead])
    assert lead.status == "flagged"


def test_lead_with_placeholder_phone_gets_flagged():
    lead = _lead(phone_e164=normalize_phone("(415) 555-0142"))
    _flag_quality_concerns([lead])
    assert lead.status == "flagged"


def test_ordinary_complete_lead_is_not_flagged():
    lead = _lead()
    _flag_quality_concerns([lead])
    assert lead.status == "clean"
