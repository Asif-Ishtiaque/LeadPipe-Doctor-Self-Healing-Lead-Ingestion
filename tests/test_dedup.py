"""Tests for the exact-match-only dedup design. See
app/deduplication/dedup.py's module docstring for the full reasoning:
fuzzy name similarity can't distinguish "same person, typo'd name" from
"different people, coincidentally similar name" (fuzz.ratio("jon li",
"jan li") == fuzz.ratio("mohammed ali", "muhammad ali") == 83.3), so
merging happens on exact email/phone identity only -- a deliberate
accuracy-over-recall tradeoff, not a missing feature."""

from datetime import datetime, timezone

from app.deduplication.dedup import deduplicate
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
        quality_score=50.0,
    )
    defaults.update(overrides)
    return Lead(**defaults)


def test_exact_email_match_is_merged():
    a = _lead(email="same@example.com", phone_e164="+14155550001")
    b = _lead(email="same@example.com", phone_e164="+14155550002")
    kept, duplicates = deduplicate([a, b])
    assert len(kept) == 1
    assert len(duplicates) == 1


def test_exact_phone_match_is_merged():
    a = _lead(email="a@example.com", phone_e164="+14155550099")
    b = _lead(email="b@example.com", phone_e164="+14155550099")
    kept, duplicates = deduplicate([a, b])
    assert len(kept) == 1
    assert len(duplicates) == 1


def test_similar_but_different_names_are_never_merged():
    """The exact false-positive case that got fuzzy matching removed: two
    genuinely different people whose names happen to look alike must
    both survive as separate leads."""
    a = _lead(first_name="Jon", last_name="Li", email="jon.li@example.com", phone_e164="+14155550001")
    b = _lead(first_name="Jan", last_name="Li", email="jan.li@example.com", phone_e164="+14155550002")
    kept, duplicates = deduplicate([a, b])
    assert len(kept) == 2
    assert len(duplicates) == 0


def test_no_shared_identifiers_means_no_merge_even_with_identical_names():
    a = _lead(first_name="Same", last_name="Name", email="a@example.com", phone_e164="+14155550001")
    b = _lead(first_name="Same", last_name="Name", email="b@example.com", phone_e164="+14155550002")
    kept, duplicates = deduplicate([a, b])
    assert len(kept) == 2
    assert len(duplicates) == 0


def test_kept_record_is_the_higher_scoring_one_and_duplicate_traces_to_it():
    strong = _lead(email="same@example.com", quality_score=90.0)
    weak = _lead(email="same@example.com", phone_e164="+14155559999", quality_score=10.0)
    kept, duplicates = deduplicate([weak, strong])
    assert kept == [strong]
    assert duplicates[0].duplicate_of_lead_id == strong.lead_id
    assert duplicates[0].status == "duplicate"


def test_leads_with_no_email_and_no_phone_are_never_merged_with_each_other():
    a = _lead(email=None, phone_e164=None)
    b = _lead(email=None, phone_e164=None)
    kept, duplicates = deduplicate([a, b])
    assert len(kept) == 2
    assert len(duplicates) == 0
