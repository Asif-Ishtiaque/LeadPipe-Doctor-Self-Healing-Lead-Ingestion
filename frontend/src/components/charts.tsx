import {
  Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { COLORS, num, prettySource, SOURCE_COLORS, STATUS_COLORS } from "../lib/format";

const AXIS = { fontSize: 12, fill: COLORS.muted };

// Recharts' enter animation starts marks at zero size and tweens up. With our
// 8s live refetch (and a second data fetch resolving after mount), a re-render
// can land mid-animation and leave bars stuck at their 0-height start frame.
// Rendering at final size immediately is both correct and avoids the whole
// dashboard re-animating on every poll.
const NO_ANIM = { isAnimationActive: false } as const;

export function SourceBars({ data }: { data: { source: string; count: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <XAxis dataKey="source" tickFormatter={prettySource} tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} />
        <Tooltip formatter={(v: number) => num(v)} cursor={{ fill: "#00000008" }} />
        <Bar dataKey="count" radius={[8, 8, 4, 4]} maxBarSize={64} {...NO_ANIM}>
          {data.map((d) => <Cell key={d.source} fill={SOURCE_COLORS[d.source] ?? COLORS.brand} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function OutcomeDonut({ data }: { data: { name: string; value: number }[] }) {
  const total = data.reduce((a, b) => a + b.value, 0);
  return (
    <div className="flex items-center gap-6 flex-wrap">
      <ResponsiveContainer width={190} height={190}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={58} outerRadius={90} paddingAngle={1} stroke="none" {...NO_ANIM}>
            {data.map((d) => <Cell key={d.name} fill={STATUS_COLORS[d.name] ?? COLORS.muted} />)}
          </Pie>
          <Tooltip formatter={(v: number) => `${num(v)} (${((v / total) * 100).toFixed(1)}%)`} />
        </PieChart>
      </ResponsiveContainer>
      <div className="flex flex-col gap-2.5 text-[0.84rem]">
        {data.map((d) => (
          <div key={d.name} className="flex items-center gap-2.5">
            <span className="w-2.5 h-2.5 rounded" style={{ background: STATUS_COLORS[d.name] ?? COLORS.muted }} />
            <span className="capitalize">{d.name}</span>
            <b className="ml-auto tnum">{total ? ((d.value / total) * 100).toFixed(1) : "0"}%</b>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ScoreHistogram({ data }: { data: { bucket: string; clean: number; flagged: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={230}>
      <BarChart data={data} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
        <XAxis dataKey="bucket" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} width={44} />
        <Tooltip formatter={(v: number) => num(v)} cursor={{ fill: "#00000008" }} />
        <Bar dataKey="clean" stackId="s" fill={COLORS.good} radius={[0, 0, 0, 0]} {...NO_ANIM} />
        <Bar dataKey="flagged" stackId="s" fill={COLORS.warn} radius={[6, 6, 0, 0]} {...NO_ANIM} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AvgBySource({ data }: { data: { source: string; avg: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart layout="vertical" data={data} margin={{ top: 6, right: 20, left: 8, bottom: 0 }}>
        <XAxis type="number" domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="source" tickFormatter={prettySource} tick={AXIS} axisLine={false} tickLine={false} width={92} />
        <Tooltip formatter={(v: number) => `${v} avg`} cursor={{ fill: "#00000008" }} />
        <Bar dataKey="avg" radius={[4, 4, 4, 4]} maxBarSize={26} {...NO_ANIM}>
          {data.map((d) => (
            <Cell key={d.source} fill={d.avg >= 70 ? COLORS.good : d.avg >= 40 ? COLORS.warn : COLORS.bad} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export type RadarSeries = { source: string; color: string; values: Record<string, number> };

// Hand-rolled SVG radar. Recharts' RadarChart (2.15) throws internally under
// StrictMode's double-render ("Cannot read properties of null (reading 'map')"),
// so we render our own — deterministic, dependency-free, and it degrades
// gracefully when there are fewer than 3 axes.
export function SignalRadar({ axes, series }: { axes: string[]; series: RadarSeries[] }) {
  const SIZE = 240;
  const C = SIZE / 2;
  const R = 82;
  const n = axes.length;
  if (n < 3) return <div className="h-[230px] grid place-items-center text-[0.82rem] text-muted">Not enough signals to plot.</div>;

  const angle = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const point = (i: number, radius: number): [number, number] => [
    C + radius * Math.cos(angle(i)),
    C + radius * Math.sin(angle(i)),
  ];
  const polygon = (radiusFor: (i: number) => number) =>
    axes.map((_, i) => point(i, radiusFor(i)).join(",")).join(" ");

  const rings = [0.25, 0.5, 0.75, 1];

  return (
    <div className="h-[230px] grid place-items-center">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width="100%" height={230} role="img" aria-label="Signal completeness radar">
        {/* grid rings */}
        {rings.map((f) => (
          <polygon key={f} points={polygon(() => R * f)} fill="none" stroke="#E3E6EC" strokeWidth={1} />
        ))}
        {/* spokes + axis labels */}
        {axes.map((axis, i) => {
          const [sx, sy] = point(i, R);
          const [lx, ly] = point(i, R + 16);
          return (
            <g key={axis}>
              <line x1={C} y1={C} x2={sx} y2={sy} stroke="#E3E6EC" strokeWidth={1} />
              <text
                x={lx}
                y={ly}
                fontSize={11}
                fill={COLORS.muted}
                textAnchor={Math.abs(lx - C) < 2 ? "middle" : lx > C ? "start" : "end"}
                dominantBaseline="middle"
              >
                {axis}
              </text>
            </g>
          );
        })}
        {/* series polygons */}
        {series.map((s) => (
          <polygon
            key={s.source}
            points={polygon((i) => (R * (s.values[axes[i]] ?? 0)) / 100)}
            fill={s.color}
            fillOpacity={0.13}
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        ))}
      </svg>
    </div>
  );
}

// Diverging "butterfly": clean (left) vs flagged (right) across score bands.
export function Butterfly({ rows }: { rows: { band: string; clean: number; flagged: number }[] }) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.clean, r.flagged]));
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex gap-4 justify-center text-[0.8rem] font-semibold mb-1.5">
        <span className="inline-flex items-center gap-1.5"><i className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: COLORS.brand }} />Clean</span>
        <span className="inline-flex items-center gap-1.5"><i className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: COLORS.warn }} />Flagged</span>
      </div>
      {rows.map((r) => (
        <div key={r.band} className="grid grid-cols-[1fr_58px_1fr] items-center gap-2">
          <div className="flex justify-end"><div className="h-[15px] rounded" style={{ width: `${(r.clean / max) * 100}%`, background: COLORS.brand }} title={`${num(r.clean)} clean`} /></div>
          <div className="text-center text-[0.74rem] text-muted font-semibold tnum">{r.band}</div>
          <div className="flex justify-start"><div className="h-[15px] rounded" style={{ width: `${(r.flagged / max) * 100}%`, background: COLORS.warn }} title={`${num(r.flagged)} flagged`} /></div>
        </div>
      ))}
    </div>
  );
}
