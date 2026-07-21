"""Persistence for pipeline output. Backed by Postgres in docker-compose
(DATABASE_URL points at the `db` service) or a local DuckDB file when run
bare-metal for development -- both go through the same SQLAlchemy engine,
so nothing else in the app needs to know which one is active."""

import json
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


def persist_leads_atomic(leads: list[Lead]) -> tuple[list[Lead], list[Lead]]:
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
        df = pd.DataFrame([_lead_to_row(first)])
        df.to_sql("leads", engine, if_exists="append", index=False)
        kept, duplicates = [first], []
        if rest:
            more_kept, more_duplicates = persist_leads_atomic(rest)
            kept += more_kept
            duplicates += more_duplicates
        return kept, duplicates

    _ensure_columns(engine, "leads", list(_lead_to_row(leads[0]).keys()))

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
    for lead in leads:
        email_key = lead.email.lower() if lead.email else None
        with engine.begin() as conn:
            if is_postgres:
                # Lock ordering (email hash, then phone hash) is fixed
                # regardless of which lead is being processed, so two
                # leads racing on both keys in opposite order can't
                # deadlock each other. A lead with neither identifier
                # (schema now allows both to be null -- see
                # app/schema/canonical.py) has nothing to protect against
                # concurrent duplicates, so it skips locking entirely and
                # is always treated as new.
                if email_key:
                    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"email:{email_key}"})
                if lead.phone_e164:
                    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"phone:{lead.phone_e164}"})

            existing = None
            if email_key or lead.phone_e164:
                # lower(email) = NULL and phone_e164 = NULL both evaluate
                # to NULL (never true) in SQL, so passing None through for
                # whichever identifier is missing is safe -- no need for
                # explicit IS NOT NULL guards here.
                existing = conn.execute(
                    text("SELECT lead_id FROM leads WHERE lower(email) = :email OR phone_e164 = :phone LIMIT 1"),
                    {"email": email_key, "phone": lead.phone_e164},
                ).fetchone()

            if existing:
                lead.status = LeadStatus.DUPLICATE
                lead.duplicate_of_lead_id = existing[0]
                duplicates.append(lead)
                continue

            row = _lead_to_row(lead)
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


def _lead_rows(where: str, params: dict, limit: int, order: str) -> list[dict]:
    """Shared reader for the two lead-list endpoints (top / search). Selects
    only the columns the UI renders -- explicitly *not* raw_payload, which is
    by far the largest field and is what made a naive `SELECT *` of the whole
    table a ~32 MB response. `where`/`order` are code-controlled fragments,
    never user text; all user input arrives through bound `params`."""
    engine = get_engine()
    if not inspect(engine).has_table("leads"):
        return []
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT {_LEAD_VIEW_COLUMNS} FROM leads WHERE {where} ORDER BY {order} LIMIT :limit"),
                {**params, "limit": limit},
            )
            return [dict(row._mapping) for row in result]
    except Exception:
        return []


def top_leads(limit: int = 8, source: str | None = None) -> list[dict]:
    """Highest-scoring leads -- the "work these first" list. Ordering and the
    row cap are pushed into SQL so only `limit` rows come back, instead of the
    frontend pulling every lead and sorting client-side."""
    where = "quality_score IS NOT NULL"
    params: dict = {}
    if source:
        where += " AND source = :source"
        params["source"] = source
    return _lead_rows(where, params, limit, order="quality_score DESC")


def search_leads(q: str | None = None, source: str | None = None, limit: int = 200) -> dict:
    """Server-side search for the Leads table. Returns at most `limit` rows
    plus the true total number of matches, so the UI can say "showing N of M"
    without ever downloading M rows. Matching is a case-insensitive substring
    over name/email (bound parameter -> no injection surface)."""
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


def get_analytics() -> dict:
    """Everything the dashboard's charts and KPIs need, computed as SQL
    aggregates in a handful of GROUP BY queries instead of shipping all
    ~34k leads to the browser to be reduced client-side (the old
    /leads?limit=100000 -> 32 MB path). The payload here is a few KB
    regardless of table size: per-source metrics + a small score-bucket
    histogram the frontend re-slices into the butterfly, distribution and
    funnel charts."""
    engine = get_engine()

    def rows(sql: str) -> list[tuple]:
        try:
            with engine.connect() as conn:
                return list(conn.execute(text(sql)))
        except Exception:
            return []

    # Per-source metrics: counts, score sum (for averages) and per-signal
    # completeness (email/phone/consent/campaign/name present), all in one pass.
    by_source: dict[str, dict] = {}
    for r in rows(
        """
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
        FROM leads GROUP BY source
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

    # Score histogram in 10-point buckets, split by source and status. bucket
    # = floor(score/10), so 0..9 with a perfect 100 landing in bucket 10 -- the
    # frontend folds bucket 10 into the top band. ~5 sources x 3 statuses x 11
    # buckets is a tiny, fixed-size result.
    buckets = [
        {"source": src, "status": status, "bucket": int(bucket), "count": int(count)}
        for src, status, bucket, count in rows(
            """
            SELECT source, status, floor(quality_score / 10) AS bucket, count(*) AS count
            FROM leads WHERE quality_score IS NOT NULL
            GROUP BY source, status, floor(quality_score / 10)
            """
        )
    ]

    invalid_by_source = {src: int(c) for src, c in rows("SELECT source, count(*) FROM invalid_leads GROUP BY source")}
    duplicate_by_source = {src: int(c) for src, c in rows("SELECT source, count(*) FROM duplicate_leads GROUP BY source")}

    return {
        "by_source": by_source,
        "buckets": buckets,
        "invalid_by_source": invalid_by_source,
        "duplicate_by_source": duplicate_by_source,
    }


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
