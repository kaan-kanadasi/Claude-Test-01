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
