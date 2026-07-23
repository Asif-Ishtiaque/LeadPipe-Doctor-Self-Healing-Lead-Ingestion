"""FastAPI entrypoint for LeadPipe Doctor.

Each /ingest/* route accepts one source's raw input, runs it through the
self-healing agent graph (ingest -> map -> clean -> validate -> dedup ->
score, with automatic LLM-driven recovery if the cleaning engine throws),
persists the results, and returns a summary."""

from __future__ import annotations

from typing import Any

import csv
import io
import os

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.agent import human_review
from app.agent.graph import run_self_healing
from app.mapping import rag_store
from app.schema.canonical import LeadSource
from app.utils.storage import (
    CALL_STATUSES,
    backfill_datasets_by_source,
    call_list,
    clear_lead_tables,
    create_dataset,
    delete_dataset,
    finish_dataset,
    get_analytics,
    get_dataset,
    get_pipeline_run,
    get_stats,
    list_datasets,
    persist_leads_atomic,
    ranked_leads,
    read_recent,
    recent_pipeline_runs,
    save_healing_events,
    save_invalid,
    save_leads,
    search_leads,
    set_disposition,
    source_performance,
    top_leads,
    update_dataset,
)


class StatusUpdate(BaseModel):
    status: str


class ResetOptions(BaseModel):
    leads: bool = True
    review_queue: bool = True
    chroma: bool = False


class DatasetUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    tags: str | None = None

app = FastAPI(title="LeadPipe Doctor", description="Self-healing lead ingestion agent")

# The Streamlit dashboard calls this API server-side, so it never needed
# CORS. The React frontend runs in the browser on a different origin
# (Vite dev :5173, preview :4173, or the nginx container :8080), so those
# fetches are subject to CORS -- without this middleware the browser blocks
# every request. Origins are overridable via CORS_ALLOW_ORIGINS (comma-
# separated); the default covers local dev. No credentials are used, so a
# wildcard is acceptable if you'd rather not enumerate origins.
_cors = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://localhost:4173,http://localhost:8080")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors.split(",") if o.strip()] or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _persist_and_summarize(source: LeadSource, final_state: dict, dataset_id: str | None = None) -> dict[str, Any]:
    result = final_state.get("result")
    summary = None
    if result is not None:
        # persist_leads_atomic is the actual source of truth for what got
        # kept vs. deduped. Everything it writes is tagged with dataset_id so
        # this batch stays isolated in its own dataset (dedup is per-dataset).
        actually_kept, redirected = persist_leads_atomic(result.scored_leads, dataset_id)
        all_duplicates = result.duplicates + redirected
        save_leads(all_duplicates, table="duplicate_leads", dataset_id=dataset_id)
        save_invalid(result.invalid, source=source.value, dataset_id=dataset_id)

        summary = {**result.summary, "scored": len(actually_kept), "duplicates": len(all_duplicates)}

    save_healing_events(source.value, final_state["healing_events"], dataset_id=dataset_id)

    return {
        "status": final_state["status"],
        "retries": final_state["retries"],
        "healing_events": final_state["healing_events"],
        "summary": summary,
    }


def _decode(raw: bytes | str) -> str:
    # Tolerant decode. Excel's default "CSV (Comma delimited)" export is
    # Windows-1252, and "CSV UTF-8" prepends a BOM -- strict UTF-8 would raise
    # UnicodeDecodeError on any accented name or smart quote and 500 the
    # request before the pipeline ever runs. utf-8-sig strips the BOM;
    # errors="replace" guarantees no byte sequence can crash the upload.
    return raw.decode("utf-8-sig", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw


def _run_and_persist(source: LeadSource, raw_text: str, dataset_id: str) -> dict[str, Any]:
    return _persist_and_summarize(source, run_self_healing(source, raw_text), dataset_id)


async def _ingest(
    source: LeadSource,
    raw_text: str,
    *,
    dataset_name: str | None = None,
    file_name: str | None = None,
    dataset_id: str | None = None,
) -> JSONResponse:
    # Blocking I/O (LLM mapping, embeddings, DB writes) runs in a threadpool so
    # the event loop stays free for the dashboard's live polls. Each ingest is
    # one dataset: either a brand-new one (default) or an existing one to add
    # to. An empty upload that creates nothing is rolled back so we don't leave
    # a phantom 0-lead dataset. Failures return a friendly payload, never a 500.
    is_new = dataset_id is None
    if is_new:
        name = (dataset_name or file_name or f"{source.value.replace('_', ' ').title()} import").strip()
        ds_id = await run_in_threadpool(create_dataset, name, file_name, source.value)
    else:
        ds_id = dataset_id
    try:
        result = await run_in_threadpool(_run_and_persist, source, raw_text, ds_id)
        summary = result.get("summary") or {}
        total = int(summary.get("scored", 0) or 0) + int(summary.get("duplicates", 0) or 0) + int(summary.get("invalid", 0) or 0)
        errored = result.get("status") == "error"

        if is_new and total == 0 and not errored:
            # Nothing landed (empty/parseless file) -> don't leave a dataset.
            await run_in_threadpool(delete_dataset, ds_id)
            result["dataset_id"] = None
        else:
            await run_in_threadpool(
                lambda: finish_dataset(ds_id, status="failed" if errored or result.get("status") == "human_review" else "completed")
            )
            result["dataset_id"] = ds_id
        return JSONResponse(result)
    except Exception:
        if is_new:
            await run_in_threadpool(lambda: finish_dataset(ds_id, status="failed"))
        return JSONResponse(
            {
                "status": "error",
                "retries": 0,
                "healing_events": [],
                "summary": None,
                "dataset_id": ds_id,
                "message": "We processed your file but hit a problem saving the results. Please try again.",
            }
        )


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest/facebook")
async def ingest_facebook(request: Request) -> JSONResponse:
    # Raw body, not a Pydantic-parsed dict: accepts either one JSON document
    # or JSONL (one webhook payload per line) -- FastAPI's automatic body
    # parsing would reject JSONL as invalid JSON before our code ever saw it.
    return await _ingest(LeadSource.FACEBOOK, _decode(await request.body()))


@app.post("/ingest/landing-page")
async def ingest_landing_page(request: Request) -> JSONResponse:
    return await _ingest(LeadSource.LANDING_PAGE, _decode(await request.body()))


@app.post("/ingest/instagram")
async def ingest_instagram(file: UploadFile) -> JSONResponse:
    return await _ingest(LeadSource.INSTAGRAM, _decode(await file.read()))


@app.post("/ingest/google-form")
async def ingest_google_form(file: UploadFile) -> JSONResponse:
    return await _ingest(LeadSource.GOOGLE_FORM, _decode(await file.read()))


@app.post("/ingest/csv")
async def ingest_csv(file: UploadFile) -> JSONResponse:
    # Generic "upload any CSV" path: no assumption about column names or which
    # tool produced the file -- the RAG/LLM field mapper resolves the columns.
    # Creates a new dataset named after the file.
    return await _ingest(LeadSource.CSV_UPLOAD, _decode(await file.read()), file_name=file.filename)


@app.post("/datasets/upload")
async def datasets_upload(
    file: UploadFile,
    name: str | None = Form(None),
    dataset_id: str | None = Form(None),
) -> JSONResponse:
    # Dataset-aware upload. Default creates a NEW dataset (named `name`, else
    # the filename). Passing dataset_id adds the file's leads to that existing
    # dataset instead. On success the response carries dataset_id so the UI can
    # navigate straight into the dataset view.
    return await _ingest(
        LeadSource.CSV_UPLOAD, _decode(await file.read()),
        dataset_name=name, file_name=file.filename, dataset_id=dataset_id,
    )


@app.get("/leads")
def list_leads(limit: int = 100) -> list[dict[str, Any]]:
    return read_recent("leads", _clamp(limit, 1, 1000)).to_dict(orient="records")


@app.get("/leads/top")
def list_top_leads(
    limit: int = 8,
    source: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    dataset_id: str | None = None,
) -> list[dict[str, Any]]:
    # Highest-scoring leads for the "work these first" panels. dataset_id scopes
    # to one dataset; omitted aggregates across all.
    return top_leads(limit=_clamp(limit, 1, 200), source=source, min_score=min_score, max_score=max_score, dataset_id=dataset_id)


@app.get("/leads/ranked")
def list_ranked_leads(
    limit: int = 10,
    offset: int = 0,
    source: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    # Paginated score-ranked call list: one page of rows + the true match total.
    return ranked_leads(
        limit=_clamp(limit, 1, 500), offset=max(0, offset), source=source,
        min_score=min_score, max_score=max_score, dataset_id=dataset_id,
    )


@app.get("/leads/search")
def search_leads_endpoint(
    q: str | None = None,
    source: str | None = None,
    limit: int = 200,
    min_score: float | None = None,
    flagged: bool | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    # Server-side search for the Leads table (name/email), with smart-filter
    # params and optional dataset scoping.
    return search_leads(q=q, source=source, limit=_clamp(limit, 1, 500), min_score=min_score, flagged=flagged, dataset_id=dataset_id)


@app.get("/leads/call-list")
def get_call_list(limit: int = 20, dataset_id: str | None = None) -> list[dict[str, Any]]:
    # The rep's prioritized queue, optionally scoped to one dataset.
    return call_list(limit=_clamp(limit, 1, 200), dataset_id=dataset_id)


@app.post("/leads/{lead_id}/status")
def update_lead_status(lead_id: str, body: StatusUpdate) -> JSONResponse:
    # A rep dispositioning a lead from the call list. Unknown status -> 400
    # with the allowed set; unknown lead -> 404. Both are friendly JSON, never
    # a raw stack trace.
    if body.status not in CALL_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Unknown status '{body.status}'.", "allowed": sorted(CALL_STATUSES)},
        )
    if not set_disposition(lead_id, body.status):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Lead not found."})
    return JSONResponse({"status": "ok", "lead_id": lead_id, "disposition": body.status})


@app.get("/analytics/source-performance")
def analytics_source_performance(dataset_id: str | None = None) -> list[dict[str, Any]]:
    # Per-source scorecard: volume, avg quality score, and junk rate.
    return source_performance(dataset_id=dataset_id)


@app.get("/pipeline/runs")
def pipeline_runs(limit: int = 20) -> list[dict[str, Any]]:
    # Recent ingest runs (newest first) for the pipeline-observability view.
    return recent_pipeline_runs(limit=_clamp(limit, 1, 100))


@app.get("/pipeline/status/{run_id}")
def pipeline_status(run_id: str) -> JSONResponse:
    # One run's live status/progress. Unknown id -> friendly 404.
    run = get_pipeline_run(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Run not found."})
    return JSONResponse(run)


@app.get("/datasets")
def datasets_list(limit: int = 100) -> list[dict[str, Any]]:
    # All datasets, newest first, for the Datasets list view.
    return list_datasets(limit=_clamp(limit, 1, 500))


@app.get("/datasets/{dataset_id}")
def datasets_get(dataset_id: str) -> JSONResponse:
    ds = get_dataset(dataset_id)
    if ds is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Dataset not found."})
    return JSONResponse(ds)


@app.patch("/datasets/{dataset_id}")
def datasets_update(dataset_id: str, body: DatasetUpdate) -> JSONResponse:
    # Rename / annotate a dataset. Unknown id -> friendly 404.
    if not update_dataset(dataset_id, name=body.name, notes=body.notes, tags=body.tags):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Dataset not found."})
    return JSONResponse(get_dataset(dataset_id) or {"status": "ok"})


@app.delete("/datasets/{dataset_id}")
def datasets_delete(dataset_id: str) -> JSONResponse:
    # Delete a dataset and every row tagged with it. Unknown id -> 404.
    if not delete_dataset(dataset_id):
        return JSONResponse(status_code=404, content={"status": "error", "message": "Dataset not found."})
    return JSONResponse({"status": "ok", "deleted": dataset_id})


@app.get("/datasets/{dataset_id}/export")
def datasets_export(dataset_id: str):
    # Download a dataset's leads as CSV.
    ds = get_dataset(dataset_id)
    if ds is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Dataset not found."})
    rows = search_leads(limit=1_000_000, dataset_id=dataset_id)["rows"]
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    safe = "".join(c for c in (ds.get("name") or "dataset") if c.isalnum() or c in " -_").strip() or "dataset"
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'},
    )


@app.post("/admin/backfill-datasets")
def admin_backfill_datasets() -> JSONResponse:
    # One-time migration: group pre-datasets leads into one dataset per source.
    return JSONResponse({"status": "ok", **backfill_datasets_by_source()})


@app.post("/admin/reset")
def admin_reset(body: ResetOptions) -> JSONResponse:
    # Destructive: clears the workspace to an empty state (demo reset). Each
    # part is opt-in via the request body; nothing is touched unless asked.
    cleared: dict[str, Any] = {}
    if body.leads:
        cleared["tables"] = clear_lead_tables()
    if body.review_queue:
        try:
            cleared["review_queue_removed"] = human_review.clear()
        except Exception:
            cleared["review_queue_removed"] = 0
    if body.chroma:
        try:
            rag_store.get_client().delete_collection("field_mappings")
            cleared["chroma_mappings"] = "cleared"
        except Exception:
            cleared["chroma_mappings"] = "skipped"
    return JSONResponse({"status": "ok", "cleared": cleared})


@app.get("/analytics")
def analytics(dataset_id: str | None = None) -> dict[str, Any]:
    # SQL-aggregated per-source metrics + score-bucket histogram, optionally
    # scoped to one dataset.
    return get_analytics(dataset_id=dataset_id)


@app.get("/duplicates")
def list_duplicates(limit: int = 1000) -> list[dict[str, Any]]:
    return read_recent("duplicate_leads", limit).to_dict(orient="records")


@app.get("/invalid")
def list_invalid(limit: int = 1000) -> list[dict[str, Any]]:
    return read_recent("invalid_leads", limit).to_dict(orient="records")


@app.get("/healing-events")
def list_healing_events(limit: int = 1000) -> list[dict[str, Any]]:
    return read_recent("healing_events", limit).to_dict(orient="records")


@app.get("/stats")
def stats(dataset_id: str | None = None) -> dict[str, Any]:
    # SQL-aggregated KPIs, optionally scoped to one dataset.
    return {**get_stats(dataset_id=dataset_id), "human_review_pending": len(human_review.read_all())}


@app.get("/human-review")
def list_human_review() -> list[dict[str, Any]]:
    return human_review.read_all()
