# Hardware Monitor

A local, read-only dashboard for this computer's hardware: CPU (per thread), memory,
GPUs (NVIDIA via NVML, Intel/AMD via Windows GPU counters), storage, and network, with
live updates every second and stored history up to 30 days.

It only *reads* hardware state. It never changes clocks, voltages, fan speeds or any
other setting, and the API has no write endpoints.

## Requirements

- Windows 10/11 (the GPU counters and CPU clock readings are Windows-specific; CPU,
  memory, storage and network work on any OS psutil supports)
- [uv](https://docs.astral.sh/uv/) (Python 3.11+)
- Node.js 20+ (only to build the dashboard)
- NVIDIA driver, if you want NVIDIA GPU details

## Run it

```sh
# 1. Build the dashboard (once, and after frontend changes)
cd frontend
npm install
npm run build

# 2. Start the monitor
cd ../backend
uv run hwmon
```

Open <http://127.0.0.1:8765>. The server only listens on this machine.

### Developing the dashboard

Run `uv run hwmon` in `backend/` and `npm run dev` in `frontend/`, then open
<http://localhost:5173>. Vite proxies `/api` and `/ws` to the backend.

## Configuration

Set environment variables before `uv run hwmon`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HWMON_PORT` | `8765` | Port to listen on |
| `HWMON_SAMPLE_INTERVAL` | `1.0` | Seconds between live readings |
| `HWMON_PERSIST_INTERVAL` | `5.0` | Seconds between readings saved to history |
| `HWMON_NVIDIA_INTERVAL` | `2.0` | Seconds between NVIDIA polls; `0` turns NVIDIA monitoring off (lets the GPU sleep longer on laptops) |
| `HWMON_RAW_RETENTION_S` | `86400` | How long full-detail history is kept |
| `HWMON_ROLLUP_RETENTION_S` | `2592000` | How long per-minute history is kept |
| `HWMON_DB_PATH` | `backend/data/metrics.db` | History database file |

## API

| Endpoint | Returns |
| --- | --- |
| `GET /api/info` | Hardware inventory and which collectors are unavailable, and why |
| `GET /api/snapshot` | The latest reading of every metric |
| `GET /api/history?keys=cpu.total,mem.used&start=&end=` | Stored series (epoch seconds; defaults to the last hour) |
| `WS /ws/live` | A snapshot pushed every sample interval |

Metric keys are dotted, e.g. `cpu.total`, `cpu.core.3`, `gpu.nvidia0.util`,
`gpu.intel0.engine.VideoDecode`, `disk.C.used`, `net.Wi-Fi.rx_bps`.

## Tests

```sh
cd backend && uv run pytest
cd frontend && npm test
```

## Not yet supported

CPU and board temperatures and fan speeds. Windows doesn't expose them to regular
apps; a later version will read them through LibreHardwareMonitor. The NVIDIA GPU
temperature is shown already because NVML provides it.
