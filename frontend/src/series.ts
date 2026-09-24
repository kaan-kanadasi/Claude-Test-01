import type { History, Snapshot } from "./api";

/** A chart row: time in ms plus one column per metric key (null = no data). */
export type Row = { t: number } & Record<string, number | null>;

export function snapshotsToRows(snaps: Snapshot[], keys: string[]): Row[] {
  return snaps.map((s) => {
    const row: Row = { t: s.ts * 1000 };
    for (const k of keys) row[k] = s.metrics[k] ?? null;
    return row;
  });
}

export function historyToRows(h: History, keys: string[]): Row[] {
  const byTime = new Map<number, Row>();
  for (const k of keys) {
    for (const [ts, v] of h.series[k] ?? []) {
      let row = byTime.get(ts);
      if (!row) {
        row = { t: ts * 1000 };
        for (const kk of keys) row[kk] = null;
        byTime.set(ts, row);
      }
      row[k] = v;
    }
  }
  const sorted = [...byTime.values()].sort((a, b) => a.t - b.t);

  // Break lines across periods with no data (e.g. the monitor wasn't running).
  const gapMs = Math.max(2 * h.step, MIN_GAP_S) * 1000;
  const out: Row[] = [];
  for (const row of sorted) {
    const prev = out.at(-1);
    if (prev && row.t - prev.t > gapMs) {
      const hole: Row = { t: prev.t + h.step * 1000 };
      for (const k of keys) hole[k] = null;
      out.push(hole);
    }
    out.push(row);
  }
  return out;
}

/** Shortest silence treated as a gap; must exceed the backend's persist interval. */
const MIN_GAP_S = 30;

export function pushBounded<T>(arr: T[], item: T, limit: number): T[] {
  const next = arr.length >= limit ? arr.slice(arr.length - limit + 1) : arr.slice();
  next.push(item);
  return next;
}

/** Mirror of the backend's metric_key(): dotted parts with unsafe characters replaced. */
export function metricKey(...parts: (string | number)[]): string {
  return parts.map((p) => String(p).replace(/[.:\\/]+/g, "_").replace(/^_+|_+$/g, "")).join(".");
}
