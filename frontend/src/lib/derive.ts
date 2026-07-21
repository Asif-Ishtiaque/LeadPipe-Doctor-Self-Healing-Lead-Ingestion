import { SOURCE_COLORS } from "./format";
import type { Analytics, SourceMetrics } from "./types";

// Everything here derives chart/KPI data from the /analytics aggregate (a few
// KB) instead of the full lead list. The backend returns per-source metrics
// plus a small (source, status, 10-point bucket) histogram; these helpers
// re-slice that into the specific shapes each chart wants.

const EMPTY: SourceMetrics = {
  total: 0, clean: 0, flagged: 0, scored: 0, sum_score: 0,
  email: 0, phone: 0, consent: 0, campaign: 0, name: 0,
};

export function sources(a: Analytics): string[] {
  return Object.keys(a.by_source).sort();
}

// Combined metrics for a single source, or summed across all when source is
// undefined ("All sources").
export function metricsFor(a: Analytics, source?: string): SourceMetrics {
  if (source) return a.by_source[source] ?? EMPTY;
  return Object.values(a.by_source).reduce(
    (acc, m) => ({
      total: acc.total + m.total,
      clean: acc.clean + m.clean,
      flagged: acc.flagged + m.flagged,
      scored: acc.scored + m.scored,
      sum_score: acc.sum_score + m.sum_score,
      email: acc.email + m.email,
      phone: acc.phone + m.phone,
      consent: acc.consent + m.consent,
      campaign: acc.campaign + m.campaign,
      name: acc.name + m.name,
    }),
    { ...EMPTY },
  );
}

// Per-bucket clean/flagged counts (bucket index 0..10), optionally scoped to
// one source. This is the single primitive the butterfly, histogram and funnel
// all fold down from.
function bucketCounts(a: Analytics, source?: string): { clean: number[]; flagged: number[] } {
  const clean = Array(11).fill(0);
  const flagged = Array(11).fill(0);
  for (const b of a.buckets) {
    if (source && b.source !== source) continue;
    if (b.bucket < 0 || b.bucket > 10) continue;
    if (b.status === "flagged") flagged[b.bucket] += b.count;
    else clean[b.bucket] += b.count;
  }
  return { clean, flagged };
}

const sumRange = (arr: number[], lo: number, hi: number) =>
  arr.slice(lo, hi + 1).reduce((a, b) => a + b, 0);

export interface Kpis {
  total: number;
  clean: number;
  flagged: number;
  avg: number | null;
  highPct: number;
  scored: number;
}

export function kpis(a: Analytics, source?: string): Kpis {
  const m = metricsFor(a, source);
  const { clean, flagged } = bucketCounts(a, source);
  const high = sumRange(clean, 7, 10) + sumRange(flagged, 7, 10); // score >= 70
  return {
    total: m.total,
    clean: m.clean,
    flagged: m.flagged,
    avg: m.scored ? Math.round(m.sum_score / m.scored) : null,
    highPct: m.scored ? Math.round((high / m.scored) * 1000) / 10 : 0,
    scored: m.scored,
  };
}

// Clean-vs-flagged across the six display bands (the "butterfly").
export function buildButterfly(a: Analytics, source?: string) {
  const { clean, flagged } = bucketCounts(a, source);
  const bands: [string, number, number][] = [
    ["80–100", 8, 10],
    ["70–79", 7, 7],
    ["60–69", 6, 6],
    ["50–59", 5, 5],
    ["40–49", 4, 4],
    ["0–39", 0, 3],
  ];
  return bands.map(([band, lo, hi]) => ({
    band,
    clean: sumRange(clean, lo, hi),
    flagged: sumRange(flagged, lo, hi),
  }));
}

// Stacked score distribution in five display buckets.
export function buildScoreHistogram(a: Analytics, source?: string) {
  const { clean, flagged } = bucketCounts(a, source);
  const spec: [string, number, number][] = [
    ["0–19", 0, 1],
    ["20–39", 2, 3],
    ["40–59", 4, 5],
    ["60–79", 6, 7],
    ["80–100", 8, 10],
  ];
  return spec.map(([bucket, lo, hi]) => ({
    bucket,
    clean: sumRange(clean, lo, hi),
    flagged: sumRange(flagged, lo, hi),
  }));
}

export function avgBySource(a: Analytics) {
  return Object.entries(a.by_source)
    .filter(([, m]) => m.scored > 0)
    .map(([source, m]) => ({ source, avg: Math.round((m.sum_score / m.scored) * 10) / 10 }))
    .sort((x, y) => x.avg - y.avg);
}

// Priority funnel counts (over all scored leads).
export function funnel(a: Analytics) {
  const { clean, flagged } = bucketCounts(a);
  const band = (lo: number, hi: number) => sumRange(clean, lo, hi) + sumRange(flagged, lo, hi);
  return { high: band(7, 10), medium: band(4, 6), low: band(0, 3) };
}

// Per-source signal completeness (%), for the radar. Top sources by volume.
const SIGNALS: [string, keyof SourceMetrics][] = [
  ["Email", "email"],
  ["Phone", "phone"],
  ["Consent", "consent"],
  ["Campaign", "campaign"],
  ["Name", "name"],
];

export function buildRadar(a: Analytics, maxSources = 3) {
  const axes = SIGNALS.map(([label]) => label);
  const top = Object.entries(a.by_source)
    .sort((x, y) => y[1].total - x[1].total)
    .slice(0, maxSources);
  const series = top.map(([source, m]) => ({
    source,
    color: SOURCE_COLORS[source] ?? "#2563EB",
    values: Object.fromEntries(
      SIGNALS.map(([label, key]) => [label, m.total ? Math.round((m[key] / m.total) * 100) : 0]),
    ),
  }));
  return { axes, series };
}

// { source, count } arrays for the simple bar charts.
export function toBars(counts: Record<string, number>) {
  return Object.entries(counts)
    .map(([source, count]) => ({ source, count }))
    .sort((a, b) => b.count - a.count);
}
