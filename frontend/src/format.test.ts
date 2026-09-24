import { describe, expect, it } from "vitest";
import { batteryState, displayName, formatBytes, formatClock, formatDuration, formatPercent, formatRate } from "./format";

describe("formatBytes", () => {
  it("uses binary units with sensible precision", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(24_444_223_488)).toBe("22.8 GB");
    expect(formatBytes(1_021_821_579_264)).toBe("952 GB");
  });
  it("handles missing values", () => {
    expect(formatBytes(undefined)).toBe("—");
  });
});

describe("formatRate", () => {
  it("formats bytes per second", () => {
    expect(formatRate(1_543_414.8)).toBe("1.47 MB/s");
    expect(formatRate(0)).toBe("0 B/s");
  });
});

describe("formatPercent", () => {
  it("rounds to whole percent above 10, one decimal below", () => {
    expect(formatPercent(72.24)).toBe("72%");
    expect(formatPercent(7.46)).toBe("7.5%");
    expect(formatPercent(undefined)).toBe("—");
  });
});

describe("formatClock", () => {
  it("shows GHz above 1000 MHz", () => {
    expect(formatClock(3483.8)).toBe("3.48 GHz");
    expect(formatClock(800)).toBe("800 MHz");
  });
});

describe("displayName", () => {
  it("drops trademark marks and extra spaces", () => {
    expect(displayName("Intel(R) Core(TM) Ultra 9 185H")).toBe("Intel Core Ultra 9 185H");
    expect(displayName("Intel(R) Arc(TM) Graphics")).toBe("Intel Arc Graphics");
  });
});

describe("formatDuration", () => {
  it("shows hours and minutes", () => {
    expect(formatDuration(12_000)).toBe("3 h 20 min");
    expect(formatDuration(2700)).toBe("45 min");
    expect(formatDuration(7200)).toBe("2 h");
    expect(formatDuration(20)).toBe("1 min");
  });
});

describe("batteryState", () => {
  it("describes charging and AC states", () => {
    expect(batteryState({ "battery.plugged": 1, "battery.charging": 1, "battery.percent": 60 })).toBe("Charging");
    expect(batteryState({ "battery.plugged": 1, "battery.charging": 0, "battery.percent": 100 })).toBe("Plugged in, fully charged");
    expect(batteryState({ "battery.plugged": 1, "battery.charging": 0, "battery.percent": 80 })).toBe("Plugged in, not charging");
    expect(batteryState({ "battery.plugged": 1, "battery.percent": 80 })).toBe("Plugged in");
  });
  it("shows time left on battery when known", () => {
    expect(batteryState({ "battery.plugged": 0, "battery.percent": 70, "battery.secs_left": 12_000 })).toBe("On battery, 3 h 20 min left");
    expect(batteryState({ "battery.plugged": 0, "battery.percent": 70 })).toBe("On battery");
  });
});
