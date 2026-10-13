import { describe, expect, it } from 'vitest';
import { DISPLAY_SCALE, columnHeight, elevationScaleFor, hasInvalidDelta, heightFraction, zoomExtrusionFactor } from '../components/map3d/scale';
import { arcPath, arrowHead, edgeRole, edgeWidthPx, pointAt } from '../components/map3d/odGeometry';
import { ACTION_PALETTE, OD_PALETTE, SELECTED_OUTLINE, rgba } from '../components/map3d/palette';
import type { Recommendation } from '../domain/types';

const p = (status: Recommendation, delta_applied: number | null) => ({ status, delta_applied });
const maxH = DISPLAY_SCALE.maxVisualHeightM;

describe('3D column height (|delta_applied| on a versioned display scale)', () => {
  it('maps |delta| linearly to the configured scale', () => {
    expect(heightFraction(p('INCREASE', 0.40))).toBe(1);
    expect(heightFraction(p('INCREASE', 0.20))).toBeCloseTo(0.5);
    expect(heightFraction(p('DECREASE', -0.10))).toBeCloseTo(0.25);
    expect(heightFraction(p('DECREASE', -0.30))).toBeCloseTo(0.75);
    expect(columnHeight(p('INCREASE', 0.40))).toBe(maxH);
  });
  it('gives +x and -x the same height', () => {
    expect(columnHeight(p('INCREASE', 0.2))).toBe(columnHeight(p('DECREASE', -0.2)));
  });
  it('clamps above deltaMax', () => {
    expect(columnHeight(p('INCREASE', 1.5))).toBe(maxH);
  });
  it('keeps HOLD and REVIEW flat', () => {
    expect(columnHeight(p('HOLD', 0))).toBe(0);
    expect(columnHeight(p('HOLD', 0.3))).toBe(0);
    expect(columnHeight(p('REVIEW', 0.3))).toBe(0);
    expect(hasInvalidDelta(p('REVIEW', null))).toBe(false);
  });
  it('never turns a missing or invalid delta into a column', () => {
    for (const d of [null, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(columnHeight(p('INCREASE', d))).toBe(0);
      expect(hasInvalidDelta(p('INCREASE', d))).toBe(true);
    }
  });
  it('fades extrusion out at low zoom and keeps a finite scale', () => {
    expect(zoomExtrusionFactor(7)).toBe(0);
    expect(zoomExtrusionFactor(11)).toBe(1);
    expect(elevationScaleFor(7, 10.8)).toBe(0);
    expect(Number.isFinite(elevationScaleFor(12, 10.8))).toBe(true);
    expect(elevationScaleFor(12, 10.8)).toBeGreaterThan(0);
  });
});

describe('OD arc geometry', () => {
  const a: [number, number] = [106.70, 10.77], b: [number, number] = [106.75, 10.80];
  const path = arcPath(a, b, 100, 40);
  it('starts and ends on the column tops', () => {
    expect(path[0]).toEqual([a[0], a[1], 100]);
    expect(path.at(-1)![0]).toBeCloseTo(b[0]);
    expect(path.at(-1)![1]).toBeCloseTo(b[1]);
    expect(path.at(-1)![2]).toBeCloseTo(40);
  });
  it('rises above both column tops mid-way', () => {
    expect(Math.max(...path.map(v => v[2]))).toBeGreaterThan(100);
    expect(pointAt(path, 0.5)[2]).toBeGreaterThan(100);
  });
  it('lands on the destination from above', () => {
    const [prev, last] = path.slice(-2);
    expect(prev[2] - last[2]).toBeGreaterThan(0);
  });
  it('places a three-point arrowhead at the destination, wings above the tip', () => {
    const arrow = arrowHead(path, 50);
    expect(arrow).toHaveLength(3);
    expect(arrow[1]).toEqual(pointAt(path, 1));
    expect(arrow[0][2]).toBeGreaterThan(arrow[1][2]);
    expect(arrow[2][2]).toBeGreaterThan(arrow[1][2]);
  });
  it('labels direction relative to the selected hex', () => {
    expect(edgeRole({ source: 1, target: 2 }, 2)).toBe('incoming');
    expect(edgeRole({ source: 2, target: 3 }, 2)).toBe('outgoing');
    expect(edgeRole({ source: 4, target: 5 }, 2)).toBe('other');
    expect(edgeRole({ source: 1, target: 2 }, -1)).toBe('other');
  });
  it('scales width monotonically with volume', () => {
    const w = [0, 10, 40, 100].map(v => edgeWidthPx(v, 100));
    expect(w).toEqual([...w].sort((x, y) => x - y));
    expect(edgeWidthPx(Number.NaN, 100)).toBe(edgeWidthPx(0, 100));
  });
});

describe('3D palette', () => {
  it('uses the spec recommendation colours', () => {
    expect(ACTION_PALETTE).toEqual({ INCREASE: '#F0643B', DECREASE: '#12A3C9', HOLD: '#AEB7C4', REVIEW: '#8B6CF0' });
    expect(SELECTED_OUTLINE).toBe('#2563EB');
  });
  it('never reuses a recommendation colour for OD edges', () => {
    const actions = new Set(Object.values(ACTION_PALETTE).map(c => c.toUpperCase()));
    for (const c of Object.values(OD_PALETTE)) expect(actions.has(c.toUpperCase())).toBe(false);
  });
  it('parses hex colours to RGBA', () => {
    expect(rgba('#2563EB', 128)).toEqual([37, 99, 235, 128]);
  });
});
