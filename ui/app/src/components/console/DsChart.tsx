import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useShallow } from 'zustand/react/shallow';
import type { HexSnapshot, Snapshot } from '../../domain/types';
import { fmtNum, fmtTime } from '../../domain/format';
import { observedRatio } from '../../adapters/demo/forecast';
import { DATASET, useStore } from '../../state/store';
import { WINDOW_STEPS, type SurgeHistoryWindow } from '../../adapters/demo/surgeHistory';

const M = { l: 38, r: 38, t: 18, b: 24 };
const COLORS = { ds: '#1f3b63', demand: '#ff0f23', supply: '#18bdf9' };
const TINT = { shortage: '#ff0f23', surplus: '#18bdf9' };

type Point = { t: number; ds: number | null; demand: number | null; supply: number | null };

function finite(v: number | undefined) { return v == null || !Number.isFinite(v) ? null : v; }

function pointAt(t: number, i: number): Point {
  return { t, ds: observedRatio(DATASET, t, i), demand: finite(DATASET.raw.D[t]?.[i]), supply: finite(DATASET.raw.S[t]?.[i]) };
}

/** Closed areas from each gap-free run of the line down to `base`; gaps stay open. */
function areaOf(pts: { x: number; y: number | null }[], base: number) {
  const runs: { x: number; y: number }[][] = [[]];
  for (const p of pts) {
    if (p.y == null) { if (runs.at(-1)!.length) runs.push([]); continue; }
    runs.at(-1)!.push({ x: p.x, y: p.y });
  }
  return runs.filter(r => r.length > 1).map(r => `M${r[0].x.toFixed(1)},${base.toFixed(1)}${r.map(p => `L${p.x.toFixed(1)},${p.y.toFixed(1)}`).join('')}L${r.at(-1)!.x.toFixed(1)},${base.toFixed(1)}Z`).join('');
}

/** Observed path with gaps: never joins across nulls, never backfills. */
function pathOf(pts: { x: number; y: number | null }[]) {
  let d = '';
  let pen = false;
  for (const p of pts) {
    if (p.y == null) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/**
 * Observed D/S (left axis) with demand and effective supply (right axis) for one hex, strictly as-of the cutoff.
 * Points after the cutoff appear only in replay, dashed. The t+5 forecast markers apply to D/S only.
 */
export function DsDemandSupplyChart({ item, snap, win }: { item: HexSnapshot; snap: Snapshot; win: SurgeHistoryWindow }) {
  const { viewMode, head } = useStore(useShallow(s => ({ viewMode: s.viewMode, head: s.head })));
  const [hoverT, setHoverT] = useState<number | null>(null);
  // Legend entries double as toggles; axes keep their scale so hiding a line never rescales the others.
  const [on, setOn] = useState({ ds: true, demand: true, supply: true, graph: true, local: true, ref: true });
  type Layer = keyof typeof on;
  const toggle = (k: Layer) => setOn(v => ({ ...v, [k]: !v[k] }));
  const box = useRef<HTMLDivElement>(null);
  const [{ W, H }, setSize] = useState({ W: 640, H: 200 });
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ W: Math.round(width), H: Math.max(120, Math.round(height)) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const i = item.hex.index;
  const t = snap.t;

  const data = useMemo(() => {
    const from = win === 'day' ? 0 : Math.max(0, t - WINDOW_STEPS[win]);
    const postTo = viewMode === 'REPLAY' ? Math.min(head, win === 'day' ? head : t + 6) : t;
    const to = Math.max(t + 1, postTo);
    const obs: Point[] = [];
    for (let k = from; k < t; k++) obs.push(pointAt(k, i));
    // The cutoff point uses the snapshot's own market values (fixtures may blank them).
    obs.push({ t, ds: item.market.observed_ratio.value, demand: item.market.demand.value, supply: item.market.effective_supply.value });
    const post: Point[] = [];
    for (let k = t + 1; k <= postTo; k++) post.push(pointAt(k, i));
    const all = [...obs, ...post];
    const ref = item.forecast.reference.value;
    const fc = item.forecast.graph.value;
    const fcLocal = item.forecast.local.value;
    const dsVals = all.map(p => p.ds).filter((v): v is number => v != null);
    for (const v of [ref, fc, fcLocal]) if (v != null) dsVals.push(v);
    const countVals = all.flatMap(p => [p.demand, p.supply]).filter((v): v is number => v != null);
    let dsLo = dsVals.length ? Math.min(...dsVals) : 0;
    let dsHi = dsVals.length ? Math.max(...dsVals) : 1;
    if (dsHi - dsLo < 1e-6) dsHi = dsLo + 1;
    const pad = (dsHi - dsLo) * 0.12;
    dsLo = Math.max(0, dsLo - pad);
    dsHi += pad;
    const cHi = Math.max(1, ...countVals) * 1.1;
    return { from, to, obs, post, ref, fc, fcLocal, dsLo, dsHi, cHi };
  }, [win, t, viewMode, head, item, i]);

  const plotH = H - M.t - M.b;
  const x = (k: number) => M.l + ((k - data.from) / Math.max(1, data.to - data.from)) * (W - M.l - M.r);
  const yDs = (v: number) => M.t + (1 - (v - data.dsLo) / (data.dsHi - data.dsLo)) * plotH;
  const yC = (v: number) => M.t + (1 - v / data.cHi) * plotH;
  const span = data.to - data.from;
  // Pick the smallest 5-minute multiple (15 min .. 6 h, then whole 6 h blocks) that keeps tick labels about 80px apart.
  const maxTicks = Math.max(2, Math.floor(W / 80));
  const step = [3, 6, 12, 24, 36, 72].find(s => span / s <= maxTicks) ?? Math.ceil(span / maxTicks / 72) * 72;
  const xTicks: number[] = [];
  for (let k = data.from; k <= data.to; k++) if ((k - data.from) % step === 0) xTicks.push(k);

  const series = [
    { key: 'supply' as const, y: yC, width: 1.8, opacity: 0.9, area: true },
    { key: 'demand' as const, y: yC, width: 1.8, opacity: 0.9, area: true },
    { key: 'ds' as const, y: yDs, width: 2.4, opacity: 1, area: false },
  ];
  const last = data.obs[data.obs.length - 1];
  const hover = hoverT == null ? null : [...data.obs, ...data.post].find(p => p.t === hoverT) ?? null;
  const missing = data.obs.filter(p => p.ds == null).length;
  const show = (v: number | null, digits: number) => v == null ? 'missing' : fmtNum(v, digits);
  const hasForecast = (on.graph && data.fc != null) || (on.local && data.fcLocal != null);

  return <div className="gc-ds-chart">
    <div ref={box} className="gc-ds-plot"><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Observed D/S, demand and effective supply for ${item.hex.id}, cutoff ${fmtTime(snap.envelope.cutoff_ts)}`}
      onMouseLeave={() => setHoverT(null)}
      onMouseMove={e => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        const k = Math.round(data.from + ((px - M.l) / (W - M.l - M.r)) * (data.to - data.from));
        setHoverT(k >= data.from && k <= (data.post.at(-1)?.t ?? t) ? k : null);
      }}>
      <text x={M.l - 6} y={9} textAnchor="end" fontSize="9" fontWeight="600" fill={COLORS.ds}>D/S</text>
      <text x={W - M.r + 6} y={9} fontSize="9" fill="#8a97a8">req</text>
      {hasForecast && <g>
        <rect x={x(t)} y={M.t} width={Math.max(0, x(t + 1) - x(t))} height={plotH} fill="#f3f4fb" />
        <text x={(x(t) + x(t + 1)) / 2} y={M.t + 10} textAnchor="middle" fontSize="8" fill="#6366f1">t+5</text>
      </g>}
      {[0, 0.5, 1].map(f => {
        const y = M.t + (1 - f) * plotH;
        return <g key={f}>
          <line x1={M.l} x2={W - M.r} y1={y} y2={y} stroke={f === 0 ? '#d5dce4' : '#edf0f4'} />
          <text x={M.l - 6} y={y + 3} textAnchor="end" fontSize="9" fill={COLORS.ds}>{(data.dsLo + f * (data.dsHi - data.dsLo)).toFixed(1)}</text>
          <text x={W - M.r + 6} y={y + 3} fontSize="9" fill="#8a97a8">{Math.round(f * data.cHi)}</text>
        </g>;
      })}
      {xTicks.map(k => <text key={k} x={x(k)} y={H - 7} textAnchor="middle" fontSize="9" fill="#8a97a8">{DATASET.raw.ts[k] ?? ''}</text>)}

      {on.ref && data.ref != null && <line x1={M.l} x2={W - M.r} y1={yDs(data.ref)} y2={yDs(data.ref)} stroke="#8c94a1" strokeDasharray="2 4" />}
      <line x1={x(t)} x2={x(t)} y1={M.t - 2} y2={H - M.b} stroke="var(--focus)" strokeWidth={1.5} />
      <text x={x(t)} y={M.t - 5} textAnchor="middle" fontSize="9" fontWeight="600" fill="var(--focus)">Now</text>
      <defs>{(['demand', 'supply'] as const).map(k => <linearGradient key={k} id={`gc-ds-fill-${k}`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={COLORS[k]} stopOpacity="0.16" /><stop offset="1" stopColor={COLORS[k]} stopOpacity="0.01" />
      </linearGradient>)}</defs>
      {series.filter(s => on[s.key]).map(s => {
        const pts = data.obs.map(p => ({ x: x(p.t), y: p[s.key] == null ? null : s.y(p[s.key]!) }));
        return <g key={s.key}>
        {s.area && <path d={areaOf(pts, M.t + plotH)} fill={`url(#gc-ds-fill-${s.key})`} />}
        {!s.area && <path d={pathOf(pts)} fill="none" stroke={COLORS[s.key]} strokeOpacity={0.14} strokeWidth={9} strokeLinejoin="round" strokeLinecap="round" />}
        <path d={pathOf(pts)} fill="none" stroke={COLORS[s.key]} strokeOpacity={s.opacity} strokeWidth={s.width} strokeLinejoin="round" strokeLinecap="round" />
        {data.post.length > 0 && <path d={pathOf([last, ...data.post].map(p => ({ x: x(p.t), y: p[s.key] == null ? null : s.y(p[s.key]!) })))} fill="none" stroke={COLORS[s.key]} strokeOpacity={0.5} strokeWidth={1.2} strokeDasharray="2 3" />}
      </g>;
      })}
      {/* Dashed links from the cutoff D/S to each t+5 forecast. */}
      {last.ds != null && [on.local ? data.fcLocal : null, on.graph ? data.fc : null].map((v, k) => v != null && <line key={k} x1={x(t)} y1={yDs(last.ds!)} x2={x(t + 1)} y2={yDs(v)} stroke={k ? 'var(--od)' : '#516179'} strokeWidth={1.2} strokeDasharray="3 3" />)}
      {on.ds && last.ds != null && <circle cx={x(t)} cy={yDs(last.ds)} r={3} fill={COLORS.ds} />}
      {on.local && data.fcLocal != null && <circle cx={x(t + 1)} cy={yDs(data.fcLocal)} r={3.5} fill="none" stroke="#516179" strokeWidth={1.4} />}
      {on.graph && data.fc != null && <rect x={x(t + 1) - 4} y={yDs(data.fc) - 4} width={8} height={8} transform={`rotate(45 ${x(t + 1)} ${yDs(data.fc)})`} fill="var(--od)" />}
      {hover && <g pointerEvents="none">
        <line x1={x(hover.t)} x2={x(hover.t)} y1={M.t} y2={H - M.b} stroke="#4c607c" strokeOpacity={0.4} />
        {series.filter(s => on[s.key] && hover[s.key] != null).map(s => <circle key={s.key} cx={x(hover.t)} cy={s.y(hover[s.key]!)} r={3} fill={COLORS[s.key]} stroke="#f3f5f9" strokeWidth={1} />)}
      </g>}
    </svg>
    {hover && <div className={`gc-chart-tip${x(hover.t) > W / 2 ? ' is-left' : ''}`} style={{ left: x(hover.t), top: M.t }}>
      <strong>{DATASET.raw.ts[hover.t]}{hover.t > t ? ' · after cutoff' : ''}</strong>
      <span><i style={{ background: COLORS.ds }} />D/S<b>{show(hover.ds, 2)}</b></span>
      <span><i style={{ background: COLORS.demand }} />Demand<b>{show(hover.demand, 0)}</b></span>
      <span><i style={{ background: COLORS.supply }} />Supply<b>{show(hover.supply, 1)}</b></span>
      {hover.demand != null && hover.supply != null && <span><i style={{ background: hover.demand > hover.supply ? TINT.shortage : TINT.surplus, opacity: 0.4 }} />{hover.demand > hover.supply ? 'Shortage' : 'Surplus'}<b>{fmtNum(Math.abs(hover.demand - hover.supply), 1)}</b></span>}
      {hover.t === t && data.fc != null && <span><i style={{ background: 'var(--od)' }} />Graph t+5<b>{fmtNum(data.fc, 2)}</b></span>}
      {hover.t === t && data.fcLocal != null && <span><i style={{ background: '#516179' }} />Local t+5<b>{fmtNum(data.fcLocal, 2)}</b></span>}
    </div>}
    </div>
    <div className="gc-ds-legend">
      {([
        ['ds', <i style={{ background: COLORS.ds }} />, 'D/S', 'Observed D/S (left axis)', true],
        ['demand', <i style={{ background: COLORS.demand }} />, 'Demand', 'Demand, requests per 5 min (right axis)', true],
        ['supply', <i style={{ background: COLORS.supply }} />, 'Supply', 'Effective supply (right axis)', true],
        ['graph', <b className="gc-ds-diamond" />, 'Graph t+5', 'Graph model D/S forecast for the next 5 minutes', data.fc != null],
        ['local', <b className="gc-ds-ring" />, 'Local t+5', 'Local model D/S forecast for the next 5 minutes', data.fcLocal != null],
        ['ref', <i className="gc-ds-ref" />, `Ref ${data.ref?.toFixed(2) ?? ''}`, 'Reference D/S line', data.ref != null],
      ] as [Layer, ReactNode, string, string, boolean][]).filter(([, , , , has]) => has).map(([k, mark, label, hint]) =>
        <button key={k} type="button" className="gc-ds-toggle" aria-pressed={on[k]} title={`${hint} · click to ${on[k] ? 'hide' : 'show'}`} onClick={() => toggle(k)}>{mark}{label}</button>)}
    </div>
    {missing > 0 && <p className="gc-ds-missing">{missing} missing points left blank, not interpolated.</p>}
  </div>;
}
