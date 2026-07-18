"""Persistence for pipeline output. Backed by Postgres in docker-compose
(DATABASE_URL points at the `db` service) or a local DuckDB file when run
bare-metal for development -- both go through the same SQLAlchemy engine,
so nothing else in the app needs to know which one is active."""

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, inspect, text

from app.schema.canonical import Lead
from app.utils.config import settings


@lru_cache(maxsize=1)
def get_engine():
    if settings.database_url.startswith("duckdb"):
        db_path = settings.database_url.replace("duckdb:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    _ensure_indexes(engine)
    return engine


def _ensure_indexes(engine) -> None:
    """Cross-batch dedup and /stats both do lookups keyed on email/phone
    -- without an index those degrade to a full table scan as the leads
    table grows. Best-effort: skip quietly if the table doesn't exist yet
    (first run) or the backend doesn't support IF NOT EXISTS the same way."""
    if not inspect(engine).has_table("leads"):
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_email ON leads (email)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads (phone_e164)"))
    except Exception:
        pass


def _lead_to_row(lead: Lead) -> dict:
    row = lead.model_dump(mode="json")
    row["raw_payload"] = json.dumps(row["raw_payload"], default=str)
    return row


def _ensure_columns(engine, table: str, row_keys: list[str]) -> None:
    """No migration tool here (no Alembic), and the Lead schema has grown
    fields since some tables were first created (e.g. duplicate_of_lead_id
    was added after leads/duplicate_leads already existed with data in
    them) -- pandas.to_sql(if_exists="append") doesn't add missing
    columns itself, it just fails with UndefinedColumn. Add any columns
    the incoming rows need but the existing table doesn't have yet,
    rather than requiring a manual migration or a destructive reset."""
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    missing = [k for k in row_keys if k not in existing]
    if not missing:
        return
    try:
        with engine.begin() as conn:
            for col in missing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT"))
    except Exception:
        pass


def save_leads(leads: list[Lead], table: str = "leads") -> None:
    if not leads:
        return
    rows = [_lead_to_row(lead) for lead in leads]
    _ensure_columns(get_engine(), table, list(rows[0].keys()))
    df = pd.DataFrame(rows)
    df.to_sql(table, get_engine(), if_exists="append", index=False)


def save_invalid(invalid: list[dict], source: str, table: str = "invalid_leads") -> None:
    if not invalid:
        return
    df = pd.DataFrame(
        [
            {
                "source": source,
                "record": json.dumps(item["record"], default=str),
                "errors": json.dumps(item["errors"], default=str),
            }
            for item in invalid
        ]
    )
    df.to_sql(table, get_engine(), if_exists="append", index=False)


def save_healing_events(source: str, events: list[dict], table: str = "healing_events") -> None:
    if not events:
        return
    df = pd.DataFrame([{**event, "source": source} for event in events])
    df.to_sql(table, get_engine(), if_exists="append", index=False)


def read_table(table: str) -> pd.DataFrame:
    try:
        return pd.read_sql_table(table, get_engine())
    except Exception:
        return pd.DataFrame()


_CROSS_BATCH_CHUNK_SIZE = 1000


def find_existing_leads(emails: list[str], phones: list[str]) -> dict[str, str]:
    """Cross-batch dedup: which of these emails/phones already exist in the
    `leads` table from a *previous* ingest, not just this batch? Returns
    {"email:<lowercased email>" | "phone:<e164>": existing lead_id}.

    Without this, the same lead submitted in two separate API calls (the
    normal way webhooks actually arrive -- one lead at a time, not in
    bulk) was never checked against anything already stored, so repeat
    submissions all came through as separate "valid" rows.

    Values are deduplicated and chunked into batches of
    _CROSS_BATCH_CHUNK_SIZE before building each IN (...) query -- a
    single query with tens of thousands of placeholders was measured
    taking 3.3s for a 25k-lead batch (50k placeholders across the two
    queries) and only gets worse as batches grow; chunking keeps each
    individual query small and fast regardless of batch size."""
    engine = get_engine()
    if not inspect(engine).has_table("leads"):
        return {}

    emails = sorted({e.lower() for e in emails if e})
    phones = sorted({p for p in phones if p})
    if not emails and not phones:
        return {}

    def chunks(values: list[str]) -> list[list[str]]:
        return [values[i : i + _CROSS_BATCH_CHUNK_SIZE] for i in range(0, len(values), _CROSS_BATCH_CHUNK_SIZE)]

    matches: dict[str, str] = {}
    with engine.connect() as conn:
        for chunk in chunks(emails):
            placeholders = ", ".join(f":e{i}" for i in range(len(chunk)))
            rows = conn.execute(
                text(f"SELECT lead_id, email FROM leads WHERE lower(email) IN ({placeholders})"),
                {f"e{i}": e for i, e in enumerate(chunk)},
            )
            for lead_id, email in rows:
                matches[f"email:{email.lower()}"] = lead_id
        for chunk in chunks(phones):
            placeholders = ", ".join(f":p{i}" for i in range(len(chunk)))
            rows = conn.execute(
                text(f"SELECT lead_id, phone_e164 FROM leads WHERE phone_e164 IN ({placeholders})"),
                {f"p{i}": p for i, p in enumerate(chunk)},
            )
            for lead_id, phone in rows:
                matches[f"phone:{phone}"] = lead_id
    return matches


def get_stats() -> dict:
    """Same numbers as before, but via SQL aggregation instead of loading
    entire tables into pandas -- the old version took 1.3s+ at ~90k rows
    because pandas.read_sql_table() pulls every row over the wire before
    doing anything, and that only gets worse as the tables grow."""
    engine = get_engine()

    def scalar(sql: str, default=0):
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql)).scalar()
                return result if result is not None else default
        except Exception:
            return default

    def rows(sql: str) -> list[tuple]:
        try:
            with engine.connect() as conn:
                return list(conn.execute(text(sql)))
        except Exception:
            return []

    leads_by_source = {source: count for source, count in rows("SELECT source, count(*) FROM leads GROUP BY source")}

    return {
        "leads_by_source": leads_by_source,
        "total_clean": scalar("SELECT count(*) FROM leads WHERE status = 'clean'"),
        "total_flagged": scalar("SELECT count(*) FROM leads WHERE status = 'flagged'"),
        "total_invalid": scalar("SELECT count(*) FROM invalid_leads"),
        "total_duplicates": scalar("SELECT count(*) FROM duplicate_leads"),
        "avg_quality_score": round(scalar("SELECT avg(quality_score) FROM leads", default=0.0) or 0.0, 2) or None,
        "self_healing_events": scalar("SELECT count(*) FROM healing_events"),
    }
