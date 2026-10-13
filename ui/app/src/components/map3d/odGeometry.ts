import type { NetworkEdge } from '../console/network';

export type LngLat = [number, number];
export type Vec3 = [number, number, number];
export type EdgeRole = 'incoming' | 'outgoing' | 'other';

const M_PER_DEG = 111320;

/** Approximate ground length in metres (equirectangular, fine at city scale). */
export function groundLengthM([x1, y1]: LngLat, [x2, y2]: LngLat): number {
  const k = Math.cos((y1 + y2) / 2 * Math.PI / 180);
  return Math.hypot((x2 - x1) * k, y2 - y1) * M_PER_DEG;
}

/** Tall 3D arc from the top of the source column that drops onto the top of the destination column.
 * Cubic bezier: both inner control points sit at the peak height, the last one almost above the
 * destination, so the arc rises, travels high and lands nearly vertically on the target hex. */
export function arcPath(source: LngLat, target: LngLat, hSource: number, hTarget: number, n = 32): Vec3[] {
  const [x1, y1] = source, [x2, y2] = target;
  const dx = x2 - x1, dy = y2 - y1;
  const peak = Math.max(hSource, hTarget) + Math.max(0.45 * groundLengthM(source, target), 140);
  const p1: Vec3 = [x1 + dx * 0.3 - dy * 0.18, y1 + dy * 0.3 + dx * 0.18, peak];
  const p2: Vec3 = [x1 + dx * 0.94 - dy * 0.04, y1 + dy * 0.94 + dx * 0.04, peak];
  const p0: Vec3 = [x1, y1, hSource], p3: Vec3 = [x2, y2, hTarget];
  const out: Vec3[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t;
    const w = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
    out.push([0, 1, 2].map(k => w[0] * p0[k] + w[1] * p1[k] + w[2] * p2[k] + w[3] * p3[k]) as Vec3);
  }
  return out;
}

/** Point at fraction f (0..1) of the path, by vertex index (paths are evenly sampled in t). */
export function pointAt(path: Vec3[], f: number): Vec3 {
  const x = Math.max(0, Math.min(1, f)) * (path.length - 1);
  const i = Math.min(path.length - 2, Math.floor(x)), r = x - i;
  const a = path[i], b = path[i + 1];
  return [a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r, a[2] + (b[2] - a[2]) * r];
}

/** Small 3D chevron at fraction `at` of the path, pointing along the path tangent
 * (downward at the destination end, since the arc lands on the hex from above). */
export function arrowHead(path: Vec3[], sizeM: number, at = 1): Vec3[] {
  const tip = pointAt(path, at), back = pointAt(path, at - 0.03);
  const k = Math.cos(tip[1] * Math.PI / 180);
  const d = [(tip[0] - back[0]) * k * M_PER_DEG, (tip[1] - back[1]) * M_PER_DEG, tip[2] - back[2]];
  const len = Math.hypot(d[0], d[1], d[2]) || 1;
  const [ux, uy, uz] = d.map(v => v / len);
  // Wings spread horizontally, perpendicular to the travel direction.
  let sx = uy, sy = -ux;
  const sl = Math.hypot(sx, sy);
  if (sl < 1e-6) { sx = 1; sy = 0; } else { sx /= sl; sy /= sl; }
  const angle = 0.5, c = Math.cos(angle) * sizeM, r = Math.sin(angle) * sizeM;
  const wing = (side: number): Vec3 => [
    tip[0] + (-ux * c + side * sx * r) / (k * M_PER_DEG),
    tip[1] + (-uy * c + side * sy * r) / M_PER_DEG,
    tip[2] - uz * c,
  ];
  return [wing(1), tip, wing(-1)];
}

export function edgeRole(edge: Pick<NetworkEdge, 'source' | 'target'>, selected: number): EdgeRole {
  if (selected < 0) return 'other';
  if (edge.target === selected) return 'incoming';
  if (edge.source === selected) return 'outgoing';
  return 'other';
}

/** Line width in pixels, sqrt-scaled by volume relative to the window's largest OD record. */
export const EDGE_WIDTH = { minPx: 1, maxPx: 3.2 } as const;
export function edgeWidthPx(volume: number, maxVolume: number): number {
  const r = maxVolume > 0 && Number.isFinite(volume) ? Math.sqrt(Math.max(0, Math.min(1, volume / maxVolume))) : 0;
  return EDGE_WIDTH.minPx + (EDGE_WIDTH.maxPx - EDGE_WIDTH.minPx) * r;
}
