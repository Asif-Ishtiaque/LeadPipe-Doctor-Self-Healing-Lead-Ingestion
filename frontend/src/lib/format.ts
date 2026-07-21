import type { Lead } from "./types";

export const COLORS = {
  brand: "#2563EB",
  brand2: "#7C5CFC",
  good: "#16A34A",
  warn: "#F59E0B",
  bad: "#E5484D",
  dup: "#7C5CFC",
  sky: "#0EA5E9",
  muted: "#6B7686",
} as const;

// Same source palette used across every chart so a source is one colour.
export const SOURCE_COLORS: Record<string, string> = {
  facebook: "#2563EB",
  landing_page: "#7C5CFC",
  instagram: "#0EA5E9",
  google_form: "#F59E0B",
  csv_upload: "#16A34A",
};

// Band boundaries match app/scoring/diagnosis.py:band() — round, then bucket.
export function band(score: number | null | undefined): "High" | "Medium" | "Low" | "Unscored" {
  if (score === null || score === undefined || Number.isNaN(score)) return "Unscored";
  const s = Math.round(score);
  return s >= 70 ? "High" : s >= 40 ? "Medium" : "Low";
}

export function bandColor(score: number | null | undefined): string {
  const b = band(score);
  return b === "High" ? COLORS.good : b === "Medium" ? COLORS.warn : b === "Low" ? COLORS.bad : COLORS.muted;
}

export const STATUS_COLORS: Record<string, string> = {
  clean: COLORS.good,
  flagged: COLORS.warn,
  duplicate: COLORS.dup,
  invalid: COLORS.bad,
};

export function num(n: number): string {
  return n.toLocaleString("en-US");
}

export function leadName(l: Lead): string {
  const name = [l.first_name, l.last_name].filter(Boolean).join(" ").trim();
  return name || "(no name)";
}

export function initials(l: Lead): string {
  const name = leadName(l);
  if (name === "(no name)") return "?";
  return name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
}

// Words that should stay all-caps rather than title-cased (e.g. "csv" -> "CSV").
const ACRONYMS: Record<string, string> = { csv: "CSV" };

export function prettySource(s: string): string {
  return s
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => ACRONYMS[w.toLowerCase()] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// e.g. "Last Updated At 9:18 PM, Tue 21 July, 2026"
export function formatUpdatedAt(d: Date): string {
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  const weekday = d.toLocaleDateString("en-US", { weekday: "short" });
  const month = d.toLocaleDateString("en-US", { month: "long" });
  return `Last Updated At ${time}, ${weekday} ${d.getDate()} ${month}, ${d.getFullYear()}`;
}
