import { describe, expect, it } from "vitest";
import { historyToRows, metricKey, pushBounded, snapshotsToRows, sortProcesses } from "./series";
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

describe("sortProcesses", () => {
  const rows = [
    { name: "b", count: 1, cpu: 5, memory: 100, gpu: 0, gpu_adapter: null },
    { name: "a", count: 2, cpu: 5, memory: 300, gpu: 9, gpu_adapter: "X" },
    { name: "c", count: 1, cpu: 1, memory: 200, gpu: 0, gpu_adapter: null },
  ];
  it("sorts descending by the chosen measure, ties by name, without mutating", () => {
    expect(sortProcesses(rows, "cpu").map((r) => r.name)).toEqual(["a", "b", "c"]);
    expect(sortProcesses(rows, "memory").map((r) => r.name)).toEqual(["a", "c", "b"]);
    expect(sortProcesses(rows, "gpu").map((r) => r.name)).toEqual(["a", "b", "c"]);
    expect(rows.map((r) => r.name)).toEqual(["b", "a", "c"]);
  });
});
