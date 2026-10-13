import type { Recommendation } from '../../domain/types';

/** Presentation palette shared by the 2D and 3D maps. Hex colour encodes the recommendation only;
 * OD colours encode connection direction only and are never reused for surge changes. */
export const ACTION_PALETTE: Record<Recommendation, string> = {
  INCREASE: '#F0643B', DECREASE: '#12A3C9', HOLD: '#AEB7C4', REVIEW: '#8B6CF0',
};
export const OD_PALETTE = { incoming: '#0D9488', outgoing: '#DB2777', other: '#94A3B8' } as const;
export const SELECTED_OUTLINE = '#2563EB';

export type RGBA = [number, number, number, number];

export function rgba(hex: string, alpha = 255): RGBA {
  const n = parseInt(hex.slice(1, 7), 16);
  return [n >> 16, (n >> 8) & 255, n & 255, Math.round(Math.max(0, Math.min(255, alpha)))];
}

/** Mix toward black (k > 0) or white (k < 0), keeping alpha. */
export function shade([r, g, b, a]: RGBA, k: number): RGBA {
  const mix = (c: number) => Math.round(k >= 0 ? c * (1 - k) : c + (255 - c) * -k);
  return [mix(r), mix(g), mix(b), a];
}
