const UNITS = ["B", "KB", "MB", "GB", "TB"];
const DASH = "—";

/** Three significant digits, without trailing zeros ("1.50" -> "1.5"). */
function sig3(v: number): string {
  return String(Number(v.toPrecision(3)));
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return DASH;
  let v = Math.abs(bytes);
  let i = 0;
  while (v >= 1024 && i < UNITS.length - 1) {
    v /= 1024;
    i++;
  }
  return i === 0 ? `${Math.round(v)} B` : `${sig3(v)} ${UNITS[i]}`;
}

export function formatRate(bytesPerSecond: number | null | undefined): string {
  const b = formatBytes(bytesPerSecond);
  return b === DASH ? b : `${b}/s`;
}

export function formatPercent(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return DASH;
  if (pct >= 10) return `${Math.round(pct)}%`;
  return `${Number(pct.toFixed(1))}%`;
}

export function formatClock(mhz: number | null | undefined): string {
  if (mhz == null || !Number.isFinite(mhz)) return DASH;
  return mhz >= 1000 ? `${(mhz / 1000).toFixed(2)} GHz` : `${Math.round(mhz)} MHz`;
}

export function formatTemp(c: number | null | undefined): string {
  return c == null ? DASH : `${Math.round(c)} °C`;
}

export function formatWatts(w: number | null | undefined): string {
  return w == null ? DASH : `${w < 10 ? w.toFixed(1) : Math.round(w)} W`;
}

/** Hardware names without (R)/(TM)/(C) marks, e.g. "Intel Core Ultra 9 185H". */
export function displayName(name: string): string {
  return name.replace(/\((R|TM|C)\)/gi, "").replace(/\s+/g, " ").trim();
}

export function formatDuration(seconds: number): string {
  const totalMin = Math.max(1, Math.round(seconds / 60));
  const h = Math.floor(totalMin / 60);
  const min = totalMin % 60;
  if (h === 0) return `${min} min`;
  return min === 0 ? `${h} h` : `${h} h ${min} min`;
}

/** Plain-language battery state from battery.* metrics. */
export function batteryState(m: Record<string, number | undefined>): string {
  if (m["battery.plugged"] === 1) {
    const charging = m["battery.charging"];
    if (charging === 1) return "Charging";
    if (charging === 0) return (m["battery.percent"] ?? 0) >= 99 ? "Plugged in, fully charged" : "Plugged in, not charging";
    return "Plugged in";
  }
  const left = m["battery.secs_left"];
  return left != null ? `On battery, ${formatDuration(left)} left` : "On battery";
}
