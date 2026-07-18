"""Parser for a custom landing-page form submission, posted as JSON -- a
single object, a batch/array of objects, or JSONL text (one object per
line, skipping malformed/empty lines rather than failing the whole batch)."""

from __future__ import annotations

import json
from typing import Any


def parse_landing_page_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        # A bare JSON string/number is technically malformed input, not a
        # cleaning-engine bug -- treat it as "no records" (same as an
        # empty body) rather than crashing. A QA audit found this taking
        # down the whole request with a confusing low-level TypeError,
        # which then wasted 6 minutes in the self-healing loop trying (and
        # structurally unable) to fix a bug that isn't in transforms.py at
        # all. Also drops any non-dict items a malformed array might
        # contain (e.g. `[1, 2, "x"]`) instead of passing them downstream.
        return [item for item in payload if isinstance(item, dict)]
    return []


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
