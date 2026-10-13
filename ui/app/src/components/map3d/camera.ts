import type { Map as MapLibreMap } from 'maplibre-gl';
import type { HexRow } from './layers';

export const CAMERA = {
  pitch: 42,
  bearing: 10,
  fitMs: 600,
  flyMs: 700,
  focusZoom: 11.8,
} as const;

/** Fit padding scaled to the map panel: bottom clears the legend, right clears the zoom controls. */
export function paddingFor(map: MapLibreMap): { top: number; bottom: number; left: number; right: number } {
  const { clientWidth: w, clientHeight: h } = map.getContainer();
  return { top: Math.round(h * 0.1), bottom: Math.round(Math.min(112, h * 0.22)), left: Math.round(w * 0.05), right: Math.max(56, Math.round(w * 0.08)) };
}

export function boundsOf(rows: HexRow[]): [[number, number], [number, number]] | null {
  const pts = rows.flatMap(r => r.polygon).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (!pts.length) return null;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  return [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]];
}

/** Fit every hex. `resetAngles` restores the default pitch/bearing (Reset Camera); otherwise keep the user's angle. */
export function fitAll(map: MapLibreMap, rows: HexRow[], animate: boolean, resetAngles = false): void {
  const bounds = boundsOf(rows);
  if (!bounds) return;
  map.fitBounds(bounds, {
    padding: paddingFor(map),
    pitch: resetAngles ? CAMERA.pitch : map.getPitch(),
    bearing: resetAngles ? CAMERA.bearing : map.getBearing(),
    duration: animate ? CAMERA.fitMs : 0,
  });
}

export function flyToHex(map: MapLibreMap, row: HexRow, animate: boolean): void {
  map.easeTo({
    center: row.centroid,
    zoom: Math.max(map.getZoom(), CAMERA.focusZoom),
    pitch: Math.max(30, map.getPitch()),
    bearing: map.getBearing(),
    padding: paddingFor(map),
    duration: animate ? CAMERA.flyMs : 0,
    easing: t => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2),
  });
}
