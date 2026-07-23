"""Persistence for pipeline output. Backed by Postgres in docker-compose
(DATABASE_URL points at the `db` service) or a local DuckDB file when run
bare-metal for development -- both go through the same SQLAlchemy engine,
so nothing else in the app needs to know which one is active."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, inspect, text

from app.schema.canonical import Lead, LeadStatus
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


def save_leads(leads: list[Lead], table: str = "leads", dataset_id: str | None = None) -> None:
    if not leads:
        return
    rows = [{**_lead_to_row(lead), "dataset_id": dataset_id} for lead in leads]
    _ensure_columns(get_engine(), table, list(rows[0].keys()))
    df = pd.DataFrame(rows)
    df.to_sql(table, get_engine(), if_exists="append", index=False)


def save_invalid(invalid: list[dict], source: str, table: str = "invalid_leads", dataset_id: str | None = None) -> None:
    if not invalid:
        return
    df = pd.DataFrame(
        [
            {
                "source": source,
                "dataset_id": dataset_id,
                "record": json.dumps(item["record"], default=str),
                "errors": json.dumps(item["errors"], default=str),
            }
            for item in invalid
        ]
    )
    _ensure_columns(get_engine(), table, ["dataset_id"])
    df.to_sql(table, get_engine(), if_exists="append", index=False)


def save_healing_events(source: str, events: list[dict], table: str = "healing_events", dataset_id: str | None = None) -> None:
    if not events:
        return
    df = pd.DataFrame([{**event, "source": source, "dataset_id": dataset_id} for event in events])
    _ensure_columns(get_engine(), table, ["dataset_id"])
    df.to_sql(table, get_engine(), if_exists="append", index=False)


def read_table(table: str) -> pd.DataFrame:
    try:
        return pd.read_sql_table(table, get_engine())
    except Exception:
        return pd.DataFrame()


def _ensure_seq_column(engine, table: str) -> None:
    """/leads, /duplicates, /invalid, /healing-events all want "the most
    recent N rows" but none of these tables have a real ordering column --
    they're created ad hoc by pandas.to_sql with whatever fields the
    pipeline produced. Add a Postgres-only BIGSERIAL column
    (auto-backfills existing rows in current physical order, and every
    row inserted afterwards -- via to_sql or the raw INSERT in
    persist_leads_atomic -- gets the next value automatically since
    neither ever names this column explicitly), plus an index so ORDER BY
    ... DESC LIMIT can use a backward index scan instead of touching every
    row. Skipped on DuckDB (dev-only, small scale, no BIGSERIAL)."""
    if not settings.database_url.startswith(("postgresql", "postgres")):
        return
    if not inspect(engine).has_table(table):
        return
    existing = {col["name"] for col in inspect(engine).get_columns(table)}
    if "_seq" in existing:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN _seq BIGSERIAL'))
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS ix_{table}_seq ON "{table}" (_seq DESC)'))
    except Exception:
        pass


def read_recent(table: str, limit: int) -> pd.DataFrame:
    """Fast replacement for read_table(table).tail(limit) -- that pattern
    loads the *entire* table over the wire before pandas trims it down,
    which measured at 200+ seconds against the /leads table once the
    sample pack data accumulated (the exact bug that broke the dashboard).
    This pushes both the ordering and the row limit down into SQL so
    Postgres only ever sends back `limit` rows."""
    engine = get_engine()
    if not inspect(engine).has_table(table):
        return pd.DataFrame()

    is_postgres = settings.database_url.startswith(("postgresql", "postgres"))
    try:
        if is_postgres:
            _ensure_seq_column(engine, table)
            df = pd.read_sql_query(
                text(f'SELECT * FROM "{table}" ORDER BY _seq DESC LIMIT :limit'),
                engine,
                params={"limit": limit},
            )
            df = df.iloc[::-1].reset_index(drop=True)  # restore ascending order, same as the old .tail()
        else:
            # DuckDB dev fallback: no BIGSERIAL/backward-index-scan story,
            # but also never runs at a scale where a plain LIMIT is slow.
            df = pd.read_sql_query(text(f'SELECT * FROM "{table}" LIMIT :limit'), engine, params={"limit": limit})
        return df.drop(columns=["_seq"], errors="ignore")
    except Exception:
        return pd.DataFrame()


_CROSS_BATCH_CHUNK_SIZE = 1000


def find_existing_leads(emails: list[str], phones: list[str]) -> dict[str, str]:
    """Cheap, non-atomic pre-filter: which of these emails/phones already
    exist in `leads`? Used as a fast-path optimization to skip obviously-
    duplicate work before scoring/persistence -- NOT a correctness
    guarantee against concurrent requests (see persist_leads_atomic for
    that; a QA audit proved this check-then-later-insert pattern alone
    lets concurrent requests race: 15 threads submitting the identical
    lead simultaneously each saw "not found" here and each inserted their
    own "clean" row -- 15 duplicates of the same person, none flagged).

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


def persist_leads_atomic(leads: list[Lead], dataset_id: str | None = None) -> tuple[list[Lead], list[Lead]]:
    """The race-safe version of "check if it exists, then insert" -- the
    only place that's actually allowed to write to `leads`. On Postgres,
    each lead's email and phone are hashed into a `pg_advisory_xact_lock`
    before checking existence, so two concurrent requests racing on the
    *same* identifier serialize on that lock instead of both seeing "not
    found" (confirmed with 15 real concurrent threads before this fix:
    all 15 inserted their own "clean" copy of the same person). Requests
    for *different* leads don't contend at all -- the lock is per-key, not
    a table-wide lock.

    On DuckDB (local dev fallback) there's no advisory lock primitive, and
    DuckDB only supports one writer process at a time anyway (a real
    constraint discovered earlier in this project), so this falls back to
    the plain check-then-insert -- theoretically still racy there, but a
    single-writer database makes that race far less likely to matter in
    practice than a real multi-worker Postgres deployment.

    Returns (actually_kept, redirected_to_duplicates) -- the *true* result
    after the atomic check, which may differ from what in-batch dedup
    upstream thought was going to be kept."""
    if not leads:
        return [], []

    engine = get_engine()
    is_postgres = settings.database_url.startswith(("postgresql", "postgres"))

    if not inspect(engine).has_table("leads"):
        # Bootstrap: let pandas create the table with correctly-inferred
        # column types the first time around. Nothing else exists yet for
        # this row to race against.
        first, rest = leads[0], leads[1:]
        df = pd.DataFrame([{**_lead_to_row(first), "dataset_id": dataset_id}])
        df.to_sql("leads", engine, if_exists="append", index=False)
        kept, duplicates = [first], []
        if rest:
            more_kept, more_duplicates = persist_leads_atomic(rest, dataset_id)
            kept += more_kept
            duplicates += more_duplicates
        return kept, duplicates

    _ensure_columns(engine, "leads", list(_lead_to_row(leads[0]).keys()) + ["dataset_id"])

    kept: list[Lead] = []
    duplicates: list[Lead] = []

    # One transaction *per lead*, not one for the whole batch. Advisory
    # locks acquired with pg_advisory_xact_lock live in shared memory
    # until their transaction ends -- a single transaction wrapping a
    # 25k-lead batch (2 locks each) exhausted Postgres's
    # max_locks_per_transaction and crashed the whole request with
    # "out of shared memory" (found running the full sample pack through
    # this fix, not just the small-scale race test that caught the
    # original bug). A short transaction per lead releases each pair of
    # locks immediately, so the count in flight at any moment stays small
    # regardless of how many leads are in the batch.
    # Dedup is scoped to the dataset: the same person appearing in two
    # different uploads is kept in both (datasets are isolated), but a repeat
    # within one dataset is still collapsed. The advisory-lock keys carry the
    # dataset_id for the same reason -- two different datasets never serialize
    # on the same identifier.
    scope = f"{dataset_id}:" if dataset_id is not None else ""
    for lead in leads:
        email_key = lead.email.lower() if lead.email else None
        with engine.begin() as conn:
            if is_postgres:
                # Lock ordering (email hash, then phone hash) is fixed
                # regardless of which lead is being processed, so two
                # leads racing on both keys in opposite order can't
                # deadlock each other. A lead with neither identifier
                # has nothing to protect against and skips locking.
                if email_key:
                    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"{scope}email:{email_key}"})
                if lead.phone_e164:
                    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"{scope}phone:{lead.phone_e164}"})

            existing = None
            if email_key or lead.phone_e164:
                # lower(email) = NULL and phone_e164 = NULL both evaluate to
                # NULL (never true), so passing None for a missing identifier
                # is safe. The dataset_id guard keeps dedup within the dataset.
                if dataset_id is not None:
                    existing = conn.execute(
                        text("SELECT lead_id FROM leads WHERE dataset_id = :did AND (lower(email) = :email OR phone_e164 = :phone) LIMIT 1"),
                        {"did": dataset_id, "email": email_key, "phone": lead.phone_e164},
                    ).fetchone()
                else:
                    existing = conn.execute(
                        text("SELECT lead_id FROM leads WHERE lower(email) = :email OR phone_e164 = :phone LIMIT 1"),
                        {"email": email_key, "phone": lead.phone_e164},
                    ).fetchone()

            if existing:
                lead.status = LeadStatus.DUPLICATE
                lead.duplicate_of_lead_id = existing[0]
                duplicates.append(lead)
                continue

            row = {**_lead_to_row(lead), "dataset_id": dataset_id}
            columns = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row.keys())
            conn.execute(text(f"INSERT INTO leads ({columns}) VALUES ({placeholders})"), row)
            kept.append(lead)

    return kept, duplicates


_LEAD_VIEW_COLUMNS = (
    "lead_id, first_name, last_name, email, phone_e164, source, campaign_id, "
    "consent, created_at, quality_score, status, duplicate_of_lead_id, "
    "diagnosis, suggested_action"
)


def _lead_rows(where: str, params: dict, limit: int, order: str, offset: int = 0) -> list[dict]:
    """Shared reader for the lead-list endpoints (top / ranked / search).
    Selects only the columns the UI renders -- explicitly *not* raw_payload,
    which is by far the largest field and is what made a naive `SELECT *` of
    the whole table a ~32 MB response. `where`/`order` are code-controlled
    fragments, never user text; all user input arrives through bound `params`."""
    engine = get_engine()
    if not inspect(engine).has_table("leads"):
        return []
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT {_LEAD_VIEW_COLUMNS} FROM leads WHERE {where} ORDER BY {order} LIMIT :limit OFFSET :offset"),
                {**params, "limit": limit, "offset": offset},
            )
            return [dict(row._mapping) for row in result]
    except Exception:
        return []


def _dataset_clause(dataset_id: str | None, params: dict) -> str:
    """Append the dataset scope to a WHERE fragment. Omitted -> all datasets."""
    if dataset_id:
        params["dataset_id"] = dataset_id
        return " AND dataset_id = :dataset_id"
    return ""


def _score_filter(
    source: str | None, min_score: float | None, max_score: float | None, dataset_id: str | None = None
) -> tuple[str, dict]:
    """Shared WHERE fragment + bound params for the score-ordered lead lists
    (top preview and paginated call list)."""
    where = "quality_score IS NOT NULL"
    params: dict = {}
    if source:
        where += " AND source = :source"
        params["source"] = source
    if min_score is not None:
        where += " AND quality_score >= :min_score"
        params["min_score"] = min_score
    if max_score is not None:
        where += " AND quality_score <= :max_score"
        params["max_score"] = max_score
    where += _dataset_clause(dataset_id, params)
    return where, params


def top_leads(
    limit: int = 8,
    source: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    dataset_id: str | None = None,
) -> list[dict]:
    """Highest-scoring leads -- the "work these first" preview. Ordering and
    the row cap are pushed into SQL so only `limit` rows come back, instead of
    the frontend pulling every lead and sorting client-side."""
    where, params = _score_filter(source, min_score, max_score, dataset_id)
    return _lead_rows(where, params, limit, order="quality_score DESC")


def ranked_leads(
    limit: int = 10,
    offset: int = 0,
    source: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    dataset_id: str | None = None,
) -> dict:
    """One page of the score-ranked call list, plus the true total number of
    matches so the UI can render page controls without downloading every row.
    Same source / score-range filters as top_leads."""
    where, params = _score_filter(source, min_score, max_score, dataset_id)
    engine = get_engine()
    total = 0
    if inspect(engine).has_table("leads"):
        try:
            with engine.connect() as conn:
                total = conn.execute(text(f"SELECT count(*) FROM leads WHERE {where}"), params).scalar() or 0
        except Exception:
            total = 0
    rows = _lead_rows(where, params, limit, order="quality_score DESC", offset=offset)
    return {"total": int(total), "rows": rows}


def search_leads(
    q: str | None = None,
    source: str | None = None,
    limit: int = 200,
    min_score: float | None = None,
    flagged: bool | None = None,
    dataset_id: str | None = None,
) -> dict:
    """Server-side search for the Leads table. Returns at most `limit` rows
    plus the true total number of matches, so the UI can say "showing N of M"
    without ever downloading M rows. Matching is a case-insensitive substring
    over name/email (bound parameter -> no injection surface). The optional
    min_score / flagged filters back the smart-filter controls: min_score is
    the score slider; flagged=True narrows to suspicious (flagged) leads,
    flagged=False to clean ones."""
    engine = get_engine()
    if not inspect(engine).has_table("leads"):
        return {"total": 0, "rows": []}

    where = "1=1"
    params: dict = {}
    if q and q.strip():
        where += " AND (lower(first_name) LIKE :like OR lower(last_name) LIKE :like OR lower(email) LIKE :like)"
        params["like"] = f"%{q.strip().lower()}%"
    if source:
        where += " AND source = :source"
        params["source"] = source
    if min_score is not None:
        where += " AND quality_score >= :min_score"
        params["min_score"] = min_score
    if flagged is not None:
        where += " AND status = :status"
        params["status"] = "flagged" if flagged else "clean"
    where += _dataset_clause(dataset_id, params)

    total = 0
    try:
        with engine.connect() as conn:
            total = conn.execute(text(f"SELECT count(*) FROM leads WHERE {where}"), params).scalar() or 0
    except Exception:
        total = 0

    # Newest first. On Postgres _seq exists (see _ensure_seq_column); on the
    # DuckDB dev fallback there's no _seq, so fall back to created_at.
    is_postgres = settings.database_url.startswith(("postgresql", "postgres"))
    if is_postgres:
        _ensure_seq_column(engine, "leads")
    order = "_seq DESC" if is_postgres else "created_at DESC"
    return {"total": int(total), "rows": _lead_rows(where, params, limit, order=order)}


# --- Rep call-list workflow -------------------------------------------------

# The dispositions a rep can set on a lead from the call list.
CALL_STATUSES = {"contacted", "not_interested", "follow_up", "high_priority"}
# Worked or dead leads drop off the call list; everything else stays queued.
_CALL_LIST_HIDDEN = ("contacted", "not_interested")


def _ensure_lead_columns(engine) -> None:
    """Add the rep-workflow column the base schema doesn't create
    (`disposition` = the call-list status a rep sets). Idempotent and
    best-effort, matching the other ad-hoc migrations here (no Alembic). Only
    the call-list/status paths touch this column, so the core read endpoints
    are unaffected whether or not it exists yet."""
    insp = inspect(engine)
    if not insp.has_table("leads"):
        return
    try:
        cols = {c["name"] for c in insp.get_columns("leads")}
        if "disposition" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS disposition TEXT"))
    except Exception:
        pass


def call_list(limit: int = 20, dataset_id: str | None = None) -> list[dict]:
    """The rep's prioritized call queue: highest-scoring leads that still need
    working. Leads marked contacted/not_interested drop off; high_priority
    floats to the top. Same view columns as the other lead lists, plus the
    current disposition."""
    engine = get_engine()
    _ensure_lead_columns(engine)
    if not inspect(engine).has_table("leads"):
        return []
    hidden = ", ".join(f"'{s}'" for s in _CALL_LIST_HIDDEN)  # fixed literals, not user input
    params: dict = {"limit": limit}
    scope = _dataset_clause(dataset_id, params)
    sql = (
        f"SELECT {_LEAD_VIEW_COLUMNS}, disposition FROM leads "
        f"WHERE quality_score IS NOT NULL AND (disposition IS NULL OR disposition NOT IN ({hidden})){scope} "
        f"ORDER BY (CASE WHEN disposition = 'high_priority' THEN 0 ELSE 1 END), quality_score DESC "
        f"LIMIT :limit"
    )
    try:
        with engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(text(sql), params)]
    except Exception:
        return []


def set_disposition(lead_id: str, status: str) -> bool:
    """Set a lead's call disposition. Returns False if the lead_id doesn't
    exist (so the API can 404), True on a successful update. Status validity
    is enforced at the API layer against CALL_STATUSES."""
    engine = get_engine()
    _ensure_lead_columns(engine)
    try:
        with engine.begin() as conn:
            # Check existence explicitly rather than trusting UPDATE rowcount --
            # DuckDB (dev fallback) doesn't report affected-row counts reliably,
            # so the caller can't distinguish "updated" from "no such lead" off
            # rowcount alone.
            exists = conn.execute(
                text("SELECT 1 FROM leads WHERE lead_id = :id LIMIT 1"), {"id": lead_id}
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                text("UPDATE leads SET disposition = :status WHERE lead_id = :id"),
                {"status": status, "id": lead_id},
            )
            return True
    except Exception:
        return False


def source_performance(dataset_id: str | None = None) -> list[dict]:
    """Per-source scorecard for the Source Performance view: volume, average
    quality score, and the junk rate (share of everything a source sent that
    failed validation). Reuses get_analytics' aggregates -- no extra scan."""
    a = get_analytics(dataset_id)
    by = a["by_source"]
    inv = a["invalid_by_source"]
    dup = a["duplicate_by_source"]

    rows = []
    for source in sorted(set(by) | set(inv) | set(dup)):
        m = by.get(source, {})
        kept = int(m.get("total", 0))
        scored = int(m.get("scored", 0))
        sum_score = float(m.get("sum_score", 0.0))
        invalid = int(inv.get(source, 0))
        duplicates = int(dup.get(source, 0))
        ingested = kept + invalid + duplicates
        rows.append(
            {
                "source": source,
                "leads": kept,
                "clean": int(m.get("clean", 0)),
                "flagged": int(m.get("flagged", 0)),
                "invalid": invalid,
                "duplicates": duplicates,
                "avg_score": round(sum_score / scored, 1) if scored else None,
                "junk_percentage": round(invalid / ingested * 100, 1) if ingested else 0.0,
            }
        )
    # Best sources first (highest avg score); unscored sources sink to the end.
    rows.sort(key=lambda r: (r["avg_score"] is None, -(r["avg_score"] or 0)))
    return rows


# --- Pipeline run tracking --------------------------------------------------

# The lead-data tables a workspace reset clears (operational history + rows).
_RESET_TABLES = ("leads", "duplicate_leads", "invalid_leads", "healing_events", "pipeline_runs", "datasets")


def _ensure_pipeline_runs(engine) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS pipeline_runs ("
                    "run_id TEXT PRIMARY KEY, source TEXT, status TEXT, "
                    "total_records INTEGER, processed INTEGER, failed INTEGER, duplicates INTEGER, "
                    "started_at TEXT, finished_at TEXT, time_taken_ms BIGINT)"
                )
            )
    except Exception:
        pass


def create_pipeline_run(source: str) -> str:
    """Open a pipeline-run record (status='processing') and return its id. The
    ingest endpoints call this at the start of a batch so a run is observable
    while it's in flight and recorded as history once it finishes."""
    engine = get_engine()
    _ensure_pipeline_runs(engine)
    run_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO pipeline_runs (run_id, source, status, started_at) VALUES (:r, :s, 'processing', :t)"),
                {"r": run_id, "s": source, "t": datetime.now(timezone.utc).isoformat()},
            )
    except Exception:
        pass
    return run_id


def finish_pipeline_run(
    run_id: str,
    *,
    status: str = "completed",
    total: int = 0,
    processed: int = 0,
    failed: int = 0,
    duplicates: int = 0,
) -> None:
    """Close out a run: set the final counts, status, and elapsed time."""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT started_at FROM pipeline_runs WHERE run_id = :r"), {"r": run_id}).fetchone()
            now = datetime.now(timezone.utc)
            ms = None
            if row and row[0]:
                try:
                    ms = int((now - datetime.fromisoformat(row[0])).total_seconds() * 1000)
                except Exception:
                    ms = None
            conn.execute(
                text(
                    "UPDATE pipeline_runs SET status = :st, total_records = :tot, processed = :p, "
                    "failed = :f, duplicates = :d, finished_at = :fin, time_taken_ms = :ms WHERE run_id = :r"
                ),
                {"st": status, "tot": total, "p": processed, "f": failed, "d": duplicates,
                 "fin": now.isoformat(), "ms": ms, "r": run_id},
            )
    except Exception:
        pass


def get_pipeline_run(run_id: str) -> dict | None:
    engine = get_engine()
    _ensure_pipeline_runs(engine)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM pipeline_runs WHERE run_id = :r"), {"r": run_id}).fetchone()
            return dict(row._mapping) if row else None
    except Exception:
        return None


def recent_pipeline_runs(limit: int = 20) -> list[dict]:
    engine = get_engine()
    _ensure_pipeline_runs(engine)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT :limit"), {"limit": limit}
            )
            return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def clear_lead_tables() -> dict[str, str]:
    """Delete all rows from the lead-data tables (workspace reset, clear-only).
    Best-effort per table; skips ones that don't exist yet."""
    engine = get_engine()
    result: dict[str, str] = {}
    insp = inspect(engine)
    for table in _RESET_TABLES:
        if not insp.has_table(table):
            result[table] = "absent"
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f'DELETE FROM "{table}"'))
            result[table] = "cleared"
        except Exception as exc:  # noqa: BLE001
            result[table] = f"error: {exc}"
    return result


# --- Datasets (upload containers) ------------------------------------------

_DATASET_COLUMNS = (
    "dataset_id, name, file_name, source_kind, status, total_leads, clean, flagged, "
    "invalid, duplicates, avg_score, notes, tags, created_at, finished_at, time_taken_ms"
)


def _ensure_datasets(engine) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS datasets ("
                    "dataset_id TEXT PRIMARY KEY, name TEXT, file_name TEXT, source_kind TEXT, status TEXT, "
                    "total_leads INTEGER, clean INTEGER, flagged INTEGER, invalid INTEGER, duplicates INTEGER, "
                    "avg_score REAL, notes TEXT, tags TEXT, created_at TEXT, finished_at TEXT, time_taken_ms BIGINT)"
                )
            )
    except Exception:
        pass


def create_dataset(name: str, file_name: str | None, source_kind: str) -> str:
    """Open a dataset (status='processing') for one upload/ingest and return
    its id. Leads/invalid/duplicate rows for this batch are tagged with it."""
    engine = get_engine()
    _ensure_datasets(engine)
    dataset_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO datasets (dataset_id, name, file_name, source_kind, status, created_at) "
                    "VALUES (:id, :n, :f, :s, 'processing', :t)"
                ),
                {"id": dataset_id, "n": name, "f": file_name, "s": source_kind, "t": datetime.now(timezone.utc).isoformat()},
            )
    except Exception:
        pass
    return dataset_id


def finish_dataset(dataset_id: str, *, status: str = "completed") -> None:
    """Close a dataset: recompute its cached counts (clean/flagged/invalid/
    duplicates/avg) from the rows tagged with it, and stamp status + elapsed."""
    engine = get_engine()

    def scalar(conn, sql: str, default=0):
        try:
            v = conn.execute(text(sql), {"id": dataset_id}).scalar()
            return v if v is not None else default
        except Exception:
            return default

    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT created_at FROM datasets WHERE dataset_id = :id"), {"id": dataset_id}).fetchone()
            now = datetime.now(timezone.utc)
            ms = None
            if row and row[0]:
                try:
                    ms = int((now - datetime.fromisoformat(row[0])).total_seconds() * 1000)
                except Exception:
                    ms = None
            clean = scalar(conn, "SELECT count(*) FROM leads WHERE dataset_id = :id AND status = 'clean'")
            flagged = scalar(conn, "SELECT count(*) FROM leads WHERE dataset_id = :id AND status = 'flagged'")
            total = scalar(conn, "SELECT count(*) FROM leads WHERE dataset_id = :id")
            avg = scalar(conn, "SELECT avg(quality_score) FROM leads WHERE dataset_id = :id", default=None)
            invalid = scalar(conn, "SELECT count(*) FROM invalid_leads WHERE dataset_id = :id")
            dups = scalar(conn, "SELECT count(*) FROM duplicate_leads WHERE dataset_id = :id")
            conn.execute(
                text(
                    "UPDATE datasets SET status = :st, total_leads = :tot, clean = :c, flagged = :fl, "
                    "invalid = :inv, duplicates = :d, avg_score = :avg, finished_at = :fin, time_taken_ms = :ms "
                    "WHERE dataset_id = :id"
                ),
                {"st": status, "tot": total, "c": clean, "fl": flagged, "inv": invalid, "d": dups,
                 "avg": round(avg, 1) if avg is not None else None, "fin": now.isoformat(), "ms": ms, "id": dataset_id},
            )
    except Exception:
        pass


def get_dataset(dataset_id: str) -> dict | None:
    engine = get_engine()
    _ensure_datasets(engine)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"SELECT {_DATASET_COLUMNS} FROM datasets WHERE dataset_id = :id"), {"id": dataset_id}).fetchone()
            return dict(row._mapping) if row else None
    except Exception:
        return None


def list_datasets(limit: int = 100) -> list[dict]:
    engine = get_engine()
    _ensure_datasets(engine)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT {_DATASET_COLUMNS} FROM datasets ORDER BY created_at DESC LIMIT :limit"), {"limit": limit})
            return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def update_dataset(dataset_id: str, name: str | None = None, notes: str | None = None, tags: str | None = None) -> bool:
    """Rename / annotate a dataset. Returns False if it doesn't exist."""
    engine = get_engine()
    _ensure_datasets(engine)
    sets, params = [], {"id": dataset_id}
    if name is not None:
        sets.append("name = :name"); params["name"] = name.strip() or "Untitled dataset"
    if notes is not None:
        sets.append("notes = :notes"); params["notes"] = notes
    if tags is not None:
        sets.append("tags = :tags"); params["tags"] = tags
    if not sets:
        return get_dataset(dataset_id) is not None
    try:
        with engine.begin() as conn:
            if not conn.execute(text("SELECT 1 FROM datasets WHERE dataset_id = :id LIMIT 1"), {"id": dataset_id}).fetchone():
                return False
            conn.execute(text(f"UPDATE datasets SET {', '.join(sets)} WHERE dataset_id = :id"), params)
            return True
    except Exception:
        return False


def delete_dataset(dataset_id: str) -> bool:
    """Delete a dataset and every row tagged with it (leads, duplicates,
    invalid, healing events). Returns False if the dataset doesn't exist."""
    engine = get_engine()
    _ensure_datasets(engine)
    insp = inspect(engine)
    try:
        with engine.begin() as conn:
            if not conn.execute(text("SELECT 1 FROM datasets WHERE dataset_id = :id LIMIT 1"), {"id": dataset_id}).fetchone():
                return False
            for table in ("leads", "duplicate_leads", "invalid_leads", "healing_events"):
                if insp.has_table(table):
                    conn.execute(text(f'DELETE FROM "{table}" WHERE dataset_id = :id'), {"id": dataset_id})
            conn.execute(text("DELETE FROM datasets WHERE dataset_id = :id"), {"id": dataset_id})
            return True
    except Exception:
        return False


def backfill_datasets_by_source() -> dict:
    """One-time migration: any leads/invalid/duplicate/healing rows with no
    dataset_id (the pre-datasets data) get grouped into one dataset per source,
    so existing data becomes browsable datasets instead of disappearing.
    Idempotent -- only touches rows where dataset_id IS NULL."""
    engine = get_engine()
    _ensure_datasets(engine)
    insp = inspect(engine)
    if not insp.has_table("leads"):
        return {"datasets_created": 0}
    # Make sure the dataset_id column exists on every table before we group by it.
    for table in ("leads", "duplicate_leads", "invalid_leads", "healing_events"):
        if insp.has_table(table):
            _ensure_columns(engine, table, ["dataset_id"])

    created = 0
    try:
        with engine.connect() as conn:
            sources = [s for (s,) in conn.execute(text("SELECT DISTINCT source FROM leads WHERE dataset_id IS NULL")) if s]
        for source in sources:
            dataset_id = str(uuid.uuid4())
            name = f"{source.replace('_', ' ').title()} feed (imported)"
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO datasets (dataset_id, name, file_name, source_kind, status, created_at) "
                        "VALUES (:id, :n, NULL, :s, 'completed', :t)"
                    ),
                    {"id": dataset_id, "n": name, "s": source, "t": datetime.now(timezone.utc).isoformat()},
                )
                for table in ("leads", "duplicate_leads", "invalid_leads", "healing_events"):
                    if insp.has_table(table):
                        conn.execute(
                            text(f'UPDATE "{table}" SET dataset_id = :did WHERE source = :s AND dataset_id IS NULL'),
                            {"did": dataset_id, "s": source},
                        )
            finish_dataset(dataset_id, status="completed")
            created += 1
    except Exception:
        pass
    return {"datasets_created": created}


def get_analytics(dataset_id: str | None = None) -> dict:
    """Everything the dashboard's charts and KPIs need, computed as SQL
    aggregates in a handful of GROUP BY queries instead of shipping all
    ~34k leads to the browser to be reduced client-side (the old
    /leads?limit=100000 -> 32 MB path). The payload here is a few KB
    regardless of table size. Scoped to one dataset when dataset_id is given,
    otherwise aggregates across all datasets."""
    engine = get_engine()
    params = {"did": dataset_id} if dataset_id else {}
    lead_where = "WHERE dataset_id = :did" if dataset_id else ""
    lead_and = "AND dataset_id = :did" if dataset_id else ""

    def rows(sql: str) -> list[tuple]:
        try:
            with engine.connect() as conn:
                return list(conn.execute(text(sql), params))
        except Exception:
            return []

    # Per-source metrics: counts, score sum (for averages) and per-signal
    # completeness (email/phone/consent/campaign/name present), all in one pass.
    by_source: dict[str, dict] = {}
    for r in rows(
        f"""
        SELECT source,
               count(*)                                                         AS total,
               sum(CASE WHEN status = 'clean'   THEN 1 ELSE 0 END)              AS clean,
               sum(CASE WHEN status = 'flagged' THEN 1 ELSE 0 END)              AS flagged,
               count(quality_score)                                            AS scored,
               coalesce(sum(quality_score), 0)                                 AS sum_score,
               sum(CASE WHEN email        IS NOT NULL AND email        <> '' THEN 1 ELSE 0 END) AS email,
               sum(CASE WHEN phone_e164   IS NOT NULL AND phone_e164   <> '' THEN 1 ELSE 0 END) AS phone,
               sum(CASE WHEN consent THEN 1 ELSE 0 END)                        AS consent,
               sum(CASE WHEN campaign_id  IS NOT NULL AND campaign_id  <> '' THEN 1 ELSE 0 END) AS campaign,
               sum(CASE WHEN first_name   IS NOT NULL AND first_name   <> '' THEN 1 ELSE 0 END) AS name
        FROM leads {lead_where} GROUP BY source
        """
    ):
        source, total, clean, flagged, scored, sum_score, email, phone, consent, campaign, name = r
        by_source[source] = {
            "total": int(total or 0),
            "clean": int(clean or 0),
            "flagged": int(flagged or 0),
            "scored": int(scored or 0),
            "sum_score": float(sum_score or 0),
            "email": int(email or 0),
            "phone": int(phone or 0),
            "consent": int(consent or 0),
            "campaign": int(campaign or 0),
            "name": int(name or 0),
        }

    # Score histogram in 10-point buckets, split by source and status.
    buckets = [
        {"source": src, "status": status, "bucket": int(bucket), "count": int(count)}
        for src, status, bucket, count in rows(
            f"""
            SELECT source, status, floor(quality_score / 10) AS bucket, count(*) AS count
            FROM leads WHERE quality_score IS NOT NULL {lead_and}
            GROUP BY source, status, floor(quality_score / 10)
            """
        )
    ]

    invalid_by_source = {src: int(c) for src, c in rows(f"SELECT source, count(*) FROM invalid_leads {lead_where} GROUP BY source")}
    duplicate_by_source = {src: int(c) for src, c in rows(f"SELECT source, count(*) FROM duplicate_leads {lead_where} GROUP BY source")}

    return {
        "by_source": by_source,
        "buckets": buckets,
        "invalid_by_source": invalid_by_source,
        "duplicate_by_source": duplicate_by_source,
    }


def get_stats(dataset_id: str | None = None) -> dict:
    """Same numbers as before, but via SQL aggregation instead of loading
    entire tables into pandas. Scoped to one dataset when dataset_id is given,
    otherwise across all datasets."""
    engine = get_engine()
    params = {"did": dataset_id} if dataset_id else {}
    where = "WHERE dataset_id = :did" if dataset_id else ""
    lead_and = "AND dataset_id = :did" if dataset_id else ""

    def scalar(sql: str, default=0):
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), params).scalar()
                return result if result is not None else default
        except Exception:
            return default

    def rows(sql: str) -> list[tuple]:
        try:
            with engine.connect() as conn:
                return list(conn.execute(text(sql), params))
        except Exception:
            return []

    leads_by_source = {source: count for source, count in rows(f"SELECT source, count(*) FROM leads {where} GROUP BY source")}

    return {
        "leads_by_source": leads_by_source,
        "total_clean": scalar(f"SELECT count(*) FROM leads WHERE status = 'clean' {lead_and}"),
        "total_flagged": scalar(f"SELECT count(*) FROM leads WHERE status = 'flagged' {lead_and}"),
        "total_invalid": scalar(f"SELECT count(*) FROM invalid_leads {where}"),
        "total_duplicates": scalar(f"SELECT count(*) FROM duplicate_leads {where}"),
        "avg_quality_score": round(scalar(f"SELECT avg(quality_score) FROM leads {where}", default=0.0) or 0.0, 2) or None,
        "self_healing_events": scalar(f"SELECT count(*) FROM healing_events {where}"),
    }
