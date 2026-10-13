import { surgeStepPath, type SurgePoint } from '../../adapters/demo/surgeHistory';
import { fmtTime } from '../../domain/format';

const W = 60;
const H = 16;
const PAD = 2;
/** Smallest vertical span, so a 1.00 → 1.02 wiggle does not read as a steep move. */
const MIN_SPAN = 0.2;

/** Observed base (bidding) surge up to the cutoff, as a step line on a per-row scale. One blue for every row (not a recommendation color), no forecast. */
export function QueueSparkline({ points }: { points: SurgePoint[] }) {
  const values = points.flatMap(p => (p.value == null ? [] : [p.value]));
  if (values.length < 2) return <span className="gc-spark-empty" title="Not enough base surge history">—</span>;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const mid = (lo + hi) / 2;
  const span = Math.max(MIN_SPAN, hi - lo);
  const x = (j: number) => PAD + (j / Math.max(1, points.length - 1)) * (W - PAD * 2);
  const y = (v: number) => H - PAD - ((v - (mid - span / 2)) / span) * (H - PAD * 2);
  const path = surgeStepPath(points.map((p, j) => ({ x: x(j), y: p.value == null ? null : y(p.value), breakBefore: p.breakBefore })));
  // Soft fill under each contiguous run of the step line; gaps and missing values break the fill too.
  const pts = points.map((p, j) => ({ x: x(j), y: p.value == null ? null : y(p.value), breakBefore: p.breakBefore }));
  let area = '';
  let run: typeof pts = [];
  const flush = () => { if (run.length > 1) area += `${surgeStepPath(run)}V${H}H${run[0].x.toFixed(2)}Z`; run = []; };
  for (const q of pts) { if (q.y == null || q.breakBefore) flush(); if (q.y != null) run.push(q); }
  flush();
  const last = points.at(-1)!;
  const first = points.find(p => p.value != null)!;
  const missing = points.length - values.length;
  const title = `Base surge, last 1h: ${first.value!.toFixed(2)} → ${last.value == null ? 'missing' : last.value.toFixed(2)} (min ${lo.toFixed(2)} · max ${hi.toFixed(2)}) · ${points.length} points${missing ? ` · ${missing} missing` : ''} · cutoff ${fmtTime(last.timestamp)}`;
  return (
    // Drawn in a fixed viewBox and stretched to the CSS width (wider when the queue panel is wider); strokes do not scale.
    <svg className="gc-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={title}>
      <title>{title}</title>
      {area && <path className="gc-spark-area" d={area} />}
      <path className="gc-spark-line" d={path} />
      {last.value != null && <path className="gc-spark-dot" d={`M${x(points.length - 1).toFixed(2)},${y(last.value).toFixed(2)}h0`} />}
    </svg>
  );
}
