"""Tests for the SQL-aggregation read layer (get_analytics / top_leads /
search_leads) that backs the React dashboard. These replaced the old path of
shipping every lead to the browser and reducing client-side; the point of the
aggregation is that the numbers come out identical, so that's what we pin here.

Each test stands up a throwaway DuckDB file and points settings at it, so the
aggregate SQL is exercised end-to-end against a real engine (not mocked)."""

from datetime import datetime, timezone

import pytest

from app.schema.canonical import Lead, LeadSource, LeadStatus
from app.utils import storage
from app.utils.config import settings


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"duckdb:///{tmp_path}/t.duckdb")
    storage.get_engine.cache_clear()
    yield
    storage.get_engine.cache_clear()


def _lead(**overrides) -> Lead:
    defaults = dict(
        source=LeadSource.FACEBOOK,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone_e164="+14155550123",
        consent=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quality_score=80.0,
        status=LeadStatus.CLEAN,
    )
    defaults.update(overrides)
    return Lead(**defaults)


def test_analytics_per_source_counts_and_average(fresh_db):
    storage.save_leads([
        _lead(email="a@x.com", phone_e164="+14155550001", quality_score=80.0, status=LeadStatus.CLEAN),
        _lead(email="b@x.com", phone_e164="+14155550002", quality_score=60.0, status=LeadStatus.CLEAN),
        _lead(email="c@x.com", phone_e164="+14155550003", quality_score=40.0, status=LeadStatus.FLAGGED, consent=False),
        _lead(source=LeadSource.INSTAGRAM, email="d@x.com", phone_e164="+14155550004", quality_score=90.0),
    ])

    a = storage.get_analytics()
    fb = a["by_source"]["facebook"]
    assert fb["total"] == 3
    assert fb["clean"] == 2
    assert fb["flagged"] == 1
    assert fb["scored"] == 3
    assert fb["sum_score"] == pytest.approx(180.0)  # avg = 60
    assert fb["consent"] == 2  # one lead had consent=False
    assert a["by_source"]["instagram"]["total"] == 1


def test_analytics_buckets_place_scores_correctly(fresh_db):
    # scores 5, 45, 85, 100 -> buckets 0, 4, 8, 10
    storage.save_leads([
        _lead(email=f"{i}@x.com", phone_e164=f"+1415555{i:04d}", quality_score=s)
        for i, s in enumerate([5.0, 45.0, 85.0, 100.0])
    ])
    buckets = {b["bucket"]: b["count"] for b in storage.get_analytics()["buckets"]}
    assert buckets == {0: 1, 4: 1, 8: 1, 10: 1}


def test_top_leads_sorted_desc_capped_and_no_raw_payload(fresh_db):
    storage.save_leads([
        _lead(email=f"{i}@x.com", phone_e164=f"+1415555{i:04d}", quality_score=float(s))
        for i, s in enumerate([30, 90, 60, 75])
    ])
    top = storage.top_leads(limit=2)
    assert [row["quality_score"] for row in top] == [90.0, 75.0]
    assert "raw_payload" not in top[0]  # the big field is deliberately excluded


def test_search_leads_filters_and_reports_true_total(fresh_db):
    storage.save_leads([
        _lead(first_name="Grace", last_name="Hopper", email="grace@x.com", phone_e164="+14155550010"),
        _lead(first_name="Ada", last_name="Lovelace", email="ada@x.com", phone_e164="+14155550011"),
        _lead(first_name="Adam", last_name="Smith", email="adam@x.com", phone_e164="+14155550012"),
    ])
    # substring "ada" matches Ada and Adam (case-insensitive)
    result = storage.search_leads(q="ada", limit=200)
    assert result["total"] == 2
    assert {r["first_name"] for r in result["rows"]} == {"Ada", "Adam"}

    # limit caps returned rows but total still reflects all matches
    capped = storage.search_leads(q=None, limit=1)
    assert capped["total"] == 3
    assert len(capped["rows"]) == 1
