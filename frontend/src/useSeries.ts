import { useEffect, useMemo, useState } from "react";
import { fetchHistory, type Snapshot } from "./api";
import { historyToRows, snapshotsToRows, type Row } from "./series";

export type Range = "live" | "1h" | "24h" | "7d";

export const RANGES: { id: Range; label: string; seconds: number }[] = [
  { id: "live", label: "Live", seconds: 300 },
  { id: "1h", label: "1 hour", seconds: 3600 },
  { id: "24h", label: "24 hours", seconds: 86_400 },
  { id: "7d", label: "7 days", seconds: 7 * 86_400 },
];

const HISTORY_REFRESH_MS = 30_000;

/** Chart rows for `keys`: from the live buffer, or from stored history for longer ranges. */
export function useSeries(keys: string[], range: Range, live: Snapshot[]): Row[] {
  const keyId = keys.join(",");
  const liveRows = useMemo(
    () => (range === "live" ? snapshotsToRows(live, keys) : []),
    [range, live, keyId],
  );
  const [historyRows, setHistoryRows] = useState<Row[]>([]);

  useEffect(() => {
    if (range === "live" || keys.length === 0) return;
    const seconds = RANGES.find((r) => r.id === range)!.seconds;
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      const end = Date.now() / 1000;
      fetchHistory(keys, end - seconds, end, controller.signal)
        .then((h) => setHistoryRows(historyToRows(h, keys)))
        .catch((e) => {
          if (e.name !== "AbortError") setHistoryRows([]);
        });
    };
    setHistoryRows([]);
    load();
    const timer = window.setInterval(load, HISTORY_REFRESH_MS);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [range, keyId]);

  return range === "live" ? liveRows : historyRows;
}
