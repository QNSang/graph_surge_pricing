import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import type { HexSnapshot, OperatorStatus } from "../domain/types";
import { decisionKey, isActionable, operatorStatus, snapshotFor, useStore } from "./store";

export function useSnapshot() {
  const ctx = useStore(useShallow((s) => ({ scenarioId: s.scenarioId, t: s.t, head: s.head, viewMode: s.viewMode, online: s.online })));
  return useMemo(() => snapshotFor(ctx), [ctx]);
}

export function useSelected(): HexSnapshot | null {
  const snap = useSnapshot();
  const id = useStore((s) => s.selectedHex);
  return useMemo(() => snap.items.find((x) => x.hex.id === id) ?? null, [snap, id]);
}

export function useOpStatus(item: HexSnapshot | null): OperatorStatus {
  return useStore((s) => (item ? operatorStatus(s, item) : "PENDING"));
}

/** Đã có quyết định cuối (không phải lỗi hay hủy) thì khóa thao tác mới trên cùng proposal version. */
export const isDecided = (st: OperatorStatus) => st !== "PENDING" && st !== "FAILED" && st !== "CANCELLED";

export function useCounts() {
  const snap = useSnapshot();
  const { decisions, pending } = useStore(useShallow((s) => ({ decisions: s.decisions, pending: s.pending })));
  return useMemo(() => {
    let review = 0;
    let eligiblePending = 0;
    for (const it of snap.items) {
      if (it.proposal.status === "REVIEW") review++;
      const st = operatorStatus({ decisions, pending }, it);
      if (isActionable(it) && it.eligibility.state === "ELIGIBLE" && st === "PENDING") eligiblePending++;
    }
    const recorded = Object.values(decisions).filter((d) => d.status === "RECORDED").length;
    return { review, eligiblePending, recorded };
  }, [snap, decisions, pending]);
}

export { decisionKey };
