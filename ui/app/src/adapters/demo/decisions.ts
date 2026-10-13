// Decision service giả cho DEMO (spec mục 5.3).
// Không gọi endpoint thực thi. Không bao giờ trả EFFECTIVE vì DEMO không có execution receipt.

import type { Decision, DecisionAction, OperatorStatus } from "../../domain/types";
import type { ServiceMode } from "./scenarios";

export interface DecisionRequest {
  idempotency_key: string;
  proposal_id: string;
  proposal_version: string;
  snapshot_id: string;
  hex_id: string;
  cutoff_ts: string;
  action: DecisionAction;
  requested_surge: string | null;
  reason: string | null;
  policy_version: string;
  metric_id: string;
  model_id: string;
}

export class TimeoutError extends Error {
  constructor(public key: string) {
    super("Hết thời gian chờ phản hồi");
  }
}

export const VERSION_CONFLICT = "Đề xuất đã thay đổi, cần xem lại";

/** Server kiểm lại tại thời điểm gửi: trả mã lỗi hoặc null nếu hợp lệ. */
export type Revalidate = (req: DecisionRequest) => string | null;

export interface BatchItemResult {
  proposal_id: string;
  outcome: "RECORDED" | "FAILED" | "UNKNOWN";
  decision: Decision | null;
  error?: string;
}

const ACTOR = "demo.operator";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface ServiceOptions {
  mode: () => ServiceMode;
  revalidate: Revalidate;
  latencyMs?: number;
  timeoutMs?: number;
}

export class DemoDecisionService {
  private byKey = new Map<string, Promise<Decision>>();
  /** Bản ghi phía server, kể cả khi client đã timeout. */
  private store = new Map<string, Decision>();
  private seq = 0;

  constructor(private opts: ServiceOptions) {}

  private latency() {
    return this.opts.latencyMs ?? 600;
  }

  private record(req: DecisionRequest, status: OperatorStatus, error?: string): Decision {
    const d: Decision = {
      decision_id: `dec-${(++this.seq).toString().padStart(4, "0")}`,
      idempotency_key: req.idempotency_key,
      proposal_id: req.proposal_id,
      proposal_version: req.proposal_version,
      snapshot_id: req.snapshot_id,
      hex_id: req.hex_id,
      cutoff_ts: req.cutoff_ts,
      action: req.action,
      requested_surge: req.requested_surge,
      reason: req.reason,
      status,
      actor: ACTOR,
      accepted_at: status === "FAILED" ? null : new Date().toISOString(),
      error,
      policy_version: req.policy_version,
      metric_id: req.metric_id,
      model_id: req.model_id,
    };
    this.store.set(req.idempotency_key, d);
    return d;
  }

  private decide(req: DecisionRequest): Decision {
    const err = this.opts.revalidate(req);
    if (err) return this.record(req, "FAILED", err);
    if (req.action === "KEEP_BIDDING") return this.record(req, "KEPT_BIDDING");
    if ((req.action === "ACCEPT_PROPOSAL" || req.action === "OVERRIDE_PROPOSAL") && req.requested_surge == null) {
      return this.record(req, "FAILED", "Thiếu giá yêu cầu");
    }
    if (req.action === "OVERRIDE_PROPOSAL" && !req.reason?.trim()) {
      return this.record(req, "FAILED", "Thiếu lý do điều chỉnh");
    }
    return this.record(req, "RECORDED");
  }

  /** Cùng idempotency key luôn trả cùng kết quả: double click không tạo quyết định thứ hai. */
  submit(req: DecisionRequest): Promise<Decision> {
    const existing = this.byKey.get(req.idempotency_key);
    if (existing) return existing;
    const p = (async () => {
      if (this.opts.mode() === "timeout") {
        // Server vẫn nhận và ghi; chỉ phản hồi bị mất.
        await sleep(this.latency());
        this.decide(req);
        await sleep(this.opts.timeoutMs ?? 900);
        throw new TimeoutError(req.idempotency_key);
      }
      await sleep(this.latency());
      return this.decide(req);
    })();
    this.byKey.set(req.idempotency_key, p);
    // Sau timeout, cho phép tra cứu lại bằng lookup thay vì giữ promise lỗi.
    p.catch(() => this.byKey.delete(req.idempotency_key));
    return p;
  }

  /** Tra kết quả theo key trước khi tạo request mới. */
  async lookup(key: string): Promise<Decision | null> {
    await sleep(Math.round(this.latency() / 2));
    return this.store.get(key) ?? null;
  }

  async submitBatch(batchKey: string, reqs: DecisionRequest[]): Promise<BatchItemResult[]> {
    await sleep(this.latency() + 200);
    const partial = this.opts.mode() === "partial";
    return reqs.map((req, i) => {
      const key = `${batchKey}:${req.proposal_id}`;
      const prior = this.store.get(key);
      if (prior) return { proposal_id: req.proposal_id, outcome: prior.status === "FAILED" ? "FAILED" : "RECORDED", decision: prior, error: prior.error };
      const r = { ...req, idempotency_key: key };
      if (partial && i === reqs.length - 1 && reqs.length > 1) {
        this.decide(r);
        return { proposal_id: req.proposal_id, outcome: "UNKNOWN", decision: null, error: "Không nhận được phản hồi cho mục này" };
      }
      if (partial && i % 3 === 1) {
        const d = this.record(r, "FAILED", VERSION_CONFLICT);
        return { proposal_id: req.proposal_id, outcome: "FAILED", decision: d, error: VERSION_CONFLICT };
      }
      const d = this.decide(r);
      return { proposal_id: req.proposal_id, outcome: d.status === "FAILED" ? "FAILED" : "RECORDED", decision: d, error: d.error };
    });
  }

  /** Hủy chỉ khi lệnh đang ở RECORDED; không xóa bản ghi gốc. */
  async cancel(original: Decision, key: string, reason: string): Promise<Decision> {
    await sleep(this.latency());
    const current = this.store.get(original.idempotency_key) ?? original;
    const req: DecisionRequest = {
      idempotency_key: key,
      proposal_id: current.proposal_id,
      proposal_version: current.proposal_version,
      snapshot_id: current.snapshot_id,
      hex_id: current.hex_id,
      cutoff_ts: current.cutoff_ts,
      action: "CANCEL",
      requested_surge: null,
      reason,
      policy_version: current.policy_version,
      metric_id: current.metric_id,
      model_id: current.model_id,
    };
    if (current.status !== "RECORDED") return this.record(req, "FAILED", "Trạng thái hiện tại không cho phép hủy");
    return this.record(req, "CANCELLED");
  }
}
