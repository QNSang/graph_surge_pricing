// Read model dành cho UI (frontend spec v0.2, mục 5.1 và 6.3).
// Đây là hợp đồng đề xuất; DEMO adapter dựng nó trong trình duyệt, production sẽ nhận từ backend.

export type DataKind = "SYNTHETIC" | "HISTORICAL" | "LIVE";
export type ViewMode = "REPLAY" | "LATEST";
export type ExecutionMode = "DEMO" | "SHADOW" | "PRODUCTION";

export type Recommendation = "INCREASE" | "DECREASE" | "HOLD" | "REVIEW";
export type Eligibility = "ELIGIBLE" | "BLOCKED" | "EXPIRED" | "SUPERSEDED" | "UNKNOWN";
export type OperatorStatus =
  | "PENDING"
  | "SUBMITTING"
  | "RECORDED"
  | "EXECUTING"
  | "EFFECTIVE"
  | "KEPT_BIDDING"
  | "FAILED"
  | "CANCELLED"
  | "UNKNOWN";

export type DecisionAction = "ACCEPT_PROPOSAL" | "KEEP_BIDDING" | "OVERRIDE_PROPOSAL" | "CANCEL";

/** Giá trị có thể thiếu: null luôn đi kèm lý do, không bao giờ thay bằng 0. */
export interface Valued<T = number> {
  value: T | null;
  reason?: string;
}

export interface MetricDefinition {
  id: string;
  version: string;
  display_name: string;
  equation: string;
  units: string;
  zero_supply_policy: string;
  output_space: string;
  reference_version: string;
  horizon_min: number;
}

export interface Envelope {
  schema_version: string;
  snapshot_id: string;
  region_id: string;
  region_label: string;
  node_mapping_version: string;
  cutoff_ts: string;
  forecast_ts: string;
  generated_at: string;
  timezone: string;
  data_kind: DataKind;
  execution_mode: ExecutionMode;
}

export interface ModelEvidence {
  demo_model_id: string;
  model_version: string | null;
  forecast_horizon_min: number;
  window_note: string;
}

export interface Hex {
  id: string;
  index: number;
  zone: string;
  zone_label: string;
  ring: number;
  lat: number;
  lng: number;
  poly: [number, number][];
}

export interface Market {
  demand: Valued;
  idle_supply: Valued;
  effective_supply: Valued;
  observed_ratio: Valued;
  bidding: Valued & { version: string };
  support: number;
}

export interface Forecast {
  local: Valued;
  graph: Valued;
  reference: Valued;
  metric_id: string;
}

export type CapStage = "NONE" | "REQUESTED_CAP" | "PRICE_CAP";

export interface ControllerTrace {
  pressure: number | null;
  revision: number | null;
  pressure_dz: number | null;
  revision_dz: number | null;
  a_P: number | null;
  a_R: number | null;
  a: number | null;
  direction_gate: "PASS" | "BLOCKED" | "DEADZONE" | null;
  requested_cap_hit: boolean;
  price_cap_hit: boolean;
  cap_stage: CapStage;
}

export interface Proposal {
  proposal_id: string;
  version: string;
  hex_id: string;
  status: Recommendation;
  s_bid: number | null;
  s_final: number | null;
  delta_requested: number | null;
  delta_applied: number | null;
  reasons: string[];
  severity: number;
  priority: number;
  trace: ControllerTrace;
  policy_version: string;
}

export interface Limits {
  step: number;
  precision: number;
  min: number;
  max: number;
  max_deviation: number;
}

export interface EligibilityInfo {
  state: Eligibility;
  blocked_reasons: string[];
  expires_at: string | null;
  validated_at: string;
  capabilities: { confirm: boolean; keep_bidding: boolean; override: boolean; cancel: boolean };
  limits: Limits | null;
}

export interface HexSnapshot {
  hex: Hex;
  market: Market;
  forecast: Forecast;
  proposal: Proposal;
  eligibility: EligibilityInfo;
}

export interface Snapshot {
  envelope: Envelope;
  model: ModelEvidence;
  metric: MetricDefinition;
  observation_metric: MetricDefinition;
  contract_ok: boolean;
  contract_issue?: string;
  t: number;
  items: HexSnapshot[];
}

export interface Decision {
  decision_id: string;
  idempotency_key: string;
  proposal_id: string;
  proposal_version: string;
  snapshot_id: string;
  hex_id: string;
  cutoff_ts: string;
  action: DecisionAction;
  requested_surge: string | null;
  reason: string | null;
  status: OperatorStatus;
  actor: string;
  accepted_at: string | null;
  error?: string;
  policy_version: string;
  metric_id: string;
  model_id: string;
}

export interface AuditEvent {
  id: string;
  at: string;
  decision_id: string;
  proposal_id: string;
  hex_id: string;
  action: DecisionAction;
  status: OperatorStatus;
  actor: string;
  requested_surge: string | null;
  reason: string | null;
  cutoff_ts: string;
  note?: string;
  versions: string;
  /** Set when the event came from one batch submit; events sharing it were accepted in one action. */
  batch_key?: string;
  /** Base (bidding) surge of the proposal when the decision was requested; client-side record for display only. */
  base_surge?: number | null;
}
