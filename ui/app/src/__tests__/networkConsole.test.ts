import { describe, expect, it } from 'vitest';
import { loadLegacy, type LegacyPayload } from '../adapters/demo/legacy';
import { ACTION_COLORS, centroidDistanceKm, curvedEdge, displayDelta, displaySurge, geographicBounds, mercator, networkAt, visibleEdges, type NetworkEdge } from '../components/console/network';

function fixture() {
  const hexes = [0, 1, 2].map(i => ({ id: `hex-${i}`, zone: 'cbd', ring: i, lat: 10.77 + i * 0.01, lng: 106.69 + i * 0.01, poly: [[10.76 + i * 0.01, 106.68 + i * 0.01], [10.78 + i * 0.01, 106.7 + i * 0.01], [10.77 + i * 0.01, 106.71 + i * 0.01]] as [number, number][] }));
  const od: [number, number, number][][] = Array.from({ length: 24 }, () => []);
  od[12] = [[0, 1, 20], [2, 1, 50], [0, 0, 99], [1, 0, 0], [8, 1, 12], [0, 2, Number.NaN]];
  od[13] = [[0, 2, 900]];
  return loadLegacy({ day: '2026-01-27', ts: ['13:00', '13:05'], hexes, D: [[1, 2, 3], [2, 3, 4]], S: [[1, 2, 3], [1, 2, 3]], I: [[1, 1, 1], [1, 1, 1]], surge: [[1, 1.2, 1.3], [1, 1.2, 1.3]], npress: [[0, 0, 0]], eta: [[1, 1, 1]], adj: [[0, 1], [1, 2]], od } as LegacyPayload);
}

describe('Network console presentation contract', () => {
  it('keeps the approved action palette separate from decision status', () => {
    expect(ACTION_COLORS).toEqual({ INCREASE: '#F0643B', DECREASE: '#12A3C9', HOLD: '#AEB7C4', REVIEW: '#8B6CF0' });
  });
  it('uses only the completed OD hour, never the unfinished hour', () => {
    const data = fixture();
    const before = JSON.stringify(data.raw.od);
    const network = networkAt(data, '2026-01-27T13:35:00+07:00');
    expect(network.hour).toBe(12);
    expect(network.edges.map(edge => edge.volume)).toEqual([50, 20]);
    expect(network.invalid).toBe(2);
    expect(network.windowLabel).toContain('12:00–13:00');
    expect(JSON.stringify(data.raw.od)).toBe(before);
  });
  it('shows no OD when no completed window is available', () => {
    const network = networkAt(fixture(), '2026-01-27T00:35:00+07:00');
    expect(network.hour).toBeNull();
    expect(network.edges).toEqual([]);
  });
  it('deduplicates hybrid edges and does not mutate input', () => {
    const edges: NetworkEdge[] = Array.from({ length: 30 }, (_, i) => ({ id: String(i), source: i % 3, target: (i + 1) % 3, volume: 100 - i }));
    const before = JSON.stringify(edges);
    const shown = visibleEdges(edges, 1, true, false);
    expect(new Set(shown.map(edge => edge.id)).size).toBe(shown.length);
    expect(shown.length).toBeLessThanOrEqual(20);
    expect(visibleEdges(edges, 1, false, false)).toHaveLength(8);
    expect(JSON.stringify(edges)).toBe(before);
  });
  it('projects geography consistently and tolerates empty geometry', () => {
    expect(mercator(0, 0)).toEqual([0.5, 0.5]);
    expect(mercator(10, 106)[1]).toBeLessThan(mercator(0, 106)[1]);
    const bounds = geographicBounds(fixture().hexes);
    expect(bounds.span.every(v => v > 0 && Number.isFinite(v))).toBe(true);
    expect(geographicBounds([]).center).toEqual([0.5, 0.5]);
  });
  it('draws curved directional relations and finite centroid distance', () => {
    const shape = curvedEdge([20, 30], [150, 120]);
    expect(shape.path).toMatch(/^M20,30 Q/);
    expect(shape.path).toContain('150,120');
    expect(shape.arrow).toContain('rotate(');
    const data = fixture();
    expect(centroidDistanceKm(data.hexes[0], data.hexes[0])).toBe(0);
    expect(centroidDistanceKm(data.hexes[0], data.hexes[1])).toBeGreaterThan(0);
  });
  it('never turns missing or non-finite prices into zeros', () => {
    expect(displaySurge(null)).toBe('—');
    expect(displaySurge(Number.NaN)).toBe('—');
    expect(displaySurge(1.35)).toBe('1.35×');
    expect(displayDelta(0.15)).toBe('+0.15');
    expect(displayDelta(-0.15)).toBe('−0.15');
    expect(displayDelta(0)).toBe('0.00');
    expect(displayDelta(undefined)).toBe('—');
  });
});
