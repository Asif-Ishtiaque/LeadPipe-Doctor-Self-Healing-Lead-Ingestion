"""FastAPI entrypoint for LeadPipe Doctor.

Each /ingest/* route accepts one source's raw input, runs it through the
self-healing agent graph (ingest -> map -> clean -> validate -> dedup ->
score, with automatic LLM-driven recovery if the cleaning engine throws),
persists the results, and returns a summary."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse

from app.agent import human_review
from app.agent.graph import run_self_healing
from app.schema.canonical import LeadSource
from app.utils.storage import get_stats, persist_leads_atomic, read_table, save_healing_events, save_invalid, save_leads

app = FastAPI(title="LeadPipe Doctor", description="Self-healing lead ingestion agent")


def _persist_and_summarize(source: LeadSource, final_state: dict) -> dict[str, Any]:
    result = final_state.get("result")
    summary = None
    if result is not None:
        # persist_leads_atomic is the actual source of truth for what got
        # kept vs. deduped -- it can reclassify a lead that in-batch dedup
        # upstream thought was "kept" into a duplicate, if a concurrent
        # request already claimed that email/phone first. The summary
        # reflects that real outcome, not the pre-persistence guess.
        actually_kept, redirected = persist_leads_atomic(result.scored_leads)
        all_duplicates = result.duplicates + redirected
        save_leads(all_duplicates, table="duplicate_leads")
        save_invalid(result.invalid, source=source.value)

        summary = {**result.summary, "scored": len(actually_kept), "duplicates": len(all_duplicates)}

    save_healing_events(source.value, final_state["healing_events"])

    return {
        "status": final_state["status"],
        "retries": final_state["retries"],
        "healing_events": final_state["healing_events"],
        "summary": summary,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest/facebook")
async def ingest_facebook(request: Request) -> JSONResponse:
    # Raw body, not a Pydantic-parsed dict: accepts either one JSON
    # document or JSONL (one webhook payload per line) -- FastAPI's
    # automatic body parsing would reject JSONL as invalid JSON before
    # our code ever saw it, since multiple newline-separated objects
    # aren't one valid JSON document.
    raw_text = (await request.body()).decode()
    final_state = run_self_healing(LeadSource.FACEBOOK, raw_text)
    return JSONResponse(_persist_and_summarize(LeadSource.FACEBOOK, final_state))


@app.post("/ingest/landing-page")
async def ingest_landing_page(request: Request) -> JSONResponse:
    raw_text = (await request.body()).decode()
    final_state = run_self_healing(LeadSource.LANDING_PAGE, raw_text)
    return JSONResponse(_persist_and_summarize(LeadSource.LANDING_PAGE, final_state))


@app.post("/ingest/instagram")
async def ingest_instagram(file: UploadFile) -> JSONResponse:
    csv_text = (await file.read()).decode()
    final_state = run_self_healing(LeadSource.INSTAGRAM, csv_text)
    return JSONResponse(_persist_and_summarize(LeadSource.INSTAGRAM, final_state))


@app.post("/ingest/google-form")
async def ingest_google_form(file: UploadFile) -> JSONResponse:
    csv_text = (await file.read()).decode()
    final_state = run_self_healing(LeadSource.GOOGLE_FORM, csv_text)
    return JSONResponse(_persist_and_summarize(LeadSource.GOOGLE_FORM, final_state))


@app.get("/leads")
def list_leads(limit: int = 100) -> list[dict[str, Any]]:
    df = read_table("leads")
    return df.tail(limit).to_dict(orient="records")


@app.get("/duplicates")
def list_duplicates(limit: int = 1000) -> list[dict[str, Any]]:
    df = read_table("duplicate_leads")
    return df.tail(limit).to_dict(orient="records")


@app.get("/invalid")
def list_invalid(limit: int = 1000) -> list[dict[str, Any]]:
    df = read_table("invalid_leads")
    return df.tail(limit).to_dict(orient="records")


@app.get("/healing-events")
def list_healing_events(limit: int = 1000) -> list[dict[str, Any]]:
    df = read_table("healing_events")
    return df.tail(limit).to_dict(orient="records")


@app.get("/stats")
def stats() -> dict[str, Any]:
    # SQL-aggregated (COUNT/AVG/GROUP BY) rather than loading entire
    # tables into pandas -- see app/utils/storage.py:get_stats for why.
    return {**get_stats(), "human_review_pending": len(human_review.read_all())}


@app.get("/human-review")
def list_human_review() -> list[dict[str, Any]]:
    return human_review.read_all()
