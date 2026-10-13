import type { Hex, HexSnapshot, Recommendation } from '../../domain/types';
import type { LegacyDataset } from '../../adapters/demo/legacy';
import { completedOdHour } from '../../adapters/demo/legacy';
import { ACTION_PALETTE, OD_PALETTE } from '../map3d/palette';

/** Presentation only. No policy, recommendation or source data is modified here. */
export const ACTION_COLORS: Record<Recommendation, string> = ACTION_PALETTE;
/** Selected-hex OD flow colours, independent of the action palette. */
export const OD_COLORS = OD_PALETTE;
export const ACTIONS: Recommendation[] = ['INCREASE', 'DECREASE', 'HOLD', 'REVIEW'];
export type NetworkMode = 'recommendation' | 'delta' | 'ds' | 'base' | 'demand' | 'supply';
export type Point = [number, number];
export interface NetworkEdge { id: string; source: number; target: number; volume: number }
export interface NetworkData { hour: number | null; edges: NetworkEdge[]; invalid: number; windowLabel: string }

export function networkAt(dataset: LegacyDataset, cutoff: string): NetworkData {
  const hour = completedOdHour(cutoff);
  const rows = hour == null ? [] : dataset.raw.od[hour] ?? [];
  let invalid = 0;
  const edges: NetworkEdge[] = [];
  for (const [index, row] of rows.entries()) {
    const [source, target, volume] = row;
    if (!Number.isInteger(source) || !Number.isInteger(target) || !dataset.hexes[source] || !dataset.hexes[target] || !Number.isFinite(volume) || volume < 0) {
      invalid++;
      continue;
    }
    // Self-loops and zero-flow records do not represent visible inter-hex connections.
    if (source === target || volume === 0) continue;
    edges.push({ id: `od-${hour}-${source}-${target}-${index}`, source, target, volume });
  }
  edges.sort((a, b) => b.volume - a.volume || a.source - b.source || a.target - b.target || a.id.localeCompare(b.id));
  return {
    hour, edges, invalid,
    windowLabel: hour == null ? 'No completed OD window' : `${String(hour).padStart(2, '0')}:00–${String(hour + 1).padStart(2, '0')}:00 · hourly average`,
  };
}

/** Hybrid visibility: a small overview, plus the selected hex's strongest edges. */
export function visibleEdges(edges: NetworkEdge[], selected: number, selectedNetwork: boolean, expanded: boolean): NetworkEdge[] {
  const global = edges.slice(0, expanded ? 24 : 8);
  const related = selectedNetwork && selected >= 0
    ? edges.filter(e => e.source === selected || e.target === selected).slice(0, expanded ? 56 : 12)
    : [];
  return [...new Map([...global, ...related].map(e => [e.id, e])).values()];
}

export function mercator(lat: number, lng: number): Point {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const sin = Math.sin(clamped * Math.PI / 180);
  return [(lng + 180) / 360, 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)];
}

export function geographicBounds(hexes: Hex[]): { center: Point; span: Point } {
  const p = hexes.flatMap(h => h.poly.map(([lat, lng]) => mercator(lat, lng))).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (!p.length) return { center: [0.5, 0.5], span: [0.1, 0.1] };
  const xs = p.map(v => v[0]), ys = p.map(v => v[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  return { center: [(minX + maxX) / 2, (minY + maxY) / 2], span: [Math.max(0.00001, maxX - minX), Math.max(0.00001, maxY - minY)] };
}

export function curvedEdge(source: Point, target: Point): { path: string; arrow: string } {
  const [x1, y1] = source, [x2, y2] = target;
  const dx = x2 - x1, dy = y2 - y1;
  const cx = (x1 + x2) / 2 - dy * 0.27, cy = (y1 + y2) / 2 + dx * 0.27;
  const t = 0.83, u = 1 - t;
  const x = u * u * x1 + 2 * u * t * cx + t * t * x2;
  const y = u * u * y1 + 2 * u * t * cy + t * t * y2;
  const angle = Math.atan2(u * (cy - y1) + t * (y2 - cy), u * (cx - x1) + t * (x2 - cx));
  return { path: `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`, arrow: `translate(${x},${y}) rotate(${angle * 180 / Math.PI})` };
}

/** Approximate straight-line centroid distance, explicitly not route/travel distance. */
export function centroidDistanceKm(a: Hex, b: Hex): number {
  const rad = Math.PI / 180;
  const h = Math.sin((b.lat - a.lat) * rad / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin((b.lng - a.lng) * rad / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, h))));
}

export const displaySurge = (value: number | null | undefined): string => value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)}×`;
export const displayNumber = (value: number | null | undefined, digits = 0): string => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits });
export const displayDelta = (value: number | null | undefined): string => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(2)}`;

export function summaryFor(item: HexSnapshot): string {
  const p = item.proposal;
  if (p.status === 'REVIEW') return item.eligibility.capabilities.override
    ? 'This recommendation needs review. Accept is unavailable; you can set a price manually after checking the reasons below.'
    : 'This recommendation needs review. Accept and manual changes are unavailable; inspect the validation reasons below.';
  if (p.status === 'HOLD') return `The provider recommends keeping the base surge at ${displaySurge(p.s_bid)}. No surge adjustment is proposed.`;
  return `The demo provider recommends ${p.status === 'INCREASE' ? 'increasing' : 'decreasing'} the base surge from ${displaySurge(p.s_bid)} to ${displaySurge(p.s_final)} (${displayDelta(p.delta_applied)} multiplier points). Review the observed market and network context before accepting.`;
}
