# Hardware Monitor Dashboard: Design & Plan (v1)

## Context
Empty repo (`Claude-Test-01`, only `.git`). The user wants a local web app that continuously collects this PC's hardware state (CPU, memory, GPU, storage, network, and later temperatures/fans) and shows it in a readable dashboard. v1 is **strictly read-only**: no clock, voltage, fan, or system changes.

Machine: Windows 11 laptop with an **NVIDIA RTX 4050 Laptop GPU (discrete)** and **Intel Arc Graphics (integrated)**.

Decisions made with the user:
- Monitors **this machine only** and binds to `127.0.0.1`
- Backend: **Python + FastAPI + psutil**
- Frontend: **React (Vite + TypeScript)**, with a live view plus **persistent history in SQLite**
- GPU: support **both** adapters (NVML for NVIDIA, Windows PDH counters for Intel)
- Temps/fans: pluggable slot now, shown as "not available". Real readings come later via LibreHardwareMonitor.

## Architecture
```
[collectors] --1s--> [sampler loop] --> WebSocket hub --> React dashboard (live)
                          |
                          +--5s--> SQLite store (raw) --rollup--> 1-min table
                                          ^
                    REST /api/history ----+  (React history charts)
```
A single process: FastAPI serves the API, the WebSocket, and the built React app.

## Layout
```
backend/
  pyproject.toml            fastapi, uvicorn[standard], psutil, nvidia-ml-py, pywin32; dev: pytest, httpx
  hwmon/
    main.py                 app factory, lifespan starts/stops sampler, serves frontend/dist
    config.py               intervals, retention, db path, nvidia poll interval (env-overridable)
    models.py               Snapshot / StaticInfo dataclasses (pydantic)
    collectors/
      base.py               Collector protocol: name, static_info(), sample() -> dict[str, float]
      cpu.py                total %, per-core %, freq, load; static: model, cores/threads
      memory.py             RAM used/total/%, swap
      storage.py            per-volume used/total; disk read/write bytes/s (delta of io_counters)
      network.py            per-interface rx/tx bytes/s (delta), up/down state, addresses
      gpu_nvidia.py         pynvml: util, VRAM used/total, temp, fan, power, clocks
      gpu_windows.py        win32pdh "GPU Engine"/"GPU Adapter Memory" counters grouped by adapter LUID -> Intel Arc util + shared/dedicated mem
      sensors.py            SensorProvider interface + NullSensors (reports unavailable)
    sampler.py              asyncio loop; runs collectors in a thread; isolates failures; broadcasts; persists every Nth tick
    store.py                SQLite: samples(ts, key, value), samples_1m(ts, key, avg, min, max); rollup + retention job
    api.py                  GET /api/info, GET /api/snapshot, GET /api/history, WS /ws/live
  tests/                    collectors (with fakes), store rollup/retention, api via TestClient
frontend/
  package.json              vite, react, typescript, recharts, vitest
  src/
    api.ts                  fetch helpers + useLiveSnapshot() WebSocket hook (auto-reconnect)
    components/             MetricCard, Gauge, TimeSeriesChart, UnavailableBadge
    panels/                 CpuPanel, MemoryPanel, GpuPanel (one per adapter), StoragePanel, NetworkPanel, SensorsPanel
    App.tsx                 overview grid + time range selector (Live 5m / 1h / 24h / 7d)
    format.ts               bytes, rates, percentages (unit-tested)
docs/superpowers/specs/2026-09-23-hardware-monitor-design.md   (this design, committed first)
README.md                   setup & run instructions
```

## Data model
- Flat dotted metric keys, e.g. `cpu.total`, `cpu.core.3`, `mem.used`, `gpu.nvidia0.util`, `gpu.intel0.util`, `disk.C.used`, `disk.io.read_bps`, `net.Wi-Fi.rx_bps`, `sensor.<name>`.
- `Snapshot = {ts, metrics: {key: value}, status: {collector: "ok" | "unavailable" | "error: ..."}}`
- `StaticInfo` holds the CPU model, core counts, RAM total, GPU names and VRAM, volumes, and interfaces. It's collected once and served by `/api/info`.
- `/api/history?keys=a,b&from=&to=` picks the raw table for ranges of 1h or less and the 1-minute rollup table for longer ones, and returns the series per key.

## Sampling & retention (defaults, all in config.py)
- Live tick every **1s** over WebSocket. The frontend keeps a 5-minute ring buffer.
- Persist raw samples every **5s**. Keep raw for **24h** and 1-minute rollups (avg/min/max) for **30 days**.
- The rollup and retention job runs every minute. Writes are batched in a single transaction.
- NVIDIA polling has its own interval (default 2s, can be disabled). On Optimus laptops, frequent NVML queries can stop the dGPU from sleeping and cost battery.

## Error handling
- Each collector is wrapped separately: an exception marks that collector `error` in `status` and backs off (1s → 30s), and the other collectors keep running.
- NVML missing, no NVIDIA driver, or PDH counters missing → the collector reports `unavailable` and the UI shows a badge instead of crashing.
- Rate metrics (disk and network bytes/s) come from deltas. The first tick and counter resets are skipped.
- The WebSocket client reconnects with backoff and the UI shows a "disconnected" banner.

## Read-only guarantee
- The server has only GET endpoints plus a WebSocket that pushes and accepts no commands.
- Collectors use only query APIs: psutil reads, NVML `nvmlDeviceGet*`, and PDH counter reads. No NVML `Set*` calls.
- It binds to `127.0.0.1` only. CORS is limited to the Vite dev origin.

## Implementation order
1. Commit the design spec to `docs/superpowers/specs/`. Scaffold `backend/` (pyproject, venv) and `frontend/` (Vite React TS).
2. Write the collector protocol, then CPU, memory, storage, and network, each with TDD using fake psutil data.
3. Write the GPU collectors (NVML, then PDH for Intel) and the NullSensors provider.
4. Write the sampler, the WebSocket hub, and `/api/info` + `/api/snapshot`.
5. Write the SQLite store: batched inserts, rollup, retention, and `/api/history`.
6. Frontend: the live hook and the panels on the overview grid, then history charts with the range selector.
7. FastAPI serves `frontend/dist`. Add a README with run instructions.

## Verification
- `cd backend && pytest`: collectors with fakes, store rollup/retention with a temp DB, API via TestClient (WebSocket receives snapshots).
- `cd frontend && npm test`: formatters and the snapshot-to-chart mapping.
- Manual end-to-end: `uvicorn hwmon.main:app` + `npm run dev` → open http://localhost:5173.
  - CPU % rises under load, e.g. `python -c "while 1: pass"`.
  - The RTX 4050 panel shows utilization while a GPU workload runs, and the Intel Arc panel shows desktop/video use.
  - Network rx climbs during a download, and disk I/O shows during a large file copy.
  - Restart the server and confirm the 1h view still shows earlier data (persistence).
  - The Sensors panel shows "not available" and nothing errors.
- Check read-only: grep the backend for `nvmlDeviceSet` or for any non-GET routes, and expect no hits.

## Later (not v1)
- A LibreHardwareMonitor sensor provider for CPU/GPU temps and fan RPM (needs admin).
- Alerts and thresholds, LAN access with auth, and multiple machines.
