"""QuaLead AI dashboard -- premium B2B SaaS UI over the LeadPipe Doctor
pipeline. Everything is chosen from the left drawer: brand, page nav, and
filters. Pages: Overview, Leads, Lead Analytics, Data Quality,
Self-Healing, Upload Leads.

Fetches everything from the FastAPI service (API_BASE_URL) rather than
opening the database directly. DuckDB (the local dev fallback) only
supports a single writer process at a time -- going through the API keeps
exactly one process touching the database, which works the same way
whether that database is DuckDB or Postgres.

Run with: streamlit run dashboard/streamlit_app.py
"""

import json
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# --- Design tokens ---------------------------------------------------------
PRIMARY = "#2563EB"
SUCCESS = "#16A34A"
WARNING = "#F59E0B"
ERROR = "#DC2626"
INK = "#0F172A"
MUTED = "#64748B"
LINE = "#E2E8F0"

STATUS_COLORS = {"clean": SUCCESS, "flagged": WARNING, "duplicate": "#7C3AED", "invalid": ERROR}
CHART_SEQ = [PRIMARY, "#7C3AED", "#0EA5E9", "#F59E0B", "#16A34A", "#DC2626", "#64748B", "#14B8A6"]

st.set_page_config(page_title="QuaLead AI", page_icon="\U0001F52E", layout="wide")

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    :root {{ --primary: {PRIMARY}; --success: {SUCCESS}; --warning: {WARNING};
             --error: {ERROR}; --ink: {INK}; --muted: {MUTED}; --line: {LINE}; }}
    #MainMenu, footer, header {{ visibility: hidden; }}
    html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    .block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1280px; }}
    [data-testid="stAppViewContainer"] {{ background: #F9FAFB; }}

    /* --- sidebar / left drawer --- */
    section[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid var(--line); }}
    section[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}
    .qa-brand {{ display: flex; align-items: center; gap: 11px; padding: 6px 4px 2px; }}
    .qa-logo {{ width: 40px; height: 40px; border-radius: 11px; flex: none;
        background: linear-gradient(135deg, #2563EB 0%, #7C3AED 100%);
        display: flex; align-items: center; justify-content: center; font-size: 21px;
        box-shadow: 0 4px 12px rgba(37,99,235,0.28); }}
    .qa-brand .name {{ font-size: 1.02rem; font-weight: 700; color: var(--ink); line-height: 1.1; }}
    .qa-brand .role {{ font-size: 0.75rem; color: var(--muted); margin-top: 2px; }}
    .qa-navlabel {{ font-size: 0.7rem; font-weight: 600; color: #94A3B8; text-transform: uppercase;
        letter-spacing: 0.06em; margin: 14px 6px 4px; }}
    /* nav buttons: left-aligned rows, active = soft blue pill */
    section[data-testid="stSidebar"] .stButton > button {{
        text-align: left; justify-content: flex-start; border: none; background: transparent;
        font-weight: 600; color: #475569; padding: 9px 12px; border-radius: 10px; font-size: 0.92rem;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover {{ background: #F1F5F9; color: var(--ink); }}
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
        background: #EFF4FF; color: var(--primary); box-shadow: none;
    }}
    .qa-promo {{ background: linear-gradient(135deg, #2563EB 0%, #7C3AED 100%); border-radius: 14px;
        padding: 16px; color: #fff; margin-top: 10px; }}
    .qa-promo .t {{ font-weight: 700; font-size: 0.92rem; }}
    .qa-promo .s {{ font-size: 0.75rem; opacity: 0.9; margin-top: 4px; line-height: 1.35; }}

    /* --- top bar --- */
    .qa-page-title {{ font-size: 1.5rem; font-weight: 700; color: var(--ink); letter-spacing: -0.02em; }}
    .qa-page-sub {{ font-size: 0.85rem; color: var(--muted); margin-top: 2px; }}
    .qa-live {{ font-size: 0.72rem; font-weight: 600; color: var(--success); background: #DCFCE7;
        padding: 4px 11px; border-radius: 999px; display: inline-flex; align-items: center; gap: 6px; }}
    .qa-live .dot {{ width: 7px; height: 7px; border-radius: 999px; background: var(--success);
        animation: qa-pulse 2s infinite; }}
    @keyframes qa-pulse {{ 0%{{box-shadow:0 0 0 0 rgba(22,163,74,.5);}} 70%{{box-shadow:0 0 0 6px rgba(22,163,74,0);}} 100%{{box-shadow:0 0 0 0 rgba(22,163,74,0);}} }}
    .qa-updated {{ font-size: 0.72rem; color: var(--muted); text-align: right; margin-top: 4px; }}

    /* --- cards --- */
    .qa-hero {{ background: #FFFFFF; border: 1px solid var(--line); border-radius: 16px; padding: 22px 24px;
        box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06); height: 100%;
        transition: box-shadow .18s ease, transform .18s ease; }}
    .qa-hero:hover {{ box-shadow: 0 6px 18px rgba(16,24,40,0.08); transform: translateY(-1px); }}
    .qa-hero .lbl {{ font-size: 0.78rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
    .qa-hero .val {{ font-size: 2.3rem; font-weight: 700; color: var(--ink); line-height: 1.1; margin-top: 6px; letter-spacing: -0.03em; }}
    .qa-hero .sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 4px; }}
    .qa-bar {{ height: 6px; border-radius: 999px; background: #EEF2F7; margin-top: 12px; overflow: hidden; }}
    .qa-bar > span {{ display: block; height: 100%; border-radius: 999px; }}
    .qa-stat {{ background: #FFFFFF; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
        height: 100%; border-left: 4px solid var(--accent); transition: box-shadow .18s ease, transform .18s ease; }}
    .qa-stat:hover {{ box-shadow: 0 6px 16px rgba(16,24,40,0.07); transform: translateY(-1px); }}
    .qa-stat .lbl {{ font-size: 0.72rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .qa-stat .val {{ font-size: 1.5rem; font-weight: 700; color: var(--ink); line-height: 1.2; margin-top: 2px; }}
    .qa-stat .sub {{ font-size: 0.72rem; color: var(--muted); margin-top: 2px; }}
    .qa-badge {{ display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }}
    .qa-gauge {{ width: 132px; height: 132px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }}
    .qa-gauge .inner {{ width: 104px; height: 104px; border-radius: 50%; background: #FFFFFF; display: flex; flex-direction: column; align-items: center; justify-content: center; }}
    .qa-gauge .num {{ font-size: 2rem; font-weight: 700; line-height: 1; }}
    .qa-gauge .of {{ font-size: 0.7rem; color: var(--muted); margin-top: 2px; }}
    h2, h3 {{ color: var(--ink); letter-spacing: -0.01em; }}
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{ border-radius: 9px; font-weight: 600; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- data + helpers --------------------------------------------------------
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
    bar = f'<div class="qa-bar"><span style="width:{max(0,min(100,bar_pct)):.0f}%; background:{accent};"></span></div>' if bar_pct is not None else ""
    col.markdown(
        f'<div class="qa-hero"><div class="lbl">{label}</div><div class="val">{value}</div>'
        f'<div class="sub">{sub}</div>{bar}</div>',
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


def transparent(fig):
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0))
    return fig


# --- load ------------------------------------------------------------------
leads = pd.DataFrame(fetch("/leads", limit=100_000))
duplicates = pd.DataFrame(fetch("/duplicates", limit=100_000))
invalid = pd.DataFrame(fetch("/invalid", limit=100_000))
healing = pd.DataFrame(fetch("/healing-events", limit=100_000))
review_queue = fetch("/human-review")

has_leads = not leads.empty and "status" in leads.columns
clean_leads = leads[leads["status"] == "clean"] if has_leads else leads
flagged_leads = leads[leads["status"] == "flagged"] if has_leads else pd.DataFrame()
total_seen = len(leads) + len(duplicates) + len(invalid)

# --- left drawer: brand, nav, filters, footer ------------------------------
PAGES = [
    ("Overview", "\U0001F3E0"),
    ("Leads", "\U0001F465"),
    ("Lead Analytics", "\U0001F4C8"),
    ("Data Quality", "\U0001F50E"),
    ("Self-Healing", "\U0001FA79"),
    ("Upload Leads", "\U0001F4E5"),
]
if "page" not in st.session_state:
    st.session_state.page = "Overview"

with st.sidebar:
    st.markdown(
        '<div class="qa-brand"><div class="qa-logo">\U0001F52E</div>'
        '<div><div class="name">QuaLead AI</div><div class="role">Lead workspace</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="qa-navlabel">Menu</div>', unsafe_allow_html=True)
    for name, icon in PAGES:
        if st.button(f"{icon}  {name}", key=f"nav_{name}", use_container_width=True,
                     type="primary" if st.session_state.page == name else "secondary"):
            st.session_state.page = name
            st.rerun()

    st.markdown('<div class="qa-navlabel">Filters</div>', unsafe_allow_html=True)
    st.caption("Applied to charts, Leads, and Lead Analytics. Headline cards always show all-time totals.")
    sources = sorted(leads["source"].dropna().unique().tolist()) if has_leads and "source" in leads.columns else []
    selected_sources = st.multiselect("Source", options=sources, default=sources, help="Which lead feeds to include.")
    statuses = sorted(leads["status"].dropna().unique().tolist()) if has_leads else []
    selected_statuses = st.multiselect("Status", options=statuses, default=statuses, help="clean = ready to work; flagged = needs a glance.")
    if has_leads and "quality_score" in leads.columns and leads["quality_score"].notna().any():
        smin, smax = float(leads["quality_score"].min()), float(leads["quality_score"].max())
        score_range = st.slider("Quality score range", 0.0, 100.0, (smin, smax))
    else:
        score_range = (0.0, 100.0)

    st.markdown(
        '<div class="qa-promo"><div class="t">\U0001F512 100% local &amp; open source</div>'
        '<div class="s">No paid APIs, no cloud LLM calls. Every model runs on your machine.</div></div>',
        unsafe_allow_html=True,
    )

if has_leads:
    filtered_leads = leads[
        leads["source"].isin(selected_sources)
        & leads["status"].isin(selected_statuses)
        & leads["quality_score"].fillna(0).between(score_range[0], score_range[1])
    ]
else:
    filtered_leads = leads

page = st.session_state.page

# --- top bar ---------------------------------------------------------------
SUBTITLES = {
    "Overview": "Live pipeline health at a glance",
    "Leads": "Every lead, searchable, with its diagnosis",
    "Lead Analytics": "Where the quality is -- and where it leaks",
    "Data Quality": "What's failing, and where the mess comes from",
    "Self-Healing": "The pipeline repairing its own code",
    "Upload Leads": "Drop any CSV and let QuaLead AI sort it out",
}
tb_left, tb_right = st.columns([3, 1])
with tb_left:
    st.markdown(
        f'<div class="qa-page-title">{page}</div><div class="qa-page-sub">{SUBTITLES.get(page, "")}</div>',
        unsafe_allow_html=True,
    )
with tb_right:
    st.markdown(
        f'<div style="text-align:right;"><span class="qa-live"><span class="dot"></span>LIVE</span>'
        f'<div class="qa-updated">Updated {datetime.now().strftime("%H:%M:%S")}</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Refresh"):
        fetch.clear()
        st.rerun()
st.write("")


# ===========================================================================
# PAGES
# ===========================================================================
def page_overview():
    workable = pd.concat([clean_leads, flagged_leads]) if has_leads else leads
    avg_score = workable["quality_score"].dropna().mean() if not workable.empty and "quality_score" in workable.columns else None
    high_quality = workable[workable["quality_score"] >= 70] if not workable.empty and "quality_score" in workable.columns else pd.DataFrame()
    hq_pct = round(100 * len(high_quality) / len(workable), 1) if len(workable) else 0.0

    h1, h2, h3 = st.columns(3)
    hero_card(h1, "Total leads", f"{len(leads):,}", f"{total_seen:,} records processed all-time", accent=PRIMARY)
    hero_card(h2, "Avg lead score", f"{avg_score:.0f}" if avg_score is not None else "-",
              f"{band_label(avg_score)} quality on average" if avg_score is not None else "no scored leads yet",
              accent=band_color(avg_score), bar_pct=avg_score if avg_score is not None else 0)
    hero_card(h3, "High-quality leads", f"{hq_pct}%", f"{len(high_quality):,} leads scoring 70+", accent=SUCCESS, bar_pct=hq_pct)
    st.write("")
    s1, s2, s3, s4 = st.columns(4)
    stat_card(s1, "Flagged", len(flagged_leads), "quality concern", accent=WARNING)
    stat_card(s2, "Duplicates merged", len(duplicates), "kept the best copy", accent=STATUS_COLORS["duplicate"])
    stat_card(s3, "Invalid rows", len(invalid), "unusable input", accent=ERROR)
    stat_card(s4, "Self-healing events", len(healing), "code auto-patched", accent=PRIMARY)
    st.write("")

    left, right = st.columns(2)
    with left:
        st.subheader("Leads by source")
        if not filtered_leads.empty:
            counts = filtered_leads["source"].value_counts().reset_index()
            counts.columns = ["source", "count"]
            fig = px.bar(counts, x="source", y="count", color="source", color_discrete_sequence=CHART_SEQ, text="count")
            fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Leads")
            st.plotly_chart(transparent(fig), use_container_width=True)
        else:
            st.info("No leads match the current filters. Loosen a filter, or add a batch from **Upload Leads**.")
    with right:
        st.subheader("Where every lead ended up")
        if total_seen:
            rate_df = pd.DataFrame({"outcome": ["clean", "flagged", "duplicate", "invalid"],
                                    "count": [len(clean_leads), len(flagged_leads), len(duplicates), len(invalid)]})
            fig = px.pie(rate_df, names="outcome", values="count", hole=0.62, color="outcome", color_discrete_map=STATUS_COLORS)
            fig.update_layout(legend_title=None)
            st.plotly_chart(transparent(fig), use_container_width=True)
        else:
            st.info("Nothing processed yet. Head to **Upload Leads** to run your first batch.")

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


def page_leads():
    search = st.text_input("Search by name or email", placeholder="e.g. curie or marie.curie@radiuminstitute.com", label_visibility="collapsed")
    table = filtered_leads
    if search and not table.empty:
        needle = search.lower()
        haystack = table[["first_name", "last_name", "email"]].astype(str).apply(lambda c: c.str.lower())
        mask = haystack.apply(lambda c: c.str.contains(needle, na=False)).any(axis=1)
        table = table[mask]
    st.caption(f"Showing {len(table):,} of {len(leads):,} leads")
    st.dataframe(table.sort_values("created_at", ascending=False) if "created_at" in table.columns else table,
                 use_container_width=True, hide_index=True)
    if not table.empty:
        st.download_button("Export as CSV", data=table.to_csv(index=False).encode("utf-8"),
                           file_name="qualead_leads.csv", mime="text/csv")

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
            if pd.notna(score):
                st.markdown(
                    f'<div class="qa-gauge" style="background:conic-gradient({color} {float(score)*3.6:.0f}deg, #EEF2F7 0deg);">'
                    f'<div class="inner"><div class="num" style="color:{color};">{score:.0f}</div><div class="of">/ 100</div></div></div>'
                    f'<div style="text-align:center;margin-top:12px;">{badge(band_label(score) + " quality", color)}</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown('<div class="qa-gauge" style="background:#EEF2F7;"><div class="inner">'
                            '<div class="num" style="color:#64748B;">-</div><div class="of">unscored</div></div></div>', unsafe_allow_html=True)
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


def page_lead_analytics():
    if filtered_leads.empty or "quality_score" not in filtered_leads.columns:
        st.info("No scored leads match the current filters. Add a batch from **Upload Leads**, or loosen a filter.")
        return
    scored = filtered_leads[filtered_leads["quality_score"].notna()]

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    hi = scored[scored["quality_score"] >= 70]
    lo = scored[scored["quality_score"] < 40]
    stat_card(k1, "Scored leads", len(scored), "in current filter", accent=PRIMARY)
    stat_card(k2, "High quality", len(hi), f"{round(100*len(hi)/len(scored),1) if len(scored) else 0}% of scored", accent=SUCCESS)
    stat_card(k3, "Low quality", len(lo), f"{round(100*len(lo)/len(scored),1) if len(scored) else 0}% -- deprioritize", accent=ERROR)
    consent_rate = round(100 * scored["consent"].fillna(False).astype(bool).mean(), 1) if "consent" in scored.columns else 0.0
    stat_card(k4, "Consented", f"{consent_rate}", "% opted in to contact", accent=STATUS_COLORS["duplicate"])
    st.write("")

    left, right = st.columns(2)
    with left:
        st.subheader("Quality funnel")
        st.caption("How the scored leads split across the priority bands.")
        band_counts = scored["quality_score"].apply(band_label).value_counts()
        funnel_df = pd.DataFrame({
            "band": ["High", "Medium", "Low"],
            "count": [int(band_counts.get("High", 0)), int(band_counts.get("Medium", 0)), int(band_counts.get("Low", 0))],
        })
        fig = go.Figure(go.Funnel(
            y=funnel_df["band"], x=funnel_df["count"],
            marker={"color": [SUCCESS, WARNING, ERROR]}, textinfo="value+percent initial"))
        st.plotly_chart(transparent(fig), use_container_width=True)
    with right:
        st.subheader("Score distribution")
        st.caption("Every scored lead, bucketed 0-100.")
        fig = px.histogram(scored, x="quality_score", color="status", nbins=20, barmode="stack", color_discrete_map=STATUS_COLORS)
        fig.update_layout(xaxis_title="Quality score", yaxis_title="Leads", legend_title=None)
        st.plotly_chart(transparent(fig), use_container_width=True)

    left2, right2 = st.columns(2)
    with left2:
        st.subheader("Avg score by source")
        st.caption("Which feed brings the strongest leads.")
        by_src = scored.groupby("source")["quality_score"].mean().round(1).sort_values(ascending=True).reset_index()
        fig = px.bar(by_src, x="quality_score", y="source", orientation="h", text="quality_score",
                     color="quality_score", color_continuous_scale=["#DC2626", "#F59E0B", "#16A34A"], range_color=[0, 100])
        fig.update_layout(xaxis_title="Avg score", yaxis_title=None, coloraxis_showscale=False)
        st.plotly_chart(transparent(fig), use_container_width=True)
    with right2:
        st.subheader("Signal completeness by source")
        st.caption("Share of leads carrying each quality signal -- the fuller the shape, the richer the feed's data.")
        signals = [
            ("Email", lambda d: d["email"].notna().mean() if "email" in d else 0),
            ("Phone", lambda d: d["phone_e164"].notna().mean() if "phone_e164" in d else 0),
            ("Consent", lambda d: d["consent"].fillna(False).astype(bool).mean() if "consent" in d else 0),
            ("Campaign", lambda d: d["campaign_id"].notna().mean() if "campaign_id" in d else 0),
            ("Name", lambda d: d["first_name"].notna().mean() if "first_name" in d else 0),
        ]
        axes = [s[0] for s in signals]
        fig = go.Figure()
        for i, src in enumerate(sorted(scored["source"].dropna().unique())):
            d = scored[scored["source"] == src]
            vals = [round(100 * fn(d), 0) for _, fn in signals]
            color = CHART_SEQ[i % len(CHART_SEQ)]
            fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=axes + [axes[0]], name=src, fill="toself",
                                          line=dict(color=color)))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], visible=True)), showlegend=True,
                          margin=dict(t=20, b=20, l=30, r=30), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Top leads to work now")
    st.caption("Highest-scoring leads in the current filter -- your call list.")
    cols = [c for c in ["first_name", "last_name", "email", "source", "quality_score", "status", "suggested_action"] if c in scored.columns]
    top = scored.sort_values("quality_score", ascending=False).head(10)[cols]
    st.dataframe(top, use_container_width=True, hide_index=True)


def page_data_quality():
    st.subheader("Where the mess comes from")
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Invalid rows by source -- which feed's payloads fail validation most.")
        if not invalid.empty and "source" in invalid.columns:
            counts = invalid["source"].value_counts().reset_index(); counts.columns = ["source", "count"]
            fig = px.bar(counts, x="source", y="count", color="source", color_discrete_sequence=CHART_SEQ)
            fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Invalid rows")
            st.plotly_chart(transparent(fig), use_container_width=True)
        else:
            st.info("No invalid rows recorded yet.")
    with c2:
        st.caption("Duplicates by source -- which feed sends the most repeat submissions.")
        if not duplicates.empty and "source" in duplicates.columns:
            counts = duplicates["source"].value_counts().reset_index(); counts.columns = ["source", "count"]
            fig = px.bar(counts, x="source", y="count", color="source", color_discrete_sequence=CHART_SEQ)
            fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Duplicates")
            st.plotly_chart(transparent(fig), use_container_width=True)
        else:
            st.info("No duplicates recorded yet.")

    st.subheader("Most common validation failures")
    if not invalid.empty and "errors" in invalid.columns:
        parsed = parse_json_column(invalid["errors"]); reasons = []
        for error_list in parsed.dropna():
            if isinstance(error_list, list):
                for err in error_list:
                    if isinstance(err, dict):
                        field = ".".join(str(p) for p in err.get("loc", [])) or "unknown field"
                        reasons.append(f"{field}: {err.get('msg', 'invalid value')}")
        if reasons:
            top = pd.Series(reasons).value_counts().head(10).reset_index(); top.columns = ["reason", "count"]
            fig = px.bar(top.sort_values("count"), x="count", y="reason", orientation="h", color_discrete_sequence=[ERROR])
            fig.update_layout(yaxis_title=None, xaxis_title="Occurrences")
            st.plotly_chart(transparent(fig), use_container_width=True)
        else:
            st.info("Invalid rows exist, but no parseable error detail was found.")
    else:
        st.info("No invalid rows recorded yet.")

    st.divider()
    st.subheader("Compliance & completeness gaps")
    st.caption("These leads pass validation, so they surface nowhere else -- but they're worth a human glance.")
    g1, g2 = st.columns(2)
    no_consent = pd.DataFrame()
    with g1:
        if has_leads and "consent" in leads.columns:
            no_consent = leads[leads["consent"] == False]  # noqa: E712
            rate = round(100 * len(no_consent) / len(leads), 1) if len(leads) else 0.0
            st.metric("No marketing consent", f"{len(no_consent):,}", f"{rate}% of leads", delta_color="off", help="Cannot be cold-called (TCPA). Email only with a lawful basis.")
        else:
            st.metric("No marketing consent", "0")
    with g2:
        if has_leads and "campaign_id" in leads.columns:
            no_campaign = leads[leads["campaign_id"].isna() | (leads["campaign_id"] == "")]
            rate = round(100 * len(no_campaign) / len(leads), 1) if len(leads) else 0.0
            st.metric("No campaign tag", f"{len(no_campaign):,}", f"{rate}% unattributable", delta_color="off", help="Can't be tied back to a marketing campaign for ROI.")
        else:
            st.metric("No campaign tag", "0")
    if not no_consent.empty:
        with st.expander(f"Preview {min(len(no_consent), 25)} of {len(no_consent):,} leads collected without consent"):
            cols = [c for c in ["first_name", "last_name", "email", "source", "quality_score", "status"] if c in no_consent.columns]
            st.dataframe(no_consent[cols].head(25), use_container_width=True, hide_index=True)


def page_self_healing():
    st.subheader("Self-healing events")
    st.caption("When the cleaning code hits an input shape it's never seen, a local LLM rewrites the failing function and the batch retries -- automatically.")
    if not healing.empty:
        ev, tab = st.columns([1, 2])
        with ev:
            if "exception_type" in healing.columns:
                c = healing["exception_type"].value_counts().reset_index(); c.columns = ["exception_type", "count"]
                fig = px.bar(c, x="count", y="exception_type", orientation="h", color_discrete_sequence=[PRIMARY])
                fig.update_layout(yaxis_title=None, xaxis_title="Retries")
                st.plotly_chart(transparent(fig), use_container_width=True)
        with tab:
            st.dataframe(healing, use_container_width=True, hide_index=True)
    else:
        st.info("No self-healing events yet -- the pipeline hasn't hit a code bug it needed to patch (or Ollama isn't running).")
    st.subheader("Human review queue")
    if review_queue:
        st.dataframe(pd.DataFrame(review_queue), use_container_width=True, hide_index=True)
    else:
        st.success("Queue is empty -- nothing has exhausted its self-healing retries.")


def page_upload():
    st.caption(
        "Drop **any** CSV -- from any CRM, ad platform, or spreadsheet, with whatever column names it "
        "happens to use. QuaLead AI figures out which columns are the name, email, phone, and so on, then "
        "cleans, validates, scores, and diagnoses every row. Nothing is dropped -- messy leads are flagged, "
        "never deleted."
    )
    uploaded = st.file_uploader("Drag and drop a CSV here", type=["csv"],
                                help="Any CSV export. Columns don't need to match a fixed schema -- the field mapper handles unknown headers.")
    if uploaded is not None:
        st.caption(f"Ready: **{uploaded.name}** ({uploaded.size / 1024:.0f} KB)")
        if st.button("Analyze leads", type="primary"):
            try:
                with st.spinner("Mapping columns, cleaning, validating, scoring, and diagnosing your leads..."):
                    resp = requests.post(f"{API_BASE_URL}/ingest/csv", files={"file": (uploaded.name, uploaded.getvalue())}, timeout=600)
                resp.raise_for_status()
                summary = resp.json().get("summary") or {}
                mapping = summary.get("field_mapping") or {}
                st.success("Analysis complete -- your leads are in.")
                st.balloons()
                m1, m2, m3 = st.columns(3)
                m1.metric("Scored & kept", f"{summary.get('scored', 0):,}")
                m2.metric("Duplicates merged", f"{summary.get('duplicates', 0):,}")
                m3.metric("Invalid rows", f"{summary.get('invalid', 0):,}")
                if mapping:
                    with st.expander("How your columns were mapped", expanded=True):
                        mapped = {k: v for k, v in mapping.items() if v}
                        if mapped:
                            st.dataframe(pd.DataFrame([{"Your column": k, "Mapped to": v} for k, v in mapped.items()]),
                                         use_container_width=True, hide_index=True)
                        unmapped = [k for k, v in mapping.items() if not v]
                        if unmapped:
                            st.caption("Kept in raw_payload, not mapped to a canonical field: " + ", ".join(unmapped))
                st.caption("Open **Overview** or **Lead Analytics** (and hit Refresh) to see them flow in.")
            except requests.RequestException as exc:
                st.error(f"Upload failed: {exc}")
    else:
        st.info("No file yet -- drop a CSV above to get started.")


ROUTES = {
    "Overview": page_overview,
    "Leads": page_leads,
    "Lead Analytics": page_lead_analytics,
    "Data Quality": page_data_quality,
    "Self-Healing": page_self_healing,
    "Upload Leads": page_upload,
}
ROUTES.get(page, page_overview)()
