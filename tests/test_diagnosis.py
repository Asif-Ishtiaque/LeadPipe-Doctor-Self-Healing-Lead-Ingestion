"""Tests for the human-readable diagnosis and suggested-action outputs.
The QA brief was emphatic that these must be SPECIFIC and NON-GENERIC and
that action must track quality -- so these tests assert on the concrete
signal phrases and the score-band routing, not just "a string came back"."""

from datetime import datetime, timezone

from app.schema.canonical import Lead, LeadSource
from app.scoring.diagnosis import diagnose, suggest_action


def _lead(**overrides) -> Lead:
    defaults = dict(
        source=LeadSource.FACEBOOK,
        first_name="Margaret",
        last_name="Hamilton",
        email="margaret.hamilton@nasa.gov",
        phone_e164="+12026750142",
        consent=True,
        campaign_id="demo_request",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality_score=85.0,
    )
    defaults.update(overrides)
    return Lead(**defaults)


# --- diagnosis: specific, cites the actual signals ---

def test_strong_lead_diagnosis_names_its_strengths():
    d = diagnose(_lead())
    assert "High-quality" in d
    assert "score 85" in d
    assert "non-personal email domain" in d
    assert "opted in to contact" in d
    assert "both email and phone captured" in d
    assert "demo_request" in d  # the actual campaign id, not a generic phrase


def test_weak_lead_diagnosis_names_its_concerns():
    d = diagnose(_lead(email="test123@mailinator.com", consent=False, quality_score=10.0))
    assert "Low-quality" in d
    assert "disposable/throwaway email domain" in d
    assert "no marketing consent captured" in d


def test_diagnosis_is_not_the_generic_bad_example():
    # The brief's explicit anti-pattern: "This lead is good."
    d = diagnose(_lead())
    assert d != "This lead is good."
    assert len(d) > 40  # substantive, not a one-liner


def test_no_contact_info_lead_diagnosis_flags_it():
    d = diagnose(_lead(email=None, phone_e164=None, quality_score=5.0))
    assert "no email or phone on file" in d


# --- suggested action: tracks quality, honors hard blockers ---

def test_high_score_says_contact_now():
    action = suggest_action(_lead(quality_score=85.0))
    assert "Contact within 24 hours" in action


def test_medium_score_says_nurture():
    action = suggest_action(_lead(quality_score=55.0, email="jane@gmail.com"))
    assert "nurture" in action.lower()


def test_low_score_says_deprioritize():
    action = suggest_action(_lead(quality_score=25.0, consent=False, email="jane@gmail.com"))
    assert "Deprioritize" in action


def test_no_consent_adds_tcpa_warning_to_action():
    action = suggest_action(_lead(consent=False, quality_score=75.0))
    assert "TCPA" in action
    assert "do not cold-call" in action.lower()


def test_no_contact_info_action_is_a_hard_block_regardless_of_score():
    # Even if something scored it high, an uncontactable lead can't be actioned.
    action = suggest_action(_lead(email=None, phone_e164=None, quality_score=90.0))
    assert "no email or phone" in action.lower()
    assert "Contact within 24 hours" not in action


def test_fake_looking_lead_action_says_verify_first():
    action = suggest_action(_lead(email="test@mailinator.com", quality_score=60.0))
    assert "Verify before any outreach" in action


def test_action_and_diagnosis_are_deterministic():
    lead = _lead()
    assert len({diagnose(_lead()) for _ in range(5)}) == 1
    assert len({suggest_action(_lead()) for _ in range(5)}) == 1
