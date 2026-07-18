"""Streamlit dashboard for LeadPipe Doctor: leads per source, clean vs
dirty rate, score distribution, self-healing events, and dedup stats.

Fetches everything from the FastAPI service (API_BASE_URL) rather than
opening the database directly. DuckDB (the local dev fallback) only
supports a single writer process at a time -- if the dashboard also opened
its own connection, it would lock out the API process running alongside
it. Going through the API keeps exactly one process touching the database,
which works the same way whether that database is DuckDB or Postgres.

Run with: streamlit run dashboard/streamlit_app.py
"""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="LeadPipe Doctor", layout="wide")
st.title("LeadPipe Doctor -- Self-Healing Lead Ingestion")


@st.cache_data(ttl=5)
def fetch(path: str, limit: int = 5000):
    try:
        resp = requests.get(f"{API_BASE_URL}{path}", params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Couldn't reach the API at {API_BASE_URL}{path}: {exc}")
        return []


leads = pd.DataFrame(fetch("/leads", limit=100_000))
duplicates = pd.DataFrame(fetch("/duplicates", limit=100_000))
invalid = pd.DataFrame(fetch("/invalid", limit=100_000))
healing = pd.DataFrame(fetch("/healing-events", limit=100_000))
review_queue = fetch("/human-review")

# `leads` holds both "clean" and "flagged" rows -- flagged didn't fail
# validation, it just tripped a quality concern (disposable email,
# placeholder name) worth a human glancing at before treating it like a
# normal lead. See app/agent/pipeline.py:_flag_quality_concerns.
clean_leads = leads[leads["status"] == "clean"] if not leads.empty and "status" in leads.columns else leads
flagged_leads = leads[leads["status"] == "flagged"] if not leads.empty and "status" in leads.columns else pd.DataFrame()

total_seen = len(leads) + len(duplicates) + len(invalid)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Clean leads", len(clean_leads))
col2.metric("Flagged leads", len(flagged_leads))
col3.metric("Duplicates removed", len(duplicates))
col4.metric("Invalid rows", len(invalid))
col5.metric("Self-healing events", len(healing))
col6.metric("Pending human review", len(review_queue))

st.divider()

left, right = st.columns(2)

with left:
    st.subheader("Leads per source")
    if not leads.empty:
        counts = leads["source"].value_counts().reset_index()
        counts.columns = ["source", "count"]
        st.plotly_chart(px.bar(counts, x="source", y="count"), use_container_width=True)
    else:
        st.info("No clean leads yet -- ingest some data first.")

with right:
    st.subheader("Clean vs. dirty rate")
    if total_seen:
        rate_df = pd.DataFrame(
            {
                "outcome": ["clean", "flagged", "duplicate", "invalid"],
                "count": [len(clean_leads), len(flagged_leads), len(duplicates), len(invalid)],
            }
        )
        st.plotly_chart(px.pie(rate_df, names="outcome", values="count"), use_container_width=True)
    else:
        st.info("No data processed yet.")

st.divider()

st.subheader("Lead quality score distribution")
if not leads.empty and "quality_score" in leads.columns:
    st.plotly_chart(px.histogram(leads, x="quality_score", nbins=20), use_container_width=True)
else:
    st.info("No scored leads yet.")

st.divider()

st.subheader("Self-healing events")
if not healing.empty:
    st.dataframe(healing, use_container_width=True)
else:
    st.info("No self-healing events recorded yet -- the pipeline hasn't hit a code bug (or Ollama isn't running).")

st.subheader("Human review queue")
if review_queue:
    st.dataframe(pd.DataFrame(review_queue), use_container_width=True)
else:
    st.info("Empty -- nothing has exhausted self-healing retries.")

st.divider()
st.subheader("Latest clean leads")
if not leads.empty:
    st.dataframe(leads.tail(50), use_container_width=True)
