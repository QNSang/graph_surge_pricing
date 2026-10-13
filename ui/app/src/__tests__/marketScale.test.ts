import { describe, expect, it } from 'vitest';
import { HOUR_WINDOWS, marketScale, shortHexId } from '../components/console/marketScale';

describe('marketScale', () => {
  // 14 snapshots, 2 hexes: hex 0 demand 2 / supply 1 each window, hex 1 demand 1 / supply 3.
  const D = Array.from({ length: 14 }, () => [2, 1]);
  const S = Array.from({ length: 14 }, () => [1, 3]);

  it('sums demand and per-window shortage over the trailing hour only', () => {
    const [a, b] = marketScale(D, S, 13, 2);
    expect(a.demand1h).toBe(2 * HOUR_WINDOWS);
    expect(a.shortage1h).toBe(1 * HOUR_WINDOWS);
    expect(b.demand1h).toBe(HOUR_WINDOWS);
    expect(b.shortage1h).toBe(0); // surplus windows never offset shortage
  });

  it('day share covers the day up to the cutoff and ranks hexes', () => {
    const [a, b] = marketScale(D, S, 13, 2);
    expect(a.demandShare).toBeCloseTo(2 / 3);
    expect(b.demandShare).toBeCloseTo(1 / 3);
    expect([a.shareRank, b.shareRank]).toEqual([1, 2]);
  });

  it('never reads snapshots after the cutoff', () => {
    const late = D.map((row, k) => (k > 3 ? [1000, 1000] : row));
    const [a] = marketScale(late, S, 3, 2);
    expect(a.demand1h).toBe(8);
  });

  it('skips missing values and an empty city total', () => {
    const [a] = marketScale([[Number.NaN, 0]], [[1, 1]], 0, 2);
    expect(a.demand1h).toBe(0);
    expect(a.demandShare).toBeNull();
  });
});

describe('shortHexId', () => {
  it('drops only the six unused res-7 digits', () => {
    expect(shortHexId('8765b5646ffffff')).toBe('8765b5646');
    expect(shortHexId('8765b565fffffff')).toBe('8765b565f');
    expect(shortHexId('hex-1')).toBe('hex-1');
  });
});
