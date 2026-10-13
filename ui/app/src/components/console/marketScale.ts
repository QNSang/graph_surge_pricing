/**
 * Per-hex market size figures for ranking hexes against each other in the queue.
 * Only snapshots at or before the cutoff index are read, so replay never sees later data.
 */

/** Snapshots in the trailing hour (12 × 5 minutes, cutoff included). */
export const HOUR_WINDOWS = 12;

export interface HexScale {
  /** Σ demand over the trailing hour, requests. */
  demand1h: number;
  /** Σ max(0, demand − effective supply) per 5-minute window over the trailing hour, requests. */
  shortage1h: number;
  /** Share of city demand from the first snapshot of the day up to the cutoff, 0..1; null when the city total is 0. */
  demandShare: number | null;
  /** 1-based rank by demandShare (1 = largest). */
  shareRank: number;
}

const num = (v: number | null | undefined) => (v != null && Number.isFinite(v) ? v : null);

export function marketScale(D: number[][], S: number[][], t: number, hexCount: number): HexScale[] {
  const out: HexScale[] = Array.from({ length: hexCount }, () => ({ demand1h: 0, shortage1h: 0, demandShare: null, shareRank: 0 }));
  if (t < 0) return out;
  const day = new Array<number>(hexCount).fill(0);
  for (let k = 0; k <= t && k < D.length; k++) {
    const inHour = k > t - HOUR_WINDOWS;
    for (let i = 0; i < hexCount; i++) {
      const d = num(D[k]?.[i]);
      if (d == null) continue;
      day[i] += d;
      if (!inHour) continue;
      out[i].demand1h += d;
      const s = num(S[k]?.[i]);
      if (s != null) out[i].shortage1h += Math.max(0, d - s);
    }
  }
  const total = day.reduce((a, b) => a + b, 0);
  if (total > 0) day.forEach((v, i) => { out[i].demandShare = v / total; });
  [...out.keys()].sort((a, b) => (out[b].demandShare ?? -1) - (out[a].demandShare ?? -1)).forEach((i, r) => { out[i].shareRank = r + 1; });
  return out;
}

/** Res-7 H3 ids end in six unused "f" digits; dropping exactly that suffix keeps ids unique. */
export const shortHexId = (id: string) => (id.length === 15 && id.endsWith('ffffff') ? id.slice(0, -6) : id);
