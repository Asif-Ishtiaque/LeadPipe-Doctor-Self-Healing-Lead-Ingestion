import { useMemo, useState } from "react";
import { useAnalytics, useStats, useTopLeads } from "../hooks/queries";
import { Avatar, KpiCard, Panel } from "../components/ui";
import { Butterfly, SignalRadar, type RadarSeries } from "../components/charts";
import { bandColor, num, prettySource, SOURCE_COLORS } from "../lib/format";
import { buildButterfly, buildRadar, kpis, sources as sourcesOf } from "../lib/derive";
import type { Lead } from "../lib/types";

const IconUsers = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="8" r="3"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M16 5.2a3.2 3.2 0 0 1 0 6"/></svg>);
const IconCheck = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 7 10 17l-5-5"/></svg>);
const IconFlag = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 21V4h11l-1.5 3.5L16 11H5"/></svg>);
const IconGauge = () => (<svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3a9 9 0 1 0 9 9"/><path d="M12 12 18 6"/></svg>);

export default function Overview() {
  const stats = useStats();
  const analyticsQ = useAnalytics();
  const [tab, setTab] = useState<string>("All");
  const src = tab === "All" ? undefined : tab;
  const topQ = useTopLeads(6, { source: src });

  const s = stats.data;
  const a = analyticsQ.data;
  const topLeads = topQ.data ?? [];

  const sources = useMemo(() => (a ? sourcesOf(a) : []), [a]);
  const k = useMemo(() => (a ? kpis(a, src) : null), [a, src]);
  const butterfly = useMemo(() => (a ? buildButterfly(a, src) : []), [a, src]);
  const radar = useMemo(() => (a ? buildRadar(a) : { axes: [], series: [] }), [a]);
  const processed = s ? s.total_clean + s.total_flagged + s.total_invalid + s.total_duplicates : 0;

  if (analyticsQ.isError || stats.isError)
    return <div className="text-bad bg-white rounded-xl2 border border-line p-6">Couldn’t reach the API at <code>{import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}</code>. Is the FastAPI service running (and CORS enabled)?</div>;
  if (!s || !a || !k) return <Skeleton />;

  return (
    <div className="flex flex-col gap-[18px]">
      {/* source tabs */}
      <div className="flex gap-6 border-b border-line">
        {["All", ...sources].map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`pb-3.5 pt-2.5 text-[0.92rem] font-semibold relative ${tab === t ? "text-ink" : "text-muted hover:text-ink"}`}>
            {t === "All" ? "All sources" : prettySource(t)}
            {tab === t && <span className="absolute left-0 right-0 -bottom-px h-[2.5px] rounded bg-brand" />}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.35fr] gap-[18px]">
        <div className="grid grid-cols-2 gap-4">
          <KpiCard icon={<IconUsers />} label="Total leads" value={num(k.total)} />
          <KpiCard icon={<IconCheck />} label="Clean leads" value={num(k.clean)} />
          <KpiCard icon={<IconFlag />} label="Flagged" value={num(k.flagged)} />
          <KpiCard icon={<IconGauge />} label="Avg lead score" value={k.avg != null ? String(k.avg) : "—"} />
        </div>

        <div className="bg-panel rounded-xl2 px-6 py-[22px] border border-line shadow-card flex flex-col">
          <h3 className="m-0 text-[1.02rem] font-bold mb-4">Where your leads come from</h3>
          <div className="grid grid-cols-[auto_1fr] gap-8 flex-1">
            <div className="flex flex-col gap-4">
              <Reach k="Records processed" v={num(processed)} />
              <Reach k="Connected sources" v={String(sources.length)} />
              <Reach k="High-quality rate" v={`${k.highPct}%`} />
              <Reach k="Human review" v={num(s.human_review_pending)} />
            </div>
            <div className="flex flex-col gap-3 justify-center">
              {sources.map((src) => {
                const c = s.leads_by_source[src] ?? 0;
                const maxc = Math.max(...Object.values(s.leads_by_source));
                return (
                  <div key={src} className="grid grid-cols-[96px_1fr_auto] items-center gap-3 text-[0.82rem]">
                    <span>{prettySource(src)}</span>
                    <span className="h-2.5 rounded-full bg-pill overflow-hidden"><i className="block h-full rounded-full" style={{ width: `${maxc ? (c / maxc) * 100 : 0}%`, background: SOURCE_COLORS[src] ?? "#2563EB" }} /></span>
                    <span className="text-white bg-chip px-2.5 py-[3px] rounded-lg text-[0.74rem] font-bold tnum">{num(c)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-[18px]">
        <Panel title="Top leads" cap="Highest-scoring leads to work first.">
          <table className="w-full text-[0.85rem]">
            <thead><tr className="text-[0.68rem] uppercase tracking-wide text-faint"><th className="text-left pb-2.5 font-bold">Name</th><th className="text-right pb-2.5 font-bold">Source</th><th className="text-right pb-2.5 font-bold">Score</th></tr></thead>
            <tbody>
              {topLeads.map((l, i) => <TopRow key={l.lead_id} l={l} i={i} />)}
              {topLeads.length === 0 && <tr><td colSpan={3} className="py-3 text-muted">No scored leads yet.</td></tr>}
            </tbody>
          </table>
        </Panel>
        <Panel title="Clean vs. flagged" cap="How leads split across score bands."><Butterfly rows={butterfly} /></Panel>
        <Panel title="Signal completeness" cap="Data richness per source.">
          <SignalRadar axes={radar.axes} series={radar.series as RadarSeries[]} />
          <div className="flex gap-4 justify-center text-[0.8rem] mt-1.5">
            {radar.series.map((s2) => <span key={s2.source} className="inline-flex items-center gap-1.5"><i className="w-4 h-[3px] rounded" style={{ background: s2.color }} />{prettySource(s2.source)}</span>)}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Reach({ k, v }: { k: string; v: string }) {
  return <div><div className="text-[0.82rem] text-muted">{k}</div><div className="text-[1.32rem] font-bold tracking-tight mt-0.5 tnum">{v}</div></div>;
}

const AV = ["#2563EB", "#7C5CFC", "#0EA5E9", "#F59E0B", "#16A34A"];
function TopRow({ l, i }: { l: Lead; i: number }) {
  const name = [l.first_name, l.last_name].filter(Boolean).join(" ") || "(no name)";
  const ini = name === "(no name)" ? "?" : name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <tr className="border-t border-line">
      <td className="py-2.5"><div className="flex items-center gap-2.5"><Avatar text={ini} color={AV[i % AV.length]} /><span className="font-semibold">{name}</span></div></td>
      <td className="py-2.5 text-right text-muted">{prettySource(l.source)}</td>
      <td className="py-2.5 text-right font-extrabold tnum" style={{ color: bandColor(l.quality_score) }}>{l.quality_score?.toFixed(0)}</td>
    </tr>
  );
}

function Skeleton() {
  return <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-28 rounded-2xl bg-panel border border-line animate-pulse" />)}</div>;
}
