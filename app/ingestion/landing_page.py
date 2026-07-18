"""Parser for a custom landing-page form submission, posted as JSON -- a
single object, a batch/array of objects, or JSONL text (one object per
line, skipping malformed/empty lines rather than failing the whole batch)."""

from __future__ import annotations

import json
from typing import Any


def parse_landing_page_json(payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = [payload]
    return list(payload)


def parse_landing_page_jsonl(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def parse_landing_page_input(raw: Any) -> list[dict[str, Any]]:
    """Entry point that accepts whatever shape actually arrives: an
    already-parsed dict/list (calling this in-process), or raw text that's
    either one big JSON document/array or JSONL (one lead per line, from
    an HTTP request body)."""
    if isinstance(raw, (dict, list)):
        return parse_landing_page_json(raw)

    text = raw if isinstance(raw, str) else raw.decode()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return parse_landing_page_jsonl(text)
    return parse_landing_page_json(parsed)
