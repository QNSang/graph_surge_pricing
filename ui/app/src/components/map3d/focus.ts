/** Explicit "fly to this hex" requests from the Recommendation Queue. Map clicks, layer toggles and replay
 * frames never emit here, so the camera only moves when the operator asks for it. */
const bus = new EventTarget();

export function requestMapFocus(hexId: string): void {
  bus.dispatchEvent(new CustomEvent<string>('focus', { detail: hexId }));
}

export function onMapFocus(listener: (hexId: string) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<string>).detail);
  bus.addEventListener('focus', handler);
  return () => bus.removeEventListener('focus', handler);
}

export function supportsWebGL2(): boolean {
  try {
    return typeof document !== 'undefined' && !!document.createElement('canvas').getContext('webgl2');
  } catch {
    return false;
  }
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}
