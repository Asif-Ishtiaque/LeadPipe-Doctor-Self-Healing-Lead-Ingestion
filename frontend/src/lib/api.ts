import type { Analytics, CallStatus, Dataset, HealingEvent, IngestResponse, Lead, LeadSearchResult, PipelineRun, SourcePerf, Stats } from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json() as Promise<T>;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json() as Promise<T>;
}

// Add dataset_id to a query string when a dataset is active (null = all).
function ds(p: URLSearchParams, datasetId?: string | null) {
  if (datasetId) p.set("dataset_id", datasetId);
  return p;
}

export const api = {
  stats: (datasetId?: string | null) => get<Stats>(`/stats?${ds(new URLSearchParams(), datasetId)}`),

  // SQL-aggregated metrics for every chart/KPI — a few KB, not the whole table.
  analytics: (datasetId?: string | null) => get<Analytics>(`/analytics?${ds(new URLSearchParams(), datasetId)}`),
  topLeads: (limit = 8, opts?: { source?: string; minScore?: number; maxScore?: number; datasetId?: string | null }) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (opts?.source) p.set("source", opts.source);
    if (opts?.minScore != null) p.set("min_score", String(opts.minScore));
    if (opts?.maxScore != null) p.set("max_score", String(opts.maxScore));
    return get<Lead[]>(`/leads/top?${ds(p, opts?.datasetId)}`);
  },
  rankedLeads: (limit = 10, offset = 0, opts?: { source?: string; minScore?: number; maxScore?: number; datasetId?: string | null }) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (opts?.source) p.set("source", opts.source);
    if (opts?.minScore != null) p.set("min_score", String(opts.minScore));
    if (opts?.maxScore != null) p.set("max_score", String(opts.maxScore));
    return get<LeadSearchResult>(`/leads/ranked?${ds(p, opts?.datasetId)}`);
  },
  searchLeads: (q: string, limit = 200, opts?: { source?: string; minScore?: number; flagged?: boolean; datasetId?: string | null }) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (q) p.set("q", q);
    if (opts?.source) p.set("source", opts.source);
    if (opts?.minScore != null) p.set("min_score", String(opts.minScore));
    if (opts?.flagged != null) p.set("flagged", String(opts.flagged));
    return get<LeadSearchResult>(`/leads/search?${ds(p, opts?.datasetId)}`);
  },

  // Rep call-list workflow.
  callList: (limit = 20, datasetId?: string | null) =>
    get<Lead[]>(`/leads/call-list?${ds(new URLSearchParams({ limit: String(limit) }), datasetId)}`),
  setLeadStatus: (leadId: string, status: CallStatus) =>
    send<{ status: string; lead_id: string; disposition: CallStatus }>("POST", `/leads/${encodeURIComponent(leadId)}/status`, { status }),

  sourcePerformance: (datasetId?: string | null) =>
    get<SourcePerf[]>(`/analytics/source-performance?${ds(new URLSearchParams(), datasetId)}`),

  // Datasets.
  datasets: () => get<Dataset[]>("/datasets"),
  getDataset: (id: string) => get<Dataset>(`/datasets/${encodeURIComponent(id)}`),
  renameDataset: (id: string, patch: { name?: string; notes?: string; tags?: string }) =>
    send<Dataset>("PATCH", `/datasets/${encodeURIComponent(id)}`, patch),
  deleteDataset: (id: string) => send<{ status: string; deleted: string }>("DELETE", `/datasets/${encodeURIComponent(id)}`),
  datasetExportUrl: (id: string) => `${API_BASE}/datasets/${encodeURIComponent(id)}/export`,

  // Pipeline run history + workspace reset.
  pipelineRuns: (limit = 20) => get<PipelineRun[]>(`/pipeline/runs?limit=${limit}`),
  resetWorkspace: (opts: { leads: boolean; review_queue: boolean; chroma: boolean }) =>
    send<{ status: string; cleared: Record<string, unknown> }>("POST", "/admin/reset", opts),

  duplicates: (limit = 2000) => get<Lead[]>(`/duplicates?limit=${limit}`),
  invalid: (limit = 2000) => get<Record<string, unknown>[]>(`/invalid?limit=${limit}`),
  healingEvents: (limit = 1000) => get<HealingEvent[]>(`/healing-events?limit=${limit}`),
  humanReview: () => get<Record<string, unknown>[]>("/human-review"),

  // Dataset-aware upload: creates a NEW dataset (named `name`, else the
  // filename), or adds to an existing one when datasetId is given.
  uploadDataset: async (file: File, opts?: { name?: string; datasetId?: string; signal?: AbortSignal }): Promise<IngestResponse> => {
    const form = new FormData();
    form.append("file", file);
    if (opts?.name) form.append("name", opts.name);
    if (opts?.datasetId) form.append("dataset_id", opts.datasetId);
    const res = await fetch(`${API_BASE}/datasets/upload`, { method: "POST", body: form, signal: opts?.signal });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${res.statusText}`);
    return (await res.json()) as IngestResponse;
  },
};
