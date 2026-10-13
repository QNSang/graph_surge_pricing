import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { ArrowDownLeft, ArrowLeft, ArrowRight, ArrowUpRight, ArrowsInSimple, ArrowsOutSimple, CaretDown, Check, CheckCircle, ClockCounterClockwise, Copy, Cube, MagnifyingGlass, MapTrifold, Pause, Play, SlidersHorizontal } from '@phosphor-icons/react';
import type { HexSnapshot, OperatorStatus, Recommendation, Snapshot } from '../../domain/types';
import { fmtDateTime, fmtTime } from '../../domain/format';
import { reasonCopy } from '../../domain/reasons';
import { SCENARIOS, scenarioById } from '../../adapters/demo/scenarios';
import { buildSurgeHistory, type SurgeHistoryWindow } from '../../adapters/demo/surgeHistory';
import { queueOrder } from '../../adapters/demo/snapshot';
import { DATASET, decisionKey, isActionable, operatorStatus, useStore, type Speed } from '../../state/store';
import { isDecided, useOpStatus, useSelected, useSnapshot } from '../../state/hooks';
import { Banners } from '../Banners';
import { Tabs } from '../ui/primitives';
import { OverrideDrawer } from '../panel/OverrideDrawer';
import { DsDemandSupplyChart } from './DsChart';
import { BatchReview } from '../queue/BatchReview';
import { AuditLog } from '../queue/AuditLog';
import { MapSlot } from '../map3d/MapSlot';
import { requestMapFocus } from '../map3d/focus';
import { marketScale, shortHexId } from './marketScale';
import { QueueSparkline } from './QueueSparkline';
import { ACTIONS, ACTION_COLORS, displayDelta, displayNumber, displaySurge, networkAt, type NetworkData, type NetworkEdge } from './network';
import '../../styles/network-console.css';

const STATUS: Record<OperatorStatus, string> = {
  PENDING: 'Pending', SUBMITTING: 'Recording…', RECORDED: 'Recorded', EXECUTING: 'Executing',
  EFFECTIVE: 'Effective', KEPT_BIDDING: 'Base kept', FAILED: 'Failed', CANCELLED: 'Cancelled', UNKNOWN: 'Checking result…',
};
const actionLabel = (action: Recommendation) => action[0] + action.slice(1).toLowerCase();
const canAccept = (item: HexSnapshot, op: OperatorStatus) => isActionable(item) && item.eligibility.state === 'ELIGIBLE' && item.eligibility.capabilities.confirm && !isDecided(op);

/** True while the media query matches; false where matchMedia is unavailable (tests). */
function useMediaQuery(query: string) {
  const get = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, [query]);
  return matches;
}

function ActionBadge({ action }: { action: Recommendation }) {
  return <span className={`gc-action-badge gc-action-${action.toLowerCase()}`}>{action}</span>;
}

/** Small, strictly as-of chart. It uses the existing tested base-history adapter. */
function CompactSurgeHistory({ item, snap }: { item: HexSnapshot; snap: Snapshot }) {
  const state = useStore(useShallow(s => ({ scenarioId: s.scenarioId, viewMode: s.viewMode, head: s.head })));
  const [range, setRange] = useState<SurgeHistoryWindow>('60');
  const data = useMemo(() => buildSurgeHistory(DATASET, item, snap, scenarioById(state.scenarioId), { window: range, viewMode: state.viewMode, head: state.head }), [item, snap, state, range]);
  // The viewBox follows the measured width, so a wider panel gives a wider chart instead of a taller one.
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(285);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => { const width = Math.round(entry.contentRect.width); if (width > 0) setW(width); });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const points = data.observed;
  const values = points.flatMap(p => p.value == null ? [] : [p.value]);
  const low = values.length ? Math.min(...values) : 0;
  const high = values.length ? Math.max(...values) : 1;
  const padding = Math.max(0.05, (high - low) * 0.2);
  const lo = Math.max(0, low - padding), hi = high + padding;
  const h = 165, left = 37, right = 13, top = 17, bottom = 30;
  const first = points[0] ? Date.parse(points[0].timestamp) : 0;
  const last = points.at(-1) ? Date.parse(points.at(-1)!.timestamp) : first + 1;
  const x = (ts: string) => left + (Date.parse(ts) - first) / Math.max(1, last - first) * (w - left - right);
  const y = (value: number) => top + (hi - value) / Math.max(0.0001, hi - lo) * (h - top - bottom);
  // Step line split into segments: a rise uses the INCREASE colour, a fall the DECREASE colour, and a flat run
  // keeps the colour of the last change (neutral before the first change). Gaps and breaks are never joined.
  const segments: { d: string; color: string }[] = [];
  let prev: { x: number; y: number } | null = null;
  let runColor = ACTION_COLORS.HOLD;
  for (const p of points) {
    if (p.value == null || !Number.isFinite(p.value)) { prev = null; continue; }
    const cur = { x: x(p.timestamp), y: y(p.value) };
    if (prev && !p.breakBefore) {
      segments.push({ d: `M${prev.x.toFixed(2)},${prev.y.toFixed(2)}H${cur.x.toFixed(2)}`, color: runColor });
      if (Math.abs(cur.y - prev.y) > 1e-6) {
        runColor = cur.y < prev.y ? ACTION_COLORS.INCREASE : ACTION_COLORS.DECREASE;
        segments.push({ d: `M${cur.x.toFixed(2)},${prev.y.toFixed(2)}V${cur.y.toFixed(2)}`, color: runColor });
      }
    } else runColor = ACTION_COLORS.HOLD;
    prev = cur;
  }
  const ticks = [0, 1, 2, 3].map(i => lo + (hi - lo) * i / 3);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const hovered = hoverIdx == null ? null : points[hoverIdx];
  const hoverPrev = hoverIdx == null ? null : points.slice(0, hoverIdx).reverse().find(p => p.value != null)?.value ?? null;
  const tickCount = w >= 420 ? 5 : 3;
  const indices = [...new Set(Array.from({ length: tickCount }, (_, k) => Math.round((points.length - 1) * k / (tickCount - 1))))].filter(i => i >= 0);
  return <div ref={box} className="gc-mini-chart">
    <div className="gc-mini-chart-head"><h3>Surge History <span>(This Hex)</span></h3><Tabs label="Surge history window" size="sm" value={range} onChange={setRange} items={[{ id: '60', label: '1h' }, { id: '180', label: '3h' }, { id: '360', label: '6h' }, { id: 'day', label: 'Day' }]} /></div>
    <div className="gc-chart-hover-box"><svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Observed base surge history for ${item.hex.id}; no model or manual prices`}
      onMouseLeave={() => setHoverIdx(null)}
      onMouseMove={e => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width * w;
        let best: number | null = null;
        points.forEach((p, i) => { if (p.value != null && (best == null || Math.abs(x(p.timestamp) - px) < Math.abs(x(points[best].timestamp) - px))) best = i; });
        setHoverIdx(px >= left - 4 && px <= w - right + 4 ? best : null);
      }}>
      {ticks.map(tick => <g key={tick}><line x1={left} x2={w - right} y1={y(tick)} y2={y(tick)} className="gc-chart-grid" /><text x={left - 7} y={y(tick) + 4} textAnchor="end">{tick.toFixed(2)}×</text></g>)}
      {indices.map(i => <g key={i}><line x1={x(points[i].timestamp)} x2={x(points[i].timestamp)} y1={top} y2={h - bottom} className="gc-chart-grid" /><text x={x(points[i].timestamp)} y={h - 10} textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}>{fmtTime(points[i].timestamp)}</text></g>)}
      {segments.map((segment, i) => <path key={i} d={segment.d} stroke={segment.color} strokeWidth="1.8" fill="none" strokeLinecap="square" />)}
      {data.current.value != null && <><line x1={x(data.current.timestamp)} x2={x(data.current.timestamp)} y1={top} y2={h - bottom} stroke="#427fb4" strokeDasharray="3 3" /><circle cx={x(data.current.timestamp)} cy={y(data.current.value)} r="4.5" fill="#1b8afb"><title>{`${fmtTime(data.current.timestamp)} · ${displaySurge(data.current.value)}`}</title></circle></>}
      {!values.length && <text x={w / 2} y={h / 2} textAnchor="middle">No base history available</text>}
      {hovered?.value != null && <g pointerEvents="none"><line x1={x(hovered.timestamp)} x2={x(hovered.timestamp)} y1={top} y2={h - bottom} stroke="#4c607c" strokeOpacity={0.4} /><circle cx={x(hovered.timestamp)} cy={y(hovered.value)} r="3.5" fill="#0e1b2c" stroke="#f3f5f9" strokeWidth="1" /></g>}
    </svg>
    {hovered?.value != null && <div className={`gc-chart-tip${x(hovered.timestamp) > w / 2 ? ' is-left' : ''}`} style={{ left: x(hovered.timestamp), top }}>
      <strong>{fmtTime(hovered.timestamp)}</strong>
      <span>Base surge<b>{displaySurge(hovered.value)}</b></span>
      {hoverPrev != null && <span>Change<b style={{ color: hovered.value > hoverPrev ? ACTION_COLORS.INCREASE : hovered.value < hoverPrev ? ACTION_COLORS.DECREASE : undefined }}>{displayDelta(hovered.value - hoverPrev)}</b></span>}
    </div>}
    </div>
    <small><i style={{ background: ACTION_COLORS.INCREASE }} />increase <i style={{ background: ACTION_COLORS.DECREASE }} />decrease</small>
  </div>;
}

/** Same series colours as the D/S chart under the map. */
const MARKET_COLORS = { demand: '#ff0f23', supply: '#18bdf9' };
const finite = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

/**
 * Demand and effective supply now versus the previous 5-minute snapshot (pale bar = previous, solid = now),
 * on one shared count axis, plus the last-hour size figures shown in the queue.
 */
function MarketFactors({ item, snap }: { item: HexSnapshot; snap: Snapshot }) {
  const prevTs = DATASET.raw.ts[snap.t - 1];
  const rows = [
    { key: 'demand' as const, label: 'Demand', value: item.market.demand.value, prev: DATASET.raw.D[snap.t - 1]?.[item.hex.index], digits: 0 },
    { key: 'supply' as const, label: 'Eff. supply', value: item.market.effective_supply.value, prev: DATASET.raw.S[snap.t - 1]?.[item.hex.index], digits: 1 },
  ];
  const countMax = Math.max(1, ...rows.flatMap(r => [r.value, r.prev]).filter(finite));
  const scale = useMemo(() => marketScale(DATASET.raw.D, DATASET.raw.S, snap.t, DATASET.hexes.length), [snap.t]);
  const hour = scale[item.hex.index];
  return <section className="gc-insight-block" aria-label="Market factors">
    <h3 className="gc-insight-title">Market <span className="gc-insight-time">{prevTs && <span><i className="gc-time-key gc-time-prev" />Prev <time>{prevTs}</time></span>}<span><i className="gc-time-key gc-time-now" />Now <time>{fmtTime(snap.envelope.cutoff_ts)}</time></span></span></h3>
    {rows.map(r => {
      const diff = finite(r.value) && finite(r.prev) ? r.value - r.prev : null;
      const eps = r.digits === 0 ? 0.5 : 0.05;
      const dir = diff == null ? null : diff > eps ? 'up' : diff < -eps ? 'down' : 'flat';
      return <div key={r.key} className="gc-market-row">
        <span className="gc-market-label">{r.label}</span>
        <span className="gc-market-bars" aria-hidden="true">
          {finite(r.prev) && <i className="gc-market-prev" style={{ width: `${r.prev / countMax * 100}%`, background: MARKET_COLORS[r.key] }} />}
          {finite(r.value) && <i className="gc-market-now" style={{ width: `${r.value / countMax * 100}%`, background: MARKET_COLORS[r.key] }} />}
        </span>
        <strong>{displayNumber(r.value, r.digits)}</strong>
        <small className={`gc-market-diff gc-trend-${dir ?? 'flat'}`} title={prevTs ? `Change vs ${prevTs}` : undefined}>{diff == null ? '—' : dir === 'flat' ? '±0' : `${diff > 0 ? '+' : '−'}${displayNumber(Math.abs(diff), r.digits)}`}</small>
      </div>;
    })}
    {hour && <div className="gc-market-hour" title="Same figures as the queue columns: last hour Σ demand, Σ max(0, demand − effective supply) per 5-minute window, and share of city demand today.">
      <span className="gc-market-label">Last 1h</span>
      <span>Dem <b>{displayNumber(hour.demand1h, 0)}</b></span>
      <span>Short <b>{displayNumber(hour.shortage1h, 0)}</b></span>
      <span>Share <b>{hour.demandShare == null ? '—' : `${(hour.demandShare * 100).toFixed(1)}%`}</b></span>
    </div>}
  </section>;
}

/** Operator-facing copy for why the action buttons are locked. */
const LOCK_COPY: Record<string, string> = {
  REPLAY_READ_ONLY: 'Replay is read-only. Go to Latest to act on proposals.',
  SUPERSEDED: 'A newer snapshot is published. Load it to act.',
  EXPIRED: 'This proposal has expired.',
  OFFLINE: 'Offline. Price changes are locked.',
  CONTRACT_MISMATCH: 'Metric contract mismatch. All proposals are blocked.',
  HOLD_NO_ACTION: 'HOLD: no price change to accept.',
  REVIEW_BLOCKED: 'Needs review: accept and manual changes are unavailable.',
  REVIEW_MANUAL_ONLY: 'Needs review: manual price only.',
};

/**
 * The single place operators act, pinned to the bottom of the detail panel: batch accept for the rows checked in
 * the queue (or every eligible row), and accept / keep base / manual edit for the focused hex.
 */
function DecisionBar({ item, snap }: { item: HexSnapshot | null; snap: Snapshot }) {
  const st = useStore(useShallow(s => ({ decisions: s.decisions, pending: s.pending, batch: s.batch })));
  const op = useOpStatus(item);
  const [batchItems, setBatchItems] = useState<HexSnapshot[] | null>(null);
  const [override, setOverride] = useState<HexSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setError(null); }, [item?.proposal.proposal_id, item?.proposal.version]);
  const eligible = snap.items.filter(i => canAccept(i, operatorStatus(st, i)));
  const selected = eligible.filter(i => st.batch[i.proposal.proposal_id] === i.proposal.version);
  // Opt-in batch: the button acts only on rows checked in the queue, never on unchecked ones.
  const allSelected = selected.length > 0 && selected.length === eligible.length;
  function review(items: HexSnapshot[]) { if (items.length) { useStore.getState().setPlaying(false); setBatchItems([...items]); } }
  const caps = item?.eligibility.capabilities;
  const decision = item ? st.decisions[decisionKey(item.proposal)] : undefined;
  const locked = !item || isDecided(op) || item.eligibility.state !== 'ELIGIBLE' || snap.envelope.execution_mode !== 'DEMO';
  const reasons = item?.eligibility.blocked_reasons ?? [];
  // HOLD and REVIEW need no message: the disabled buttons already show what is available.
  const blockReason = reasons.filter(r => r !== 'HOLD_NO_ACTION' && r !== 'REVIEW_MANUAL_ONLY' && r !== 'REVIEW_BLOCKED').map(r => LOCK_COPY[r] ?? r).join(' · ');
  const replay = reasons.includes('REPLAY_READ_ONLY'), superseded = reasons.includes('SUPERSEDED');
  async function decide(action: 'ACCEPT_PROPOSAL' | 'KEEP_BIDDING') {
    if (!item || locked || (action === 'ACCEPT_PROPOSAL' ? !caps?.confirm : !caps?.keep_bidding)) return;
    setError(null);
    try { await useStore.getState().submit(item, action, action === 'ACCEPT_PROPOSAL' ? item.proposal.s_final : item.proposal.s_bid, null); }
    catch { setError('The request did not return a confirmed result. Check the decision history before retrying.'); }
  }
  return <footer className="gc-detail-actions" aria-label="Decision actions">
    <div className="gc-bulk-row">{selected.length
      ? <button className="gc-button gc-button-batch" title="Accept the rows checked in the recommendation queue. A review dialog opens first." onClick={() => review(selected)}>{allSelected ? 'Accept All' : 'Accept Selected'} ({selected.length})</button>
      : <button className="gc-button gc-button-batch is-select" disabled={!eligible.length} title="Check every eligible INCREASE/DECREASE row in this snapshot. Nothing is accepted until you confirm." onClick={() => useStore.getState().set('batch', Object.fromEntries(eligible.map(i => [i.proposal.proposal_id, i.proposal.version])))}>Select all eligible ({eligible.length})</button>}</div>
    {item && (op !== 'PENDING' || blockReason || error) && <div className="gc-action-message" role="status"><span>{error || (op !== 'PENDING' ? STATUS[op] : blockReason)}</span>{op === 'PENDING' && (replay || superseded) && <button type="button" className="gc-link-btn" onClick={() => superseded ? useStore.getState().loadLatest() : useStore.getState().goLatest()}>{superseded ? 'Load latest' : 'Go to Latest'}</button>}{decision?.error && <span>{decision.error}</span>}{decision?.requested_surge && <strong>{displaySurge(Number(decision.requested_surge))}</strong>}</div>}
    <div className="gc-action-buttons" aria-label={item ? `Actions for ${item.hex.id}` : 'Select a hex to act on it'}><button className="gc-button gc-button-accept" disabled={locked || !caps?.confirm} onClick={() => void decide('ACCEPT_PROPOSAL')}>{op === 'SUBMITTING' ? 'Recording…' : 'Accept'}</button><button className="gc-button gc-button-secondary" disabled={locked || !caps?.keep_bidding} onClick={() => void decide('KEEP_BIDDING')}>Keep Base</button><button className="gc-button" disabled={locked || !caps?.override} onClick={() => { if (!item) return; useStore.getState().setPlaying(false); setOverride(item); }}>Edit Manually</button></div>
    <BatchReview open={batchItems != null} items={batchItems ?? []} onClose={() => { setBatchItems(null); useStore.getState().clearBatch(); }} />
    {override && <OverrideDrawer item={override} open onClose={() => setOverride(null)} />}
  </footer>;
}

function SelectionPanel({ item, snap, connections, showQueue }: { item: HexSnapshot | null; snap: Snapshot; connections: ReactNode; showQueue: boolean }) {
  const [tabState, setTab] = useState<'insight' | 'recommendations'>('insight');
  // The queue view already shows the recommendation table on the left, so the tab only exists in the map view.
  const tab = tabState === 'recommendations' && !showQueue ? 'insight' : tabState;
  const [queueHistory, setQueueHistory] = useState(false);
  const [focusDetail, setFocusDetail] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => { setCopied(false); }, [item?.hex.id]);
  const copyId = () => {
    if (!item || !navigator.clipboard) return;
    void navigator.clipboard.writeText(item.hex.id).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); }, () => undefined);
  };
  const scroller = useRef<HTMLDivElement>(null);
  const tabsRow = useRef<HTMLDivElement>(null);
  // Switching tab brings the tab content to the top of the panel instead of leaving it below the summary.
  const showTab = (next: typeof tab) => {
    setTab(next);
    const el = scroller.current, row = tabsRow.current;
    if (el && row && el.scrollTop < row.offsetTop) el.scrollTo({ top: row.offsetTop });
  };
  if (!item) return <aside className="gc-card gc-detail"><div className="gc-empty">Select a hex on the map or in the recommendation queue.</div><DecisionBar item={null} snap={snap} /></aside>;
  const proposal = item.proposal;
  const deltaPct = proposal.status !== 'REVIEW' && proposal.delta_applied != null && proposal.s_bid ? proposal.delta_applied / proposal.s_bid * 100 : null;
  return <aside className="gc-card gc-detail" aria-label="Selected hex recommendation">
    <div ref={scroller} className="gc-detail-scroll">
    {!focusDetail && <div className="gc-detail-top">
      <section className="gc-selected-summary">
        <div className="gc-summary-head"><h2>Selected Hex</h2><ActionBadge action={proposal.status} /></div>
        <div className="gc-hex-identity"><svg viewBox="0 0 42 37" aria-hidden="true"><path d="M11 1.5H31L40.5 18.5L31 35.5H11L1.5 18.5Z" fill={ACTION_COLORS[proposal.status]} stroke={ACTION_COLORS[proposal.status]} strokeWidth="1.5" strokeLinejoin="round" /></svg>
          <div><small>H3 Index</small><strong>{item.hex.id}<button type="button" className="gc-copy-icon" aria-label="Copy H3 index" title="Copy H3 index" onClick={copyId}>{copied ? <Check size={13} /> : <Copy size={13} />}</button></strong><small className="gc-hex-place">{item.hex.zone_label} · Ho Chi Minh City</small></div></div>
        <div className="gc-price-comparison">
          <div className="gc-price-base"><div><small>Base Surge</small><strong>{displaySurge(proposal.s_bid)}</strong></div><ArrowRight size={22} /></div>
          <div className="gc-price-next"><div><small>Proposed Surge</small><strong style={{ color: ACTION_COLORS[proposal.status] }}>{proposal.status === 'REVIEW' ? '—' : displaySurge(proposal.s_final)}</strong></div>
            <div className="gc-delta" style={{ color: ACTION_COLORS[proposal.status] }}><strong>Δ {proposal.status === 'REVIEW' ? '—' : displayDelta(proposal.delta_applied)}</strong>{deltaPct != null && <small>({deltaPct >= 0 ? '+' : ''}{deltaPct.toFixed(1)}%)</small>}</div></div>
        </div>
      </section>
      <CompactSurgeHistory item={item} snap={snap} />
    </div>}
    <div ref={tabsRow} className="gc-tabs gc-detail-tabs"><Tabs label="Recommendation detail tabs" value={tab} onChange={showTab} items={[{ id: 'insight', label: 'Insight' }, ...(showQueue ? [{ id: 'recommendations' as const, label: 'Recommendations' }] : [])]} />
      <button className="gc-detail-focus" aria-pressed={focusDetail} title={focusDetail ? 'Show hex summary' : 'Expand detail (hide hex summary)'} aria-label={focusDetail ? 'Show hex summary' : 'Expand detail'} onClick={() => setFocusDetail(v => !v)}>{focusDetail ? <ArrowsInSimple size={16} /> : <ArrowsOutSimple size={16} />}</button></div>
    <div className="gc-detail-body">
      {tab === 'insight' && <>
        <MarketFactors item={item} snap={snap} />
        {connections}
        {proposal.reasons.length > 0 && <details className="gc-evidence"><summary>Reasons & data provenance <span>{proposal.reasons.length}</span></summary>{proposal.reasons.map(reason => <p key={reason}><code>{reason}</code><br />{reasonCopy(reason).detail}</p>)}<p>Provider: {snap.model.demo_model_id}. Policy: {proposal.policy_version}. D/S definition: {snap.metric.equation}.</p></details>}
      </>}
      {tab === 'recommendations' && <div className="gc-panel-queue"><RecommendationQueue history={queueHistory} onHistoryChange={setQueueHistory} /></div>}
    </div>
    </div>
    <DecisionBar item={item} snap={snap} />
  </aside>;
}

/** Observed D/S, demand and supply history of the selected hex, shown under the map. */
function DsCard({ item, snap }: { item: HexSnapshot; snap: Snapshot }) {
  const [win, setWin] = useState<SurgeHistoryWindow>('60');
  const card = useRef<HTMLElement>(null);
  const drag = useRef<{ y: number; h: number } | null>(null);
  // Card height in px; null keeps the CSS default. Dragging the top edge up grows the chart and shrinks the map.
  const [height, setHeight] = useState<number | null>(null);
  const limits = () => {
    const column = card.current?.parentElement;
    return { min: 180, max: Math.max(180, (column?.clientHeight ?? 600) - 140) };
  };
  const resize = (next: number) => { const { min, max } = limits(); setHeight(Math.round(Math.min(max, Math.max(min, next)))); };
  const current = () => card.current?.offsetHeight ?? 260;
  return <section ref={card} className="gc-card gc-ds-card" aria-label={`D/S history for ${item.hex.id}`} style={height == null ? undefined : { flexBasis: height }}>
    <div className="gc-ds-resizer" role="separator" aria-orientation="horizontal" aria-label="Resize D/S chart" tabIndex={0}
      aria-valuemin={limits().min} aria-valuemax={limits().max} aria-valuenow={height ?? undefined}
      onPointerDown={e => { if (e.button !== 0) return; drag.current = { y: e.clientY, h: current() }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => { const d = drag.current; if (d) resize(d.h + d.y - e.clientY); }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
      onDoubleClick={() => setHeight(height != null && height >= limits().max - 1 ? null : limits().max)}
      onKeyDown={e => {
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); resize(current() + (e.key === 'ArrowUp' ? 24 : -24)); }
        else if (e.key === 'Home') { e.preventDefault(); setHeight(null); }
        else if (e.key === 'End') { e.preventDefault(); resize(limits().max); }
      }} />
    <div className="gc-ds-heading"><h2>D/S · Demand · Supply <small>{item.hex.zone_label}</small></h2><Tabs label="D/S window" size="sm" value={win} onChange={setWin} items={[{ id: '60', label: '1h' }, { id: '180', label: '3h' }, { id: '360', label: '6h' }, { id: 'day', label: 'Day' }]} /></div>
    <DsDemandSupplyChart item={item} snap={snap} win={win} />
  </section>;
}

/** Partner rows shown before "Show all". */
const OD_TOP = 5;

/**
 * OD flow for the selected hex: a diverging total bar (incoming left, outgoing right) and one row per partner
 * hex whose bars are the hourly request flow in each direction. Bars select the edge on the map; the hex id
 * selects the partner. Flow is observed demand movement, not an effect of the recommendation.
 */
function Connections({ snap, network, selectedHex, selectedEdge, onSelect, onEdgeSelect }: { snap: Snapshot; network: NetworkData; selectedHex: string | null; selectedEdge: string | null; onSelect: (id: string) => void; onEdgeSelect: (id: string | null) => void }) {
  const [showAll, setShowAll] = useState(false);
  const selected = snap.items.find(i => i.hex.id === selectedHex);
  const index = selected?.hex.index ?? -1;
  const byIndex = new Map(snap.items.map(item => [item.hex.index, item.hex]));
  const partners = new Map<number, { in?: NetworkEdge; out?: NetworkEdge }>();
  for (const edge of network.edges) {
    if (edge.target === index && edge.source !== index) partners.set(edge.source, { ...partners.get(edge.source), in: edge });
    else if (edge.source === index && edge.target !== index) partners.set(edge.target, { ...partners.get(edge.target), out: edge });
  }
  const rows = [...partners].map(([partner, p]) => ({ hex: byIndex.get(partner), ...p }))
    .filter(r => r.hex)
    .sort((a, b) => (b.in?.volume ?? 0) + (b.out?.volume ?? 0) - (a.in?.volume ?? 0) - (a.out?.volume ?? 0));
  const inTotal = rows.reduce((n, r) => n + (r.in?.volume ?? 0), 0), outTotal = rows.reduce((n, r) => n + (r.out?.volume ?? 0), 0);
  const totalMax = Math.max(inTotal, outTotal, 1e-9);
  const edgeMax = Math.max(1e-9, ...rows.flatMap(r => [r.in?.volume ?? 0, r.out?.volume ?? 0]));
  // An edge picked on the map must stay visible, even when it ranks below the top rows.
  const selectedRank = rows.findIndex(r => r.in?.id === selectedEdge || r.out?.id === selectedEdge);
  useEffect(() => { if (selectedRank >= OD_TOP) setShowAll(true); }, [selectedRank]);
  useEffect(() => { setShowAll(false); }, [index]);
  const visible = showAll ? rows : rows.slice(0, OD_TOP);
  const bar = (edge: NetworkEdge | undefined, side: 'incoming' | 'outgoing', partner: string) => edge
    ? <button type="button" className={`gc-od-bar gc-flow-${side}${selectedEdge === edge.id ? ' is-selected' : ''}`} aria-pressed={selectedEdge === edge.id}
        title={`${side === 'incoming' ? `${partner} → selected` : `selected → ${partner}`} · ${displayNumber(edge.volume, 1)} requests/hour`}
        aria-label={`${side === 'incoming' ? 'Incoming from' : 'Outgoing to'} ${partner}: ${displayNumber(edge.volume, 1)} requests per hour`}
        onClick={() => onEdgeSelect(selectedEdge === edge.id ? null : edge.id)}>
        <b style={{ width: `${Math.max(4, edge.volume / edgeMax * 100)}%` }} /><span>{displayNumber(edge.volume, 1)}</span>
      </button>
    : <span className="gc-od-bar is-empty" />;
  return <section className="gc-insight-block gc-od" id="gc-connections" tabIndex={-1} aria-label="OD flow">
    <h3 className="gc-insight-title">OD flow <span className="gc-insight-time">{network.hour == null ? network.windowLabel : <><span><time>{network.windowLabel.split(' · ')[0]}</time></span><span>requests/hour</span></>}</span></h3>
    {rows.length > 0 && <>
      <div className="gc-od-total" role="img" aria-label={`Incoming ${displayNumber(inTotal, 1)}, outgoing ${displayNumber(outTotal, 1)} requests per hour`}>
        <span className="gc-od-total-label gc-flow-incoming"><ArrowDownLeft size={12} weight="bold" aria-hidden="true" />In <b>{displayNumber(inTotal, 1)}</b></span>
        <span className="gc-od-total-bar gc-flow-incoming"><b style={{ width: `${inTotal / totalMax * 100}%` }} /></span>
        <span className="gc-od-total-bar gc-flow-outgoing"><b style={{ width: `${outTotal / totalMax * 100}%` }} /></span>
        <span className="gc-od-total-label gc-flow-outgoing"><b>{displayNumber(outTotal, 1)}</b> Out<ArrowUpRight size={12} weight="bold" aria-hidden="true" /></span>
      </div>
      <div className="gc-od-head" aria-hidden="true"><span>Partner hex</span><span>◂ in</span><span>out ▸</span></div>
      <ul className="gc-od-rows">{visible.map(r => <li key={r.hex!.id}>
        <button type="button" className="gc-hex-link" title={`Select ${r.hex!.id}`} onClick={() => onSelect(r.hex!.id)}>{r.hex!.id}</button>
        {bar(r.in, 'incoming', r.hex!.id)}
        {bar(r.out, 'outgoing', r.hex!.id)}
      </li>)}</ul>
      {rows.length > OD_TOP && <button type="button" className="gc-link-btn gc-od-more" onClick={() => setShowAll(v => !v)}>{showAll ? 'Show top 5' : `Show all ${rows.length}`}</button>}
    </>}
    {!rows.length && <div className="gc-empty">{network.hour == null ? 'No completed OD window yet.' : 'No OD links for this hex.'}</div>}
    {network.invalid > 0 && <footer>{network.invalid} invalid records omitted</footer>}
  </section>;
}

const NAV_PAGES = [
  { id: 'map', label: 'Map', key: 'M', Icon: MapTrifold },
  { id: 'history', label: 'History', key: 'H', Icon: ClockCounterClockwise },
] as const;

type QueueSort = 'priority' | 'short' | 'share';

function RecommendationQueue({ history, onHistoryChange, compact = false }: { history: boolean; onHistoryChange: (value: boolean) => void; compact?: boolean }) {
  const snap = useSnapshot();
  const st = useStore(useShallow(s => ({ selectedHex: s.selectedHex, decisions: s.decisions, pending: s.pending, search: s.search, batch: s.batch })));
  const [filter, setFilter] = useState<Recommendation | 'ALL'>('ALL');
  const ops = new Map(snap.items.map(item => [item.hex.id, operatorStatus(st, item)]));
  const counts = Object.fromEntries(ACTIONS.map(action => [action, snap.items.filter(item => item.proposal.status === action).length])) as Record<Recommendation, number>;
  const [sortBy, setSortBy] = useState<QueueSort>('priority');
  const scale = useMemo(() => marketScale(DATASET.raw.D, DATASET.raw.S, snap.t, DATASET.hexes.length), [snap.t]);
  const shortMax = Math.max(1e-9, ...scale.map(s => s.shortage1h));
  const shareMax = Math.max(1e-9, ...scale.map(s => s.demandShare ?? 0));
  const bareSurge = (v: number | null | undefined) => displaySurge(v).replace(/×$/, '');
  const histState = useStore(useShallow(s => ({ scenarioId: s.scenarioId, viewMode: s.viewMode, head: s.head })));
  // Same source as the Surge History chart, so the row sparkline and the chart always agree.
  const spark = useMemo(() => compact ? new Map(snap.items.map(item => [item.hex.id, buildSurgeHistory(DATASET, item, snap, scenarioById(histState.scenarioId), { window: '60', viewMode: histState.viewMode, head: histState.head }).observed])) : null, [compact, snap, histState]);
  const rows = useMemo(() => {
    const byScale = (key: 'shortage1h' | 'demandShare') => (a: HexSnapshot, b: HexSnapshot) => (scale[b.hex.index]?.[key] ?? -1) - (scale[a.hex.index]?.[key] ?? -1) || queueOrder(a, b);
    return [...snap.items].filter(item => (filter === 'ALL' || item.proposal.status === filter) && `${item.hex.id} ${item.hex.zone_label}`.toLowerCase().includes(st.search.toLowerCase().trim()))
      .sort(sortBy === 'short' ? byScale('shortage1h') : sortBy === 'share' ? byScale('demandShare') : queueOrder);
  }, [snap, filter, st.search, sortBy, scale]);
  const sortHead = (key: QueueSort, label: string, title: string) => <th className="gc-num" aria-sort={sortBy === key ? 'descending' : 'none'}><button type="button" className={`gc-sort${sortBy === key ? ' is-active' : ''}`} title={title} onClick={() => setSortBy(sortBy === key ? 'priority' : key)}>{label}{sortBy === key && <CaretDown size={10} weight="bold" aria-hidden="true" />}</button></th>;
  const eligibleVisible = rows.filter(item => canAccept(item, ops.get(item.hex.id)!));
  const allChecked = eligibleVisible.length > 0 && eligibleVisible.every(item => st.batch[item.proposal.proposal_id] === item.proposal.version);
  // Snapshot-wide locks (replay, superseded, offline, contract) disable every accept button at once.
  const globalLock = ['REPLAY_READ_ONLY', 'SUPERSEDED', 'OFFLINE', 'CONTRACT_MISMATCH'].find(code => snap.items.length > 0 && snap.items.every(item => item.eligibility.blocked_reasons.includes(code)));
  // Keep the selected row visible when the hex is picked on the map.
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!compact || !st.selectedHex) return;
    const row = scroller.current?.querySelector<HTMLElement>(`tr[data-hex="${st.selectedHex}"]`);
    row?.scrollIntoView?.({ block: 'nearest' });
  }, [compact, st.selectedHex]);
  function toggleAll() {
    const next = { ...st.batch };
    for (const item of eligibleVisible) {
      if (allChecked) delete next[item.proposal.proposal_id];
      else next[item.proposal.proposal_id] = item.proposal.version;
    }
    useStore.getState().set('batch', next);
  }
  return <section className={`gc-card gc-queue${compact ? ' gc-queue-compact' : ''}`} id="gc-queue" tabIndex={-1} aria-label="Recommendation queue">
    <div className="gc-queue-heading"><h2>{history ? 'Decision History' : 'Recommendation Queue'} <span className="gc-count">{snap.items.length} hexes</span></h2>{history ? <button className="gc-button gc-button-small" onClick={() => onHistoryChange(false)}><ArrowLeft size={14} /> Back to Map</button> : <label className="gc-search"><input value={st.search} onChange={e => useStore.getState().set('search', e.target.value)} placeholder="Search hex…" aria-label="Search recommendations" /><MagnifyingGlass size={16} /></label>}</div>
    {history ? <div className="gc-audit" onClick={e => { if ((e.target as HTMLElement).closest('li button')) onHistoryChange(false); }}><AuditLog /></div> : <>
      <div className="gc-queue-toolbar"><div className="gc-action-filters" aria-label="Filter recommendation actions"><button aria-pressed={filter === 'ALL'} className={filter === 'ALL' ? 'is-active' : ''} onClick={() => setFilter('ALL')}>All <span>{snap.items.length}</span></button>{ACTIONS.map(action => <button key={action} aria-pressed={filter === action} className={filter === action ? 'is-active' : ''} onClick={() => setFilter(action)}>{actionLabel(action)} <span>{counts[action]}</span></button>)}</div></div>
      {globalLock && <div className="gc-lock-note" role="status"><span>{LOCK_COPY[globalLock]}</span>{(globalLock === 'REPLAY_READ_ONLY' || globalLock === 'SUPERSEDED') && <button type="button" className="gc-link-btn" onClick={() => globalLock === 'SUPERSEDED' ? useStore.getState().loadLatest() : useStore.getState().goLatest()}>{globalLock === 'SUPERSEDED' ? 'Load latest' : 'Go to Latest'}</button>}</div>}
      <div ref={scroller} className="gc-table-scroll"><table className="gc-recommendations-table"><thead><tr><th><input type="checkbox" checked={allChecked} disabled={!eligibleVisible.length} onChange={toggleAll} aria-label="Select all eligible filtered rows" /></th><th>{compact ? 'Hex' : 'H3 Index'}</th>{compact ? <><th className="gc-spark-head" title="Base surge over the last hour up to the cutoff, 5-minute steps. Scale is per row.">Surge 1h</th><th title="Surge multiplier (×), base → proposed">Surge</th><th className="gc-num">Δ</th>{sortHead('short', 'Short 1h', 'Σ max(0, demand − effective supply) per 5-minute window, last hour (requests). Click to sort.')}{sortHead('share', 'Share', 'Share of city demand today up to this snapshot. Click to sort.')}</> : <><th>Action</th><th>Base Surge</th><th></th><th>Proposed Surge</th><th>Δ</th><th>Key Reason</th><th>Status</th></>}</tr></thead><tbody>{rows.map(item => {
        const op = ops.get(item.hex.id)!;
        const p = item.proposal, valid = canAccept(item, op);
        const reason = p.reasons[0] ? reasonCopy(p.reasons[0]).title : p.status === 'HOLD' ? 'Keep base surge' : 'Provider recommendation';
        const check = <td onClick={e => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${item.hex.id}`} disabled={!valid} checked={valid && st.batch[p.proposal_id] === p.version} onChange={() => useStore.getState().toggleBatch(item)} /></td>;
        if (compact) return <tr key={p.proposal_id} data-hex={item.hex.id} className={item.hex.id === st.selectedHex ? 'gc-row-selected' : ''} onClick={() => { useStore.getState().select(item.hex.id); requestMapFocus(item.hex.id); }}>
          {isDecided(op)
            ? <td><span className={`gc-row-status gc-row-status-check${op === 'RECORDED' || op === 'KEPT_BIDDING' || op === 'EFFECTIVE' ? ' is-done' : ''}`} title={`${STATUS[op]} · see History`} aria-label={STATUS[op]}><CheckCircle size={16} weight="fill" /></span></td>
            : check}
          <td><div className="gc-queue-hex"><i className="gc-action-dot" style={{ background: ACTION_COLORS[p.status] }} title={p.status} aria-label={p.status} /><button className="gc-hex-link" title={`${item.hex.id} · ${item.hex.zone_label}`} onClick={() => { useStore.getState().select(item.hex.id); requestMapFocus(item.hex.id); }}>{shortHexId(item.hex.id)}</button></div></td>
          <td><QueueSparkline points={spark?.get(item.hex.id) ?? []} /></td>
          <td><span className="gc-queue-price"><span className="gc-muted">{bareSurge(p.s_bid)}</span><ArrowRight size={10} /><b style={{ color: ACTION_COLORS[p.status] }}>{p.status === 'REVIEW' ? '—' : bareSurge(p.s_final)}</b></span></td>
          <td className="gc-num" style={{ color: ACTION_COLORS[p.status] }}>{p.status === 'REVIEW' ? '—' : displayDelta(p.delta_applied)}</td>
          <td className="gc-num"><span className="gc-short-cell"><i aria-hidden="true"><b style={{ width: `${(scale[item.hex.index]?.shortage1h ?? 0) / shortMax * 100}%` }} /></i>{displayNumber(scale[item.hex.index]?.shortage1h ?? null, 0)}</span></td>
          <td className="gc-num" title={scale[item.hex.index]?.demandShare == null ? undefined : `#${scale[item.hex.index].shareRank} of ${scale.length}`}>{scale[item.hex.index]?.demandShare == null ? '—' : <span className="gc-share-chip" style={{ '--share': (scale[item.hex.index].demandShare! / shareMax).toFixed(3) } as CSSProperties}>{(scale[item.hex.index].demandShare! * 100).toFixed(1)}%</span>}</td>
        </tr>;
        return <tr key={p.proposal_id} data-hex={item.hex.id} className={item.hex.id === st.selectedHex ? 'gc-row-selected' : ''} onClick={() => { useStore.getState().select(item.hex.id); requestMapFocus(item.hex.id); }}>
          {check}
          <td><button className="gc-hex-link" onClick={() => { useStore.getState().select(item.hex.id); requestMapFocus(item.hex.id); }}>{item.hex.id}</button></td><td><ActionBadge action={p.status} /></td><td className="gc-muted">{displaySurge(p.s_bid)}</td><td className="gc-arrow-cell"><ArrowRight size={18} /></td><td className="gc-price-cell" style={{ color: ACTION_COLORS[p.status] }}>{p.status === 'REVIEW' ? '—' : displaySurge(p.s_final)}</td><td style={{ color: ACTION_COLORS[p.status] }}>{p.status === 'REVIEW' ? '—' : displayDelta(p.delta_applied)}</td><td className="gc-reason-cell" title={reason}>{reason}</td><td><span className={`gc-status ${op === 'RECORDED' || op === 'KEPT_BIDDING' ? 'gc-status-success' : ''}`} title={item.eligibility.blocked_reasons.join(' · ')}>{op === 'PENDING' && item.eligibility.state !== 'ELIGIBLE' ? 'Blocked' : STATUS[op]}</span></td>
        </tr>;
      })}</tbody></table>{!rows.length && <div className="gc-empty">No recommendations match this filter. <button onClick={() => { setFilter('ALL'); useStore.getState().set('search', ''); }}>Clear filters</button></div>}</div>
    </>}
  </section>;
}

function ConsoleReplay() {
  const { t, head, playing, speed, viewMode, audit } = useStore(useShallow(s => ({ t: s.t, head: s.head, playing: s.playing, speed: s.speed, viewMode: s.viewMode, audit: s.audit })));
  const actions = useStore.getState();
  const last = Math.max(1, DATASET.stamps.length - 1);
  const ticks = [...new Set([0, ...DATASET.stamps.map((stamp, i) => stamp.slice(14, 16) === '00' && Number(stamp.slice(11, 13)) % 3 === 0 ? i : -1).filter(i => i >= 0)])];
  const percent = (i: number) => `${i / last * 100}%`;
  const markers = [...new Set(audit.map(event => DATASET.stamps.indexOf(event.cutoff_ts)).filter(i => i >= 0))];
  return <section className="gc-card gc-replay" aria-label="Replay timeline">
    <h2>Replay Timeline</h2><button className="gc-play" aria-label={playing ? 'Pause replay' : 'Play replay'} title={playing ? 'Pause replay' : 'Play replay'} onClick={() => actions.setPlaying(!playing)}>{playing ? <Pause weight="fill" size={19} /> : <Play weight="fill" size={19} />}</button>
    <div className="gc-replay-time">{DATASET.stamps[t].slice(0, 16).replace('T', ' ')}</div>
    <div className="gc-timeline"><div className="gc-track"><div className="gc-available" style={{ width: percent(head) }} /><div className="gc-progress" style={{ width: percent(t) }} />{ticks.map(i => <span key={i} className="gc-time-dot" style={{ left: percent(i) }} />)}{markers.map(i => <i key={i} className="gc-audit-marker" style={{ left: percent(i) }} title={`Decision at ${fmtTime(DATASET.stamps[i])}`} />)}</div><input id="gc-replay-slider" type="range" min={0} max={last} step={1} value={t} aria-label="Replay snapshot" aria-valuetext={`${fmtDateTime(DATASET.stamps[t])}, ${viewMode}`} onChange={e => { actions.setPlaying(false); actions.seek(Math.min(head, Number(e.target.value))); }} /><div className="gc-time-labels">{ticks.map(i => <span key={i} style={{ left: percent(i) }}>{fmtTime(DATASET.stamps[i])}</span>)}</div></div>
    <select value={speed} aria-label="Replay speed" title="1× = one snapshot per second, not wall-clock time" onChange={e => actions.setSpeed(Number(e.target.value) as Speed)}><option value={1}>1×</option><option value={4}>4×</option><option value={12}>12×</option></select>
    <button className="gc-button" aria-pressed={viewMode === 'LATEST'} onClick={actions.goLatest}>Latest</button>
  </section>;
}

export function NetworkConsole() {
  const snap = useSnapshot();
  const item = useSelected();
  const { selectedHex, scenarioId, online, t, head, auditCount } = useStore(useShallow(s => ({ selectedHex: s.selectedHex, scenarioId: s.scenarioId, online: s.online, t: s.t, head: s.head, auditCount: s.audit.length })));
  const [nav, setNav] = useState<'map' | 'history'>('map');
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const settings = useRef<HTMLDetailsElement>(null);
  const network = useMemo(() => networkAt(DATASET, snap.envelope.cutoff_ts), [snap.envelope.cutoff_ts]);
  useEffect(() => setSelectedEdge(null), [snap.envelope.snapshot_id, selectedHex]);
  // Map view: map + detail. Recommendations/History view: queue (or decision history) + the same detail panel.
  const view = nav === 'history' ? 'queue' : 'map';
  // Wide screens put the queue left of the map; narrow screens keep it as a panel tab.
  const narrow = useMediaQuery('(max-width:1199px)');
  const threeCol = view === 'map' && !narrow;
  // The target may only mount after the view switch, so focus on the next frame.
  const focus = (id: string) => requestAnimationFrame(() => { const el = document.getElementById(id); el?.scrollIntoView({ block: 'nearest' }); el?.focus({ preventScroll: true }); });
  const openPage = (page: 'map' | 'history') => { setNav(page); focus(page === 'map' ? 'gc-map-region' : 'gc-queue'); };
  // M / H switch pages, except while typing or inside a dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      const el = e.target as HTMLElement | null;
      if (el?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], dialog')) return;
      const key = e.key.toLowerCase();
      if (key === 'm') openPage('map');
      else if (key === 'h') openPage('history');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  const connections = <Connections snap={snap} network={network} selectedHex={selectedHex} selectedEdge={selectedEdge} onSelect={id => useStore.getState().select(id)} onEdgeSelect={setSelectedEdge} />;
  const panel = <SelectionPanel item={item} snap={snap} connections={connections} showQueue={view === 'map' && !threeCol} />;
  const grid = useRef<HTMLDivElement>(null);
  const widthDrag = useRef<{ x: number; w: number } | null>(null);
  // Detail panel width in px; null keeps the CSS ratio. Dragging the divider left widens the panel.
  const [panelWidth, setPanelWidth] = useState<number | null>(null);
  // In the 3-column layout the queue and its gap also take width from the map.
  const leftWidth = () => threeCol ? ((grid.current?.firstElementChild as HTMLElement | null)?.offsetWidth ?? 360) + 8 : 0;
  const widthLimits = () => ({ min: 320, max: Math.max(320, (grid.current?.clientWidth ?? 1200) - 8 - 360 - leftWidth()) });
  const panelNow = () => (grid.current?.lastElementChild as HTMLElement | null)?.offsetWidth ?? 480;
  const resizePanel = (next: number) => { const { min, max } = widthLimits(); setPanelWidth(Math.round(Math.min(max, Math.max(min, next)))); };
  // Left queue width in px (3-column layout only); null keeps the CSS clamp. Dragging its divider right widens the queue.
  const queueDrag = useRef<{ x: number; w: number } | null>(null);
  const [queueWidth, setQueueWidth] = useState<number | null>(null);
  const queueNow = () => (grid.current?.firstElementChild as HTMLElement | null)?.offsetWidth ?? 360;
  const queueLimits = () => ({ min: 300, max: Math.max(300, (grid.current?.clientWidth ?? 1200) - 16 - 360 - panelNow()) });
  const resizeQueue = (next: number) => { const { min, max } = queueLimits(); setQueueWidth(Math.round(Math.min(max, Math.max(min, next)))); };
  const gridStyle = {
    ...(panelWidth == null ? {} : { gridTemplateColumns: `${threeCol ? 'var(--gc-queue-col) 8px ' : ''}minmax(0,1fr) 8px ${panelWidth}px` }),
    ...(threeCol && queueWidth != null ? { '--gc-queue-col': `${queueWidth}px` } : {}),
  } as CSSProperties;
  const queueDivider = <div className="gc-col-resizer" role="separator" aria-orientation="vertical" aria-label="Resize recommendation queue" tabIndex={0}
    aria-valuemin={queueLimits().min} aria-valuemax={queueLimits().max} aria-valuenow={queueWidth ?? undefined}
    onPointerDown={e => { if (e.button !== 0) return; queueDrag.current = { x: e.clientX, w: queueNow() }; e.currentTarget.setPointerCapture(e.pointerId); }}
    onPointerMove={e => { const d = queueDrag.current; if (d) resizeQueue(d.w + e.clientX - d.x); }}
    onPointerUp={() => { queueDrag.current = null; }} onPointerCancel={() => { queueDrag.current = null; }}
    onDoubleClick={() => setQueueWidth(queueWidth != null && queueWidth >= queueLimits().max - 1 ? null : queueLimits().max)}
    onKeyDown={e => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); resizeQueue(queueNow() + (e.key === 'ArrowRight' ? 32 : -32)); }
      else if (e.key === 'Home') { e.preventDefault(); setQueueWidth(null); }
      else if (e.key === 'End') { e.preventDefault(); resizeQueue(queueLimits().max); }
    }} />;
  const divider = <div className="gc-col-resizer" role="separator" aria-orientation="vertical" aria-label="Resize detail panel" tabIndex={0}
    aria-valuemin={widthLimits().min} aria-valuemax={widthLimits().max} aria-valuenow={panelWidth ?? undefined}
    onPointerDown={e => { if (e.button !== 0) return; widthDrag.current = { x: e.clientX, w: panelNow() }; e.currentTarget.setPointerCapture(e.pointerId); }}
    onPointerMove={e => { const d = widthDrag.current; if (d) resizePanel(d.w + d.x - e.clientX); }}
    onPointerUp={() => { widthDrag.current = null; }} onPointerCancel={() => { widthDrag.current = null; }}
    onDoubleClick={() => setPanelWidth(panelWidth != null && panelWidth >= widthLimits().max - 1 ? null : widthLimits().max)}
    onKeyDown={e => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); resizePanel(panelNow() + (e.key === 'ArrowLeft' ? 32 : -32)); }
      else if (e.key === 'Home') { e.preventDefault(); setPanelWidth(null); }
      else if (e.key === 'End') { e.preventDefault(); resizePanel(widthLimits().max); }
    }} />;
  return <div className="gc-shell">
    <header className="gc-header"><a className="gc-brand" href="#gc-map-region" onClick={() => setNav('map')}><span className="gc-brand-mark"><Cube size={30} weight="duotone" /></span><div><strong>Graph Surge</strong><small>Network-aware surge recommendations</small></div></a>
      <nav className="gc-nav" aria-label="Console navigation">{NAV_PAGES.map(({ id, label, key, Icon }) => <button key={id} className={nav === id ? 'is-active' : ''} aria-current={nav === id ? 'page' : undefined} title={`${label} (${key})`} aria-keyshortcuts={key} onClick={() => openPage(id)}><Icon size={17} weight={nav === id ? 'fill' : 'regular'} />{label}{id === 'history' && auditCount > 0 && <span key={auditCount} className="gc-nav-badge" aria-label={`${auditCount} decision events`}>{auditCount}</span>}</button>)}</nav>
      <div className="gc-header-context"><div className="gc-region" title={snap.envelope.region_label}>Ho Chi Minh City <CaretDown size={12} /></div><select className="gc-snapshot-picker" value={t} aria-label="Snapshot time" onChange={e => useStore.getState().seek(Number(e.target.value))}>{DATASET.stamps.slice(0, head + 1).map((stamp, index) => <option key={stamp} value={index}>{stamp.slice(0, 16).replace('T', ' ')}</option>)}</select><span className={`gc-online-dot ${online ? '' : 'is-offline'}`} title={online ? 'Connected' : 'Offline'} />
        <details ref={settings} className="gc-settings"><summary><span className="gc-avatar">OP</span><span>Ops User</span><CaretDown size={12} /></summary><div className="gc-settings-menu"><h3><SlidersHorizontal size={17} /> Controls</h3><label>Scenario<select value={scenarioId} onChange={e => useStore.getState().setScenario(e.target.value)}>{SCENARIOS.map(scenario => <option key={scenario.id} value={scenario.id}>{scenario.label}</option>)}</select></label><label className="gc-settings-check"><input type="checkbox" checked={online} onChange={e => useStore.getState().setOnline(e.target.checked)} />Connected</label><button className="gc-button gc-button-small" disabled={head >= DATASET.stamps.length - 1} onClick={() => useStore.getState().publishNext()}>Publish next snapshot</button></div></details>
      </div>
    </header>
    <Banners />
    <main className={`gc-workspace gc-view-${view}`}>{view === 'map'
      ? <div ref={grid} className={`gc-top-grid${threeCol ? ' gc-three-grid' : ''}`} style={gridStyle}>{threeCol && <><RecommendationQueue compact history={false} onHistoryChange={value => { if (value) setNav('history'); }} />{queueDivider}</>}<div className="gc-map-column"><div className="gc-map-region" id="gc-map-region" tabIndex={-1}><MapSlot snap={snap} network={network} selectedHex={selectedHex} selectedEdge={selectedEdge} onSelect={id => useStore.getState().select(id)} onEdgeSelect={setSelectedEdge} /></div>{item && <DsCard item={item} snap={snap} />}</div>{divider}{panel}</div>
      : <div ref={grid} className="gc-top-grid gc-queue-grid" style={gridStyle}><RecommendationQueue history={nav === 'history'} onHistoryChange={value => setNav(value ? 'history' : 'map')} />{divider}{panel}</div>}</main>
    <ConsoleReplay />
    <span className="gc-sr-only" role="status">{snap.items.length} recommendations at {fmtTime(snap.envelope.cutoff_ts)}.</span>
  </div>;
}
