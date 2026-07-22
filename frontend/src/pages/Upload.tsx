import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Panel } from "../components/ui";
import { num } from "../lib/format";
import type { IngestSummary } from "../lib/types";

// The real pipeline stages, shown in order while processing. We don't get
// live progress from the backend, but these are the actual steps a lead goes
// through -- surfacing them turns the wait into "watch the AI work" instead of
// a dead spinner, and sets the expectation that real work is happening.
const STAGES = [
  "Reading your file",
  "Mapping your columns with AI",
  "Cleaning & normalizing",
  "Validating every row",
  "De-duplicating",
  "Scoring & diagnosing",
];
const UPLOAD_TIMEOUT_MS = 300_000;
const isCsv = (f: File) => /\.csv$/i.test(f.name) || f.type === "text/csv" || f.type === "application/vnd.ms-excel";

export default function Upload() {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<IngestSummary | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Tick the elapsed-seconds counter while a request is in flight.
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);

  const reset = () => { setResult(null); setNotice(null); setError(null); };

  function pick(f: File | null) {
    if (!f) return;
    if (!isCsv(f)) { setError("That doesn't look like a CSV. Please choose a .csv file."); return; }
    reset();
    setFile(f);
  }

  async function analyze() {
    if (!file || busy) return;
    reset();
    setBusy(true);
    setElapsed(0);
    const ac = new AbortController();
    abortRef.current = ac;
    const timeout = setTimeout(() => ac.abort(), UPLOAD_TIMEOUT_MS);
    try {
      const resp = await api.uploadCsv(file, ac.signal);
      if (resp.status === "error") {
        setError(resp.message ?? "We couldn't finish processing this file. Please try again.");
      } else if (!resp.summary) {
        setNotice("We couldn't auto-process this file, so it's been sent to the review queue. It may be malformed or in a format we haven't seen yet.");
      } else if (resp.summary.scored + resp.summary.duplicates + resp.summary.invalid === 0) {
        setNotice("No rows found in this file. Make sure it has a header row and at least one row of data.");
      } else {
        setResult(resp.summary);
        qc.invalidateQueries(); // refresh dashboard data
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setError("This is taking longer than expected — the local model may still be warming up. Please try again in a moment.");
      } else {
        setError(e instanceof Error ? e.message : "Upload failed. Please try again.");
      }
    } finally {
      clearTimeout(timeout);
      abortRef.current = null;
      setBusy(false);
    }
  }

  const stage = STAGES[Math.min(Math.floor(elapsed / 4), STAGES.length - 1)];
  const mapping = result?.field_mapping ?? {};
  const mapped = Object.entries(mapping).filter(([, v]) => v);
  const unmapped = Object.entries(mapping).filter(([, v]) => !v).map(([k]) => k);

  return (
    <Panel title="Upload leads" cap="Drop any CSV — from any CRM, ad platform, or spreadsheet, with whatever column names it uses. QuaLead AI figures out which columns are the name, email, phone, and so on, then cleans, validates, scores, and diagnoses every row. Nothing is dropped — messy leads are flagged, never deleted.">
      <div
        onDragOver={(e) => { e.preventDefault(); if (!busy) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); if (!busy) pick(e.dataTransfer.files?.[0] ?? null); }}
        onClick={() => !busy && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl px-6 py-10 text-center transition ${busy ? "opacity-60 cursor-not-allowed" : "cursor-pointer"} ${dragging ? "border-brand bg-brandbg" : "border-line2 bg-content hover:border-brand"}`}
      >
        <div className="text-3xl mb-2">📥</div>
        <div className="font-semibold">{file ? file.name : "Drag & drop a CSV here"}</div>
        <div className="text-[0.8rem] text-muted mt-1">{file ? `${(file.size / 1024).toFixed(0)} KB — click Analyze below` : "or click to browse · any CSV, any headers"}</div>
        <input ref={inputRef} type="file" accept=".csv" className="hidden" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button onClick={analyze} disabled={!file || busy}
          className="rounded-xl px-5 py-2.5 font-semibold text-white bg-brand disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2">
          {busy && <Spinner />}
          {busy ? "Analyzing…" : "Analyze leads"}
        </button>
        {file && !busy && <button onClick={() => { setFile(null); reset(); }} className="text-muted text-sm hover:text-ink">Clear</button>}
      </div>

      {busy && (
        <div className="mt-5 rounded-xl border border-line bg-content px-5 py-4">
          <div className="flex items-center gap-3">
            <Spinner />
            <div className="font-semibold">{stage}…</div>
            <div className="ml-auto text-[0.8rem] text-muted tnum">{elapsed}s</div>
          </div>
          <div className="mt-3 h-1.5 rounded-full bg-pill overflow-hidden">
            <div className="h-full rounded-full bg-brand transition-all duration-500"
              style={{ width: `${Math.min(95, 12 + (Math.floor(elapsed / 4) / STAGES.length) * 88)}%` }} />
          </div>
          {elapsed >= 8 && (
            <div className="text-[0.78rem] text-muted mt-2.5">First run can take up to a minute while the local model warms up — later uploads are much faster.</div>
          )}
        </div>
      )}

      {error && <div className="mt-4 text-bad bg-white border border-line rounded-xl px-4 py-3 text-sm">{error}</div>}
      {notice && <div className="mt-4 text-ink bg-warnbg border border-line rounded-xl px-4 py-3 text-sm">{notice}</div>}

      {result && (
        <div className="mt-5">
          <div className="text-good font-semibold mb-3">✓ Analysis complete — your leads are in.</div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <Metric label="Scored & kept" value={num(result.scored)} />
            <Metric label="Duplicates merged" value={num(result.duplicates)} />
            <Metric label="Invalid rows" value={num(result.invalid)} />
          </div>
          {mapped.length > 0 && (
            <div className="rounded-xl border border-line overflow-hidden">
              <div className="bg-content px-4 py-2.5 text-[0.8rem] font-semibold">How your columns were mapped</div>
              <table className="w-full text-[0.84rem]">
                <tbody>
                  {mapped.map(([col, to]) => (
                    <tr key={col} className="border-t border-line"><td className="px-4 py-2">{col}</td><td className="px-4 py-2 text-right text-brand font-semibold">{to}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {unmapped.length > 0 && <div className="text-[0.78rem] text-muted mt-2">Kept in raw_payload, not mapped: {unmapped.join(", ")}</div>}
        </div>
      )}
    </Panel>
  );
}

function Spinner() {
  return <span className="w-[15px] h-[15px] rounded-full border-2 border-current border-t-transparent animate-spin inline-block" />;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-content rounded-xl px-4 py-3 border border-line">
      <div className="text-[0.72rem] text-muted uppercase tracking-wide font-bold">{label}</div>
      <div className="text-[1.4rem] font-bold tnum mt-0.5">{value}</div>
    </div>
  );
}
