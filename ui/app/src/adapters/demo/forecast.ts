// Forecast heuristic DEMO, port từ prototype v0.1. KHÔNG phải model đã train.
// Metric: smoothed ratio (D+1)/(S_eff+1), khớp prototype và profile smoothed_ratio_demo.

import type { LegacyDataset } from "./legacy";

export const DEMO_MODEL_ID = "demo/heuristic-persistence-neighbor.v0";

export function observedRatio(ds: LegacyDataset, t: number, i: number): number | null {
  const d = ds.raw.D[t]?.[i];
  const s = ds.raw.S[t]?.[i];
  if (d == null || s == null || !Number.isFinite(d) || !Number.isFinite(s)) return null;
  return (d + 1) / (s + 1);
}

const logRatio = (ds: LegacyDataset, t: number, i: number) => Math.log(observedRatio(ds, t, i) ?? 1);

function smooth(ds: LegacyDataset, t: number, i: number) {
  const a = Math.max(0, t - 2);
  let s = 0;
  let w = 0;
  for (let k = a; k <= t; k++) {
    const wk = k - a + 1;
    s += wk * logRatio(ds, k, i);
    w += wk;
  }
  return s / w;
}

/** Trả DS_local, DS_graph cho t+5 theo không gian smoothed ratio. */
export function demoForecast(ds: LegacyDataset, t: number, i: number) {
  const now = smooth(ds, t, i);
  const prev = smooth(ds, Math.max(0, t - 3), i);
  const yL = now + 0.2 * (now - prev);
  const nb = ds.neighbors[i];
  const nbMean = nb.length ? nb.reduce((acc, j) => acc + smooth(ds, t, j), 0) / nb.length : now;
  const yG = yL + 0.35 * (nbMean - now);
  return { local: Math.exp(yL), graph: Math.exp(yG) };
}
