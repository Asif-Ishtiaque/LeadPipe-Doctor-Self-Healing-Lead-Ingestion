"""QuaLead AI dashboard -- premium B2B SaaS UI over the LeadPipe Doctor
pipeline. Leads-per-source, clean-vs-dirty rate, score distribution,
self-healing events, dedup stats, per-lead diagnosis, and drag-and-drop
lead upload.

Fetches everything from the FastAPI service (API_BASE_URL) rather than
opening the database directly. DuckDB (the local dev fallback) only
supports a single writer process at a time -- if the dashboard also opened
its own connection, it would lock out the API process running alongside
it. Going through the API keeps exactly one process touching the database,
which works the same way whether that database is DuckDB or Postgres.

Run with: streamlit run dashboard/streamlit_app.py
"""

import json
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# --- Design tokens (the product's color system) ---------------------------
PRIMARY = "#2563EB"   # deep blue
SUCCESS = "#16A34A"   # green   -> high quality
WARNING = "#F59E0B"   # amber   -> medium
ERROR = "#DC2626"     # red     -> low
INK = "#0F172A"       # near-black text
MUTED = "#64748B"     # secondary text
LINE = "#E2E8F0"      # hairline borders

# Status -> color, reused by charts and badges so a "flagged" lead is the
# same amber everywhere.
STATUS_COLORS = {"clean": SUCCESS, "flagged": WARNING, "duplicate": "#7C3AED", "invalid": ERROR}
# Categorical sequence for by-source charts -- tints of the brand blue plus
# the status accents, so charts read as one calm system, not a rainbow.
CHART_SEQ = [PRIMARY, "#7C3AED", "#0EA5E9", "#F59E0B", "#16A34A", "#DC2626", "#64748B", "#14B8A6"]

st.set_page_config(page_title="QuaLead AI", page_icon="\U0001F52E", layout="wide")

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    :root {{
        --primary: {PRIMARY}; --success: {SUCCESS}; --warning: {WARNING};
        --error: {ERROR}; --ink: {INK}; --muted: {MUTED}; --line: {LINE};
    }}
    #MainMenu, footer, header {{ visibility: hidden; }}
    html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1280px; }}

    /* --- top bar --- */
    .qa-topbar {{ display: flex; align-items: center; gap: 12px; }}
    .qa-logo {{
        width: 38px; height: 38px; border-radius: 10px; flex: none;
        background: linear-gradient(135deg, #2563EB 0%, #7C3AED 100%);
        display: flex; align-items: center; justify-content: center;
        font-size: 20px; box-shadow: 0 4px 12px rgba(37,99,235,0.28);
    }}
    .qa-wordmark {{ font-size: 1.35rem; font-weight: 700; color: var(--ink); letter-spacing: -0.02em; line-height: 1; }}
    .qa-tagline {{ font-size: 0.82rem; color: var(--muted); margin-top: 2px; }}
    .qa-live {{
        font-size: 0.72rem; font-weight: 600; color: var(--success);
        background: #DCFCE7; padding: 4px 11px; border-radius: 999px;
        display: inline-flex; align-items: center; gap: 6px;
    }}
    .qa-live .dot {{ width: 7px; height: 7px; border-radius: 999px; background: var(--success);
        box-shadow: 0 0 0 0 rgba(22,163,74,0.5); animation: qa-pulse 2s infinite; }}
    @keyframes qa-pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(22,163,74,0.5);}} 70% {{ box-shadow: 0 0 0 6px rgba(22,163,74,0);}} 100% {{ box-shadow: 0 0 0 0 rgba(22,163,74,0);}} }}
    .qa-updated {{ font-size: 0.72rem; color: var(--muted); text-align: right; margin-top: 4px; }}

    /* --- cards --- */
    .qa-hero {{
        background: #FFFFFF; border: 1px solid var(--line); border-radius: 16px;
        padding: 22px 24px; box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06);
        height: 100%; transition: box-shadow .18s ease, transform .18s ease;
    }}
    .qa-hero:hover {{ box-shadow: 0 6px 18px rgba(16,24,40,0.08); transform: translateY(-1px); }}
    .qa-hero .lbl {{ font-size: 0.78rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
    .qa-hero .val {{ font-size: 2.35rem; font-weight: 700; color: var(--ink); line-height: 1.1; margin-top: 6px; letter-spacing: -0.03em; }}
    .qa-hero .sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; }}
    .qa-bar {{ height: 6px; border-radius: 999px; background: #EEF2F7; margin-top: 12px; overflow: hidden; }}
    .qa-bar > span {{ display: block; height: 100%; border-radius: 999px; }}

    .qa-stat {{
        background: #FFFFFF; border: 1px solid var(--line); border-radius: 12px;
        padding: 14px 16px; height: 100%; border-left: 4px solid var(--accent);
        transition: box-shadow .18s ease, transform .18s ease;
    }}
    .qa-stat:hover {{ box-shadow: 0 6px 16px rgba(16,24,40,0.07); transform: translateY(-1px); }}
    .qa-stat .lbl {{ font-size: 0.72rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .qa-stat .val {{ font-size: 1.5rem; font-weight: 700; color: var(--ink); line-height: 1.2; margin-top: 2px; }}
    .qa-stat .sub {{ font-size: 0.72rem; color: var(--muted); margin-top: 2px; }}

    /* --- badges --- */
    .qa-badge {{ display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }}

    /* --- score gauge --- */
    .qa-gauge {{ width: 132px; height: 132px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }}
    .qa-gauge .inner {{ width: 104px; height: 104px; border-radius: 50%; background: #FFFFFF; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
    .qa-gauge .num {{ font-size: 2rem; font-weight: 700; color: var(--ink); line-height: 1; }}
    .qa-gauge .of {{ font-size: 0.7rem; color: var(--muted); margin-top: 2px; }}

    /* --- section headings --- */
    h2, h3 {{ color: var(--ink); letter-spacing: -0.01em; }}

    /* --- tabs --- */
    button[data-baseweb="tab"] {{ font-weight: 600; }}

    /* --- primary buttons: deep blue --- */
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
        border-radius: 9px; font-weight: 600; border: 1px solid var(--line);
    }}
    .stFormSubmitButton > button {{ background: var(--primary); color: #FFFFFF; border: none; }}

    section[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid var(--line); }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- data access -----------------------------------------------------------
@st.cache_data(ttl=5)
def fetch(path: str, limit: int = 5000):
    try:
        resp = requests.get(f"{API_BASE_URL}{path}", params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Couldn't reach the API at {API_BASE_URL}{path}: {exc}")
        return []


def parse_json_column(series: pd.Series) -> pd.Series:
    def _safe_load(value):
        try:
            return json.loads(value) if isinstance(value, str) else value
        except (TypeError, json.JSONDecodeError):
            return None

    return series.apply(_safe_load)


def band_color(score) -> str:
    if score is None or pd.isna(score):
        return MUTED
    s = round(score)
    return SUCCESS if s >= 70 else WARNING if s >= 40 else ERROR


def band_label(score) -> str:
    if score is None or pd.isna(score):
        return "Unscored"
    s = round(score)
    return "High" if s >= 70 else "Medium" if s >= 40 else "Low"


def hero_card(col, label, value, sub="", accent=PRIMARY, bar_pct=None):
    bar = ""
    if bar_pct is not None:
        bar = f'<div class="qa-bar"><span style="width:{max(0,min(100,bar_pct)):.0f}%; background:{accent};"></span></div>'
    col.markdown(
        f'<div class="qa-hero"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div><div class="sub">{sub}</div>{bar}</div>',
        unsafe_allow_html=True,
    )


def stat_card(col, label, value, sub="", accent=PRIMARY):
    col.markdown(
        f'<div class="qa-stat" style="--accent:{accent};"><div class="lbl">{label}</div>'
        f'<div class="val">{value:,}</div><div class="sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def badge(text, color) -> str:
    return f'<span class="qa-badge" style="background:{color}1A; color:{color};">{text}</span>'


# --- top bar ----------------------------------------------------------------
bar_left, bar_right = st.columns([3, 1])
with bar_left:
    st.markdown(
        '<div class="qa-topbar"><div class="qa-logo">\U0001F52E</div>'
        '<div><div class="qa-wordmark">QuaLead AI</div>'
        '<div class="qa-tagline">AI lead scoring &amp; diagnosis &mdash; self-healing ingestion</div></div></div>',
        unsafe_allow_html=True,
    )
with bar_right:
    st.markdown(
        f'<div style="text-align:right;"><span class="qa-live"><span class="dot"></span>LIVE</span>'
        f'<div class="qa-updated">Updated {datetime.now().strftime("%H:%M:%S")}</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Refresh", use_container_width=False):
        fetch.clear()
        st.rerun()

st.write("")

leads = pd.DataFrame(fetch("/leads", limit=100_000))
duplicates = pd.DataFrame(fetch("/duplicates", limit=100_000))
invalid = pd.DataFrame(fetch("/invalid", limit=100_000))
healing = pd.DataFrame(fetch("/healing-events", limit=100_000))
review_queue = fetch("/human-review")

# `leads` holds both "clean" and "flagged" rows -- flagged didn't fail
# validation, it just tripped a quality concern (disposable email,
# placeholder name) worth a human glancing at. See
# app/agent/pipeline.py:_flag_quality_concerns.
clean_leads = leads[leads["status"] == "clean"] if not leads.empty and "status" in leads.columns else leads
flagged_leads = leads[leads["status"] == "flagged"] if not leads.empty and "status" in leads.columns else pd.DataFrame()
total_seen = len(leads) + len(duplicates) + len(invalid)

# --- sidebar (brand + filters) ---------------------------------------------
with st.sidebar:
    st.markdown(
        '<div class="qa-topbar" style="margin-bottom:14px;"><div class="qa-logo" style="width:30px;height:30px;font-size:16px;border-radius:8px;">\U0001F52E</div>'
        '<div class="qa-wordmark" style="font-size:1.05rem;">QuaLead AI</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("###### Filters")
    st.caption("Shape the charts and the Leads tab. Headline cards always show all-time totals.")

    sources = sorted(leads["source"].dropna().unique().tolist()) if not leads.empty and "source" in leads.columns else []
    selected_sources = st.multiselect("Source", options=sources, default=sources, help="Which lead feeds to include.")

    statuses = sorted(leads["status"].dropna().unique().tolist()) if not leads.empty and "status" in leads.columns else []
    selected_statuses = st.multiselect("Status", options=statuses, default=statuses, help="clean = ready to work; flagged = needs a glance.")

    if not leads.empty and "quality_score" in leads.columns and leads["quality_score"].notna().any():
        score_min, score_max = float(leads["quality_score"].min()), float(leads["quality_score"].max())
        score_range = st.slider("Quality score range", 0.0, 100.0, (score_min, score_max), help="Filter leads by their 0-100 quality score.")
    else:
        score_range = (0.0, 100.0)

    st.divider()
    st.caption("Live from the API, refreshed every 5s (or on demand).")

if not leads.empty:
    filtered_leads = leads[
        leads["source"].isin(selected_sources)
        & leads["status"].isin(selected_statuses)
        & leads["quality_score"].fillna(0).between(score_range[0], score_range[1])
    ]
else:
    filtered_leads = leads

# --- hero KPIs (the three the product leads with) --------------------------
workable = pd.concat([clean_leads, flagged_leads]) if not leads.empty else leads
avg_score = workable["quality_score"].dropna().mean() if not workable.empty and "quality_score" in workable.columns else None
high_quality = workable[workable["quality_score"] >= 70] if not workable.empty and "quality_score" in workable.columns else pd.DataFrame()
hq_pct = round(100 * len(high_quality) / len(workable), 1) if len(workable) else 0.0
quality_rate = round(100 * len(clean_leads) / total_seen, 1) if total_seen else 0.0

h1, h2, h3 = st.columns(3)
hero_card(h1, "Total leads", f"{len(leads):,}", f"{total_seen:,} records processed all-time", accent=PRIMARY)
hero_card(
    h2, "Avg lead score",
    f"{avg_score:.0f}" if avg_score is not None else "-",
    f"{band_label(avg_score)} quality on average" if avg_score is not None else "no scored leads yet",
    accent=band_color(avg_score), bar_pct=avg_score if avg_score is not None else 0,
)
hero_card(h3, "High-quality leads", f"{hq_pct}%", f"{len(high_quality):,} leads scoring 70+", accent=SUCCESS, bar_pct=hq_pct)

st.write("")

# --- secondary pipeline-health strip ---------------------------------------
s1, s2, s3, s4 = st.columns(4)
stat_card(s1, "Flagged", len(flagged_leads), "quality concern", accent=WARNING)
stat_card(s2, "Duplicates merged", len(duplicates), "kept the best copy", accent=STATUS_COLORS["duplicate"])
stat_card(s3, "Invalid rows", len(invalid), "unusable input", accent=ERROR)
stat_card(s4, "Self-healing events", len(healing), "code auto-patched", accent=PRIMARY)

st.write("")

tab_overview, tab_quality, tab_healing, tab_leads, tab_upload = st.tabs(
    ["\U0001F4C8  Overview", "\U0001F50E  Data Quality", "\U0001FA79  Self-Healing", "\U0001F465  Leads", "\U0001F4E5  Upload Leads"]
)

with tab_overview:
    left, right = st.columns(2)
    with left:
        st.subheader("Leads by source")
        if not filtered_leads.empty:
            counts = filtered_leads["source"].value_counts().reset_index()
            counts.columns = ["source", "count"]
            fig = px.bar(counts, x="source", y="count", color="source", color_discrete_sequence=CHART_SEQ, text="count")
            fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Leads", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No leads match the current filters yet. Loosen a filter, or upload a batch from the **Upload Leads** tab.")

    with right:
        st.subheader("Where every lead ended up")
        if total_seen:
            rate_df = pd.DataFrame({
                "outcome": ["clean", "flagged", "duplicate", "invalid"],
                "count": [len(clean_leads), len(flagged_leads), len(duplicates), len(invalid)],
            })
            fig = px.pie(rate_df, names="outcome", values="count", hole=0.62, color="outcome", color_discrete_map=STATUS_COLORS)
            fig.update_layout(legend_title=None, paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nothing processed yet. Head to **Upload Leads** to run your first batch.")

    st.subheader("Quality score distribution")
    scored = filtered_leads[filtered_leads["quality_score"].notna()] if not filtered_leads.empty else filtered_leads
    if not scored.empty:
        fig = px.histogram(scored, x="quality_score", color="status", nbins=20, barmode="stack", color_discrete_map=STATUS_COLORS)
        fig.update_layout(xaxis_title="Quality score", yaxis_title="Leads", legend_title=None, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No scored leads match the current filters.")

    dup_col, invalid_col = st.columns(2)
    with dup_col:
        st.subheader("Recent duplicates")
        if not duplicates.empty:
            cols = [c for c in ["first_name", "last_name", "email", "source", "duplicate_of_lead_id"] if c in duplicates.columns]
            st.dataframe(duplicates[cols].tail(25), use_container_width=True, hide_index=True)
        else:
            st.info("No duplicates yet -- every lead so far is one of a kind.")
    with invalid_col:
        st.subheader("Recent invalid rows")
        if not invalid.empty:
            preview = invalid.tail(25).copy()
            if "record" in preview.columns:
                preview["record"] = parse_json_column(preview["record"])
            st.dataframe(preview, use_container_width=True, hide_index=True)
        else:
            st.info("No invalid rows -- clean inputs all around.")

with tab_quality:
    st.subheader("Where the mess comes from")
    src_col1, src_col2 = st.columns(2)
    with src_col1:
        st.caption("Invalid rows by source -- which feed's payloads fail validation most.")
        if not invalid.empty and "source" in invalid.columns:
            counts = invalid["source"].value_counts().reset_index()
            counts.columns = ["source", "count"]
            fig = px.bar(counts, x="source", y="count", color="source", color_discrete_sequence=CHART_SEQ)
            fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Invalid rows", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No invalid rows recorded yet.")
    with src_col2:
        st.caption("Duplicates by source -- which feed sends the most repeat submissions.")
        if not duplicates.empty and "source" in duplicates.columns:
            counts = duplicates["source"].value_counts().reset_index()
            counts.columns = ["source", "count"]
            fig = px.bar(counts, x="source", y="count", color="source", color_discrete_sequence=CHART_SEQ)
            fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Duplicates", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No duplicates recorded yet.")

    st.subheader("Most common validation failures")
    if not invalid.empty and "errors" in invalid.columns:
        parsed_errors = parse_json_column(invalid["errors"])
        reasons = []
        for error_list in parsed_errors.dropna():
            if isinstance(error_list, list):
                for err in error_list:
                    if isinstance(err, dict):
                        field = ".".join(str(p) for p in err.get("loc", [])) or "unknown field"
                        reasons.append(f"{field}: {err.get('msg', 'invalid value')}")
        if reasons:
            top_reasons = pd.Series(reasons).value_counts().head(10).reset_index()
            top_reasons.columns = ["reason", "count"]
            fig = px.bar(top_reasons.sort_values("count"), x="count", y="reason", orientation="h", color_discrete_sequence=[ERROR])
            fig.update_layout(yaxis_title=None, xaxis_title="Occurrences", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Invalid rows exist, but no parseable error detail was found.")
    else:
        st.info("No invalid rows recorded yet.")

    st.divider()
    st.subheader("Compliance & completeness gaps")
    st.caption("These leads pass validation, so they surface nowhere else -- but they're worth a human glance.")
    gap_col1, gap_col2 = st.columns(2)
    no_consent = pd.DataFrame()
    with gap_col1:
        if not leads.empty and "consent" in leads.columns:
            no_consent = leads[leads["consent"] == False]  # noqa: E712 -- pandas bool column
            rate = round(100 * len(no_consent) / len(leads), 1) if len(leads) else 0.0
            st.metric("No marketing consent", f"{len(no_consent):,}", f"{rate}% of leads", delta_color="off", help="Cannot be cold-called (TCPA). Email only with a lawful basis.")
        else:
            st.metric("No marketing consent", "0")
    with gap_col2:
        if not leads.empty and "campaign_id" in leads.columns:
            no_campaign = leads[leads["campaign_id"].isna() | (leads["campaign_id"] == "")]
            rate = round(100 * len(no_campaign) / len(leads), 1) if len(leads) else 0.0
            st.metric("No campaign tag", f"{len(no_campaign):,}", f"{rate}% unattributable", delta_color="off", help="Can't be tied back to a marketing campaign for ROI.")
        else:
            st.metric("No campaign tag", "0")

    if not no_consent.empty:
        with st.expander(f"Preview {min(len(no_consent), 25)} of {len(no_consent):,} leads collected without consent"):
            cols = [c for c in ["first_name", "last_name", "email", "source", "quality_score", "status"] if c in no_consent.columns]
            st.dataframe(no_consent[cols].head(25), use_container_width=True, hide_index=True)

with tab_healing:
    st.subheader("Self-healing events")
    st.caption("When the cleaning code hits an input shape it's never seen, a local LLM rewrites the failing function and the batch retries -- automatically.")
    if not healing.empty:
        event_col, table_col = st.columns([1, 2])
        with event_col:
            if "exception_type" in healing.columns:
                exc_counts = healing["exception_type"].value_counts().reset_index()
                exc_counts.columns = ["exception_type", "count"]
                fig = px.bar(exc_counts, x="count", y="exception_type", orientation="h", color_discrete_sequence=[PRIMARY])
                fig.update_layout(yaxis_title=None, xaxis_title="Retries", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
                st.plotly_chart(fig, use_container_width=True)
        with table_col:
            st.dataframe(healing, use_container_width=True, hide_index=True)
    else:
        st.info("No self-healing events yet -- the pipeline hasn't hit a code bug it needed to patch (or Ollama isn't running).")

    st.subheader("Human review queue")
    if review_queue:
        st.dataframe(pd.DataFrame(review_queue), use_container_width=True, hide_index=True)
    else:
        st.success("Queue is empty -- nothing has exhausted its self-healing retries.")

with tab_leads:
    st.subheader("Leads")
    search = st.text_input("Search by name or email", placeholder="e.g. curie or marie.curie@radiuminstitute.com", label_visibility="collapsed")
    table = filtered_leads
    if search and not table.empty:
        needle = search.lower()
        haystack = table[["first_name", "last_name", "email"]].astype(str).apply(lambda c: c.str.lower())
        mask = haystack.apply(lambda c: c.str.contains(needle, na=False)).any(axis=1)
        table = table[mask]

    st.caption(f"Showing {len(table):,} of {len(leads):,} leads")
    st.dataframe(
        table.sort_values("created_at", ascending=False) if "created_at" in table.columns else table,
        use_container_width=True, hide_index=True,
    )
    if not table.empty:
        st.download_button("Export as CSV", data=table.to_csv(index=False).encode("utf-8"),
                           file_name="qualead_leads.csv", mime="text/csv")

    # --- per-lead diagnosis: the "why + what next" view -----------------
    if not table.empty and "diagnosis" in table.columns:
        st.divider()
        st.subheader("Lead insights")
        detail = table.sort_values("created_at", ascending=False) if "created_at" in table.columns else table
        options = list(range(len(detail)))

        def _label(i: int) -> str:
            row = detail.iloc[i]
            name = " ".join(str(row.get(c) or "").strip() for c in ("first_name", "last_name")).strip() or "(no name)"
            email = row.get("email") or "(no email)"
            score = row.get("quality_score")
            return f"{name} <{email}> - score {score:.0f}" if pd.notna(score) else f"{name} <{email}>"

        idx = st.selectbox("Pick a lead to diagnose", options=options, format_func=_label)
        row = detail.iloc[idx]
        status = str(row.get("status") or "")
        score = row.get("quality_score")
        color = band_color(score)

        gauge_col, detail_col = st.columns([1, 3])
        with gauge_col:
            pct = float(score) if pd.notna(score) else 0
            st.markdown(
                f'<div class="qa-gauge" style="background:conic-gradient({color} {pct*3.6:.0f}deg, #EEF2F7 0deg);">'
                f'<div class="inner"><div class="num" style="color:{color};">{score:.0f}</div><div class="of">/ 100</div></div></div>'
                f'<div style="text-align:center;margin-top:12px;">{badge(band_label(score) + " quality", color)}</div>'
                if pd.notna(score) else
                f'<div class="qa-gauge" style="background:#EEF2F7;"><div class="inner"><div class="num" style="color:{MUTED};">-</div><div class="of">unscored</div></div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<div style="text-align:center;margin-top:10px;">Status &nbsp;{badge(status or "-", STATUS_COLORS.get(status, MUTED))}</div>', unsafe_allow_html=True)
        with detail_col:
            st.markdown("**Diagnosis** &nbsp; <span style='color:#64748B;font-size:0.8rem;'>why this lead scored the way it did</span>", unsafe_allow_html=True)
            st.info(row.get("diagnosis") or "No diagnosis on file -- re-ingest this lead to populate it.")
            st.markdown("**Recommended action** &nbsp; <span style='color:#64748B;font-size:0.8rem;'>what a rep should do next</span>", unsafe_allow_html=True)
            action = row.get("suggested_action")
            if action:
                (st.success if status == "clean" and pd.notna(score) and score >= 70 else st.warning)(action)
            else:
                st.write("No recommended action on file -- re-ingest to populate.")

with tab_upload:
    st.subheader("Upload leads")
    st.caption("Drag a raw export in and QuaLead AI will clean, validate, score, and diagnose every row. Nothing is dropped -- messy leads are flagged, never deleted.")

    up_col, cfg_col = st.columns([2, 1])
    with cfg_col:
        source = st.selectbox(
            "Which feed is this?",
            ["instagram", "google_form", "facebook", "landing_page"],
            help="Picks the right parser. Instagram & Google Form expect CSV; Facebook & landing pages expect JSON / JSONL.",
        )
        is_csv_source = source in ("instagram", "google_form")
        st.caption("CSV expected." if is_csv_source else "JSON or JSONL expected.")
    with up_col:
        uploaded = st.file_uploader(
            "Drop a file here",
            type=["csv", "json", "jsonl", "txt"],
            help="Drag and drop, or browse. Max a few MB for a snappy demo.",
        )

    if uploaded is not None:
        st.caption(f"Ready: **{uploaded.name}** ({uploaded.size / 1024:.0f} KB)")
        if st.button("Analyze leads", type="primary"):
            endpoint = {
                "instagram": "/ingest/instagram",
                "google_form": "/ingest/google-form",
                "facebook": "/ingest/facebook",
                "landing_page": "/ingest/landing-page",
            }[source]
            try:
                with st.spinner("Cleaning, validating, scoring, and diagnosing your leads..."):
                    raw = uploaded.getvalue()
                    if source in ("instagram", "google_form"):
                        resp = requests.post(f"{API_BASE_URL}{endpoint}", files={"file": (uploaded.name, raw)}, timeout=600)
                    else:
                        resp = requests.post(f"{API_BASE_URL}{endpoint}", data=raw,
                                             headers={"Content-Type": "application/json"}, timeout=600)
                resp.raise_for_status()
                summary = resp.json().get("summary") or {}
                st.success("Analysis complete -- your leads are in.")
                st.balloons()
                m1, m2, m3 = st.columns(3)
                m1.metric("Scored & kept", f"{summary.get('scored', 0):,}")
                m2.metric("Duplicates merged", f"{summary.get('duplicates', 0):,}")
                m3.metric("Invalid rows", f"{summary.get('invalid', 0):,}")
                st.caption("Refresh (top right) to see them flow into the dashboard.")
            except requests.RequestException as exc:
                st.error(f"Upload failed: {exc}")
    else:
        st.info("No file yet -- drop a CSV or JSON export above to get started.")
