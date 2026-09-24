import { useEffect, useState } from "react";
import type { GpuInfo, Info, ProcessRow, Snapshot } from "./api";
import { CollectorNotice, Legend, Meter, Stats, TimeChart, type Line } from "./components";
import { batteryState, displayName, formatBytes, formatClock, formatPercent, formatRate, formatTemp, formatWatts } from "./format";
import { metricKey, sortProcesses, type ProcessSort } from "./series";
import { useSeries, type Range } from "./useSeries";

interface PanelProps {
  info: Info;
  latest: Snapshot | undefined;
  live: Snapshot[];
  range: Range;
}

const pct = (v: number) => formatPercent(v);

// ---- CPU -------------------------------------------------------------------

export function CpuHero({ info, latest, live, range }: PanelProps) {
  const cpu = info.cpu;
  const m = latest?.metrics ?? {};
  const threads = cpu?.threads ?? 0;
  const rows = useSeries(["cpu.total"], range, live);
  const lines: Line[] = [{ key: "cpu.total", color: "var(--cpu)", label: "CPU load" }];

  return (
    <section className="hero" aria-label="Processor">
      <div>
        <h1>{cpu ? displayName(cpu.name) : "Processor"}</h1>
        {cpu && (
          <p className="spec">
            {cpu.cores} cores, {cpu.threads} threads
            {cpu.base_mhz ? `, ${formatClock(cpu.base_mhz)} base clock` : ""}
          </p>
        )}
      </div>
      <div className="readout">
        <div>
          <span className="big num">{formatPercent(m["cpu.total"])}</span>
          <span className="label">Load</span>
        </div>
        <div>
          <span className="mid num">{formatClock(m["cpu.freq_mhz"])}</span>
          <span className="label">Clock</span>
        </div>
      </div>

      <div className="skyline-wrap">
        <div className="skyline" role="img" aria-label={`Load on each of ${threads} threads`}>
          {Array.from({ length: threads }, (_, i) => {
            const v = m[`cpu.core.${i}`] ?? 0;
            return (
              <div className="col" key={i} title={`Thread ${i + 1}: ${formatPercent(v)}`}>
                <div className="bar" style={{ height: `${Math.max(v, 0.5)}%` }} />
              </div>
            );
          })}
        </div>
        <div className="skyline-axis">
          <span>Thread 1</span>
          <span>Thread {threads}</span>
        </div>
      </div>

      <div className="trend">
        <CollectorNotice status={latest?.status.cpu} />
        <TimeChart rows={rows} lines={lines} range={range} format={pct} max={100} height={110} />
      </div>
    </section>
  );
}

// ---- Memory ----------------------------------------------------------------

export function MemoryPanel({ info, latest, live, range }: PanelProps) {
  const m = latest?.metrics ?? {};
  const total = info.memory?.total ?? m["mem.total"];
  const rows = useSeries(["mem.used"], range, live);
  const lines: Line[] = [{ key: "mem.used", color: "var(--mem)", label: "In use" }];

  return (
    <section className="panel span-4" aria-labelledby="mem-h">
      <h2 id="mem-h">Memory</h2>
      <div className="headline">
        <span className="value num">{formatBytes(m["mem.used"])}</span>
        <span className="of">of {formatBytes(total)} in use</span>
      </div>
      <Meter fraction={m["mem.percent"] / 100} color="var(--mem)" label="Memory in use" />
      <Stats items={[
        ["Available", formatBytes(m["mem.available"])],
        ["Page file", `${formatBytes(m["swap.used"])} of ${formatBytes(m["swap.total"])}`],
      ]} />
      <CollectorNotice status={latest?.status.memory} />
      <TimeChart rows={rows} lines={lines} range={range} format={formatBytes} max={total} />
    </section>
  );
}

// ---- GPU -------------------------------------------------------------------

const ENGINE_LABELS: [string, string][] = [
  ["3D", "3D"],
  ["VideoDecode", "Video decode"],
  ["VideoEncode", "Video encode"],
  ["VideoProcessing", "Video processing"],
  ["Compute", "Compute"],
  ["Copy", "Copy"],
];

function gpuColor(gpu: GpuInfo) {
  return gpu.vendor === "NVIDIA" ? "var(--nvidia)" : "var(--arc)";
}

export function GpuPanel({ gpu, latest, live, range }: Omit<PanelProps, "info"> & { gpu: GpuInfo }) {
  const m = latest?.metrics ?? {};
  const k = (s: string) => `gpu.${gpu.id}.${s}`;
  const color = gpuColor(gpu);
  const rows = useSeries([k("util")], range, live);
  const lines: Line[] = [{ key: k("util"), color, label: "GPU load" }];
  const status = latest?.status[gpu.source === "nvml" ? "gpu_nvidia" : "gpu_windows"];

  const sharesMemory = gpu.vram_total < 2 ** 30;
  const sub = gpu.source === "nvml"
    ? `${formatBytes(gpu.vram_total)} video memory${gpu.driver ? `, driver ${gpu.driver}` : ""}`
    : sharesMemory ? "Integrated, shares system memory" : `${formatBytes(gpu.vram_total)} video memory`;

  const stats: [string, string][] = gpu.source === "nvml"
    ? [
        ["Video memory", `${formatBytes(m[k("vram_used")])} of ${formatBytes(m[k("vram_total")] ?? gpu.vram_total)}`],
        ["Temperature", formatTemp(m[k("temp_c")])],
        ["Power", formatWatts(m[k("power_w")])],
        ["Clock", formatClock(m[k("clock_gfx_mhz")])],
      ]
    : [
        [sharesMemory ? "Shared memory" : "Video memory",
          formatBytes(sharesMemory ? m[k("shared_used")] : m[k("dedicated_used")])],
      ];
  if (gpu.source === "nvml" && m[k("fan_pct")] != null) stats.push(["Fan", formatPercent(m[k("fan_pct")])]);

  const engines = ENGINE_LABELS.filter(([id]) => m[k(`engine.${id}`)] != null);

  return (
    <section className="panel span-4" aria-labelledby={`${gpu.id}-h`}>
      <h2 id={`${gpu.id}-h`}>{displayName(gpu.name)}</h2>
      <p className="sub">{sub}</p>
      <div className="headline">
        <span className="value num" style={{ color }}>{formatPercent(m[k("util")])}</span>
        <span className="of">load</span>
      </div>
      <Stats items={stats} />
      {engines.length > 0 && (
        <ul className="rows">
          {engines.map(([id, label]) => {
            const v = m[k(`engine.${id}`)];
            return (
              <li key={id}>
                <div className="line"><span>{label}</span><span className="v num">{formatPercent(v)}</span></div>
                <Meter fraction={v / 100} color={color} label={`${label} engine load`} />
              </li>
            );
          })}
        </ul>
      )}
      <CollectorNotice status={status} />
      <TimeChart rows={rows} lines={lines} range={range} format={pct} max={100} />
    </section>
  );
}

// ---- Storage ---------------------------------------------------------------

export function StoragePanel({ info, latest, live, range }: PanelProps) {
  const m = latest?.metrics ?? {};
  const lines: Line[] = [
    { key: "disk.io.read_bps", color: "var(--disk)", label: "Read" },
    { key: "disk.io.write_bps", color: "var(--disk-2)", label: "Write" },
  ];
  const rows = useSeries(lines.map((l) => l.key), range, live);

  return (
    <section className="panel span-5" aria-labelledby="disk-h">
      <h2 id="disk-h">Storage</h2>
      <ul className="rows">
        {(info.disks ?? []).map((d) => (
          <li key={d.id}>
            <div className="line">
              <span>{d.mountpoint} <span className="v">{d.fstype}</span></span>
              <span className="v num">{formatBytes(m[`disk.${d.id}.used`])} of {formatBytes(d.total)} used</span>
            </div>
            <Meter fraction={m[`disk.${d.id}.percent`] / 100} color="var(--disk)" label={`${d.mountpoint} space used`} />
          </li>
        ))}
      </ul>
      <Stats items={[["Read", formatRate(m["disk.io.read_bps"])], ["Write", formatRate(m["disk.io.write_bps"])]]} />
      <CollectorNotice status={latest?.status.storage} />
      <TimeChart rows={rows} lines={lines} range={range} format={formatRate} />
      <Legend lines={lines} />
    </section>
  );
}

// ---- Network ---------------------------------------------------------------

function defaultInterface(info: Info, m: Record<string, number>): string | undefined {
  const nics = info.network ?? [];
  const up = nics.filter((n) => m[metricKey("net", n.name, "up")] === 1);
  const routable = (n: (typeof nics)[number]) =>
    n.addresses.some((a) => a.includes(".") && !a.startsWith("169.254.")) && !n.name.startsWith("vEthernet");
  return (up.find(routable) ?? up[0] ?? nics[0])?.name;
}

function busiestInterface(info: Info, live: Snapshot[]): string | undefined {
  let best: string | undefined;
  let bestBytes = 0;
  for (const n of info.network ?? []) {
    const rx = metricKey("net", n.name, "rx_bps");
    const tx = metricKey("net", n.name, "tx_bps");
    const total = live.reduce((sum, s) => sum + (s.metrics[rx] ?? 0) + (s.metrics[tx] ?? 0), 0);
    if (total > bestBytes) {
      best = n.name;
      bestBytes = total;
    }
  }
  return best;
}

export function NetworkPanel({ info, latest, live, range }: PanelProps) {
  const m = latest?.metrics ?? {};
  const [chosen, setChosen] = useState<string>();
  // Once a few seconds of traffic are buffered, settle on the busiest connection.
  useEffect(() => {
    if (chosen || live.length < 5) return;
    const busiest = busiestInterface(info, live);
    if (busiest) setChosen(busiest);
  }, [chosen, info, live]);
  const selected = chosen ?? defaultInterface(info, m);
  const nics = (info.network ?? []).filter((n) => m[metricKey("net", n.name, "up")] === 1);

  const lines: Line[] = selected
    ? [
        { key: metricKey("net", selected, "rx_bps"), color: "var(--net)", label: "Download" },
        { key: metricKey("net", selected, "tx_bps"), color: "var(--net-2)", label: "Upload" },
      ]
    : [];
  const rows = useSeries(lines.map((l) => l.key), range, live);

  return (
    <section className="panel span-7" aria-labelledby="net-h">
      <h2 id="net-h">Network</h2>
      <p className="sub">Select a connection to chart it.</p>
      <div className="rows" role="group" aria-label="Connected network adapters">
        {nics.map((n) => (
          <button
            key={n.name} className="iface" aria-pressed={n.name === selected}
            onClick={() => setChosen(n.name)} title={n.addresses.join("\n")}
          >
            <span className="name">{n.name}</span>
            <span className="v num">↓ {formatRate(m[metricKey("net", n.name, "rx_bps")])}</span>
            <span className="v num">↑ {formatRate(m[metricKey("net", n.name, "tx_bps")])}</span>
          </button>
        ))}
        {nics.length === 0 && latest && <p className="notice">No network adapters are connected.</p>}
      </div>
      <CollectorNotice status={latest?.status.network} />
      {selected && (
        <>
          <TimeChart rows={rows} lines={lines} range={range} format={formatRate} />
          <Legend lines={lines} />
        </>
      )}
    </section>
  );
}

// ---- Processes -------------------------------------------------------------

const PROCESS_ROWS = 12;
const PROCESS_COLUMNS: { key: ProcessSort; label: string }[] = [
  { key: "cpu", label: "CPU" },
  { key: "memory", label: "Memory" },
  { key: "gpu", label: "GPU" },
];

function adapterColor(info: Info, adapter: string | null): string {
  const gpu = info.gpus.find((g) => g.name === adapter);
  return gpu ? gpuColor(gpu) : "var(--muted)";
}

export function ProcessesPanel({ info, latest, wide }: Pick<PanelProps, "info" | "latest"> & { wide: boolean }) {
  const [sortBy, setSortBy] = useState<ProcessSort>("cpu");
  const all: ProcessRow[] = latest?.details?.processes ?? [];
  const rows = sortProcesses(all, sortBy).slice(0, PROCESS_ROWS);
  const running = latest?.metrics["proc.count"];

  return (
    <section className={`panel ${wide ? "span-12" : "span-8"}`} aria-labelledby="procs-h">
      <h2 id="procs-h">Top apps</h2>
      <p className="sub">
        Processes grouped by app{running ? `, ${running} running` : ""}. Select a column to sort.
      </p>
      <CollectorNotice status={latest?.status.processes} />
      {rows.length === 0 ? (
        !latest || latest.status.processes === "ok" ? <p className="notice">Collecting the first readings…</p> : null
      ) : (
        <table className="procs">
          <colgroup><col /><col className="n" /><col className="n" /><col className="n" /></colgroup>
          <thead>
            <tr>
              <th scope="col">App</th>
              {PROCESS_COLUMNS.map((c) => (
                <th key={c.key} scope="col" aria-sort={sortBy === c.key ? "descending" : "none"}>
                  <button onClick={() => setSortBy(c.key)} aria-pressed={sortBy === c.key}>
                    {c.label}{sortBy === c.key ? " ↓" : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td className="app" title={r.name}>
                  {r.name}{r.count > 1 && <span className="count"> ({r.count})</span>}
                </td>
                <td className="num">{formatPercent(r.cpu)}</td>
                <td className="num">{formatBytes(r.memory)}</td>
                <td className="num" title={r.gpu_adapter ? displayName(r.gpu_adapter) : undefined}>
                  {r.gpu >= 0.05 && r.gpu_adapter && (
                    <i className="gpu-dot" style={{ background: adapterColor(info, r.gpu_adapter) }} aria-hidden="true" />
                  )}
                  {formatPercent(r.gpu)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ---- Battery ---------------------------------------------------------------

export function BatteryPanel({ latest, live, range }: Omit<PanelProps, "info">) {
  const m = latest?.metrics ?? {};
  const rows = useSeries(["battery.percent"], range, live);
  const lines: Line[] = [{ key: "battery.percent", color: "var(--battery)", label: "Charge" }];

  const stats: [string, string][] = [];
  if ((m["battery.discharge_w"] ?? 0) > 0) stats.push(["Power draw", formatWatts(m["battery.discharge_w"])]);
  else if ((m["battery.charge_w"] ?? 0) > 0) stats.push(["Charging at", formatWatts(m["battery.charge_w"])]);
  if (m["battery.voltage_v"] != null) stats.push(["Voltage", `${m["battery.voltage_v"].toFixed(1)} V`]);
  if (m["battery.full_wh"] != null) stats.push(["Full charge", `${m["battery.full_wh"].toFixed(1)} Wh`]);
  if (m["battery.cycles"] != null) stats.push(["Charge cycles", String(m["battery.cycles"])]);

  return (
    <section className="panel span-4" aria-labelledby="battery-h">
      <h2 id="battery-h">Battery</h2>
      <p className="sub">{latest ? batteryState(m) : "Reading battery…"}</p>
      <div className="headline">
        <span className="value num" style={{ color: "var(--battery)" }}>{formatPercent(m["battery.percent"])}</span>
        <span className="of">charged</span>
      </div>
      <Meter fraction={(m["battery.percent"] ?? 0) / 100} color="var(--battery)" label="Battery charge" />
      <Stats items={stats} />
      <CollectorNotice status={latest?.status.battery} />
      <TimeChart rows={rows} lines={lines} range={range} format={formatPercent} max={100} />
    </section>
  );
}

// ---- Sensors ---------------------------------------------------------------

export function SensorsPanel({ info, latest }: Pick<PanelProps, "info" | "latest">) {
  const status = latest?.status.sensors ?? (info.unavailable.sensors ? `unavailable: ${info.unavailable.sensors}` : undefined);
  const gpuTemps = info.gpus.filter((g) => latest?.metrics[`gpu.${g.id}.temp_c`] != null);
  return (
    <section className="panel span-12" aria-labelledby="sensors-h">
      <div className="sensors">
        <h2 id="sensors-h">Temperatures and fans</h2>
        {gpuTemps.map((g) => (
          <span key={g.id}>
            {displayName(g.name)} <span className="num">{formatTemp(latest?.metrics[`gpu.${g.id}.temp_c`])}</span>
          </span>
        ))}
      </div>
      {status?.startsWith("unavailable") ? (
        <p className="notice">
          CPU and board temperatures and fan speeds aren't shown yet. Windows doesn't expose them to regular apps;
          a later version will read them through LibreHardwareMonitor.
        </p>
      ) : (
        <CollectorNotice status={status} />
      )}
    </section>
  );
}
