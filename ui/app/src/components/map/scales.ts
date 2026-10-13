// Thang màu cố định cho cả ngày (spec MAP-02): không đổi theo frame để màu giữ nghĩa khi replay.
// Đây là thang trình bày của profile smoothed_ratio_demo, không phải ngưỡng production.

import { DATASET } from "../../state/store";

type RGB = [number, number, number];
const hex = (h: string): RGB => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const mix = (a: RGB, b: RGB, t: number) => {
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
};

const LOW = hex("#1f6f9c");
const LOW_SOFT = hex("#cedae5");
const MID = hex("#d5dbe3");
const HIGH_SOFT = hex("#d3bdb8");
const HIGH = hex("#d53e20");

function diverging(x: number) {
  // x trong [-1, 1]
  const v = Math.max(-1, Math.min(1, x));
  if (v < 0) return v > -0.5 ? mix(MID, LOW_SOFT, -v * 2) : mix(LOW_SOFT, LOW, (-v - 0.5) * 2);
  return v < 0.5 ? mix(MID, HIGH_SOFT, v * 2) : mix(HIGH_SOFT, HIGH, (v - 0.5) * 2);
}

export const DS_SCALE = { min: 0.3, ref: 1.2, max: 2.4, version: "demo-scale.smoothed.v1" };

/** D/S quanh mốc tham chiếu, theo log để đối xứng dư cung và thiếu cung. */
export function dsColor(q: number) {
  const lo = Math.log(DS_SCALE.min / DS_SCALE.ref);
  const hi = Math.log(DS_SCALE.max / DS_SCALE.ref);
  const l = Math.log(q / DS_SCALE.ref);
  return diverging(l < 0 ? -l / lo : l / hi);
}

export const DELTA_SCALE = { max: 0.4 };
export const deltaColor = (d: number) => (Math.abs(d) < 1e-9 ? "rgb(213,219,227)" : diverging(d / DELTA_SCALE.max));

const SEQ_LO = hex("#e9ecf1");
const SEQ_HI = hex("#5fc9ba");
const maxOf = (m: number[][]) => m.reduce((a, row) => Math.max(a, ...row), 0);
export const DEMAND_MAX = Math.max(1, maxOf(DATASET.raw.D));
export const SUPPLY_MAX = Math.max(1, maxOf(DATASET.raw.S));
export const seqColor = (v: number, max: number) => mix(SEQ_LO, SEQ_HI, Math.sqrt(Math.max(0, v) / max));

export const legendGradient = {
  ds: `linear-gradient(90deg, ${dsColor(DS_SCALE.min)}, ${dsColor(0.7)}, ${dsColor(DS_SCALE.ref)}, ${dsColor(1.7)}, ${dsColor(DS_SCALE.max)})`,
  delta: `linear-gradient(90deg, ${deltaColor(-0.4)}, ${deltaColor(-0.15)}, ${deltaColor(0)}, ${deltaColor(0.15)}, ${deltaColor(0.4)})`,
  seq: `linear-gradient(90deg, ${seqColor(0, 1)}, ${seqColor(0.25, 1)}, ${seqColor(1, 1)})`,
};
