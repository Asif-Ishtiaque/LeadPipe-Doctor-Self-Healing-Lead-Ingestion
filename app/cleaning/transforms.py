"""Field-level cleaning transforms. Each function takes one messy raw value
and returns a normalized value, or None if it can't make sense of it (bad
data is not an error -- it's just left for the validation layer to reject).

This module is intentionally kept small and self-contained: it is the piece
the self-healing agent (app/agent) is allowed to rewrite on disk when a
transform raises an unexpected exception, so keep each function narrowly
scoped to one field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import phonenumbers
from dateutil import parser as dateutil_parser
from email_validator import EmailNotValidError, validate_email

# Common one-character/one-letter typos of the big providers -- a lead
# with a mistyped domain is still a real person who made a fat-fingered
# mistake, so this corrects it rather than just rejecting or scoring it
# down (unlike disposable domains and placeholder-looking addresses,
# which are quality concerns, not typos -- see app/scoring/features.py).
COMMON_DOMAIN_TYPOS = {
    "gmial.com": "gmail.com", "gmal.com": "gmail.com", "gmai.com": "gmail.com",
    "gmaill.com": "gmail.com", "gnail.com": "gmail.com", "gmailc.om": "gmail.com",
    "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.co": "yahoo.com",
    "hotmial.com": "hotmail.com", "hotmil.com": "hotmail.com", "hotmai.com": "hotmail.com",
    "outlok.com": "outlook.com", "outllok.com": "outlook.com", "outloo.com": "outlook.com",
    "iclould.com": "icloud.com", "iclou.com": "icloud.com", "iclod.com": "icloud.com",
}

CONSENT_TRUE = {"true", "yes", "y", "1", "on", "opted_in", "opt_in", "checked", "agree", "agreed"}
CONSENT_FALSE = {"false", "no", "n", "0", "off", "opted_out", "opt_out", "unchecked", "disagree"}

# Real forms often phrase consent as a full sentence ("I agree", "I do not
# wish to be contacted") rather than a single word -- checked as substrings
# after the exact-match fast path above misses. Negative phrases are
# checked before positive ones, since several contain a positive keyword
# as a substring ("do not agree" contains "agree"; "disagree" contains
# "agree") and would otherwise be misread as consent given.
CONSENT_FALSE_PHRASES = ("not agree", "don't agree", "do not", "don't", "disagree", "opt out", "opt-out", "unsubscribe", "decline", "refuse", "no thanks")
CONSENT_TRUE_PHRASES = ("i agree", "agree", "i accept", "accept", "consent", "opt in", "opt-in", "subscribe", "yes")


def normalize_phone(value: Any, default_region: str = "US") -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = phonenumbers.parse(text, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        result = validate_email(text, check_deliverability=False)
    except EmailNotValidError:
        return None
    normalized = result.normalized.lower()
    local, _, domain = normalized.partition("@")
    corrected_domain = COMMON_DOMAIN_TYPOS.get(domain)
    return f"{local}@{corrected_domain}" if corrected_domain else normalized


def parse_datetime_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = dateutil_parser.parse(text)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_consent(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in CONSENT_TRUE:
        return True
    if text in CONSENT_FALSE:
        return False
    if any(phrase in text for phrase in CONSENT_FALSE_PHRASES):
        return False
    if any(phrase in text for phrase in CONSENT_TRUE_PHRASES):
        return True
    return None


def split_full_name(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    parts = str(value).strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])
