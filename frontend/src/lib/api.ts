import type { Analytics, HealingEvent, IngestSummary, Lead, LeadSearchResult, Stats } from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ||
  "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  stats: () => get<Stats>("/stats"),

  // SQL-aggregated metrics for every chart/KPI — a few KB, not the whole table.
  analytics: () => get<Analytics>("/analytics"),
  topLeads: (limit = 8, opts?: { source?: string; minScore?: number; maxScore?: number }) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (opts?.source) p.set("source", opts.source);
    if (opts?.minScore != null) p.set("min_score", String(opts.minScore));
    if (opts?.maxScore != null) p.set("max_score", String(opts.maxScore));
    return get<Lead[]>(`/leads/top?${p.toString()}`);
  },
  rankedLeads: (limit = 10, offset = 0, opts?: { source?: string; minScore?: number; maxScore?: number }) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (opts?.source) p.set("source", opts.source);
    if (opts?.minScore != null) p.set("min_score", String(opts.minScore));
    if (opts?.maxScore != null) p.set("max_score", String(opts.maxScore));
    return get<LeadSearchResult>(`/leads/ranked?${p.toString()}`);
  },
  searchLeads: (q: string, limit = 200, source?: string) =>
    get<LeadSearchResult>(
      `/leads/search?limit=${limit}${q ? `&q=${encodeURIComponent(q)}` : ""}${source ? `&source=${encodeURIComponent(source)}` : ""}`,
    ),

  duplicates: (limit = 2000) => get<Lead[]>(`/duplicates?limit=${limit}`),
  invalid: (limit = 2000) => get<Record<string, unknown>[]>(`/invalid?limit=${limit}`),
  healingEvents: (limit = 1000) => get<HealingEvent[]>(`/healing-events?limit=${limit}`),
  humanReview: () => get<Record<string, unknown>[]>("/human-review"),

  // Generic "upload any CSV" — routes straight to the RAG field mapper.
  uploadCsv: async (file: File): Promise<IngestSummary | null> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/ingest/csv`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${res.statusText}`);
    const body = (await res.json()) as { summary: IngestSummary | null };
    return body.summary;
  },
};
