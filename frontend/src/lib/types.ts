// Mirrors app/schema/canonical.py:Lead and the /stats payload. Fields the
// backend allows to be null are optional here too (the "flag, never drop"
// contract means a lead can arrive with almost nothing populated).
export type LeadStatus = "clean" | "flagged" | "duplicate";

// The dispositions a rep can set on a lead from the call list.
export type CallStatus = "contacted" | "not_interested" | "follow_up" | "high_priority";

export interface Lead {
  lead_id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  phone_e164: string | null;
  source: string;
  campaign_id: string | null;
  consent: boolean;
  created_at: string;
  quality_score: number | null;
  status: LeadStatus | string;
  duplicate_of_lead_id: string | null;
  diagnosis?: string | null;
  suggested_action?: string | null;
  disposition?: CallStatus | null;
  raw_payload?: unknown;
}

// An upload container from /datasets. Every upload is one dataset.
export interface Dataset {
  dataset_id: string;
  name: string;
  file_name: string | null;
  source_kind: string | null;
  status: string; // "processing" | "completed" | "failed"
  total_leads: number | null;
  clean: number | null;
  flagged: number | null;
  invalid: number | null;
  duplicates: number | null;
  avg_score: number | null;
  notes: string | null;
  tags: string | null;
  created_at: string | null;
  finished_at: string | null;
  time_taken_ms: number | null;
}

// One ingest run from /pipeline/runs (or /pipeline/status/{id}).
export interface PipelineRun {
  run_id: string;
  source: string;
  status: string; // "processing" | "completed" | "failed"
  total_records: number | null;
  processed: number | null;
  failed: number | null;
  duplicates: number | null;
  started_at: string | null;
  finished_at: string | null;
  time_taken_ms: number | null;
}

// Per-source scorecard from /analytics/source-performance.
export interface SourcePerf {
  source: string;
  leads: number;
  clean: number;
  flagged: number;
  invalid: number;
  duplicates: number;
  avg_score: number | null;
  junk_percentage: number;
}

export interface Stats {
  leads_by_source: Record<string, number>;
  total_clean: number;
  total_flagged: number;
  total_invalid: number;
  total_duplicates: number;
  avg_quality_score: number | null;
  self_healing_events: number;
  human_review_pending: number;
}

// Per-source aggregate metrics from /analytics (all computed in SQL).
export interface SourceMetrics {
  total: number;
  clean: number;
  flagged: number;
  scored: number;
  sum_score: number;
  email: number;
  phone: number;
  consent: number;
  campaign: number;
  name: number;
}

// One (source, status, 10-point score bucket) count. bucket = floor(score/10),
// so 0..10 (a perfect 100 lands in bucket 10).
export interface ScoreBucket {
  source: string;
  status: string;
  bucket: number;
  count: number;
}

export interface Analytics {
  by_source: Record<string, SourceMetrics>;
  buckets: ScoreBucket[];
  invalid_by_source: Record<string, number>;
  duplicate_by_source: Record<string, number>;
}

// /leads/search envelope: a page of rows plus the true total match count.
export interface LeadSearchResult {
  total: number;
  rows: Lead[];
}

export interface HealingEvent {
  attempt?: number;
  exception_type?: string;
  message?: string;
  source?: string;
}

export interface IngestSummary {
  source: string;
  scored: number;
  duplicates: number;
  invalid: number;
  field_mapping: Record<string, string | null>;
}

// Full /ingest/csv response. status is "success" | "human_review" | "error";
// summary is null when a batch was routed to human review or failed to save.
export interface IngestResponse {
  status: string;
  summary: IngestSummary | null;
  dataset_id?: string | null;
  message?: string;
}
