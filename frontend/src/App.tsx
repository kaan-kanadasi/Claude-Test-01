import { useEffect, useState } from "react";
import { fetchInfo, useLiveSnapshots, type Connection, type Info } from "./api";
import { CpuHero, GpuPanel, MemoryPanel, NetworkPanel, SensorsPanel, StoragePanel } from "./panels";
import { RANGES, type Range } from "./useSeries";

const LIVE_POINTS = 300; // five minutes at one sample per second

const CONNECTION_TEXT: Record<Connection, string> = {
  connecting: "Connecting…",
  live: "Updating every second",
  offline: "Reconnecting…",
};

export default function App() {
  const [info, setInfo] = useState<Info>();
  const [infoError, setInfoError] = useState<string>();
  const [range, setRange] = useState<Range>("live");
  const { buffer, latest, connection } = useLiveSnapshots(LIVE_POINTS);

  useEffect(() => {
    let timer: number | undefined;
    const load = () =>
      fetchInfo()
        .then((i) => {
          setInfo(i);
          setInfoError(undefined);
        })
        .catch((e: Error) => {
          setInfoError(e.message);
          timer = window.setTimeout(load, 3000);
        });
    load();
    return () => window.clearTimeout(timer);
  }, []);

  const offline = connection === "offline" || (infoError && !info);

  return (
    <main className="page">
      <div className="topbar">
        <div className="connection" data-state={connection} role="status">
          <span className="dot" aria-hidden="true" />
          {CONNECTION_TEXT[connection]}
        </div>
        <div className="range" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r.id} aria-pressed={range === r.id} onClick={() => setRange(r.id)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {offline && (
        <p className="banner">
          Can't reach the monitor service. Start it with <code>uv run hwmon</code> in the <code>backend</code> folder;
          this page reconnects on its own.
        </p>
      )}

      {info && (
        <>
          <CpuHero info={info} latest={latest} live={buffer} range={range} />
          <div className="grid">
            <MemoryPanel info={info} latest={latest} live={buffer} range={range} />
            {info.gpus.map((g) => (
              <GpuPanel key={g.id} gpu={g} latest={latest} live={buffer} range={range} />
            ))}
            <StoragePanel info={info} latest={latest} live={buffer} range={range} />
            <NetworkPanel info={info} latest={latest} live={buffer} range={range} />
            <SensorsPanel info={info} latest={latest} />
          </div>
        </>
      )}
    </main>
  );
}
