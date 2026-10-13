import { PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer } from '@deck.gl/core';
import type { HexSnapshot } from '../../domain/types';
import type { NetworkEdge } from '../console/network';
import { ACTION_PALETTE, OD_PALETTE, SELECTED_OUTLINE, rgba, shade, type RGBA } from './palette';
import { columnHeight, hasInvalidDelta, heightFraction } from './scale';
import type { EdgeRole, LngLat, Vec3 } from './odGeometry';

/** Stable per-node geometry: rebuilt only when the node mapping changes, never per snapshot or selection. */
export interface HexRow { id: string; index: number; ring: number; polygon: LngLat[]; centroid: LngLat; radiusM: number }
export interface ArcRow { edge: NetworkEdge; role: EdgeRole; path: Vec3[]; arrow: Vec3[]; width: number }

export function hexRows(items: HexSnapshot[]): HexRow[] {
  return items.map(({ hex }) => {
    const polygon = hex.poly.map(([lat, lng]) => [lng, lat] as LngLat);
    const k = Math.cos(hex.lat * Math.PI / 180);
    const radiusM = polygon.reduce((m, [x, y]) => Math.max(m, Math.hypot((x - hex.lng) * k, y - hex.lat) * 111320), 0);
    return { id: hex.id, index: hex.index, ring: hex.ring, polygon, centroid: [hex.lng, hex.lat], radiusM };
  });
}

export interface LayerState {
  rows: HexRow[];
  lookup: Map<string, HexSnapshot>;
  /** Changes with every replay frame (cutoff); drives colour/height attribute updates. */
  frameKey: string;
  selectedHex: string | null;
  hoverHex: string | null;
  related: Set<number>;
  arcs: ArcRow[];
  showOD: boolean;
  odOpacity: number;
  selectedEdge: string | null;
  hoverEdge: string | null;
  elevationScale: number;
  /** 0 at city zoom, 1 at street zoom: hex fills thin out so the basemap reads through. Outlines stay. */
  closeFade: number;
  /** Intro reveal multiplier per ring, or null once the intro has finished. */
  reveal: ((ring: number) => number) | null;
  revealKey: number;
  transitionMs: number;
  /** One-shot halo progress 0..1, or null when settled. */
  halo: number | null;
  particles: Vec3[];
}

const easeInOut = (t: number) => t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
const ROLE_COLOR: Record<EdgeRole, string> = { incoming: OD_PALETTE.incoming, outgoing: OD_PALETTE.outgoing, other: OD_PALETTE.other };

export function buildLayers(s: LayerState): Layer[] {
  const statusOf = (row: HexRow) => s.lookup.get(row.id)?.proposal;
  const focus = s.selectedHex != null;
  const dimmed = (row: HexRow) => focus && row.id !== s.selectedHex && !s.related.has(row.index);
  const base = (row: HexRow): RGBA => rgba(ACTION_PALETTE[statusOf(row)?.status ?? 'REVIEW']);
  /** Outline colour for the selected hex (blue) and its OD-linked hexes (their own vivid colour); null otherwise. */
  const glow = (row: HexRow): RGBA | null =>
    row.id === s.selectedHex ? rgba(SELECTED_OUTLINE) : focus && s.related.has(row.index) ? base(row) : null;
  const height = (row: HexRow) => {
    const p = statusOf(row);
    return p ? columnHeight(p) * (s.reveal ? s.reveal(row.ring) : 1) : 0;
  };
  const frame = [s.frameKey, s.revealKey];
  const colorKey = [s.frameKey, s.selectedHex, s.hoverHex, s.related.size, s.closeFade];
  const thin = (alpha: number) => Math.round(alpha * (1 - 0.65 * s.closeFade));
  const transitions = s.transitionMs > 0
    ? { getElevation: { duration: s.transitionMs, easing: easeInOut }, getFillColor: { duration: 200 }, getLineColor: { duration: 200 } }
    : undefined;
  const selectedRow = s.rows.find(r => r.id === s.selectedHex);
  const markers = s.rows.filter(row => { const p = statusOf(row); return p != null && (p.status === 'REVIEW' || hasInvalidDelta(p)); });

  const layers: Layer[] = [
    // Soft shadow: an offset disc whose density follows the column height fraction.
    new ScatterplotLayer<HexRow>({
      id: 'hex-shadow', data: s.rows, radiusUnits: 'meters', stroked: false,
      getPosition: r => [r.centroid[0] + 0.0012, r.centroid[1] - 0.0010, 0],
      getRadius: r => r.radiusM * 0.92,
      getFillColor: r => { const p = statusOf(r); return [15, 23, 42, thin((p ? 6 + 30 * heightFraction(p) : 0) * (dimmed(r) ? 0.4 : 1) * (s.reveal ? s.reveal(r.ring) : 1))]; },
      updateTriggers: { getFillColor: [...colorKey, s.revealKey] },
      parameters: { depthWriteEnabled: false },
    }),
    // Translucent base footprint with a crisp hairline border.
    new PolygonLayer<HexRow>({
      id: 'hex-footprint', data: s.rows, getPolygon: r => r.polygon, filled: true, stroked: true, extruded: false,
      lineWidthUnits: 'pixels', getLineWidth: r => (r.id === s.selectedHex ? 0 : glow(r) ? 2.5 : 1),
      getFillColor: r => { const c = base(r); return [c[0], c[1], c[2], thin(dimmed(r) ? 22 : 60)]; },
      getLineColor: r => { const g = glow(r); if (g) return g; const c = shade(base(r), 0.1); return [c[0], c[1], c[2], dimmed(r) ? 70 : 210]; },
      updateTriggers: { getFillColor: colorKey, getLineColor: colorKey, getLineWidth: colorKey },
      parameters: { depthWriteEnabled: false },
      pickable: true,
    }),
    // 3D columns: top face carries the recommendation colour, lit side faces read darker.
    new PolygonLayer<HexRow>({
      id: 'hex-columns', data: s.rows, getPolygon: r => r.polygon, extruded: true, wireframe: true, filled: true,
      elevationScale: s.elevationScale,
      getElevation: height,
      getFillColor: r => {
        const c = base(r);
        const lit = r.id === s.hoverHex ? shade(c, -0.18) : c;
        return [lit[0], lit[1], lit[2], thin(dimmed(r) ? 70 : 215)];
      },
      // Wireframe edges share the column's own elevation, so the highlight can never drift from the column.
      getLineColor: r => glow(r) ?? (dimmed(r) ? [255, 255, 255, 60] : [255, 255, 255, 170]),
      material: { ambient: 0.62, diffuse: 0.55, shininess: 28, specularColor: [255, 255, 255] },
      updateTriggers: { getElevation: frame, getFillColor: colorKey, getLineColor: colorKey },
      transitions,
      pickable: true,
    }),
    // Thick top rim for highlighted hexes. Data is the stable row list (never a per-frame array) and z is the
    // raw column height scaled by modelMatrix, so it transitions exactly like getElevation above.
    new PathLayer<HexRow>({
      id: 'hex-top-rim', data: s.rows, widthUnits: 'pixels', capRounded: true, jointRounded: true,
      getPath: r => { const h = height(r); return [...r.polygon, r.polygon[0]].map(([x, y]): Vec3 => [x, y, h]); },
      getColor: r => glow(r) ?? [0, 0, 0, 0],
      getWidth: r => (glow(r) ? 2.5 : 0),
      modelMatrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, s.elevationScale, 0, 0, 0, 0, 1],
      updateTriggers: { getPath: frame, getColor: colorKey, getWidth: colorKey },
      transitions: transitions && { getPath: transitions.getElevation },
      // Pull the rim slightly toward the camera so it wins over the coplanar top face.
      parameters: { depthWriteEnabled: false, depthCompare: 'less-equal', depthBias: -4, depthBiasSlopeScale: -4 },
    }),
  ];

  if (selectedRow) {
    const t = s.halo;
    layers.push(
      new ScatterplotLayer<HexRow>({
        id: 'selected-halo', data: [selectedRow], radiusUnits: 'meters', stroked: true, lineWidthUnits: 'pixels',
        getPosition: r => [r.centroid[0], r.centroid[1], 0],
        getRadius: r => r.radiusM * (t == null ? 1.18 : 1 + 0.55 * t),
        getFillColor: rgba(SELECTED_OUTLINE, t == null ? 26 : 50 * (1 - t)),
        getLineColor: rgba(SELECTED_OUTLINE, t == null ? 0 : 190 * (1 - t)),
        getLineWidth: 2,
        updateTriggers: { getRadius: [t], getFillColor: [t], getLineColor: [t] },
        parameters: { depthWriteEnabled: false },
      }),
      new PathLayer<HexRow>({
        id: 'selected-base', data: [selectedRow], widthUnits: 'pixels', getWidth: 3, capRounded: true, jointRounded: true,
        getPath: r => [...r.polygon, r.polygon[0]].map(([x, y]): Vec3 => [x, y, 1]),
        getColor: rgba(SELECTED_OUTLINE),
      }),
    );
  }

  if (markers.length) layers.push(new TextLayer<HexRow>({
    id: 'review-markers', data: markers, getPosition: r => [r.centroid[0], r.centroid[1], 4],
    getText: () => '!', getSize: 15, sizeUnits: 'pixels', fontWeight: 800, getColor: rgba(ACTION_PALETTE.REVIEW),
    fontSettings: { sdf: true }, outlineWidth: 3, outlineColor: [255, 255, 255, 240],
    billboard: true, updateTriggers: { getPosition: [s.frameKey] },
  }));

  if (s.showOD && s.arcs.length && s.odOpacity > 0) {
    const emphasised = (a: ArcRow) => a.edge.id === s.selectedEdge || a.edge.id === s.hoverEdge;
    const color = (a: ArcRow): RGBA => rgba(ROLE_COLOR[a.role], emphasised(a) ? 255 : a.role === 'other' ? 120 : 225);
    const odKey = [s.selectedEdge, s.hoverEdge, s.selectedHex, s.frameKey];
    layers.push(
      new PathLayer<ArcRow>({
        id: 'od-arcs', data: s.arcs, getPath: a => a.path, widthUnits: 'pixels', billboard: true, capRounded: true, jointRounded: true,
        getWidth: a => a.width + (emphasised(a) ? 1.5 : 0), getColor: color, opacity: s.odOpacity,
        updateTriggers: { getWidth: odKey, getColor: odKey }, pickable: true,
      }),
      new PathLayer<ArcRow>({
        id: 'od-arrows', data: s.arcs, getPath: a => a.arrow, widthUnits: 'pixels', billboard: true, capRounded: true, jointRounded: true,
        getWidth: a => Math.max(1.5, a.width * 0.8), getColor: color, opacity: s.odOpacity,
        updateTriggers: { getColor: odKey, getWidth: odKey }, pickable: true,
      }),
    );
    // Direction glyphs only: particle count carries no information about drivers or volume.
    if (s.particles.length) layers.push(new ScatterplotLayer<Vec3>({
      id: 'od-particles', data: s.particles, getPosition: p => p, radiusUnits: 'pixels', getRadius: 2.4,
      getFillColor: [255, 255, 255, 235], stroked: true, lineWidthUnits: 'pixels', getLineWidth: 1, getLineColor: [30, 41, 59, 120],
      opacity: s.odOpacity,
    }));
  }
  return layers;
}
