// Shared state (spec mục 5.2). Một query identity cho mọi view: map, queue và panel cùng đọc
// snapshot dựng từ (scenario, t, head, viewMode, online). Quyết định khóa theo proposal_id + version.

import { create } from "zustand";
import raw from "../../../data.json";
import type { AuditEvent, Decision, DecisionAction, HexSnapshot, OperatorStatus, Snapshot, ViewMode } from "../domain/types";
import { canonical, uid } from "../domain/format";
import { loadLegacy, type LegacyPayload } from "../adapters/demo/legacy";
import { buildSnapshot } from "../adapters/demo/snapshot";
import { scenarioById } from "../adapters/demo/scenarios";
import { DemoDecisionService, TimeoutError, VERSION_CONFLICT, type BatchItemResult, type DecisionRequest } from "../adapters/demo/decisions";
import { DEMO_MODEL_ID } from "../adapters/demo/forecast";

export const DATASET = loadLegacy(raw as unknown as LegacyPayload);
const LAST = DATASET.stamps.length - 1;
const at = (hhmm: string) => {
  const i = DATASET.raw.ts.indexOf(hhmm);
  return i < 0 ? Math.floor(LAST * 0.7) : i;
};
/** Snapshot "mới nhất" của phiên DEMO: chọn 18:00 để có cao điểm chiều. Có thể phát hành thêm bằng nút mô phỏng. */
export const DEFAULT_HEAD = at("18:00");

export type MapLayer = "ds" | "delta" | "demand" | "supply";
export type QueueFilter = "pending" | "eligible" | "review" | "done";
export type Speed = 1 | 4 | 12;

export const decisionKey = (p: { proposal_id: string; version: string }) => `${p.proposal_id}@${p.version}`;

interface Pending {
  idempotency_key: string;
  action: DecisionAction;
  status: "SUBMITTING" | "UNKNOWN";
  requested_surge: string | null;
}

export interface BatchOutcome {
  batch_key: string;
  results: BatchItemResult[];
  at: string;
}

interface State {
  scenarioId: string;
  head: number;
  t: number;
  viewMode: ViewMode;
  online: boolean;
  newSnapshotAt: string | null;

  playing: boolean;
  speed: Speed;
  lookAhead: boolean;

  selectedHex: string | null;
  layer: MapLayer;
  dsMode: "obs" | "fc";
  showOD: boolean;
  showAdj: boolean;
  odExpanded: boolean;

  panelTab: "history" | "detail" | "data";
  chartSub: "surge" | "ds" | "demand" | "supply";
  chartWindow: "60" | "day";

  queueTab: "queue" | "log";
  queueFilter: QueueFilter;
  search: string;
  /** proposal_id -> version đã chọn cho batch. */
  batch: Record<string, string>;
  lastBatch: BatchOutcome | null;

  decisions: Record<string, Decision>;
  pending: Record<string, Pending>;
  audit: AuditEvent[];
}

interface Actions {
  setScenario(id: string): void;
  seek(t: number): void;
  step(dir: 1 | -1): void;
  goLatest(): void;
  setPlaying(p: boolean): void;
  setSpeed(s: Speed): void;
  tick(): void;
  setLookAhead(v: boolean): void;
  publishNext(): void;
  loadLatest(): void;
  setOnline(v: boolean): void;

  select(hexId: string | null): void;
  set<K extends keyof State>(key: K, value: State[K]): void;

  toggleBatch(item: HexSnapshot): void;
  clearBatch(): void;

  submit(item: HexSnapshot, action: DecisionAction, surge: number | null, reason: string | null): Promise<void>;
  cancel(item: HexSnapshot, reason: string): Promise<void>;
  submitBatch(items: HexSnapshot[]): Promise<BatchOutcome>;
}

export type Store = State & Actions;

// ---------- snapshot cache (một identity cho mọi view) ----------
const cache = new Map<string, Snapshot>();
export function snapshotFor(s: Pick<State, "scenarioId" | "t" | "head" | "viewMode" | "online">): Snapshot {
  const k = `${s.scenarioId}|${s.t}|${s.head}|${s.viewMode}|${s.online}`;
  let snap = cache.get(k);
  if (!snap) {
    snap = buildSnapshot(DATASET, s.t, scenarioById(s.scenarioId), { head: s.head, viewMode: s.viewMode, offline: !s.online });
    if (cache.size > 64) cache.delete(cache.keys().next().value as string);
    cache.set(k, snap);
  }
  return snap;
}
export const currentSnapshot = () => snapshotFor(useStore.getState());

// ---------- decision service ----------
const service = new DemoDecisionService({
  mode: () => scenarioById(useStore.getState().scenarioId).service,
  revalidate: (req) => {
    const st = useStore.getState();
    if (!st.online) return "Mất kết nối";
    // Server kiểm lại trên snapshot mới nhất, không tin trạng thái nút ở client.
    const latest = snapshotFor({ ...st, t: st.head, viewMode: "LATEST" });
    const item = latest.items.find((x) => x.proposal.proposal_id === req.proposal_id);
    if (!item || item.proposal.version !== req.proposal_version) return VERSION_CONFLICT;
    if (item.eligibility.state !== "ELIGIBLE") return "Đề xuất không còn đủ điều kiện";
    if (req.action === "ACCEPT_PROPOSAL" && !item.eligibility.capabilities.confirm) return "Không có quyền xác nhận đề xuất này";
    if (req.action === "KEEP_BIDDING" && !item.eligibility.capabilities.keep_bidding) return "Không có quyền giữ bidding cho đề xuất này";
    if (req.action === "OVERRIDE_PROPOSAL") {
      const lim = item.eligibility.limits;
      const v = Number(req.requested_surge);
      if (!lim || !Number.isFinite(v)) return "Giới hạn điều chỉnh chưa được cấp";
      if (v < lim.min || v > lim.max) return "Giá ngoài khoảng cho phép";
      const base = item.proposal.s_bid ?? v;
      if (Math.abs(v - base) > lim.max_deviation + 1e-9) return "Vượt mức sai lệch cho phép";
    }
    return null;
  },
});

/** Base surge per proposal at request time, kept client-side so the audit log can show base → requested. Not sent to the service. */
const baseAtRequest = new Map<string, number | null>();

function requestFor(snap: Snapshot, item: HexSnapshot, action: DecisionAction, surge: string | null, reason: string | null, key: string): DecisionRequest {
  baseAtRequest.set(item.proposal.proposal_id, item.proposal.s_bid);
  return {
    idempotency_key: key,
    proposal_id: item.proposal.proposal_id,
    proposal_version: item.proposal.version,
    snapshot_id: snap.envelope.snapshot_id,
    hex_id: item.hex.id,
    cutoff_ts: snap.envelope.cutoff_ts,
    action,
    requested_surge: surge,
    reason,
    policy_version: item.proposal.policy_version,
    metric_id: snap.metric.id,
    model_id: DEMO_MODEL_ID,
  };
}

function auditFrom(d: Decision, note?: string, batchKey?: string): AuditEvent {
  return {
    id: uid("evt"),
    at: new Date().toISOString(),
    decision_id: d.decision_id,
    proposal_id: d.proposal_id,
    hex_id: d.hex_id,
    action: d.action,
    status: d.status,
    actor: d.actor,
    requested_surge: d.requested_surge,
    reason: d.reason,
    cutoff_ts: d.cutoff_ts,
    note: note ?? d.error,
    versions: `${d.model_id} · ${d.policy_version} · ${d.metric_id}`,
    ...(batchKey ? { batch_key: batchKey } : {}),
    base_surge: baseAtRequest.get(d.proposal_id) ?? null,
  };
}

/** Ý định thao tác: cùng ý định trên cùng proposal version luôn dùng cùng idempotency key. */
const intentKeys = new Map<string, string>();
const intentOf = (k: string, action: DecisionAction, surge: string | null) => `${k}|${action}|${surge ?? "-"}`;

export const useStore = create<Store>()((set, get) => {
  const applyDecision = (k: string, d: Decision, note?: string, batchKey?: string) =>
    set((s) => {
      const pending = { ...s.pending };
      delete pending[k];
      return { decisions: { ...s.decisions, [k]: d }, pending, audit: [...s.audit, auditFrom(d, note, batchKey)] };
    });

  const resolveUnknown = async (k: string, key: string, req: DecisionRequest) => {
    set((s) => ({
      pending: { ...s.pending, [k]: { idempotency_key: key, action: req.action, status: "UNKNOWN", requested_surge: req.requested_surge } },
      audit: [
        ...s.audit,
        {
          id: uid("evt"),
          at: new Date().toISOString(),
          decision_id: "chưa có",
          proposal_id: req.proposal_id,
          hex_id: req.hex_id,
          action: req.action,
          status: "UNKNOWN" as OperatorStatus,
          actor: "demo.operator",
          requested_surge: req.requested_surge,
          reason: req.reason,
          cutoff_ts: req.cutoff_ts,
          note: "Hết thời gian chờ. Đang tra cứu theo idempotency key.",
          versions: `${req.model_id} · ${req.policy_version} · ${req.metric_id}`,
          base_surge: baseAtRequest.get(req.proposal_id) ?? null,
        },
      ],
    }));
    await new Promise((r) => setTimeout(r, 1500));
    const found = await service.lookup(key);
    if (found) applyDecision(k, found, "Kết quả tra cứu theo idempotency key sau timeout");
  };

  return {
    scenarioId: "day",
    head: DEFAULT_HEAD,
    t: DEFAULT_HEAD,
    viewMode: "LATEST",
    online: true,
    newSnapshotAt: null,
    playing: false,
    speed: 1,
    lookAhead: false,
    selectedHex: null,
    layer: "ds",
    dsMode: "obs",
    showOD: true,
    showAdj: false,
    odExpanded: false,
    panelTab: "history",
    chartSub: "surge",
    chartWindow: "60",
    queueTab: "queue",
    queueFilter: "pending",
    search: "",
    batch: {},
    lastBatch: null,
    decisions: {},
    pending: {},
    audit: [],

    setScenario(id) {
      const sc = scenarioById(id);
      intentKeys.clear();
      set({
        scenarioId: sc.id,
        head: DEFAULT_HEAD,
        t: DEFAULT_HEAD,
        viewMode: "LATEST",
        online: !sc.offline,
        newSnapshotAt: null,
        playing: false,
        lookAhead: false,
        batch: {},
        lastBatch: null,
        selectedHex: null,
        queueFilter: "pending",
        search: "",
      });
    },
    seek(t) {
      const { head } = get();
      const nt = Math.max(0, Math.min(head, Math.round(t)));
      set({ t: nt, viewMode: "REPLAY", batch: {}, lookAhead: false });
    },
    step(dir) {
      const { t, head } = get();
      const nt = Math.max(0, Math.min(head, t + dir));
      if (nt !== t || get().viewMode === "LATEST") set({ t: nt, viewMode: "REPLAY", batch: {}, lookAhead: false });
    },
    goLatest() {
      set((s) => ({ t: s.head, viewMode: "LATEST", playing: false, newSnapshotAt: null, batch: {}, lookAhead: false }));
    },
    setPlaying(p) {
      const s = get();
      if (p && s.t >= s.head) {
        set({ t: 0, viewMode: "REPLAY", playing: true, batch: {} });
        return;
      }
      set(p ? { playing: true, viewMode: "REPLAY", batch: {} } : { playing: false });
    },
    setSpeed(speed) {
      set({ speed });
    },
    tick() {
      const s = get();
      if (!s.playing) return;
      if (s.t >= s.head) {
        set({ playing: false });
        return;
      }
      set({ t: s.t + 1, lookAhead: false });
    },
    setLookAhead(v) {
      set({ lookAhead: v, playing: false });
    },
    publishNext() {
      const s = get();
      if (s.head >= LAST) return;
      const head = s.head + 1;
      // Giữ nội dung đang xem; đề xuất cũ thành SUPERSEDED cho tới khi người dùng tải snapshot mới.
      set({ head, newSnapshotAt: s.viewMode === "LATEST" ? DATASET.stamps[head] : s.newSnapshotAt });
    },
    loadLatest() {
      // Refresh nguyên khối; batch selection bị xóa, không chuyển sang proposal ID mới.
      set((s) => ({ t: s.head, viewMode: "LATEST", newSnapshotAt: null, batch: {}, lastBatch: null, lookAhead: false }));
    },
    setOnline(v) {
      set({ online: v, batch: v ? get().batch : {} });
    },

    select(hexId) {
      set({ selectedHex: hexId });
    },
    set(key, value) {
      set({ [key]: value } as Partial<State>);
    },

    toggleBatch(item) {
      if (item.eligibility.state !== "ELIGIBLE" || !item.eligibility.capabilities.confirm) return;
      set((s) => {
        const batch = { ...s.batch };
        if (batch[item.proposal.proposal_id]) delete batch[item.proposal.proposal_id];
        else batch[item.proposal.proposal_id] = item.proposal.version;
        return { batch };
      });
    },
    clearBatch() {
      set({ batch: {} });
    },

    async submit(item, action, surge, reason) {
      const snap = currentSnapshot();
      const k = decisionKey(item.proposal);
      const s = get();
      if (s.decisions[k] && s.decisions[k].status !== "FAILED" && s.decisions[k].status !== "CANCELLED") return;
      const surgeStr = surge == null ? null : canonical(surge, item.eligibility.limits?.precision ?? 2);
      const intent = intentOf(k, action, surgeStr);
      let key = intentKeys.get(intent);
      if (!key) {
        key = uid("idem");
        intentKeys.set(intent, key);
      }
      if (s.pending[k]?.status === "SUBMITTING") return; // khóa double click
      set((st) => ({
        playing: false,
        pending: { ...st.pending, [k]: { idempotency_key: key!, action, status: "SUBMITTING", requested_surge: surgeStr } },
      }));
      const req = requestFor(snap, item, action, surgeStr, reason, key);
      try {
        const d = await service.submit(req);
        applyDecision(k, d);
        if (d.status === "FAILED") intentKeys.delete(intent);
      } catch (e) {
        if (e instanceof TimeoutError) await resolveUnknown(k, key, req);
        else throw e;
      }
    },

    async cancel(item, reason) {
      const k = decisionKey(item.proposal);
      const d = get().decisions[k];
      if (!d || d.status !== "RECORDED") return;
      const res = await service.cancel(d, uid("idem"), reason);
      if (res.status === "CANCELLED") applyDecision(k, res);
      else set((s) => ({ audit: [...s.audit, auditFrom(res)] }));
    },

    async submitBatch(items) {
      const snap = currentSnapshot();
      const batchKey = uid("batch");
      set((s) => {
        const pending = { ...s.pending };
        for (const it of items) {
          pending[decisionKey(it.proposal)] = {
            idempotency_key: `${batchKey}:${it.proposal.proposal_id}`,
            action: "ACCEPT_PROPOSAL",
            status: "SUBMITTING",
            requested_surge: it.proposal.s_final == null ? null : canonical(it.proposal.s_final, 2),
          };
        }
        return { pending, playing: false };
      });
      const reqs = items.map((it) =>
        requestFor(snap, it, "ACCEPT_PROPOSAL", it.proposal.s_final == null ? null : canonical(it.proposal.s_final, it.eligibility.limits?.precision ?? 2), null, ""),
      );
      const results = await service.submitBatch(batchKey, reqs);
      for (const r of results) {
        const it = items.find((x) => x.proposal.proposal_id === r.proposal_id)!;
        const k = decisionKey(it.proposal);
        if (r.decision) applyDecision(k, r.decision, undefined, batchKey);
        else {
          const req = reqs.find((x) => x.proposal_id === r.proposal_id)!;
          void resolveUnknown(k, `${batchKey}:${r.proposal_id}`, { ...req, idempotency_key: `${batchKey}:${r.proposal_id}` });
        }
      }
      const outcome = { batch_key: batchKey, results, at: new Date().toISOString() };
      set({ batch: {}, lastBatch: outcome });
      return outcome;
    },
  };
});

/** Trạng thái vận hành của một proposal: từ decision server, pending client, hoặc PENDING. */
export function operatorStatus(s: Pick<State, "decisions" | "pending">, item: HexSnapshot): OperatorStatus {
  const k = decisionKey(item.proposal);
  const p = s.pending[k];
  if (p) return p.status;
  return s.decisions[k]?.status ?? "PENDING";
}

export const isActionable = (item: HexSnapshot) => item.proposal.status === "INCREASE" || item.proposal.status === "DECREASE";
