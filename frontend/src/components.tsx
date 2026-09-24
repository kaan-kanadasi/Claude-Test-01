import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Range } from "./useSeries";
import type { Row } from "./series";

export interface Line {
  key: string;
  color: string; // CSS color, may be var(--x)
  label: string;
}

const TIME_FORMAT: Record<Range, Intl.DateTimeFormatOptions> = {
  live: { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" },
  "1h": { hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
  "24h": { hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
  "7d": { weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
};

export function TimeChart({
  rows, lines, range, format, max, height = 140,
}: {
  rows: Row[];
  lines: Line[];
  range: Range;
  format: (v: number) => string;
  max?: number;
  height?: number;
}) {
  if (rows.length < 2) {
    return (
      <div className="chart chart-empty" style={{ height }}>
        {range === "live" ? "Collecting the first readings…" : "No history for this period yet."}
      </div>
    );
  }
  const timeFmt = new Intl.DateTimeFormat(undefined, TIME_FORMAT[range]);
  return (
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--rule)" vertical={false} />
          <XAxis
            dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
            tickFormatter={(t) => timeFmt.format(t)} minTickGap={48}
            stroke="var(--muted)" tick={{ fontSize: 12 }} tickLine={false} axisLine={false}
          />
          <YAxis
            domain={[0, max ?? "auto"]} tickFormatter={format} width={74}
            // A known maximum gets evenly spaced 0 / half / max ticks; otherwise let Recharts pick 3.
            ticks={max ? [0, max / 2, max] : undefined} tickCount={3}
            stroke="var(--muted)" tick={{ fontSize: 12 }} tickLine={false} axisLine={false}
          />
          <Tooltip
            labelFormatter={(t) => timeFmt.format(Number(t))}
            formatter={(v, name) => [format(Number(v)), lines.find((l) => l.key === name)?.label ?? name]}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)" }}
          />
          {lines.map((l) => (
            <Area
              key={l.key} dataKey={l.key} name={l.key} type="monotone"
              stroke={l.color} strokeWidth={1.75} fill={l.color} fillOpacity={0.12}
              isAnimationActive={false} connectNulls={false} dot={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Meter({ fraction, color, label }: { fraction: number | undefined; color: string; label: string }) {
  const pct = Math.max(0, Math.min(1, fraction ?? 0)) * 100;
  return (
    <div className="meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <span style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export function Stats({ items }: { items: [string, string][] }) {
  return (
    <ul className="stats">
      {items.map(([k, v]) => (
        <li key={k}>
          <span className="k">{k}</span>
          <span className="v num">{v}</span>
        </li>
      ))}
    </ul>
  );
}

export function Legend({ lines }: { lines: Line[] }) {
  return (
    <div className="legend">
      {lines.map((l) => (
        <span key={l.key}><i style={{ background: l.color }} />{l.label}</span>
      ))}
    </div>
  );
}

/** Shown in place of a panel's data when its collector is failing or unavailable. */
export function CollectorNotice({ status }: { status: string | undefined }) {
  if (!status || status === "ok") return null;
  const error = status.startsWith("error");
  return (
    <p className={error ? "notice error" : "notice"}>
      {error ? `Reading failed: ${status.slice(7)}. Retrying automatically.` : status.replace(/^unavailable: /, "")}
    </p>
  );
}
