import type { DecisionAction, Eligibility, OperatorStatus, Recommendation } from "./types";

export type Tone = "up" | "down" | "neutral" | "review" | "ok" | "focus" | "muted";

export const REC_LABEL: Record<Recommendation, { label: string; tone: Tone }> = {
  INCREASE: { label: "Tăng", tone: "up" },
  DECREASE: { label: "Giảm", tone: "down" },
  HOLD: { label: "Giữ", tone: "neutral" },
  REVIEW: { label: "Cần xem xét", tone: "review" },
};

export const ELIG_LABEL: Record<Eligibility, { label: string; tone: Tone }> = {
  ELIGIBLE: { label: "Đủ điều kiện duyệt demo", tone: "ok" },
  BLOCKED: { label: "Bị chặn", tone: "review" },
  EXPIRED: { label: "Hết hạn", tone: "muted" },
  SUPERSEDED: { label: "Đã bị thay thế", tone: "muted" },
  UNKNOWN: { label: "Chưa xác định", tone: "muted" },
};

export const OP_LABEL: Record<OperatorStatus, { label: string; tone: Tone }> = {
  PENDING: { label: "Chờ xử lý", tone: "muted" },
  SUBMITTING: { label: "Đang gửi", tone: "focus" },
  RECORDED: { label: "Đã ghi nhận demo", tone: "ok" },
  EXECUTING: { label: "Đang thực thi", tone: "focus" },
  EFFECTIVE: { label: "Đã có hiệu lực", tone: "ok" },
  KEPT_BIDDING: { label: "Đã chọn giữ bidding", tone: "neutral" },
  FAILED: { label: "Lỗi", tone: "up" },
  CANCELLED: { label: "Đã hủy", tone: "muted" },
  UNKNOWN: { label: "Chưa xác định kết quả", tone: "review" },
};

export const ACTION_LABEL: Record<DecisionAction, string> = {
  ACCEPT_PROPOSAL: "Xác nhận demo",
  KEEP_BIDDING: "Giữ bidding",
  OVERRIDE_PROPOSAL: "Điều chỉnh thủ công",
  CANCEL: "Hủy lệnh",
};

export const TONE_VAR: Record<Tone, string> = {
  up: "var(--increase)",
  down: "var(--decrease)",
  neutral: "var(--neutral)",
  review: "var(--review)",
  ok: "var(--recorded)",
  focus: "var(--focus)",
  muted: "var(--text-2)",
};
