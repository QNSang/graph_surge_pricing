import { useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import { scenarioById } from "./adapters/demo/scenarios";
import { queueOrder } from "./adapters/demo/snapshot";
import { NetworkConsole } from "./components/console/NetworkConsole";
import { useSnapshot } from "./state/hooks";
import { useStore } from "./state/store";

function usePlayback() {
  const { playing, speed } = useStore(useShallow((s) => ({ playing: s.playing, speed: s.speed })));
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => useStore.getState().tick(), 1000 / speed);
    return () => window.clearInterval(id);
  }, [playing, speed]);
}

/** Kịch bản "stale": backend DEMO phát hành snapshot mới định kỳ để thử luồng đề xuất bị thay thế. */
function useAutoPublish() {
  const scenarioId = useStore((s) => s.scenarioId);
  useEffect(() => {
    const sec = scenarioById(scenarioId).autoAdvanceSec;
    if (!sec) return;
    const id = window.setInterval(() => useStore.getState().publishNext(), sec * 1000);
    return () => window.clearInterval(id);
  }, [scenarioId]);
}

/** Preserve existing initial selection and priority; never choose invented showcase data. */
function useAutoSelect() {
  const snap = useSnapshot();
  const selected = useStore((s) => s.selectedHex);
  useEffect(() => {
    if (selected && snap.items.some((x) => x.hex.id === selected)) return;
    const first = [...snap.items].sort(queueOrder)[0];
    if (first) useStore.getState().select(first.hex.id);
  }, [snap, selected]);
}

export function App() {
  usePlayback();
  useAutoPublish();
  useAutoSelect();
  return <NetworkConsole />;
}
