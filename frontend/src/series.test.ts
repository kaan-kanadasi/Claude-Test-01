import { describe, expect, it } from "vitest";
import { historyToRows, metricKey, pushBounded, snapshotsToRows } from "./series";
import type { Snapshot } from "./api";

const snap = (ts: number, metrics: Record<string, number>): Snapshot => ({ ts, metrics, status: {} });

describe("snapshotsToRows", () => {
  it("picks the requested keys and converts seconds to ms", () => {
    const rows = snapshotsToRows([snap(10, { a: 1, b: 2 }), snap(11, { a: 3 })], ["a", "b"]);
    expect(rows).toEqual([
      { t: 10_000, a: 1, b: 2 },
      { t: 11_000, a: 3, b: null },
    ]);
  });
});

describe("historyToRows", () => {
  it("joins series on timestamp and leaves gaps as null", () => {
    const rows = historyToRows({ source: "raw", step: 5, series: { a: [[0, 1], [5, 2]], b: [[5, 9]] } }, ["a", "b"]);
    expect(rows).toEqual([
      { t: 0, a: 1, b: null },
      { t: 5000, a: 2, b: 9 },
    ]);
  });
});

describe("historyToRows gaps", () => {
  it("inserts a null row where samples are missing so lines break instead of bridging", () => {
    const rows = historyToRows({ source: "raw", step: 5, series: { a: [[0, 1], [5, 2], [60, 3]] } }, ["a"]);
    expect(rows).toEqual([
      { t: 0, a: 1 },
      { t: 5000, a: 2 },
      { t: 10_000, a: null },
      { t: 60_000, a: 3 },
    ]);
  });
});

describe("pushBounded", () => {
  it("drops the oldest entries past the limit", () => {
    expect(pushBounded([1, 2, 3], 4, 3)).toEqual([2, 3, 4]);
    expect(pushBounded([], 1, 3)).toEqual([1]);
  });
});

describe("metricKey", () => {
  it("matches the backend's key sanitizing", () => {
    expect(metricKey("net", "vEthernet (WSL.1)", "rx_bps")).toBe("net.vEthernet (WSL_1).rx_bps");
    expect(metricKey("disk", "C:\\", "used")).toBe("disk.C.used");
  });
});
