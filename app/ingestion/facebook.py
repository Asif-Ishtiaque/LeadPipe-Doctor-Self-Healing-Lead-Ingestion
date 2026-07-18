"""Parser for Facebook Lead Ads webhook payloads.

Facebook's webhook nests every submitted field inside a `field_data` list of
`{"name": ..., "values": [...]}` pairs, several levels deep inside
`entry -> changes -> value`. This flattens each leadgen event into one flat
dict so the rest of the pipeline never has to know about Facebook's shape.

Accepts either a single parsed webhook payload (one HTTP delivery, possibly
containing several leadgen events in its `entry` list) or JSONL text (one
complete webhook payload per line -- how a batch of individually-delivered
webhook calls would be captured to a sample file).
"""

import json
from typing import Any


def parse_facebook_webhook(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value", {})

            flat: dict[str, Any] = {
                "leadgen_id": value.get("leadgen_id"),
                "form_id": value.get("form_id"),
                "page_id": value.get("page_id"),
                "created_time": value.get("created_time"),
            }
            for field in value.get("field_data", []):
                name = field.get("name")
                values = field.get("values") or [None]
                flat[name] = values[0]

            records.append(flat)

    return records


def parse_facebook_jsonl(text: str) -> list[dict[str, Any]]:
    """One complete webhook payload per line. Malformed lines are skipped
    rather than failing the whole batch -- a single corrupted delivery
    shouldn't take down every other lead in the file."""
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.extend(parse_facebook_webhook(payload))
    return records


def parse_facebook_input(raw: Any) -> list[dict[str, Any]]:
    """Entry point that accepts whatever shape Facebook data actually
    arrives in: an already-parsed single webhook payload or list of them
    (calling this in-process, e.g. from a script or the self-healing
    demo), or raw text that's either one big JSON document or JSONL (one
    payload per line, from an HTTP request body).

    A bare JSON string/number/bool at the top level, or a non-dict item
    inside an array, is malformed input, not a cleaning-engine bug -- so
    this treats it as "no records" (matching an empty body) instead of
    crashing. A QA audit found that crash burning 6 minutes in the
    self-healing loop trying (and structurally unable) to fix a bug that
    was never in transforms.py to begin with."""
    if isinstance(raw, dict):
        return parse_facebook_webhook(raw)
    if isinstance(raw, list):
        records: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                records.extend(parse_facebook_webhook(item))
        return records
    if not isinstance(raw, (str, bytes)):
        return []

    text = raw if isinstance(raw, str) else raw.decode()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return parse_facebook_jsonl(text)
    return parse_facebook_input(parsed)
