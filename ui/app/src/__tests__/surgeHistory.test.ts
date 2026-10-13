import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import raw from "../../../data.json";
import { loadLegacy, type LegacyDataset, type LegacyPayload } from "../adapters/demo/legacy";
import { buildSnapshot, featuredIndex } from "../adapters/demo/snapshot";
import { scenarioById } from "../adapters/demo/scenarios";
import { buildSurgeHistory, surgeStepPath, validBase, type SurgeHistoryOptions } from "../adapters/demo/surgeHistory";
import { HistoryChart } from "../components/panel/HistoryChart";

const dataset = loadLegacy(raw as unknown as LegacyPayload);
const T = dataset.raw.ts.indexOf("18:00");
const options: SurgeHistoryOptions = { window: "60", viewMode: "LATEST", head: T };

function fixture(t = T, scenarioId = "day", ds: LegacyDataset = dataset, index = featuredIndex(ds)) {
  const scenario = scenarioById(scenarioId);
  const snap = buildSnapshot(ds, t, scenario, { head: ds.stamps.length - 1, viewMode: "REPLAY", offline: false });
  const item = snap.items[index];
  const history = (opts: Partial<SurgeHistoryOptions> = {}) => buildSurgeHistory(ds, item, snap, scenario, { ...options, head: t, ...opts });
  return { snap, item, history };
}

describe("Surge Base history", () => {
  it("uses unchanged source bidding and 13 endpoints spanning 60 minutes", () => {
    const { item, history } = fixture();
    const h = history();
    expect(h.observed).toHaveLength(13);
    expect(h.observed.map((p) => p.value)).toEqual(dataset.raw.surge.slice(T - 12, T + 1).map((row) => row[item.hex.index]));
    expect(h.current.value).toBe(item.market.bidding.value);
    expect(h.delta5m).toBeCloseTo(dataset.raw.surge[T][item.hex.index] - dataset.raw.surge[T - 1][item.hex.index]);
  });

  it("updates the current point for both cutoff and hex changes", () => {
    for (const t of [T - 3, T]) {
      for (const i of [0, 1]) {
        const { history } = fixture(t, "day", dataset, i);
        expect(history().current.value).toBe(dataset.raw.surge[t][i]);
        expect(history().current.timestamp).toBe(dataset.stamps[t]);
      }
    }
  });

  it("keeps an explicitly missing snapshot base null, never falling back to the raw row", () => {
    const { item, history } = fixture();
    item.market.bidding = { value: null, reason: "INVALID_BIDDING", version: "fixture-null" };
    expect(history().current.value).toBeNull();
    expect(history().current.reason).toBe("INVALID_BIDDING");
    expect(history().delta5m).toBeNull();
  });

  it("does not use a proposed or overridden final price as base history", () => {
    const { item, history } = fixture();
    const before = history().observed;
    item.proposal.s_final = 2.75;
    item.proposal.delta_applied = 0.4;
    expect(history().observed).toEqual(before);
  });

  it("uses consistent scenario bid overrides at every timestamp", () => {
    const { history } = fixture(T, "report-11-1");
    expect(history().observed.every((p) => p.value === 1.3)).toBe(true);
    expect(history().delta5m).toBe(0);
    expect(history().min).toBe(1.3);
    expect(history().max).toBe(1.3);
  });

  it("keeps missing bidding in the REVIEW fixture missing across history", () => {
    const index = (featuredIndex(dataset) + 13) % 61;
    const { history } = fixture(T, "review", dataset, index);
    expect(history().missing).toBe(13);
    expect(history().min).toBeNull();
    expect(history().max).toBeNull();
  });

  it("shows future source values only in REPLAY and never beyond head", () => {
    const { history } = fixture();
    expect(history({ head: T + 3 }).future).toEqual([]);
    const replay = history({ head: T + 3, viewMode: "REPLAY" });
    expect(replay.future.map((p) => p.index)).toEqual([T + 1, T + 2, T + 3]);
    expect(replay.min).toBe(history().min);
    expect(replay.max).toBe(history().max);
    expect(replay.delta5m).toBe(history().delta5m);
  });

  it("caps replay to available dataset length and preserves midnight's full date", () => {
    const last = dataset.stamps.length - 1;
    const { history } = fixture(last);
    const h = history({ head: last + 100, viewMode: "REPLAY" });
    expect(h.future).toEqual([]);
    expect(h.current.timestamp).toBe("2026-01-28T00:00:00+07:00");
  });

  it("renders the first timestamp without inventing a previous value", () => {
    const { history } = fixture(0);
    expect(history().observed).toHaveLength(1);
    expect(history().delta5m).toBeNull();
  });

  it("uses the available day for the day window without a future leak in LATEST", () => {
    const { history } = fixture();
    const h = history({ window: "day", head: T + 2 });
    expect(h.observed).toHaveLength(T + 1);
    expect(h.future).toEqual([]);
  });

  it("rejects bad numeric values without rounding or clamping valid base multipliers", () => {
    for (const value of [null, undefined, NaN, Infinity, -Infinity, 0, -1, "1.30"]) {
      expect(validBase(value).value).toBeNull();
    }
    expect(validBase(1.234567).value).toBe(1.234567);
    expect(validBase(4.5).value).toBe(4.5); // no hard-coded demo price cap in the chart
  });

  it("does not substitute history from a different hex mapping", () => {
    const { item, history } = fixture();
    item.hex = { ...item.hex, id: "unknown-hex" };
    expect(history().current.reason).toBe("HISTORY_SNAPSHOT_MISMATCH");
    expect(history().observed.every((p) => p.value == null)).toBe(true);
  });

  it("breaks a missing time interval and does not call its difference a 5-minute change", () => {
    const ds = { ...dataset, stamps: [...dataset.stamps] };
    ds.stamps[T - 1] = ds.stamps[T - 2];
    const { history } = fixture(T, "day", ds);
    expect(history().current.breakBefore).toBe(true);
    expect(history().delta5m).toBeNull();
    expect(history().gaps).toBeGreaterThan(0);
  });
});

describe("step-after geometry", () => {
  it("draws horizontal then vertical, without smoothing", () => {
    expect(surgeStepPath([{ x: 0, y: 10 }, { x: 5, y: 20 }])).toBe("M0.00,10.00H5.00V20.00");
  });
  it("never connects through null, NaN or time gaps", () => {
    const path = surgeStepPath([
      { x: 0, y: 10 }, { x: 1, y: null }, { x: 2, y: 20 },
      { x: 3, y: NaN }, { x: 4, y: 30 }, { x: 5, y: 40, breakBefore: true },
    ]);
    expect(path).toBe("M0.00,10.00M2.00,20.00M4.00,30.00M5.00,40.00");
    expect(path).not.toMatch(/NaN|Infinity/);
  });
});

describe("Surge Base default panel render", () => {
  it("renders one metric toolbar, a keyboard time control and a finite SVG", () => {
    const { item, snap } = fixture();
    const html = renderToStaticMarkup(createElement(HistoryChart, { item, snap }));
    expect(html).toContain('data-testid="surge-base-chart"');
    expect(html).toContain('role="slider"');
    expect(html).toContain('aria-valuetext=');
    expect(html.match(/aria-label="Chỉ số biểu đồ"/g)).toHaveLength(1);
    expect(html).toContain('Surge Base');
    expect(html).not.toContain('data-testid="surge-base-replay"');
    expect(html).not.toMatch(/NaN|Infinity/);
    item.market.bidding = { value: null, reason: "INVALID_BIDDING", version: "fixture-null" };
    const missing = renderToStaticMarkup(createElement(HistoryChart, { item, snap }));
    expect(missing).toContain("Thiếu giá nền hoặc giá trị không hợp lệ.");
    expect(missing).toContain("INVALID_BIDDING");
    expect(missing).not.toMatch(/NaN|Infinity/);
  });
});
