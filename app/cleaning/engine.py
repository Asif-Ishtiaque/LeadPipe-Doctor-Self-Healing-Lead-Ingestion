"""Runs mapped-but-still-messy records through the field transforms in
transforms.py, producing records shaped like the canonical Lead schema
(still pre-validation).

`transforms` is imported lazily through `_load_transforms()` rather than
once at module scope, so that after the self-healing agent rewrites
app/cleaning/transforms.py on disk, a fresh `importlib.reload` picks up the
patched code on the very next retry without restarting the process.
"""

import importlib
from typing import Any

from app.cleaning import transforms as _transforms_module


def _load_transforms():
    importlib.reload(_transforms_module)
    return _transforms_module


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    t = _load_transforms()
    cleaned = dict(record)

    if "full_name" in cleaned and not (cleaned.get("first_name") and cleaned.get("last_name")):
        first, last = t.split_full_name(cleaned.get("full_name"))
        cleaned.setdefault("first_name", first)
        cleaned.setdefault("last_name", last)
    cleaned.pop("full_name", None)

    # LLM field mapping occasionally maps a combined "First Last" field to
    # first_name instead of the full_name it actually is (mapping quality
    # varies with model size) -- if first_name has multiple words and
    # last_name never got set, treat it the same way full_name would be.
    if cleaned.get("first_name") and not cleaned.get("last_name"):
        first, last = t.split_full_name(cleaned["first_name"])
        if last:
            cleaned["first_name"], cleaned["last_name"] = first, last

    if "phone_e164" in cleaned:
        cleaned["phone_e164"] = t.normalize_phone(cleaned.get("phone_e164"))
    if "email" in cleaned:
        cleaned["email"] = t.normalize_email(cleaned.get("email"))
    if "created_at" in cleaned:
        cleaned["created_at"] = t.parse_datetime_utc(cleaned.get("created_at"))
    if "consent" in cleaned:
        cleaned["consent"] = t.normalize_consent(cleaned.get("consent"))

    return cleaned


def clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Note: deliberately not wrapped in a per-record try/except. A genuine
    bug in transforms.py (e.g. it can't handle a value type it never
    expected) is meant to propagate up to the self-healing agent, which
    treats an uncaught exception here as a signal to patch the code -- not
    to skip the row and move on."""
    return [clean_record(r) for r in records]
