import { useMemo } from "react";
import { useAnalytics, useTopLeads } from "../hooks/queries";
import { Avatar, Panel, StatCard } from "../components/ui";
import { AvgBySource, ScoreHistogram, SignalRadar, type RadarSeries } from "../components/charts";
import { avgBySource, buildRadar, buildScoreHistogram, funnel, metricsFor } from "../lib/derive";
import { bandColor, COLORS, initials, leadName, num, prettySource } from "../lib/format";

export default function LeadAnalytics() {
  const { data: a, isError } = useAnalytics();
  const topQ = useTopLeads(8);
  const top = topQ.data ?? [];

  const m = useMemo(() => (a ? metricsFor(a) : null), [a]);
  const fun = useMemo(() => (a ? funnel(a) : { high: 0, medium: 0, low: 0 }), [a]);
  const hist = useMemo(() => (a ? buildScoreHistogram(a) : []), [a]);
  const bySrc = useMemo(() => (a ? avgBySource(a) : []), [a]);
  const radar = useMemo(() => (a ? buildRadar(a) : { axes: [], series: [] }), [a]);

  if (isError) return <div className="text-bad">Couldn’t reach the API.</div>;
  if (!a || !m) return <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-24 rounded-2xl bg-panel border border-line animate-pulse" />)}</div>;

  const scoredCount = m.scored;
  const consentPct = scoredCount ? Math.round((m.consent / scoredCount) * 100) : 0;
  const pct = (n: number) => (scoredCount ? Math.round((n / scoredCount) * 1000) / 10 : 0);

  return (
    <div className="flex flex-col gap-[18px]">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Scored leads" value={num(scoredCount)} sub="in view" accent={COLORS.brand} />
        <StatCard label="High quality" value={num(fun.high)} sub={`${pct(fun.high)}% of scored`} accent={COLORS.good} />
        <StatCard label="Low quality" value={num(fun.low)} sub={`${pct(fun.low)}% — deprioritize`} accent={COLORS.bad} />
        <StatCard label="Consented" value={`${consentPct}%`} sub="opted in to contact" accent={COLORS.dup} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-[18px]">
        <Panel title="Quality funnel" cap="How scored leads split across the priority bands.">
          <div className="flex flex-col items-center gap-2 pt-1">
            <Fbar label="High" value={fun.high} pct={100} color={COLORS.good} />
            <Fbar label="Medium" value={fun.medium} pct={fun.high ? Math.round((fun.medium / fun.high) * 100) : 100} color={COLORS.warn} />
            <Fbar label="Low" value={fun.low} pct={fun.high ? Math.round((fun.low / fun.high) * 100) : 100} color={COLORS.bad} />
          </div>
        </Panel>
        <Panel title="Score distribution" cap="Every scored lead, bucketed 0–100."><ScoreHistogram data={hist} /></Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-[18px]">
        <Panel title="Avg score by source" cap="Which feed brings the strongest leads."><AvgBySource data={bySrc} /></Panel>
        <Panel title="Signal completeness by source" cap="Share of each feed’s leads carrying every quality signal.">
          <SignalRadar axes={radar.axes} series={radar.series as RadarSeries[]} />
          <div className="flex gap-4 justify-center text-[0.8rem] mt-1.5">
            {radar.series.map((s) => <span key={s.source} className="inline-flex items-center gap-1.5"><i className="w-4 h-[3px] rounded" style={{ background: s.color }} />{prettySource(s.source)}</span>)}
          </div>
        </Panel>
      </div>

      <Panel title="Top leads to work now" cap="Highest-scoring leads in view — your call list.">
        <table className="w-full text-[0.85rem]">
          <thead><tr className="text-[0.68rem] uppercase tracking-wide text-faint">
            <th className="text-left pb-2.5 font-bold">Name</th><th className="text-left pb-2.5 font-bold">Source</th>
            <th className="text-right pb-2.5 font-bold">Score</th><th className="text-left pb-2.5 pl-4 font-bold">Why it scored high</th></tr></thead>
          <tbody>
            {top.map((l, i) => (
              <tr key={l.lead_id} className="border-t border-line">
                <td className="py-2.5"><div className="flex items-center gap-2.5"><Avatar text={initials(l)} color={["#2563EB","#7C5CFC","#0EA5E9","#F59E0B","#16A34A"][i % 5]} /><span className="font-semibold">{leadName(l)}</span></div></td>
                <td className="py-2.5 text-muted">{prettySource(l.source)}</td>
                <td className="py-2.5 text-right font-extrabold tnum" style={{ color: bandColor(l.quality_score) }}>{l.quality_score?.toFixed(0)}</td>
                <td className="py-2.5 pl-4 text-muted max-w-[340px]">{l.diagnosis ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function Fbar({ label, value, pct, color }: { label: string; value: number; pct: number; color: string }) {
  return (
    <div className="text-white rounded-lg py-3.5 text-center font-bold" style={{ width: `${Math.max(24, Math.min(100, pct))}%`, background: color }}>
      {num(value)}<span className="block font-semibold opacity-90 text-[0.74rem] mt-0.5">{label}</span>
    </div>
  );
}
