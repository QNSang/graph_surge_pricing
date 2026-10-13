import { Component, Suspense, lazy, useState, type ComponentProps, type ReactNode } from 'react';
import { NetworkMap } from '../console/NetworkMap';
import { supportsWebGL2 } from './focus';

// The 3D map pulls in MapLibre + deck.gl; load it only when the 3D view is shown.
const Surge3DMap = lazy(() => import('./Surge3DMap'));

type MapProps = ComponentProps<typeof NetworkMap>;
type Mode = '3d' | '2d';
const STORAGE_KEY = 'gc.mapMode';

function storedMode(): Mode {
  if (!supportsWebGL2()) return '2d';
  try { return window.localStorage.getItem(STORAGE_KEY) === '2d' ? '2d' : '3d'; } catch { return '3d'; }
}

class MapErrorBoundary extends Component<{ onError: (reason: string) => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onError('The 3D map failed to render; showing the 2D map.'); }
  render() { return this.state.failed ? null : this.props.children; }
}

/** 3D map by default where WebGL2 exists; the SVG map is both the 2D mode and the fallback. */
export function MapSlot(props: MapProps) {
  const [mode, setMode] = useState<Mode>(storedMode);
  const [fallback, setFallback] = useState<string | null>(null);
  const choose = (next: Mode) => {
    setMode(next);
    if (next === '3d') setFallback(null);
    try { window.localStorage.setItem(STORAGE_KEY, next); } catch { /* storage unavailable */ }
  };
  const fail = (reason: string) => { setFallback(reason); setMode('2d'); };

  if (mode === '3d' && !fallback) return <MapErrorBoundary onError={fail}>
    <Suspense fallback={<section className="gc-card gc-map gc3d-loading" aria-busy="true"><span>Loading 3D map…</span></section>}>
      <Surge3DMap {...props} onRequest2D={() => choose('2d')} onFallback={fail} />
    </Suspense>
  </MapErrorBoundary>;

  const can3d = supportsWebGL2();
  return <div className="gc3d-slot">
    <NetworkMap {...props} />
    {fallback && <p className="gc3d-fallback" role="status">{fallback}</p>}
    <button type="button" className="gc3d-switch gc3d-glass" disabled={!can3d} aria-label="Switch to 3D map"
      title={can3d ? 'Show extruded 3D columns' : '3D needs WebGL2, which this browser does not provide'} onClick={() => choose('3d')}>3D view</button>
  </div>;
}
