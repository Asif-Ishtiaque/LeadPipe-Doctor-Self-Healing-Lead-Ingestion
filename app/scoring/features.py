"""Turns a validated Lead into a flat numeric feature vector for scoring.
Shared by both the rule-based scorer and the XGBoost model so the two stay
comparable."""

from __future__ import annotations

from app.schema.canonical import Lead, LeadSource

SOURCE_ORDER = [s.value for s in LeadSource]

FEATURE_NAMES = [
    "has_first_name",
    "has_last_name",
    "has_email",
    "has_phone",
    "has_campaign_id",
    "consent",
    "email_is_free_provider",
    "email_is_disposable",
    "email_is_placeholder_like",
    "name_is_placeholder_like",
    "phone_is_placeholder",
    "created_hour",
    *[f"source_{s}" for s in SOURCE_ORDER],
]

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"}

# Not exhaustive -- disposable-email services launch constantly -- but
# catches the common ones a QA audit found gaming the old scorer (a
# mailinator.com spam submission outscored a real gmail user because
# "not in the 5-domain freemail list" was being read as "looks
# professional"). A real deployment should use a maintained third-party
# list; this is deliberately a floor, not a complete solution.
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.info", "10minutemail.com",
    "tempmail.com", "temp-mail.org", "throwawaymail.com", "yopmail.com",
    "trashmail.com", "getnada.com", "dispostable.com", "fakeinbox.com",
    "sharklasers.com", "maildrop.cc", "mailnesia.com", "mintemail.com",
    "spamgourmet.com", "mytrashmail.com", "tempinbox.com", "discard.email",
    "emailondeck.com", "mohmal.com", "moakt.com", "burnermail.io",
    "grr.la", "spam4.me", "0-mail.com", "mailcatch.com",
}

# Obvious test/keyboard-mash/placeholder values -- doesn't catch every
# fake name (that's an open problem), but catches the cheap, common
# cases without penalizing legitimate short names.
PLACEHOLDER_NAME_TOKENS = {
    "test", "testing", "asdf", "asdfg", "asdfgh", "qwerty", "xxx", "yyy",
    "zzz", "aaa", "foo", "bar", "baz", "none", "na", "n/a", "unknown",
    "sample", "example", "fake", "spam", "abc", "lorem", "ipsum", "asd",
}


# Obviously-fake email local parts ("test@test.com", "asdf@asdf.com") --
# same idea as PLACEHOLDER_NAME_TOKENS but for the part of an email
# before the @. Not "asdf@asdf" itself (missing a TLD), which
# email_validator already rejects as malformed before this ever runs.
PLACEHOLDER_EMAIL_LOCAL_PARTS = {
    "test", "testing", "asdf", "example", "admin", "user", "sample",
    "fake", "none", "na", "foo", "bar", "spam", "noreply", "no-reply",
}


def _is_placeholder_name(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in PLACEHOLDER_NAME_TOKENS


def _is_placeholder_phone(phone_e164: str | None) -> bool:
    """NANP's 555 exchange (+1AAA555XXXX) is reserved for
    fiction/directory-assistance use and is exactly what Faker generates
    for synthetic US phone numbers -- structurally a real, possible
    number (normalize_phone now accepts it, see
    app/cleaning/transforms.py), but not a number anyone could actually
    be reached at. A quality signal, not a rejection reason."""
    if not phone_e164 or not phone_e164.startswith("+1") or len(phone_e164) != 12:
        return False
    return phone_e164[5:8] == "555"


def _is_placeholder_email(email: str) -> bool:
    """Exact match, or the token followed by nothing but digits
    ("test123", "admin007") -- not a blanket prefix match. A QA audit
    caught that being far too aggressive: real first names like
    "bartholomew@" and "nathaniel@" were getting flagged (contain "bar"/
    "na" as a prefix), along with "testimonials@" and "administrator@".
    Requiring the suffix to be digits-only still catches a fake address
    with a per-submission number tacked on, without matching ordinary
    words or names that merely start with the same letters."""
    local = email.split("@")[0].lower() if email and "@" in email else ""
    for token in PLACEHOLDER_EMAIL_LOCAL_PARTS:
        if local == token:
            return True
        if local.startswith(token) and local[len(token):].isdigit():
            return True
    return False


def build_features(lead: Lead) -> dict[str, float]:
    email_domain = (lead.email or "").split("@")[-1].lower() if lead.email else ""
    source_value = lead.source.value if isinstance(lead.source, LeadSource) else lead.source

    features = {
        "has_first_name": float(bool(lead.first_name)),
        "has_last_name": float(bool(lead.last_name)),
        "has_email": float(bool(lead.email)),
        "has_phone": float(bool(lead.phone_e164)),
        "has_campaign_id": float(bool(lead.campaign_id)),
        "consent": float(bool(lead.consent)),
        "email_is_free_provider": float(email_domain in FREE_EMAIL_DOMAINS),
        "email_is_disposable": float(email_domain in DISPOSABLE_EMAIL_DOMAINS),
        "email_is_placeholder_like": float(_is_placeholder_email(lead.email)),
        "name_is_placeholder_like": float(_is_placeholder_name(lead.first_name) or _is_placeholder_name(lead.last_name)),
        "phone_is_placeholder": float(_is_placeholder_phone(lead.phone_e164)),
        "created_hour": float(lead.created_at.hour),
    }
    for s in SOURCE_ORDER:
        features[f"source_{s}"] = float(source_value == s)

    return features


def features_to_vector(features: dict[str, float]) -> list[float]:
    return [features[name] for name in FEATURE_NAMES]
