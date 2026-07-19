"""Tests for the two field-cleaning fixes from the same review:
normalize_consent must never return None (missing/ambiguous consent is
TCPA-safe False, not a reason to drop the lead), and normalize_phone must
accept NANP's 555 exchange (what Faker generates for synthetic US phone
numbers) instead of rejecting it outright."""

from app.cleaning.transforms import normalize_consent, normalize_email, normalize_phone


def test_normalize_consent_missing_value_defaults_to_false():
    assert normalize_consent(None) is False


def test_normalize_consent_empty_string_defaults_to_false():
    assert normalize_consent("") is False


def test_normalize_consent_ambiguous_text_defaults_to_false():
    assert normalize_consent("maybe later") is False


def test_normalize_consent_never_returns_none():
    for value in (None, "", "???", "banana", 12345, [], {}):
        assert normalize_consent(value) is not None


def test_normalize_consent_recognizes_explicit_true_and_false():
    assert normalize_consent("yes") is True
    assert normalize_consent(True) is True
    assert normalize_consent("no") is False
    assert normalize_consent(False) is False


def test_normalize_consent_recognizes_sentence_phrasing():
    assert normalize_consent("I agree to be contacted") is True
    assert normalize_consent("I do not agree") is False
    assert normalize_consent("please unsubscribe me") is False


def test_normalize_phone_accepts_faker_style_555_exchange():
    # This is what the review found rejecting 111 of 238 dropped
    # Facebook leads -- a 555 number is structurally a real, possible US
    # phone number, just not one anyone could be reached at.
    result = normalize_phone("(415) 555-0123")
    assert result == "+14155550123"


def test_normalize_phone_still_rejects_unparseable_garbage():
    assert normalize_phone("not a phone number") is None


def test_normalize_phone_returns_none_for_missing_value():
    assert normalize_phone(None) is None


def test_normalize_email_corrects_common_typo_domain():
    assert normalize_email("person@gmial.com") == "person@gmail.com"


def test_normalize_email_returns_none_for_garbage():
    assert normalize_email("definitely not an email") is None
