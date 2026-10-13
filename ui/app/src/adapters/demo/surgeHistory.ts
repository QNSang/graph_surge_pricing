// Read-only history for the DEMO bidding series. Never derive it from a proposal or a receipt.
import type { HexSnapshot, Snapshot, Valued, ViewMode } from "../../domain/types";
import type { LegacyDataset } from "./legacy";
import type { Scenario } from "./scenarios";

export const SURGE_STEP_MS = 5 * 60_000;

export interface SurgePoint {
  index: number;
  timestamp: string;
  value: number | null;
  reason?: string;
  breakBefore: boolean;
}

/** Look-back windows in minutes; "day" means everything from the first snapshot. */
export type SurgeHistoryWindow = "60" | "180" | "360" | "day";

/** Snapshots per look-back window at the 5-minute cadence. */
export const WINDOW_STEPS: Record<Exclude<SurgeHistoryWindow, "day">, number> = { "60": 12, "180": 36, "360": 72 };

export interface SurgeHistoryOptions {
  window: SurgeHistoryWindow;
  viewMode: ViewMode;
  head: number;
}

export function validBase(value: unknown, reason?: string): Valued {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? { value }
    : { value: null, reason: reason ?? "MISSING_OR_INVALID_BIDDING" };
}

/** The scenario uses the same explicit bid overrides as the snapshot adapter, at every cutoff.
 * The current point always uses market.bidding, including an explicit null. No raw-data fallback.
 */
export function buildSurgeHistory(
  dataset: LegacyDataset,
  item: HexSnapshot,
  snap: Snapshot,
  scenario: Scenario,
  options: SurgeHistoryOptions,
) {
  const t = snap.t;
  const i = item.hex.index;
  const from = options.window === "day" ? 0 : Math.max(0, t - WINDOW_STEPS[options.window]);
  const head = Math.min(dataset.stamps.length - 1, Math.max(t, options.head));
  const postTo = options.viewMode === "REPLAY"
    ? Math.min(head, options.window === "day" ? head : t + 6)
    : t;
  const featured = dataset.hexes.findIndex((hex) => hex.zone === "cbd");
  const mappingOk = dataset.hexes[i]?.id === item.hex.id;
  const cutoffOk = dataset.stamps[t] === snap.envelope.cutoff_ts;

  const pointAt = (k: number): SurgePoint => {
    let base: Valued;
    if (!mappingOk || !cutoffOk) {
      base = { value: null, reason: "HISTORY_SNAPSHOT_MISMATCH" };
    } else if (k === t) {
      base = validBase(item.market.bidding.value, item.market.bidding.reason);
    } else {
      const override = scenario.override?.(i, featured < 0 ? 0 : featured, k);
      const value = override && "bid" in override ? override.bid : dataset.raw.surge[k]?.[i];
      base = validBase(value);
    }
    return {
      index: k,
      timestamp: dataset.stamps[k],
      ...base,
      breakBefore: k > 0 && Date.parse(dataset.stamps[k]) - Date.parse(dataset.stamps[k - 1]) !== SURGE_STEP_MS,
    };
  };

  const observed: SurgePoint[] = [];
  const future: SurgePoint[] = [];
  for (let k = from; k <= t; k += 1) observed.push(pointAt(k));
  for (let k = t + 1; k <= postTo; k += 1) future.push(pointAt(k));
  const current = observed.at(-1)!;
  const previous = t > 0 ? pointAt(t - 1) : null;
  const delta5m = current.value != null && previous?.value != null && !current.breakBefore
    ? current.value - previous.value
    : null;
  // Summary statistics are strictly as-of; replay-future points must not influence them.
  const values = observed.flatMap((p) => p.value == null ? [] : [p.value]);
  return {
    from,
    to: Math.max(t + 1, postTo),
    observed,
    future,
    current,
    delta5m,
    min: values.length ? Math.min(...values) : null,
    max: values.length ? Math.max(...values) : null,
    missing: observed.filter((p) => p.value == null).length,
    gaps: observed.filter((p, j) => j > 0 && p.breakBefore).length,
  };
}

/** Step-after drawing: a value is held only until the next known contiguous sample.
 * Null/non-finite points and missing time intervals always break the path.
 */
export function surgeStepPath(points: { x: number; y: number | null; breakBefore?: boolean }[]): string {
  let path = "";
  let pen = false;
  for (const p of points) {
    if (!Number.isFinite(p.x) || p.y == null || !Number.isFinite(p.y)) {
      pen = false;
      continue;
    }
    const x = p.x.toFixed(2);
    const y = p.y.toFixed(2);
    path += pen && !p.breakBefore ? `H${x}V${y}` : `M${x},${y}`;
    pen = true;
  }
  return path;
}
