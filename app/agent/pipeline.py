"""The actual lead-processing pipeline: ingest -> map -> clean -> validate ->
dedup -> score. This is deliberately a plain function with no error
swallowing around the cleaning step -- if app/cleaning/transforms.py has a
bug that a batch of data triggers, it's supposed to raise, so the
self-healing graph in app/agent/graph.py can catch it, patch the code, and
retry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.cleaning.engine import clean_records
from app.deduplication.dedup import deduplicate
from app.ingestion import ingest
from app.mapping.mapper import apply_mapping, map_source_fields
from app.schema.canonical import Lead, LeadSource
from app.scoring.scorer import LeadScorer
from app.validation.validator import validate_records

_scorer = LeadScorer()


@dataclass
class PipelineResult:
    source: str
    scored_leads: list[Lead] = field(default_factory=list)
    duplicates: list[Lead] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)
    field_mapping: dict[str, str | None] = field(default_factory=dict)

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "scored": len(self.scored_leads),
            "duplicates": len(self.duplicates),
            "invalid": len(self.invalid),
            "field_mapping": self.field_mapping,
        }


def run_pipeline(source: LeadSource, raw_data: Any) -> PipelineResult:
    raw_records = ingest(source, raw_data)
    if not raw_records:
        return PipelineResult(source=source.value)

    field_mapping = map_source_fields(source.value, raw_records)
    mapped_records = apply_mapping(raw_records, field_mapping)

    cleaned_records = clean_records(mapped_records)

    validation = validate_records(cleaned_records, source=source.value)
    # Score before deduping (not after) so every member of a duplicate
    # cluster carries a real quality_score -- that's both what dedup uses
    # to decide which record is "best," and what lets a human see *why*
    # one record won over the other instead of just trusting a black box.
    scored_valid = _scorer.score_batch(validation.valid)
    kept, duplicates = deduplicate(scored_valid)

    return PipelineResult(
        source=source.value,
        scored_leads=kept,
        duplicates=duplicates,
        invalid=validation.invalid,
        field_mapping=field_mapping,
    )
