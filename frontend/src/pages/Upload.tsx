import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useActiveDataset } from "../lib/datasetContext";
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
  const navigate = useNavigate();
  const { setDatasetId } = useActiveDataset();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<IngestSummary | null>(null);
  const [newDatasetId, setNewDatasetId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Tick the elapsed-seconds counter while a request is in flight.
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);

  const reset = () => { setResult(null); setNewDatasetId(null); setNotice(null); setError(null); };

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
      const resp = await api.uploadDataset(file, { signal: ac.signal });
      if (resp.status === "error") {
        setError(resp.message ?? "We couldn't finish processing this file. Please try again.");
      } else if (!resp.summary) {
        setNotice("We couldn't auto-process this file, so it's been sent to the review queue. It may be malformed or in a format we haven't seen yet.");
      } else if (resp.summary.scored + resp.summary.duplicates + resp.summary.invalid === 0) {
        setNotice("No rows found in this file. Make sure it has a header row and at least one row of data.");
      } else {
        setResult(resp.summary);
        setNewDatasetId(resp.dataset_id ?? null);
        qc.invalidateQueries(); // refresh dashboard + dataset list
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
    <div className="flex flex-col gap-[18px]">
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
          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <div className="text-good font-semibold">✓ Analysis complete — a new dataset is ready.</div>
            {newDatasetId && (
              <button
                onClick={() => { setDatasetId(newDatasetId); navigate("/"); }}
                className="rounded-xl px-4 py-2 font-semibold text-white bg-brand text-[0.85rem]">
                View dataset →
              </button>
            )}
          </div>
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

    <ResetSection />
    </div>
  );
}

function ResetSection() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [opts, setOpts] = useState({ leads: true, review_queue: true, chroma: false });
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function confirm() {
    setBusy(true); setErr(null);
    try {
      await api.resetWorkspace(opts);
      await qc.invalidateQueries();
      setDone("Workspace cleared. The dashboard is back to an empty state.");
      setOpen(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Reset failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-panel rounded-xl2 px-[22px] py-5 border border-line shadow-card" style={{ borderLeft: "4px solid #E5484D" }}>
      <h3 className="m-0 text-[1.02rem] font-bold">Reset workspace</h3>
      <p className="text-[0.78rem] text-muted mt-1 mb-3.5">Clear all leads and the review queue to start the demo from a clean slate. This can’t be undone.</p>
      {done && <div className="mb-3 text-good bg-goodbg border border-line rounded-xl px-4 py-2.5 text-[0.85rem]">{done}</div>}
      <button onClick={() => { setDone(null); setOpen(true); }}
        className="rounded-xl px-4 py-2.5 font-semibold text-bad border border-bad/40 hover:bg-warnbg transition-colors">
        Reset workspace…
      </button>

      {open && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4" onClick={() => !busy && setOpen(false)}>
          <div className="bg-panel rounded-2xl shadow-lift max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-[1.1rem] font-bold m-0">Reset workspace?</h3>
            <p className="text-[0.85rem] text-muted mt-1.5 mb-4">This permanently clears the selected data. It can’t be undone.</p>
            <div className="flex flex-col gap-2.5 mb-5">
              <Check label="Clear all leads (and pipeline history)" checked={opts.leads} onChange={(v) => setOpts((o) => ({ ...o, leads: v }))} />
              <Check label="Clear the human-review queue" checked={opts.review_queue} onChange={(v) => setOpts((o) => ({ ...o, review_queue: v }))} />
              <Check label="Clear AI column-mapping memory" checked={opts.chroma} onChange={(v) => setOpts((o) => ({ ...o, chroma: v }))} sub="uploads re-learn column mappings from scratch" />
            </div>
            {err && <div className="mb-3 text-bad text-[0.82rem]">{err}</div>}
            <div className="flex justify-end gap-2.5">
              <button onClick={() => setOpen(false)} disabled={busy} className="px-4 py-2 rounded-xl font-semibold text-muted hover:text-ink disabled:opacity-50">Cancel</button>
              <button onClick={confirm} disabled={busy || (!opts.leads && !opts.review_queue && !opts.chroma)}
                className="px-4 py-2 rounded-xl font-semibold text-white inline-flex items-center gap-2 disabled:opacity-50" style={{ background: "#E5484D" }}>
                {busy && <Spinner />}{busy ? "Resetting…" : "Reset now"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Check({ label, sub, checked, onChange }: { label: string; sub?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-2.5 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 w-4 h-4 accent-brand" />
      <span className="text-[0.88rem] leading-tight">{label}{sub && <span className="block text-[0.74rem] text-muted">{sub}</span>}</span>
    </label>
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
