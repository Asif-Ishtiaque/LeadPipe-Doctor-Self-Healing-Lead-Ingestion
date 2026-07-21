import { useMemo } from "react";
import { useAnalytics, useInvalid } from "../hooks/queries";
import { Panel, StatCard } from "../components/ui";
import { SourceBars } from "../components/charts";
import { metricsFor, toBars } from "../lib/derive";
import { COLORS, num } from "../lib/format";

export default function DataQuality() {
  const inv = useInvalid();
  const { data: a } = useAnalytics();
  const invalid = inv.data ?? [];

  // True per-source counts come from SQL aggregates, not a sampled page of
  // rows (the old approach only ever showed whichever source happened to be
  // most recent).
  const invBySource = useMemo(() => (a ? toBars(a.invalid_by_source) : []), [a]);
  const dupBySource = useMemo(() => (a ? toBars(a.duplicate_by_source) : []), [a]);
  const failures = useMemo(() => topFailures(invalid), [invalid]);

  const m = a ? metricsFor(a) : null;
  const noConsent = m ? m.total - m.consent : 0;
  const noCampaign = m ? m.total - m.campaign : 0;

  return (
    <div className="flex flex-col gap-[18px]">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-[18px]">
        <Panel title="Invalid rows by source" cap="Which feed’s payloads fail validation most.">
          {invBySource.length ? <SourceBars data={invBySource} /> : <p className="text-muted text-sm">No invalid rows recorded yet.</p>}
        </Panel>
        <Panel title="Duplicates by source" cap="Which feed sends the most repeat submissions.">
          {dupBySource.length ? <SourceBars data={dupBySource} /> : <p className="text-muted text-sm">No duplicates recorded yet.</p>}
        </Panel>
      </div>

      <Panel title="Most common validation failures" cap="The specific reasons rows get rejected.">
        {failures.length ? (
          <div className="flex flex-col gap-2">
            {failures.map((f) => {
              const max = failures[0].count;
              return (
                <div key={f.reason} className="grid grid-cols-[1fr_auto] items-center gap-3">
                  <div className="h-6 rounded-md flex items-center px-2 text-[0.78rem] text-white" style={{ width: `${(f.count / max) * 100}%`, background: COLORS.bad, minWidth: "120px" }}>{f.reason}</div>
                  <span className="text-[0.8rem] font-bold tnum">{num(f.count)}</span>
                </div>
              );
            })}
          </div>
        ) : <p className="text-muted text-sm">No parseable failure details yet.</p>}
      </Panel>

      <div>
        <h3 className="text-[1.02rem] font-bold mb-1">Compliance &amp; completeness gaps</h3>
        <p className="text-[0.8rem] text-muted mb-3.5">These leads pass validation, so they surface nowhere else — but they’re worth a human glance.</p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <StatCard label="No marketing consent" value={num(noConsent)} sub="cannot be cold-called (TCPA)" accent={COLORS.warn} />
          <StatCard label="No campaign tag" value={num(noCampaign)} sub="can’t be attributed to ROI" accent={COLORS.dup} />
        </div>
      </div>
    </div>
  );
}

function topFailures(invalid: Record<string, unknown>[]): { reason: string; count: number }[] {
  const m = new Map<string, number>();
  for (const row of invalid) {
    let errs = row["errors"];
    if (typeof errs === "string") { try { errs = JSON.parse(errs); } catch { errs = null; } }
    if (Array.isArray(errs)) {
      for (const e of errs as { loc?: unknown[]; msg?: string }[]) {
        const field = Array.isArray(e.loc) ? e.loc.join(".") : "unknown field";
        const reason = `${field}: ${e.msg ?? "invalid value"}`;
        m.set(reason, (m.get(reason) ?? 0) + 1);
      }
    }
  }
  return [...m.entries()].map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count).slice(0, 8);
}
