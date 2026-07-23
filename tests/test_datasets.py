"""Tests for the Dataset system: per-dataset isolation + dedup, dataset-scoped
reads, CRUD, and the per-source backfill migration. Against a throwaway DuckDB."""

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
        source=LeadSource.CSV_UPLOAD, first_name="Ada", last_name="Lovelace",
        email="ada@example.com", phone_e164="+14155550123", consent=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), quality_score=80.0, status=LeadStatus.CLEAN,
    )
    defaults.update(overrides)
    return Lead(**defaults)


def test_dataset_lifecycle_and_counts(fresh_db):
    ds = storage.create_dataset("My upload", "leads.csv", "csv_upload")
    assert storage.get_dataset(ds)["status"] == "processing"

    storage.persist_leads_atomic([
        _lead(email="a@x.com", phone_e164="+14155550001", quality_score=80.0, status=LeadStatus.CLEAN),
        _lead(email="b@x.com", phone_e164="+14155550002", quality_score=40.0, status=LeadStatus.FLAGGED),
    ], dataset_id=ds)
    storage.finish_dataset(ds)

    d = storage.get_dataset(ds)
    assert d["status"] == "completed"
    assert d["total_leads"] == 2
    assert d["clean"] == 1 and d["flagged"] == 1
    assert d["avg_score"] == 60.0


def test_dedup_is_per_dataset(fresh_db):
    d1 = storage.create_dataset("D1", None, "csv_upload")
    d2 = storage.create_dataset("D2", None, "csv_upload")

    kept1, dup1 = storage.persist_leads_atomic([_lead(email="same@x.com", phone_e164="+14155559999")], dataset_id=d1)
    assert len(kept1) == 1 and len(dup1) == 0

    # Same identifier again in d1 -> duplicate.
    kept1b, dup1b = storage.persist_leads_atomic([_lead(email="same@x.com", phone_e164="+14155559999")], dataset_id=d1)
    assert len(kept1b) == 0 and len(dup1b) == 1

    # Same identifier in a DIFFERENT dataset -> kept (datasets are isolated).
    kept2, dup2 = storage.persist_leads_atomic([_lead(email="same@x.com", phone_e164="+14155559999")], dataset_id=d2)
    assert len(kept2) == 1 and len(dup2) == 0


def test_reads_are_dataset_scoped(fresh_db):
    d1 = storage.create_dataset("D1", None, "csv_upload")
    d2 = storage.create_dataset("D2", None, "csv_upload")
    storage.persist_leads_atomic([_lead(email="a@x.com", phone_e164="+14155550001")], dataset_id=d1)
    storage.persist_leads_atomic([
        _lead(email="b@x.com", phone_e164="+14155550002"),
        _lead(email="c@x.com", phone_e164="+14155550003"),
    ], dataset_id=d2)

    assert storage.get_stats(dataset_id=d1)["total_clean"] == 1
    assert storage.get_stats(dataset_id=d2)["total_clean"] == 2
    assert storage.get_stats()["total_clean"] == 3  # unscoped = all datasets
    assert storage.search_leads(dataset_id=d2)["total"] == 2
    assert len(storage.top_leads(limit=10, dataset_id=d1)) == 1


def test_rename_and_delete_dataset(fresh_db):
    ds = storage.create_dataset("Original", None, "csv_upload")
    storage.persist_leads_atomic([_lead(email="a@x.com", phone_e164="+14155550001")], dataset_id=ds)

    assert storage.update_dataset(ds, name="Renamed") is True
    assert storage.get_dataset(ds)["name"] == "Renamed"
    assert storage.update_dataset("nope", name="x") is False

    assert storage.delete_dataset(ds) is True
    assert storage.get_dataset(ds) is None
    assert storage.get_stats()["total_clean"] == 0  # its leads are gone too
    assert storage.delete_dataset(ds) is False


def test_backfill_groups_legacy_leads_by_source(fresh_db):
    # Legacy rows (no dataset_id), two sources.
    storage.save_leads([
        _lead(source=LeadSource.FACEBOOK, email="f@x.com", phone_e164="+14155550001"),
        _lead(source=LeadSource.INSTAGRAM, email="i@x.com", phone_e164="+14155550002"),
    ])
    result = storage.backfill_datasets_by_source()
    assert result["datasets_created"] == 2

    datasets = storage.list_datasets()
    assert len(datasets) == 2
    # Every legacy lead now belongs to a dataset (scoped stats sum to the total).
    scoped_total = sum(storage.get_stats(dataset_id=d["dataset_id"])["total_clean"] for d in datasets)
    assert scoped_total == 2
