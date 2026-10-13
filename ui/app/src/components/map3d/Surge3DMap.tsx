import { useEffect, useMemo, useRef, useState } from 'react';
import { Map as MapLibreMap, setWorkerUrl, type ExpressionSpecification, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
// MapLibre resolves its worker next to its own module, which breaks once Vite pre-bundles or hashes it.
// Let Vite bundle the worker and hand MapLibre the emitted URL instead.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { AmbientLight, DirectionalLight, LightingEffect, type PickingInfo } from '@deck.gl/core';
import { ArrowArcLeft, ArrowArcRight, ArrowCounterClockwise, ArrowsIn, CaretDown, CaretUp, Crosshair, Minus, Plus } from '@phosphor-icons/react';
import type { Snapshot } from '../../domain/types';
import { ACTIONS, displayDelta, displayNumber, displaySurge, visibleEdges, type NetworkData } from '../console/network';
import { DEFAULT_TILES } from '../console/NetworkMap';
import { ACTION_PALETTE, OD_PALETTE } from './palette';
import { DISPLAY_SCALE, columnHeight, elevationScaleFor, hasInvalidDelta, pixelsPerMetre } from './scale';
import { arcPath, arrowHead, edgeRole, edgeWidthPx, pointAt, type Vec3 } from './odGeometry';
import { buildLayers, hexRows, type ArcRow, type HexRow } from './layers';
import { CAMERA, fitAll, flyToHex } from './camera';
import { onMapFocus, prefersReducedMotion } from './focus';

/** Zoom band over which the basemap sharpens and the hex fills thin out, so close-ups show the streets. */
const CLOSE_ZOOM = { from: 12, to: 14.5 } as const;
const byZoom = (city: number, street: number): ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], CLOSE_ZOOM.from, city, CLOSE_ZOOM.to, street];
const closeFadeAt = (zoom: number) => Math.max(0, Math.min(1, (zoom - CLOSE_ZOOM.from) / (CLOSE_ZOOM.to - CLOSE_ZOOM.from)));

/** Orbit control steps. Rotation is free (any bearing); pitch is capped so columns never go edge-on. */
const ORBIT = { stepDeg: 30, tiltDeg: 10, maxPitch: 65, ms: 400 } as const;

export interface Surge3DMapProps {
  snap: Snapshot;
  network: NetworkData;
  selectedHex: string | null;
  selectedEdge: string | null;
  onSelect: (id: string) => void;
  onEdgeSelect: (id: string | null) => void;
  onRequest2D: () => void;
  onFallback: (reason: string) => void;
}
type Hover = { kind: 'hex' | 'edge'; id: string; x: number; y: number };

setWorkerUrl(maplibreWorkerUrl);

// The intro reveal plays once per session, never again on snapshot changes or 2D/3D toggles.
let introPlayed = false;
const INTRO = { growMs: 500, maxMs: 1200, staggerMs: 50, odFadeMs: 300 } as const;
const HALO_MS = 900;
const PARTICLE_PERIOD_MS = 2200;
const easeOutCubic = (t: number) => 1 - (1 - t) ** 3;

const LIGHTING = new LightingEffect({
  ambient: new AmbientLight({ color: [255, 255, 255], intensity: 1.0 }),
  // Key light from the upper left (north-west) so south/east side faces read darker.
  key: new DirectionalLight({ color: [255, 255, 255], intensity: 1.15, direction: [1.5, -2.5, -3] }),
  fill: new DirectionalLight({ color: [235, 240, 255], intensity: 0.3, direction: [-1, 2, -1] }),
});

function basemapStyle(): StyleSpecification {
  const useTiles = import.meta.env.VITE_BASEMAP_PROVIDER !== 'none';
  const tiles = import.meta.env.VITE_BASEMAP_TILE_URL || DEFAULT_TILES;
  return {
    version: 8,
    sources: useTiles ? { base: { type: 'raster', tiles: [tiles], tileSize: 256, maxzoom: 19 } } : {},
    layers: [
      { id: 'paper', type: 'background', paint: { 'background-color': '#FBFAF7' } },
      // Washed-out ivory basemap at city scale so the columns lead; zooming in to street level brings
      // the map back to near full strength so roads and labels are easy to read under the hexes.
      ...(useTiles ? [{ id: 'base', type: 'raster' as const, source: 'base', paint: {
        'raster-saturation': byZoom(-0.85, -0.25),
        'raster-opacity': byZoom(0.55, 0.95),
        'raster-contrast': byZoom(-0.2, 0.05),
        'raster-brightness-min': byZoom(0.3, 0.05),
      } }] : []),
    ],
  };
}

export default function Surge3DMap(props: Surge3DMapProps) {
  const { snap, network, selectedHex, selectedEdge, onRequest2D } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;
  const [ready, setReady] = useState(false);
  const [zoom, setZoom] = useState(11.5);
  const [view, setView] = useState<{ bearing: number; pitch: number }>({ bearing: CAMERA.bearing, pitch: CAMERA.pitch });
  const [showOD, setShowOD] = useState(true);
  const [animateFlows, setAnimateFlows] = useState(false);
  const [hover, setHover] = useState<Hover | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);
  const [reduced, setReduced] = useState(prefersReducedMotion);
  const [introDone, setIntroDone] = useState(() => introPlayed || prefersReducedMotion());
  const anim = useRef({ introT: 0, halo: null as number | null, particleT: 0 });

  const rows = useMemo(() => hexRows(snap.items), [snap.envelope.node_mapping_version]);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const lookup = useMemo(() => new Map(snap.items.map(item => [item.hex.id, item])), [snap]);
  const byIndex = useMemo(() => new Map(snap.items.map(item => [item.hex.index, item])), [snap]);
  const rowByIndex = useMemo(() => new Map(rows.map(row => [row.index, row])), [rows]);
  const selected = lookup.get(selectedHex ?? '')?.hex.index ?? -1;
  const latitude = rows[0]?.centroid[1] ?? 0;
  const elevationScale = elevationScaleFor(zoom, latitude);
  const edgeMax = network.edges[0]?.volume || 1;

  // Same visibility rule as the 2D map; a pinned edge from the Connections table is always drawn.
  const edges = useMemo(() => {
    const all = visibleEdges(network.edges, selected, true, false);
    const shown = selected >= 0 ? all.filter(e => e.source === selected || e.target === selected || e.id === selectedEdge) : all;
    const pinned = network.edges.find(e => e.id === selectedEdge);
    return pinned && !shown.some(e => e.id === pinned.id) ? [...shown, pinned] : shown;
  }, [network, selected, selectedEdge]);
  const related = useMemo(() => new Set(edges.flatMap(e => (e.source === selected || e.target === selected ? [e.source, e.target] : []))), [edges, selected]);
  const arcs = useMemo<ArcRow[]>(() => {
    const arrowM = 7 / pixelsPerMetre(zoom, latitude);
    return edges.flatMap(edge => {
      const a = rowByIndex.get(edge.source), b = rowByIndex.get(edge.target);
      if (!a || !b) return [];
      const ha = columnHeight(byIndex.get(edge.source)?.proposal ?? { status: 'REVIEW', delta_applied: null }) * elevationScale;
      const hb = columnHeight(byIndex.get(edge.target)?.proposal ?? { status: 'REVIEW', delta_applied: null }) * elevationScale;
      const path = arcPath(a.centroid, b.centroid, ha, hb);
      return [{ edge, role: edgeRole(edge, selected), path, arrow: arrowHead(path, arrowM), width: edgeWidthPx(edge.volume, edgeMax) }];
    });
  }, [edges, rowByIndex, byIndex, elevationScale, selected, edgeMax, zoom, latitude]);

  // Layers are rebuilt from the latest values; animation loops only schedule a frame.
  const maxRing = useMemo(() => Math.max(1, ...rows.map(r => r.ring)), [rows]);
  const stagger = Math.min(INTRO.staggerMs, (INTRO.maxMs - INTRO.growMs) / maxRing);
  const introTotal = Math.min(INTRO.maxMs, maxRing * stagger + INTRO.growMs);
  const renderNow = () => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    const a = anim.current;
    const reveal = introDone ? null : (ring: number) => easeOutCubic(Math.max(0, Math.min(1, (a.introT - ring * stagger) / INTRO.growMs)));
    const odOpacity = introDone ? 1 : Math.max(0, Math.min(1, (a.introT - introTotal * 0.7) / INTRO.odFadeMs));
    const particles: Vec3[] = animateFlows && !reduced && showOD
      ? arcs.flatMap(arc => [0, 1 / 3, 2 / 3].map(o => pointAt(arc.path, (a.particleT + o) % 1)))
      : [];
    overlay.setProps({
      layers: buildLayers({
        rows, lookup, frameKey: snap.envelope.cutoff_ts, selectedHex, hoverHex: hover?.kind === 'hex' ? hover.id : null, related,
        arcs, showOD, odOpacity, selectedEdge, hoverEdge: hover?.kind === 'edge' ? hover.id : null,
        elevationScale, closeFade: closeFadeAt(zoom), reveal, revealKey: introDone ? -1 : a.introT, transitionMs: introDone && !reduced ? 450 : 0,
        halo: a.halo, particles,
      }),
    });
  };
  const renderRef = useRef(renderNow);
  renderRef.current = renderNow;
  const frame = useRef(0);
  const schedule = () => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => { frame.current = 0; renderRef.current(); });
  };

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let map: MapLibreMap;
    try {
      map = new MapLibreMap({
        container: element, style: basemapStyle(), center: rowsRef.current[0]?.centroid ?? [0, 0], zoom: 11,
        pitch: CAMERA.pitch, bearing: CAMERA.bearing, maxPitch: ORBIT.maxPitch, attributionControl: false,
        canvasContextAttributes: { antialias: true },
      });
    } catch {
      callbacks.current.onFallback('WebGL map could not start; showing the 2D map.');
      return;
    }
    // @deck.gl/mapbox 9.4 reads `map.transform` (near/far planes, height); MapLibre 6 moved it to the
    // internal camera. Expose it read-only only when missing, so a deck release that drops the
    // dependency (or a MapLibre that restores it) makes this a no-op. Re-check on any version bump.
    const internal = map as unknown as { transform?: unknown; _camera?: { transform?: unknown } };
    if (internal.transform === undefined && internal._camera?.transform !== undefined) {
      Object.defineProperty(map, 'transform', { configurable: true, get: () => internal._camera?.transform });
    }
    // luma.gl 9.4.2 only resizes its default framebuffer when it resizes the canvas itself. MapLibre
    // owns this canvas, so after a container resize deck kept drawing into the old-size viewport:
    // columns shrank towards the bottom-left and everything above the old height was cut off.
    // Resize that framebuffer to the canvas here. Private luma fields: re-check on any version bump.
    const syncDeckFramebuffer = () => {
      const deck = (map as unknown as { __deck?: { device?: { canvasContext?: { _framebuffer?: { width: number; height: number; resize: (size: [number, number]) => void } | null } } } }).__deck;
      const framebuffer = deck?.device?.canvasContext?._framebuffer;
      const { width, height } = map.getCanvas();
      if (framebuffer && (framebuffer.width !== width || framebuffer.height !== height)) framebuffer.resize([width, height]);
    };
    const overlay = new MapboxOverlay({
      interleaved: true, layers: [], effects: [LIGHTING], pickingRadius: 6,
      onResize: () => { syncDeckFramebuffer(); map.triggerRepaint(); },
      onHover: (info: PickingInfo) => {
        const id = info.layer?.id;
        if ((id === 'hex-columns' || id === 'hex-footprint') && info.object) setHover({ kind: 'hex', id: (info.object as HexRow).id, x: info.x, y: info.y });
        else if ((id === 'od-arcs' || id === 'od-arrows') && info.object) setHover({ kind: 'edge', id: (info.object as ArcRow).edge.id, x: info.x, y: info.y });
        else setHover(null);
      },
      onClick: (info: PickingInfo) => {
        const id = info.layer?.id;
        if ((id === 'hex-columns' || id === 'hex-footprint') && info.object) callbacks.current.onSelect((info.object as HexRow).id);
        else if ((id === 'od-arcs' || id === 'od-arrows') && info.object) callbacks.current.onEdgeSelect((info.object as ArcRow).edge.id);
      },
      getCursor: ({ isHovering, isDragging }) => (isDragging ? 'grabbing' : isHovering ? 'pointer' : 'grab'),
    });
    map.addControl(overlay);
    mapRef.current = map;
    overlayRef.current = overlay;
    if (import.meta.env.DEV) Object.assign(window, { __surgeMap3d: map, __surgeOverlay: overlay });
    const lost = () => callbacks.current.onFallback('The 3D renderer lost its WebGL context; showing the 2D map.');
    map.getCanvas().addEventListener('webglcontextlost', lost);
    map.on('load', () => {
      fitAll(map, rowsRef.current, false, true);
      setZoom(Math.round(map.getZoom() * 20) / 20);
      setReady(true);
    });
    map.on('zoom', () => setZoom(Math.round(map.getZoom() * 20) / 20));
    const syncView = () => setView({ bearing: Math.round(map.getBearing()), pitch: Math.round(map.getPitch()) });
    map.on('rotate', syncView);
    map.on('pitch', syncView);
    map.on('error', event => { if ((event as { sourceId?: string }).sourceId === 'base') setTilesFailed(true); });
    map.on('resize', syncDeckFramebuffer);
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      map.getCanvas().removeEventListener('webglcontextlost', lost);
      cancelAnimationFrame(frame.current);
      frame.current = 0;
      overlayRef.current = null;
      mapRef.current = null;
      map.removeControl(overlay);
      map.remove();
    };
  }, []);

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!query) return;
    const change = () => setReduced(query.matches);
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);

  useEffect(() => { if (ready) schedule(); });

  // ANIM-01: ring-staggered column growth from the centre, then OD fade-in.
  useEffect(() => {
    if (!ready || introDone) return;
    if (reduced) { introPlayed = true; setIntroDone(true); return; }
    const start = performance.now();
    let id = 0;
    const step = (now: number) => {
      anim.current.introT = now - start;
      renderRef.current();
      if (anim.current.introT >= introTotal + INTRO.odFadeMs) { introPlayed = true; setIntroDone(true); return; }
      id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [ready, introDone, reduced, introTotal]);

  // ANIM-03: one-shot halo on selection; no infinite pulse.
  useEffect(() => {
    anim.current.halo = null;
    if (!ready) return;
    if (!selectedHex || reduced) { schedule(); return; }
    const start = performance.now();
    let id = 0;
    const step = (now: number) => {
      const t = (now - start) / HALO_MS;
      anim.current.halo = t >= 1 ? null : easeOutCubic(t);
      renderRef.current();
      if (t < 1) id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(id); anim.current.halo = null; };
  }, [selectedHex, ready, reduced]);

  // ANIM-04: optional direction particles, off by default and under reduced motion.
  useEffect(() => {
    if (!ready || !animateFlows || reduced || !showOD) return;
    let id = 0;
    const step = (now: number) => {
      anim.current.particleT = (now % PARTICLE_PERIOD_MS) / PARTICLE_PERIOD_MS;
      renderRef.current();
      id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [ready, animateFlows, reduced, showOD]);

  // ANIM-05: fly-to only on explicit queue requests.
  useEffect(() => onMapFocus(id => {
    const map = mapRef.current, row = rowsRef.current.find(r => r.id === id);
    if (map && row) flyToHex(map, row, !prefersReducedMotion());
  }), []);

  useEffect(() => { setHover(null); }, [snap.envelope.snapshot_id]);

  const map = () => mapRef.current;
  const selectedRow = rows.find(r => r.id === selectedHex);
  const hoverItem = hover?.kind === 'hex' ? lookup.get(hover.id) : undefined;
  const hoverArc = hover?.kind === 'edge' ? arcs.find(a => a.edge.id === hover.id) : undefined;
  const size = container.current ? { w: container.current.clientWidth, h: container.current.clientHeight } : { w: 900, h: 600 };
  const tipStyle = hover ? { left: Math.min(hover.x + 16, size.w - 290), top: Math.min(hover.y + 16, size.h - 200) } : undefined;
  const useTiles = import.meta.env.VITE_BASEMAP_PROVIDER !== 'none';
  const roleLabel = { incoming: 'Incoming to selected hex', outgoing: 'Outgoing from selected hex', other: 'Network context' } as const;

  const orbit = (deg: number) => { const m = map(); if (m) m.easeTo({ bearing: m.getBearing() + deg, duration: reduced ? 0 : ORBIT.ms }); };
  const tilt = (deg: number) => { const m = map(); if (m) m.easeTo({ pitch: Math.max(0, Math.min(ORBIT.maxPitch, m.getPitch() + deg)), duration: reduced ? 0 : ORBIT.ms }); };

  return <section className="gc-card gc-map gc3d-map" aria-label="3D network map" aria-describedby="gc3d-desc">
    <div ref={container} className="gc3d-canvas" />
    <p id="gc3d-desc" className="gc-sr-only">3D H3 map of {snap.items.length} hexes. Column colour is the recommendation; column height is the size of the proposed surge correction. Use the recommendation queue for keyboard selection.</p>

    <div className="gc3d-toolbar gc3d-glass" role="toolbar" aria-label="Map view controls">
      <button className="is-active" aria-pressed="true" title="3D columns">3D</button>
      <button aria-pressed="false" title="Switch to the flat 2D map" onClick={onRequest2D}>2D</button>
      <span className="gc3d-sep" aria-hidden="true" />
      <button aria-pressed={showOD} className={showOD ? 'is-on' : ''} onClick={() => setShowOD(v => !v)}>OD Flow</button>
      <button aria-pressed={animateFlows && !reduced} className={animateFlows && !reduced ? 'is-on' : ''} disabled={reduced || !showOD}
        title={reduced ? 'Disabled: reduced motion is on' : 'Direction particles (symbolic only)'} onClick={() => setAnimateFlows(v => !v)}>Animate flows</button>
    </div>

    <div className="gc-map-zoom gc3d-glass gc3d-zoom">
      <button aria-label="Zoom in" title="Zoom in" onClick={() => map()?.zoomIn({ duration: reduced ? 0 : 250 })}><Plus size={20} /></button>
      <button aria-label="Zoom out" title="Zoom out" onClick={() => map()?.zoomOut({ duration: reduced ? 0 : 250 })}><Minus size={20} /></button>
      <button aria-label="Fit all hexes" title="Fit all hexes" onClick={() => { const m = map(); if (m) fitAll(m, rows, !reduced); }}><ArrowsIn size={19} /></button>
      <button aria-label="Focus selected hex" title="Focus selected hex" disabled={!selectedRow} onClick={() => { const m = map(); if (m && selectedRow) flyToHex(m, selectedRow, !reduced); }}><Crosshair size={19} /></button>
      <button aria-label="Reset camera" title="Reset camera (default pitch and bearing)" onClick={() => { const m = map(); if (m) fitAll(m, rows, !reduced, true); }}><ArrowCounterClockwise size={19} /></button>
    </div>

    {/* Orbit: rotate around the view centre and tilt. Mouse: right-drag or Ctrl+drag; touch: two fingers. */}
    <div className="gc3d-orbit gc3d-glass" role="group" aria-label="Rotate and tilt">
      <button aria-label="Rotate left" title="Rotate left 30° (or right-drag / Ctrl+drag the map)" onClick={() => orbit(-ORBIT.stepDeg)}><ArrowArcLeft size={18} /></button>
      <button className="gc3d-compass" aria-label={`Bearing ${(((view.bearing % 360) + 360) % 360)}°, face north`} title="Face north" onClick={() => map()?.easeTo({ bearing: 0, duration: reduced ? 0 : ORBIT.ms })}>
        <svg width="18" height="18" viewBox="-9 -9 18 18" aria-hidden="true" style={{ transform: `rotate(${-view.bearing}deg)` }}>
          <path d="M0,-8 L3.2,0 L-3.2,0 Z" fill="#E5484D" /><path d="M0,8 L3.2,0 L-3.2,0 Z" fill="#94A3B8" />
        </svg>
      </button>
      <button aria-label="Rotate right" title="Rotate right 30° (or right-drag / Ctrl+drag the map)" onClick={() => orbit(ORBIT.stepDeg)}><ArrowArcRight size={18} /></button>
      <span className="gc3d-sep" aria-hidden="true" />
      <button aria-label="Tilt up" title="Tilt more (see columns from the side)" disabled={view.pitch >= ORBIT.maxPitch} onClick={() => tilt(ORBIT.tiltDeg)}><CaretUp size={18} /></button>
      <button aria-label="Tilt down" title="Tilt less (towards top-down)" disabled={view.pitch <= 0} onClick={() => tilt(-ORBIT.tiltDeg)}><CaretDown size={18} /></button>
    </div>

    {hover && (hoverItem || hoverArc) && <div className="gc3d-tooltip gc3d-glass" role="tooltip" style={tipStyle}>
      {hoverItem ? (() => {
        const p = hoverItem.proposal;
        const review = p.status === 'REVIEW', invalid = hasInvalidDelta(p);
        return <div className="gc3d-tip">
          <div className="gc3d-tip-head"><i className="gc3d-swatch" style={{ background: ACTION_PALETTE[p.status] }} /><b>{p.status}</b><span className="gc3d-tip-id">{hoverItem.hex.id}</span></div>
          <div className="gc3d-tip-main">{displaySurge(p.s_bid)}{review
            ? <small>needs review · no proposal</small>
            : <> → <strong style={{ color: ACTION_PALETTE[p.status] }}>{displaySurge(p.s_final)}</strong><small>{invalid ? 'Δ n/a' : `Δ ${displayDelta(p.delta_applied)}`}</small></>}</div>
        </div>;
      })() : hoverArc ? <div className="gc3d-tip">
        <div className="gc3d-tip-head"><i className="gc3d-swatch" style={{ background: OD_PALETTE[hoverArc.role] }} /><b>{roleLabel[hoverArc.role]}</b><span className="gc3d-tip-id">{network.windowLabel}</span></div>
        <div className="gc3d-tip-main"><span className="gc3d-tip-id">{byIndex.get(hoverArc.edge.source)?.hex.id ?? '—'} → {byIndex.get(hoverArc.edge.target)?.hex.id ?? '—'}</span></div>
        <div className="gc3d-tip-main"><strong>{displayNumber(hoverArc.edge.volume, 1)}</strong><small>requests/h · hourly avg</small></div>
      </div> : null}
    </div>}

    <div className="gc3d-legend gc3d-glass" aria-label="Map legend">
      <div className="gc3d-legend-row">{ACTIONS.map(action => <span key={action}><i className="gc3d-swatch" style={{ background: ACTION_PALETTE[action] }} />{action[0] + action.slice(1).toLowerCase()}</span>)}</div>
      <div className="gc3d-legend-height" title={`Height = proposed |Δ surge|, 0 → ${DISPLAY_SCALE.deltaMax.toFixed(2)} (scale ${DISPLAY_SCALE.version}). Taller means a stronger proposed correction, not confidence.`}>
        <svg width="24" height="12" viewBox="0 0 24 12" aria-hidden="true">
          {[0.33, 0.66, 1].map((f, i) => <rect key={f} x={1 + i * 8} y={11 - 10 * f} width="6" height={10 * f} rx="1" fill="#AEB7C4" opacity={0.5 + 0.2 * i} />)}
        </svg>
        <span>Height = |Δ surge|</span>
      </div>
      {showOD && <div className="gc3d-legend-row">{selected >= 0
        ? (['incoming', 'outgoing'] as const).map(role => <span key={role}><i className="gc3d-line" style={{ background: OD_PALETTE[role] }} />{role === 'incoming' ? 'Incoming' : 'Outgoing'}</span>)
        : <span><i className="gc3d-line" style={{ background: OD_PALETTE.other }} />OD flow</span>}
        {!edges.length && <small>No OD flow</small>}</div>}
    </div>

    <div className="gc-map-attribution">{tilesFailed && <span>Some tiles unavailable · </span>}{!useTiles ? 'Offline geography' : <>Tiles © <a href="https://www.esri.com/" target="_blank" rel="noreferrer">Esri</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap</a> contributors · <a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>{import.meta.env.VITE_BASEMAP_ATTRIBUTION ? ` · ${import.meta.env.VITE_BASEMAP_ATTRIBUTION}` : ''}</>}</div>
  </section>;
}
