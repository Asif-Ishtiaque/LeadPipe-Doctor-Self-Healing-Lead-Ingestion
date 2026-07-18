"""Maps arbitrary source field names onto the canonical schema.

Resolution order per field:
  1. Exact-match memory in ChromaDB -- have we mapped this (source, field
     name) pair before? If so, reuse it for free.
  2. Ask the local LLM, grounded with the nearest canonical field
     descriptions retrieved from ChromaDB (RAG).
  3. If Ollama is unreachable, fall back to a synonym/fuzzy-match heuristic
     so the pipeline still runs without any LLM available.

Every fresh resolution (LLM or heuristic) is written back to ChromaDB, which
is what makes mapping "improve over time": the second time a source sends
the same field name, step 1 answers instantly.
"""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz, process

from app.mapping import rag_store
from app.mapping.llm_client import OllamaUnavailable, extract_json, generate
from app.mapping.profiler import profile_fields
from app.schema.canonical import CANONICAL_FIELD_DESCRIPTIONS

# "full_name" is a virtual target -- not a real canonical field, but a
# recognized intermediate that the cleaning engine knows how to split into
# first_name/last_name. This is what lets "Full Name" -> full_name -> two
# canonical fields, per the brief's own example.
VIRTUAL_FIELDS = {"full_name": "A single field holding both first and last name together."}

MAPPING_TARGETS = {**CANONICAL_FIELD_DESCRIPTIONS, **VIRTUAL_FIELDS}

def _normalize(field_name: str) -> str:
    return field_name.strip().lower().replace("_", " ").replace("-", " ")


# Keys are written in whatever casing/separator reads naturally here; they're
# normalized once at import time (same normalization applied to incoming
# field names) so lookups don't silently miss on "opt_in" vs "opt in".
_RAW_SYNONYMS: dict[str, str] = {
    "fname": "first_name",
    "first name": "first_name",
    "firstname": "first_name",
    "lname": "last_name",
    "last name": "last_name",
    "lastname": "last_name",
    "full name": "full_name",
    "name": "full_name",
    "email address": "email",
    "e-mail": "email",
    "contact_email": "email",
    "phone": "phone_e164",
    "phone number": "phone_e164",
    "mobile": "phone_e164",
    "whatsapp": "phone_e164",
    "contact_number": "phone_e164",
    "opt_in": "consent",
    "opted in": "consent",
    "marketing_consent": "consent",
    "gdpr_consent": "consent",
    "i agree to be contacted": "consent",
    "created_time": "created_at",
    "timestamp": "created_at",
    "submitted at": "created_at",
    "date": "created_at",
    "ts": "created_at",
    "utm_campaign": "campaign_id",
    "ad_id": "campaign_id",
    "form_id": "campaign_id",
    "campaign": "campaign_id",
}

SYNONYMS: dict[str, str] = {_normalize(k): v for k, v in _RAW_SYNONYMS.items()}


def _heuristic_match(field_name: str) -> str | None:
    normalized = _normalize(field_name)
    if normalized in SYNONYMS:
        return SYNONYMS[normalized]

    candidates = list(SYNONYMS.keys()) + list(MAPPING_TARGETS.keys())
    match = process.extractOne(normalized, candidates, scorer=fuzz.token_sort_ratio)
    if match is None or match[1] < 75:
        return None
    matched_text = match[0]
    return SYNONYMS.get(matched_text, matched_text)


def _llm_match(field_name: str, samples: list[str]) -> str | None:
    context = rag_store.query_similar_canonical_fields(field_name, ", ".join(samples[:3]))
    context_block = "\n".join(f"- {c['field']}: {c['description']}" for c in context)

    prompt = f"""You are mapping a messy CRM lead field onto a canonical schema.
Source fields are often phrased as casual questions, not keywords -- infer
the intent, don't just pattern-match on words. For example:
- "What is your full name?" -> full_name
- "Where can we reach you by phone?" -> phone_e164
- "Which campaign brought you here?" -> campaign_id
- "May we contact you about updates?" -> consent
Only answer "unknown" if the field genuinely doesn't correspond to any
canonical field below, not just because the wording is indirect.

Canonical fields you may choose from (plus "full_name" if the field holds a
combined first+last name, and "unknown" if nothing fits):
{context_block}
- full_name: {VIRTUAL_FIELDS['full_name']}

Source field name: "{field_name}"
Sample values: {samples[:3]}

Respond with ONLY a JSON object like {{"canonical_field": "first_name"}} or
{{"canonical_field": "unknown"}}. No other text."""

    response = generate(prompt)
    parsed = extract_json(response)
    field = parsed.get("canonical_field")
    if field in ("unknown", None, ""):
        return None
    return field


def map_source_fields(source: str, records: list[dict]) -> dict[str, str | None]:
    """Returns {raw_field_name: canonical_field_or_None} for one batch."""
    profiles = profile_fields(records)
    mapping: dict[str, str | None] = {}

    for field_name, samples in profiles.items():
        known = rag_store.lookup_known_mapping(source, field_name)
        if known is not None:
            mapping[field_name] = known
            continue

        try:
            resolved = _llm_match(field_name, samples)
        except OllamaUnavailable:
            resolved = _heuristic_match(field_name)

        mapping[field_name] = resolved
        if resolved:
            rag_store.remember_mapping(source, field_name, resolved, samples[0] if samples else "")

    return mapping


def apply_mapping(records: list[dict[str, Any]], mapping: dict[str, str | None]) -> list[dict[str, Any]]:
    """Rename each record's fields per `mapping`. Anything unmapped (or
    starting with '_') is preserved under raw_payload instead of dropped."""
    mapped_records = []

    for record in records:
        mapped: dict[str, Any] = {"raw_payload": dict(record)}
        for field_name, value in record.items():
            if field_name.startswith("_"):
                continue
            canonical = mapping.get(field_name)
            if canonical:
                mapped[canonical] = value
        mapped_records.append(mapped)

    return mapped_records
