import type { Proposal } from '../../domain/types';

/** Versioned display scale for column height. Height encodes |delta_applied| (the proposed correction
 * after policy limits) and nothing else: not confidence, not market quality, not realised impact. */
export const DISPLAY_SCALE = { version: 'demo-v1', deltaMax: 0.40, maxVisualHeightM: 180 } as const;
export type DisplayScale = { version: string; deltaMax: number; maxVisualHeightM: number };

type HeightInput = Pick<Proposal, 'status' | 'delta_applied'>;

/** |Δ| for INCREASE/DECREASE with a finite delta; null otherwise (HOLD, REVIEW, missing or invalid). */
export function deltaMagnitude(p: HeightInput): number | null {
  if (p.status !== 'INCREASE' && p.status !== 'DECREASE') return null;
  const d = p.delta_applied;
  return d == null || !Number.isFinite(d) ? null : Math.abs(d);
}

/** True when an actionable status arrived without a usable delta: shown flat with a warning marker. */
export function hasInvalidDelta(p: HeightInput): boolean {
  return (p.status === 'INCREASE' || p.status === 'DECREASE') && deltaMagnitude(p) == null;
}

export function heightFraction(p: HeightInput, scale: DisplayScale = DISPLAY_SCALE): number {
  const m = deltaMagnitude(p);
  return m == null || !(scale.deltaMax > 0) ? 0 : Math.min(1, m / scale.deltaMax);
}

/** Column height in display metres (render units, not terrain). */
export function columnHeight(p: HeightInput, scale: DisplayScale = DISPLAY_SCALE): number {
  return heightFraction(p, scale) * scale.maxVisualHeightM;
}

/** Extrusion fades out at low zoom so the overview stays readable as a flat map. */
export function zoomExtrusionFactor(zoom: number, flatBelow = 8.5, fullAbove = 9.75): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.max(0, Math.min(1, (zoom - flatBelow) / (fullAbove - flatBelow)));
}

/** Screen pixels per metre at a zoom and latitude (512px Web Mercator world used by MapLibre). */
export function pixelsPerMetre(zoom: number, lat: number): number {
  return 512 * 2 ** zoom / (40075016.686 * Math.cos(lat * Math.PI / 180));
}

/** Visual exaggeration so the tallest column reads at a fixed-ish screen height across zooms. */
export function elevationScaleFor(zoom: number, lat: number, scale: DisplayScale = DISPLAY_SCALE): number {
  const targetPx = Math.max(48, Math.min(150, 80 * 2 ** ((zoom - 11.5) * 0.5)));
  return zoomExtrusionFactor(zoom) * targetPx / (scale.maxVisualHeightM * pixelsPerMetre(zoom, lat));
}
