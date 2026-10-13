import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowsIn, ArrowUpRight, Crosshair, Minus, Plus, Stack } from '@phosphor-icons/react';
import type { HexSnapshot, Snapshot } from '../../domain/types';
import { DATASET } from '../../state/store';
import { DEMAND_MAX, DS_SCALE, SUPPLY_MAX, deltaColor, dsColor, seqColor } from '../map/scales';
import { ACTIONS, ACTION_COLORS, OD_COLORS, curvedEdge, displayNumber, displaySurge, geographicBounds, mercator, visibleEdges, type NetworkData, type NetworkEdge, type NetworkMode, type Point } from './network';
import { SELECTED_OUTLINE } from '../map3d/palette';

interface Props {
  snap: Snapshot;
  network: NetworkData;
  selectedHex: string | null;
  selectedEdge: string | null;
  onSelect: (id: string) => void;
  onEdgeSelect: (id: string | null) => void;
}
const MODES: { id: NetworkMode; label: string }[] = [
  { id: 'recommendation', label: 'Recommendation' }, { id: 'delta', label: 'Surge Delta' },
  { id: 'ds', label: 'Demand / Supply' }, { id: 'base', label: 'Base Surge' },
];

/** SVG renderer retained deliberately: no new install is needed to run the approved visual design.
 * Geography and visible raster tiles share Web Mercator. Curved edges use actual OD records.
 * This is not a claim that deck.gl has been installed. */
/** Max zoom relative to the fit-all view. */
const MAX_ZOOM = 24;
// Esri World Topo: light keyless basemap with soft roads, labels, green areas and blue water.
// Note the {z}/{y}/{x} order of the ArcGIS tile endpoint.
export const DEFAULT_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}';

/** Mix a #rrggbb colour toward white by k (0..1). */
function lighten(hex: string, k: number): string {
  const n = parseInt(hex.slice(1, 7), 16);
  const mix = (c: number) => Math.round(c + (255 - c) * k).toString(16).padStart(2, '0');
  return `#${mix(n >> 16)}${mix((n >> 8) & 255)}${mix(n & 255)}`;
}

export function NetworkMap({ snap, network, selectedHex, selectedEdge, onSelect, onEdgeSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 900, h: 550 });
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const [mode, setMode] = useState<NetworkMode>('recommendation');
  const [showOD, setShowOD] = useState(true);
  const [showAdj, setShowAdj] = useState(false);
  const [showSelected, setShowSelected] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const layers = useRef<HTMLDivElement>(null);
  const [tilesFailed, setTilesFailed] = useState(false);
  const [hoverHex, setHoverHex] = useState<HexSnapshot | null>(null);
  const [hoverEdge, setHoverEdge] = useState<NetworkEdge | null>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const dragged = useRef(false);
  const [panning, setPanning] = useState(false);
  const bounds = useMemo(() => geographicBounds(snap.items.map(i => i.hex)), [snap.envelope.node_mapping_version]);
  const selected = snap.items.find(i => i.hex.id === selectedHex)?.hex.index ?? -1;
  const byIndex = new Map(snap.items.map(item => [item.hex.index, item]));
  const deltaMax = Math.max(0.01, ...snap.items.filter(item => item.proposal.status === 'INCREASE' || item.proposal.status === 'DECREASE').map(item => Math.abs(item.proposal.delta_applied ?? 0)));
  const hexGradId = (item: HexSnapshot) => `gc-hexfill-${item.hex.id}`;
  // With a selected hex only its own incoming/outgoing flows (plus a pinned edge) are drawn.
  const edges = useMemo(() => {
    const all = visibleEdges(network.edges, selected, showSelected, expanded);
    return showSelected && selected >= 0 ? all.filter(e => e.source === selected || e.target === selected || e.id === selectedEdge) : all;
  }, [network, selected, showSelected, expanded, selectedEdge]);
  // Hexes joined to the selected one by a drawn OD edge (same rule as the 3D map).
  const linked = useMemo(() => new Set(selected < 0 ? [] : edges.flatMap(e => (e.source === selected || e.target === selected ? [e.source, e.target] : [])).filter(i => i !== selected)), [edges, selected]);
  const edgeMax = network.edges[0]?.volume || 1;
  const fitScale = Math.min(Math.max(220, size.w - 235) / bounds.span[0], Math.max(180, size.h - 88) / bounds.span[1]);
  const scale = fitScale * view.zoom;
  const origin: Point = [size.w / 2 + Math.min(65, size.w * 0.07) + view.x, size.h / 2 - 5 + view.y];
  const project = (lat: number, lng: number): Point => {
    const [x, y] = mercator(lat, lng);
    return [(x - bounds.center[0]) * scale + origin[0], (y - bounds.center[1]) * scale + origin[1]];
  };
  const centers = new Map(snap.items.map(item => [item.hex.index, project(item.hex.lat, item.hex.lng)]));
  const baseRange = useMemo(() => {
    const values = DATASET.raw.surge.flat().filter(Number.isFinite);
    return { min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 1 };
  }, []);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const update = () => setSize({ w: Math.max(280, element.clientWidth), h: Math.max(280, element.clientHeight) });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => { setHoverHex(null); setHoverEdge(null); }, [snap.envelope.snapshot_id]);

  useEffect(() => {
    if (!layersOpen) return;
    const outside = (event: PointerEvent) => { if (!layers.current?.contains(event.target as Node)) setLayersOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setLayersOpen(false); };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [layersOpen]);

  function zoom(factor: number) {
    setView(v => ({ ...v, zoom: Math.max(0.6, Math.min(MAX_ZOOM, v.zoom * factor)) }));
  }
  useEffect(() => {
    const element = svg.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      setView(v => ({ ...v, zoom: Math.max(0.6, Math.min(MAX_ZOOM, v.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12))) }));
    };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, []);

  const tileTemplate = import.meta.env.VITE_BASEMAP_TILE_URL || DEFAULT_TILES;
  const useTiles = import.meta.env.VITE_BASEMAP_PROVIDER !== 'none';
  const tiles = useMemo(() => {
    if (!useTiles) return [];
    // Pick the tile level for the device pixel ratio and round instead of floor, so tiles are never upscaled ~2x (blurry).
    const dpr = typeof window === 'undefined' ? 1 : Math.min(2, window.devicePixelRatio || 1);
    const z = Math.max(0, Math.min(19, Math.round(Math.log2(scale * dpr / 256))));
    const count = 2 ** z, tileSize = scale / count;
    const xmin = Math.floor((bounds.center[0] - origin[0] / scale) * count);
    const xmax = Math.floor((bounds.center[0] + (size.w - origin[0]) / scale) * count);
    const ymin = Math.max(0, Math.floor((bounds.center[1] - origin[1] / scale) * count));
    const ymax = Math.min(count - 1, Math.floor((bounds.center[1] + (size.h - origin[1]) / scale) * count));
    const out: { id: string; href: string; x: number; y: number; size: number }[] = [];
    for (let x = xmin; x <= xmax; x++) for (let y = ymin; y <= ymax; y++) {
      const wrapped = ((x % count) + count) % count;
      out.push({ id: `${z}/${x}/${y}`, href: tileTemplate.replace('{z}', String(z)).replace('{x}', String(wrapped)).replace('{y}', String(y)), x: (x / count - bounds.center[0]) * scale + origin[0], y: (y / count - bounds.center[1]) * scale + origin[1], size: tileSize + 0.4 });
    }
    // Only visible tiles, no offline download/prefetch across the dataset.
    return out.slice(0, 64);
  }, [scale, origin[0], origin[1], size.w, size.h, bounds, tileTemplate, useTiles]);

  // Recommendation strength: sqrt of |Δ| over the ±0.40 display scale, so small moves stay visible but lighter.
  // |Δ| scaled 0..1 against the largest move in this snapshot, so the full light-to-dark range is always used.
  function deltaLevel(item: HexSnapshot): number | null {
    const p = item.proposal;
    if ((p.status !== 'INCREASE' && p.status !== 'DECREASE') || p.delta_applied == null) return null;
    return Math.min(1, Math.abs(p.delta_applied) / deltaMax);
  }
  // Hex colour: the action colour mixed toward white for small moves, full colour for the largest move.
  function hexColor(item: HexSnapshot): string {
    const t = deltaLevel(item);
    return t == null ? ACTION_COLORS[item.proposal.status] : lighten(ACTION_COLORS[item.proposal.status], 0.82 * (1 - t));
  }
  function strength(item: HexSnapshot): number {
    const t = deltaLevel(item);
    if (t != null) return 0.45 + 0.5 * t;
    return item.proposal.status === 'HOLD' ? 0.3 : 0.6;
  }
  function fill(item: HexSnapshot): string {
    if (mode === 'recommendation') return `url(#${hexGradId(item)})`;
    if (mode === 'delta') return item.proposal.delta_applied == null ? 'url(#gc-missing)' : deltaColor(item.proposal.delta_applied);
    if (mode === 'ds') return item.market.observed_ratio.value == null ? 'url(#gc-missing)' : dsColor(item.market.observed_ratio.value);
    if (mode === 'base') return item.market.bidding.value == null ? 'url(#gc-missing)' : seqColor(Math.max(0, item.market.bidding.value - baseRange.min), Math.max(0.01, baseRange.max - baseRange.min));
    const v = mode === 'demand' ? item.market.demand.value : item.market.effective_supply.value;
    return v == null ? 'url(#gc-missing)' : seqColor(v, mode === 'demand' ? DEMAND_MAX : SUPPLY_MAX);
  }
  const scaleKm = 5;
  const centerLat = snap.items[0]?.hex.lat ?? 0;
  const kmPixels = scaleKm / (40075.017 * Math.cos(centerLat * Math.PI / 180)) * scale;
  const legend = mode === 'delta' ? 'Surge Δ · −0.40 / 0 / +0.40' : mode === 'ds' ? `D/S · ${DS_SCALE.min}–${DS_SCALE.max}` : mode === 'base' ? `Base bidding · ${displaySurge(baseRange.min)}–${displaySurge(baseRange.max)}` : 'Recommendation';

  return <section ref={container} className="gc-card gc-map" aria-label="Network map">
    <svg ref={svg} className={`gc-map-svg${panning ? ' gc-panning' : ''}`} viewBox={`0 0 ${size.w} ${size.h}`} tabIndex={0} role="group" aria-label={`H3 map, ${snap.items.length} hexes. Drag background to pan; use zoom buttons.`}
      onPointerDown={e => {
        if (e.button !== 0) return;
        dragged.current = false;
        drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
      }}
      onPointerMove={e => {
        const d = drag.current;
        if (!d) return;
        const dx = e.clientX - d.x, dy = e.clientY - d.y;
        // Pan from anywhere, including hexes and edges; a small movement still counts as a click.
        if (!dragged.current && Math.hypot(dx, dy) < 4) return;
        if (!dragged.current) { dragged.current = true; setPanning(true); e.currentTarget.setPointerCapture(e.pointerId); }
        setView(v => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
      }}
      onPointerUp={() => { drag.current = null; setPanning(false); }} onPointerCancel={() => { drag.current = null; setPanning(false); }}
      onClickCapture={e => { if (dragged.current) { e.stopPropagation(); dragged.current = false; } }}
      onKeyDown={e => {
        if (e.target !== e.currentTarget) return;
        if (e.key === '+' || e.key === '=') zoom(1.25);
        if (e.key === '-') zoom(0.8);
        const moves: Record<string, Point> = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] };
        if (moves[e.key]) { e.preventDefault(); const [x, y] = moves[e.key]; setView(v => ({ ...v, x: v.x + x, y: v.y + y })); }
      }}>
      <defs>
        {/* Per-action radial fill: bright core fading to the edge; overall strength comes from |Δ| via fill-opacity. */}
        {mode === 'recommendation' && snap.items.map(item => { const c = hexColor(item); return <radialGradient key={item.hex.id} id={hexGradId(item)} cx="50%" cy="50%" r="60%"><stop offset="0%" stopColor={c} stopOpacity={1} /><stop offset="100%" stopColor={c} stopOpacity={0.45} /></radialGradient>; })}
        <pattern id="gc-grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#ebf0f4" strokeWidth="0.5" /></pattern>
        <pattern id="gc-missing" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="#edf0f4" /><line x1="0" y1="0" x2="0" y2="7" stroke="#788593" strokeWidth="2" /></pattern>
        <filter id="gc-edge-glow" filterUnits="userSpaceOnUse" x={0} y={0} width={size.w} height={size.h}><feGaussianBlur stdDeviation="2.5" /></filter>
        <filter id="gc-glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <rect width={size.w} height={size.h} fill="#f3f6f9" /><rect width={size.w} height={size.h} fill="url(#gc-grid)" />
      <g className="gc-map-tiles" pointerEvents="none">{tiles.map(tile => <image key={tile.id} href={tile.href} x={tile.x} y={tile.y} width={tile.size} height={tile.size} onError={() => setTilesFailed(true)} />)}</g>
      <rect width={size.w} height={size.h} fill="#ffffff" opacity="0.18" pointerEvents="none" />
      {snap.items.map(item => {
        const chosen = item.hex.id === selectedHex;
        const points = item.hex.poly.map(([lat, lng]) => project(lat, lng).join(',')).join(' ');
        return <polygon key={item.hex.id} points={points} data-interactive role="button" tabIndex={0}
          aria-label={`${item.hex.id}, ${item.proposal.status}, base ${displaySurge(item.proposal.s_bid)}, proposed ${displaySurge(item.proposal.s_final)}`} aria-pressed={chosen}
          fill={fill(item)} fillOpacity={chosen ? 0.95 : mode !== 'recommendation' ? 0.85 : strength(item)}
          stroke={chosen ? SELECTED_OUTLINE : mode === 'recommendation' ? hexColor(item) : fill(item)} strokeOpacity={chosen ? 1 : item.proposal.status === 'HOLD' ? 0.7 : 1} strokeWidth={chosen ? 2.2 : 1.1}
          className="gc-hex" onClick={() => onSelect(item.hex.id)}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(item.hex.id); } }}
          onMouseEnter={() => { setHoverHex(item); setHoverEdge(null); }} onMouseLeave={() => setHoverHex(null)} onFocus={() => setHoverHex(item)} onBlur={() => setHoverHex(null)} />;
      })}
      {/* Highlight outlines drawn above all hexes: selected in blue, OD-linked hexes in their own vivid colour. */}
      <g pointerEvents="none">{snap.items.filter(item => item.hex.id === selectedHex || linked.has(item.hex.index)).map(item => {
        const chosen = item.hex.id === selectedHex;
        const points = item.hex.poly.map(([lat, lng]) => project(lat, lng).join(',')).join(' ');
        return <polygon key={item.hex.id} points={points} fill="none" strokeLinejoin="round"
          stroke={chosen ? SELECTED_OUTLINE : ACTION_COLORS[item.proposal.status]} strokeWidth={chosen ? 2.6 : 2.2} />;
      })}</g>
      {showAdj && DATASET.adj.map(([a, b], i) => {
        const source = centers.get(a), target = centers.get(b);
        if (!source || !target) return null;
        return <line key={i} x1={source[0]} y1={source[1]} x2={target[0]} y2={target[1]} stroke="#4d647a" strokeWidth="0.7" opacity={a === selected || b === selected ? 0.5 : 0.12} pointerEvents="none" />;
      })}
      {showOD && edges.map(edge => {
        const source = centers.get(edge.source), target = centers.get(edge.target);
        if (!source || !target) return null;
        const related = showSelected && (edge.source === selected || edge.target === selected);
        const highlighted = selectedEdge === edge.id || hoverEdge?.id === edge.id;
        // With a selected hex: incoming flows teal, outgoing indigo (a pinned unrelated edge stays grey).
        const focus = showSelected && selected >= 0;
        const dimmed = focus && !related && !highlighted;
        // OD edges never take recommendation colours; with no selection they stay neutral slate.
        const color = !focus ? OD_COLORS.other
          : edge.target === selected ? OD_COLORS.incoming : edge.source === selected ? OD_COLORS.outgoing : OD_COLORS.other;
        const width = highlighted ? 3.2 : dimmed ? 1.2 + 0.8 * Math.sqrt(edge.volume / edgeMax) : 1.5 + 1.8 * Math.sqrt(edge.volume / edgeMax);
        const strong = highlighted || related;
        const shape = curvedEdge(source, target);
        return <g key={edge.id} data-interactive role="button" tabIndex={0} aria-label={`OD ${byIndex.get(edge.source)?.hex.id} to ${byIndex.get(edge.target)?.hex.id}, ${displayNumber(edge.volume, 1)} requests hourly average`} aria-pressed={selectedEdge === edge.id}
          className="gc-edge" onMouseEnter={() => { setHoverEdge(edge); setHoverHex(null); }} onMouseLeave={() => setHoverEdge(null)} onFocus={() => setHoverEdge(edge)} onBlur={() => setHoverEdge(null)}
          onClick={() => onEdgeSelect(edge.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onEdgeSelect(edge.id); } }}>
          <path d={shape.path} fill="none" stroke="transparent" strokeWidth="12" />
          {/* Soft coloured glow under the stroke, then the stroke and a filled head. */}
          <path d={shape.path} fill="none" stroke={color} strokeWidth={width + 3.5} strokeLinecap="round" opacity={dimmed ? 0 : strong ? 0.35 : 0.18} filter="url(#gc-edge-glow)" />
          <path d={shape.path} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" opacity={highlighted ? 1 : related ? 0.95 : dimmed ? 0.45 : 0.65} />
          <path d="M-8,-4.5 L2,0 L-8,4.5 L-5.5,0 Z" transform={shape.arrow} fill={color} stroke="#ffffff" strokeWidth="0.8" strokeLinejoin="round" opacity={strong ? 1 : dimmed ? 0.5 : 0.8} />
        </g>;
      })}
      {snap.items.filter(item => item.hex.id === selectedHex || edges.some(e => e.source === item.hex.index || e.target === item.hex.index)).map(item => {
        const c = centers.get(item.hex.index)!;
        return <circle key={item.hex.id} cx={c[0]} cy={c[1]} r={item.hex.id === selectedHex ? 5 : 2.6} fill={ACTION_COLORS[item.proposal.status]} filter="url(#gc-glow)" pointerEvents="none" />;
      })}
    </svg>
    <div ref={layers} className="gc-map-layers">
      <button className="gc-map-layers-toggle" aria-expanded={layersOpen} aria-controls="gc-map-controls" onClick={() => setLayersOpen(open => !open)}>
        <Stack size={16} />{MODES.find(option => option.id === mode)?.label}
      </button>
      {layersOpen && <div id="gc-map-controls" className="gc-map-controls" role="dialog" aria-label="Map layers">
        <h3>View Mode</h3>
        {MODES.map(option => <label key={option.id}><input type="radio" name="gc-map-mode" value={option.id} checked={mode === option.id} onChange={() => setMode(option.id)} />{option.label}</label>)}
        <div className="gc-divider" /><h3>Network</h3>
        {[
          { name: 'OD Flows (Top)', checked: showOD, set: setShowOD },
          { name: 'Selected Network', checked: showSelected, set: setShowSelected },
        ].map(control => <label key={control.name}><input type="checkbox" checked={control.checked} onChange={e => control.set(e.target.checked)} />{control.name}</label>)}
        <details className="gc-map-options"><summary>Technical</summary><label><input type="checkbox" checked={expanded} onChange={e => setExpanded(e.target.checked)} />Show more edges</label><label><input type="checkbox" checked={showAdj} onChange={e => setShowAdj(e.target.checked)} />Adjacency</label><p>With a selected hex, arrows show incoming and outgoing OD flows; otherwise they are neutral slate. Color is not a model effect.</p></details>
      </div>}
    </div>
    <div className="gc-map-zoom">
      <button aria-label="Zoom in" title="Zoom in" onClick={() => zoom(1.25)}><Plus size={21} /></button>
      <button aria-label="Zoom out" title="Zoom out" onClick={() => zoom(0.8)}><Minus size={21} /></button>
      <button aria-label="Fit all hexes" title="Fit all hexes" onClick={() => setView({ zoom: 1, x: 0, y: 0 })}><ArrowsIn size={19} /></button>
      <button aria-label="Center selected hex" title="Center selected hex" disabled={selected < 0} onClick={() => {
        const c = centers.get(selected);
        if (c) setView(v => ({ ...v, x: v.x + size.w / 2 - c[0], y: v.y + size.h / 2 - c[1] }));
      }}><Crosshair size={20} /></button>
    </div>
    {(hoverHex || hoverEdge) && <div className="gc-map-tooltip" role="tooltip">
      {hoverHex ? <><strong>{hoverHex.hex.id}</strong><span style={{ color: ACTION_COLORS[hoverHex.proposal.status] }}>{hoverHex.proposal.status}</span><span>Base {displaySurge(hoverHex.proposal.s_bid)} → {displaySurge(hoverHex.proposal.s_final)}</span><small>{snap.envelope.cutoff_ts.slice(0, 16).replace('T', ' ')}</small></> : hoverEdge ? <><span>From: <strong>{byIndex.get(hoverEdge.source)?.hex.id}</strong></span><span>To: <strong>{byIndex.get(hoverEdge.target)?.hex.id}</strong></span><span className="gc-tooltip-volume"><ArrowUpRight size={13} weight="bold" style={{ color: hoverEdge.target === selected ? OD_COLORS.incoming : hoverEdge.source === selected ? OD_COLORS.outgoing : undefined }} />OD volume: {displayNumber(hoverEdge.volume, 1)} <small>/ h avg</small></span><small>({network.windowLabel})</small></> : null}
    </div>}
    <div className="gc-map-legend">{mode === 'recommendation' ? <>{ACTIONS.map(action => <span key={action}><i style={{ background: ACTION_COLORS[action] }} />{action[0] + action.slice(1).toLowerCase()}</span>)}<span className="gc-legend-strength"><b style={{ background: `linear-gradient(90deg,${lighten(ACTION_COLORS.INCREASE, 0.82)},${ACTION_COLORS.INCREASE})` }} />|Δ| 0 → {deltaMax.toFixed(2)}</span></> : <span>{legend}</span>}</div>
    {showOD && showSelected && selected >= 0 && <div className="gc-od-legend" aria-label="OD flow legend">
      <h4>OD Flow</h4>
      {([['incoming', 'Incoming'], ['outgoing', 'Outgoing']] as const).map(([key, label]) =>
        <span key={key}><svg width="28" height="8" aria-hidden="true"><line x1="1" y1="4" x2="22" y2="4" stroke={OD_COLORS[key]} strokeWidth="2" /><path d="M20,0.5 L27,4 L20,7.5 Z" fill={OD_COLORS[key]} /></svg>{label}</span>)}
    </div>}
    <div className="gc-edge-count">{showOD ? `${edges.length}/${network.edges.length} OD edges` : 'OD hidden'}<small>{network.windowLabel}</small></div>
    {kmPixels > 20 && kmPixels < size.w / 3 && <div className="gc-map-scale" style={{ width: kmPixels }}><span>0</span><span>{scaleKm} km</span></div>}
    <div className="gc-map-attribution">{tilesFailed && <span>Some tiles unavailable · </span>}{!useTiles ? 'Offline geography' : <>Tiles © <a href="https://www.esri.com/" target="_blank" rel="noreferrer">Esri</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap</a> contributors{import.meta.env.VITE_BASEMAP_ATTRIBUTION ? ` · ${import.meta.env.VITE_BASEMAP_ATTRIBUTION}` : ''}</>}</div>
  </section>;
}
