import { useEffect, useRef, useState } from "react";
import { pushBounded } from "./series";

export interface Snapshot {
  ts: number; // epoch seconds
  metrics: Record<string, number>;
  status: Record<string, string>;
}

export interface GpuInfo {
  id: string;
  name: string;
  vendor: string;
  vram_total: number;
  driver: string | null;
  source: "nvml" | "pdh";
}

export interface Info {
  cpu?: { name: string; cores: number; threads: number; base_mhz: number | null };
  memory?: { total: number; swap_total: number };
  gpus: GpuInfo[];
  disks?: { id: string; mountpoint: string; fstype: string; total: number }[];
  network?: { name: string; speed_mbps: number; addresses: string[] }[];
  unavailable: Record<string, string>;
  config: { sample_interval: number; persist_interval: number };
}

export interface History {
  source: "raw" | "1m";
  step: number;
  series: Record<string, [number, number][]>;
}

export async function fetchInfo(): Promise<Info> {
  const r = await fetch("/api/info");
  if (!r.ok) throw new Error(`Couldn't load hardware info (HTTP ${r.status})`);
  return r.json();
}

export async function fetchHistory(keys: string[], start: number, end: number, signal?: AbortSignal): Promise<History> {
  const params = new URLSearchParams({ keys: keys.join(","), start: String(start), end: String(end) });
  const r = await fetch(`/api/history?${params}`, { signal });
  if (!r.ok) throw new Error(`Couldn't load history (HTTP ${r.status})`);
  return r.json();
}

export type Connection = "connecting" | "live" | "offline";

/** Live snapshots over WebSocket, keeping the last `keep` of them. Reconnects with backoff. */
export function useLiveSnapshots(keep: number) {
  const [buffer, setBuffer] = useState<Snapshot[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/live`);
      ws.onopen = () => {
        retry.current = 0;
        setConnection("live");
      };
      ws.onmessage = (ev) => {
        const snap: Snapshot = JSON.parse(ev.data);
        setBuffer((b) => pushBounded(b, snap, keep));
      };
      ws.onclose = () => {
        if (closed) return;
        setConnection("offline");
        const delay = Math.min(1000 * 2 ** retry.current, 15_000);
        retry.current++;
        timer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, [keep]);

  return { buffer, latest: buffer.at(-1), connection };
}
