"""One-off maintenance: re-score every already-stored lead with the current
scorer and refresh its diagnosis + suggested_action.

Run this after a change to the scoring logic (weights, the scorer itself,
or the diagnosis text) so the rows already in the database reflect the new
logic instead of whatever was current when they were first ingested. New
ingests are unaffected -- they score correctly on the way in; this only
back-fills existing rows.

Run inside the API container (it has the DB connection + the app code):
    docker compose exec api python -m scripts.rescore
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.agent.pipeline import _annotate_diagnosis_and_action, _flag_quality_concerns  # noqa: E402
from app.schema.canonical import Lead  # noqa: E402
from app.scoring.scorer import LeadScorer  # noqa: E402
from app.utils.storage import _ensure_columns, get_engine  # noqa: E402

_scorer = LeadScorer()
_CHUNK = 1000


def _row_to_lead(row: dict) -> Lead:
    return Lead(
        lead_id=row.get("lead_id"),
        source=row.get("source") or "facebook",
        first_name=row.get("first_name"),
        last_name=row.get("last_name"),
        email=row.get("email"),
        phone_e164=row.get("phone_e164"),
        campaign_id=row.get("campaign_id"),
        consent=bool(row.get("consent")),
        created_at=row.get("created_at"),
    )


def rescore_table(table: str) -> int:
    engine = get_engine()
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(f'SELECT * FROM "{table}"'))]
    if not rows:
        return 0

    # duplicate_leads may predate the diagnosis/suggested_action columns --
    # add them the same way the write path does, so the UPDATE below can set
    # them rather than failing on an UndefinedColumn.
    _ensure_columns(engine, table, ["diagnosis", "suggested_action"])

    leads = [_row_to_lead(r) for r in rows]
    _scorer.score_batch(leads)
    _flag_quality_concerns(leads)
    _annotate_diagnosis_and_action(leads)

    updates = [
        {
            "lid": lead.lead_id,
            "score": lead.quality_score,
            "status": lead.status.value if hasattr(lead.status, "value") else lead.status,
            "diag": lead.diagnosis,
            "act": lead.suggested_action,
        }
        for lead in leads
    ]
    stmt = text(
        f'UPDATE "{table}" SET quality_score = :score, status = :status, '
        f"diagnosis = :diag, suggested_action = :act WHERE lead_id = :lid"
    )
    with engine.begin() as conn:
        for i in range(0, len(updates), _CHUNK):
            conn.execute(stmt, updates[i : i + _CHUNK])
    return len(updates)


def main() -> None:
    # duplicate_leads carries Lead rows too, so refresh both.
    for table in ("leads", "duplicate_leads"):
        try:
            n = rescore_table(table)
            print(f"re-scored {n} rows in {table}")
        except Exception as exc:  # noqa: BLE001 -- maintenance script, report and continue
            print(f"skipped {table}: {exc}")


if __name__ == "__main__":
    main()
