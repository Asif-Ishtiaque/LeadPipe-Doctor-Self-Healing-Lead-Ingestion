import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDatasets, useDeleteDataset, useRenameDataset } from "../hooks/queries";
import { useActiveDataset } from "../lib/datasetContext";
import { api } from "../lib/api";
import { COLORS, num, prettySource } from "../lib/format";
import type { Dataset } from "../lib/types";

const STATUS: Record<string, { label: string; color: string }> = {
  completed: { label: "Completed", color: COLORS.good },
  processing: { label: "Processing", color: COLORS.brand },
  failed: { label: "Failed", color: COLORS.bad },
};

export default function Datasets() {
  const { data, isError, isLoading } = useDatasets();
  const { datasetId, setDatasetId } = useActiveDataset();
  const navigate = useNavigate();
  const datasets = data ?? [];

  if (isError) return <div className="text-bad bg-panel rounded-xl2 border border-line p-6">Couldn’t reach the API.</div>;
  if (isLoading) return <div className="grid grid-cols-1 md:grid-cols-2 gap-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-40 rounded-2xl bg-panel border border-line animate-pulse" />)}</div>;

  function open(id: string | null) {
    setDatasetId(id);
    navigate("/");
  }

  return (
    <div className="flex flex-col gap-[18px]">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <button
          onClick={() => open(null)}
          className={`rounded-xl px-4 py-2 text-[0.85rem] font-semibold border transition-colors ${datasetId === null ? "bg-pill text-ink border-line2" : "text-muted border-line2 hover:text-ink hover:bg-content"}`}
        >
          {datasetId === null ? "✓ " : ""}All datasets (aggregate)
        </button>
        <button onClick={() => navigate("/upload")} className="rounded-xl px-5 py-2.5 font-semibold text-white bg-brand">
          + Upload dataset
        </button>
      </div>

      {datasets.length === 0 ? (
        <div className="bg-panel rounded-xl2 border border-line shadow-card p-10 text-center">
          <div className="text-3xl mb-2">📂</div>
          <div className="font-semibold">No datasets yet</div>
          <div className="text-muted text-[0.85rem] mt-1">Upload a CSV to create your first dataset.</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {datasets.map((d) => (
            <Card key={d.dataset_id} d={d} active={d.dataset_id === datasetId} onOpen={() => open(d.dataset_id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function Card({ d, active, onOpen }: { d: Dataset; active: boolean; onOpen: () => void }) {
  const del = useDeleteDataset();
  const rename = useRenameDataset();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(d.name);
  const [confirmDel, setConfirmDel] = useState(false);
  const st = STATUS[d.status] ?? { label: d.status, color: COLORS.muted };

  function saveName() {
    setEditing(false);
    const trimmed = name.trim();
    if (trimmed && trimmed !== d.name) rename.mutate({ id: d.dataset_id, name: trimmed });
  }

  return (
    <div className={`bg-panel rounded-2xl border shadow-card p-5 transition ${active ? "border-brand ring-1 ring-brand/30" : "border-line hover:shadow-lift"}`}>
      <div className="flex items-start justify-between gap-2 mb-1">
        {editing ? (
          <input
            autoFocus value={name} onChange={(e) => setName(e.target.value)}
            onBlur={saveName} onKeyDown={(e) => { if (e.key === "Enter") saveName(); if (e.key === "Escape") { setName(d.name); setEditing(false); } }}
            className="font-bold text-[1.02rem] border border-line2 rounded-lg px-2 py-1 outline-none focus:border-brand w-full mr-2"
          />
        ) : (
          <button onClick={onOpen} className="font-bold text-[1.02rem] text-left hover:text-brand truncate">{d.name}</button>
        )}
        <span className="inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full text-[0.68rem] font-bold shrink-0" style={{ color: st.color, background: `${st.color}1A` }}>
          {d.status === "processing" && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: st.color }} />}
          {st.label}
        </span>
      </div>
      <div className="text-[0.74rem] text-muted mb-4">
        {d.source_kind ? prettySource(d.source_kind) : "upload"} · {fmtDate(d.created_at)}
        {active && <span className="ml-2 text-brand font-bold">· viewing</span>}
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <Stat label="Leads" value={num(d.total_leads ?? 0)} />
        <Stat label="Flagged" value={num(d.flagged ?? 0)} />
        <Stat label="Avg score" value={d.avg_score != null ? String(d.avg_score) : "—"} />
      </div>

      <div className="flex items-center gap-2 flex-wrap text-[0.82rem]">
        <button onClick={onOpen} className="rounded-lg px-3 py-1.5 font-semibold text-white bg-brand">View</button>
        <button onClick={() => setEditing(true)} className="rounded-lg px-3 py-1.5 font-semibold text-muted border border-line2 hover:text-ink">Rename</button>
        <a href={api.datasetExportUrl(d.dataset_id)} className="rounded-lg px-3 py-1.5 font-semibold text-muted border border-line2 hover:text-ink no-underline">Export</a>
        {confirmDel ? (
          <span className="inline-flex items-center gap-1.5 ml-auto">
            <button onClick={() => del.mutate(d.dataset_id)} disabled={del.isPending}
              className="rounded-lg px-3 py-1.5 font-semibold text-white disabled:opacity-50" style={{ background: COLORS.bad }}>
              {del.isPending ? "Deleting…" : "Confirm"}
            </button>
            <button onClick={() => setConfirmDel(false)} className="text-muted hover:text-ink">Cancel</button>
          </span>
        ) : (
          <button onClick={() => setConfirmDel(true)} className="rounded-lg px-3 py-1.5 font-semibold text-bad hover:bg-warnbg ml-auto">Delete</button>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-content rounded-xl px-3 py-2 border border-line">
      <div className="text-[0.64rem] uppercase tracking-wide text-faint font-bold">{label}</div>
      <div className="text-[1.05rem] font-bold tnum mt-0.5">{value}</div>
    </div>
  );
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
