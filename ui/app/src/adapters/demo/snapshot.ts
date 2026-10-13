// Dựng Snapshot read model (spec mục 6.3) cho một cutoff trong DEMO.
// Một snapshot là nguồn sự thật duy nhất cho map, queue và panel.

import type {
  EligibilityInfo,
  HexSnapshot,
  MetricDefinition,
  Proposal,
  Snapshot,
  ViewMode,
} from "../../domain/types";
import { isKnownReason, reasonCopy } from "../../domain/reasons";
import { DEMO_POLICY, type DemoPolicy } from "./policy";
import { runController, type ControllerOutput } from "./controller";
import { DEMO_MODEL_ID, demoForecast, observedRatio } from "./forecast";
import type { LegacyDataset } from "./legacy";
import type { Scenario } from "./scenarios";

export const SMOOTHED_METRIC: MetricDefinition = {
  id: "smoothed_ratio_demo",
  version: "0.1-demo",
  display_name: "Tỷ lệ cầu/cung làm trơn",
  equation: "(D + 1) / (S_eff + 1)",
  units: "tỷ lệ, không đơn vị",
  zero_supply_policy: "D = S_eff = 0 cho 1.00, đánh dấu support thấp",
  output_space: "exp của log tỷ lệ",
  reference_version: DEMO_POLICY.reference_version,
  horizon_min: 5,
};

export const RAW_METRIC: MetricDefinition = {
  id: "raw_ratio_demo",
  version: "0.1-demo",
  display_name: "Tỷ lệ cầu/cung thô",
  equation: "D / S_eff",
  units: "tỷ lệ, không đơn vị",
  zero_supply_policy: "S_eff = 0 không xác định, mask",
  output_space: "expm1 của log1p tỷ lệ",
  reference_version: "unregistered",
  horizon_min: 5,
};

export interface BuildContext {
  head: number;
  viewMode: ViewMode;
  offline: boolean;
}

const pad = (n: number) => String(n).padStart(2, "0");
const hhmm = (iso: string) => iso.slice(11, 16).replace(":", "");

function addMinutes(iso: string, min: number) {
  // Giữ offset +07:00 khi cộng phút.
  const ms = new Date(iso).getTime() + min * 60_000;
  const local = new Date(ms + 7 * 3_600_000);
  const s = `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())}T${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}:${pad(local.getUTCSeconds())}+07:00`;
  return s;
}

export const forecastStamp = (ds: LegacyDataset, t: number) =>
  t + 1 < ds.stamps.length ? ds.stamps[t + 1] : addMinutes(ds.stamps[t], 5);

/** Hex fixture cố định: hex trung tâm đầu tiên, để mọi kịch bản chỉ cùng một vùng dễ tìm. */
export const featuredIndex = (ds: LegacyDataset) => {
  const i = ds.hexes.findIndex((h) => h.zone === "cbd");
  return i < 0 ? 0 : i;
};

const NULLING_REVIEW = new Set(["INVALID_TARGET_TRANSFORM", "FEATURE_ROUTING_MISMATCH", "INVALID_HORIZON", "NONFINITE_FORECAST"]);

function severityOf(status: Proposal["status"], reasons: string[]) {
  if (status === "REVIEW") return reasons.some((r) => reasonCopy(r).blocking) ? 2 : 1;
  if (status === "INCREASE" || status === "DECREASE") return 1;
  return 0;
}

function eligibilityFor(
  proposal: Proposal,
  ctx: BuildContext,
  t: number,
  contractOk: boolean,
  cutoff: string,
  validatedAt: string,
  policy: DemoPolicy,
): EligibilityInfo {
  const none = { confirm: false, keep_bidding: false, override: false, cancel: false };
  const base = { expires_at: addMinutes(cutoff, policy.ttl_min), validated_at: validatedAt, limits: null };
  const blocked = (state: EligibilityInfo["state"], reason: string): EligibilityInfo => ({
    ...base,
    state,
    blocked_reasons: [reason],
    capabilities: none,
  });

  if (!contractOk) return blocked("BLOCKED", "CONTRACT_MISMATCH");
  if (ctx.offline) return blocked("UNKNOWN", "OFFLINE");
  if (ctx.viewMode === "REPLAY") return blocked("BLOCKED", "REPLAY_READ_ONLY");
  if (t < ctx.head) return blocked("SUPERSEDED", "SUPERSEDED");
  const limits = {
    step: policy.override_step,
    precision: policy.precision,
    min: policy.price_min,
    max: policy.price_max,
    max_deviation: policy.override_max_deviation,
  };
  if (proposal.status === "REVIEW") {
    // REVIEW allows a manual price whenever a base surge exists; contract errors are already blocked above.
    if (proposal.s_bid == null) return blocked("BLOCKED", "REVIEW_BLOCKED");
    return {
      ...base,
      state: "ELIGIBLE",
      blocked_reasons: ["REVIEW_MANUAL_ONLY"],
      capabilities: { confirm: false, keep_bidding: false, override: true, cancel: false },
      limits,
    };
  }
  if (proposal.status === "HOLD") {
    return {
      ...base,
      state: "ELIGIBLE",
      blocked_reasons: ["HOLD_NO_ACTION"],
      capabilities: { confirm: false, keep_bidding: false, override: true, cancel: false },
      limits,
    };
  }
  return {
    ...base,
    state: "ELIGIBLE",
    blocked_reasons: [],
    capabilities: { confirm: true, keep_bidding: true, override: true, cancel: false },
    limits,
  };
}

export function buildSnapshot(ds: LegacyDataset, t: number, scenario: Scenario, ctx: BuildContext): Snapshot {
  const cutoff = ds.stamps[t];
  const fts = forecastStamp(ds, t);
  const generatedAt = addMinutes(cutoff, 0.5);
  const featured = featuredIndex(ds);
  const contractOk = !scenario.contractMismatch;
  const metric = contractOk ? SMOOTHED_METRIC : RAW_METRIC;
  const snapshotId = `snap-${ds.day.replaceAll("-", "")}-${hhmm(cutoff)}-${scenario.id}`;

  const items: HexSnapshot[] = ds.hexes.map((hex, i) => {
    const ov = scenario.override?.(i, featured, t) ?? null;
    const policy: DemoPolicy = ov?.policy ? { ...DEMO_POLICY, ...ov.policy } : DEMO_POLICY;

    const dRaw = ds.raw.D[t]?.[i] ?? null;
    const demand = ov && "demand" in ov ? ov.demand ?? null : dRaw;
    const sEff = ds.raw.S[t]?.[i] ?? null;
    const idle = ds.raw.I[t]?.[i] ?? null;
    const ratio = demand == null ? null : observedRatio(ds, t, i);
    const bidRaw = ds.raw.surge[t]?.[i] ?? null;
    const bid = ov && "bid" in ov ? ov.bid ?? null : bidRaw;
    const support = ov?.support ?? (demand ?? 0) + (sEff ?? 0);

    const fc = demoForecast(ds, t, i);
    let dsLocal: number | null = ov && "dsLocal" in ov ? ov.dsLocal ?? null : fc.local;
    let dsGraph: number | null = ov && "dsGraph" in ov ? ov.dsGraph ?? null : fc.graph;

    let out: ControllerOutput;
    const forced = ov?.forceReview ?? [];
    if (!contractOk) {
      out = { ...runController({ dsLocal: null, dsGraph: null, bid: null, support }, policy), status: "REVIEW", reasons: ["REFERENCE_SCALE_MISMATCH"] };
    } else if (demand == null) {
      out = { ...runController({ dsLocal, dsGraph, bid, support }, policy), status: "REVIEW", reasons: ["MISSING_MARKET_DATA"] };
      out = { ...out, s_final: null, delta_applied: null, delta_requested: null };
    } else {
      out = runController({ dsLocal, dsGraph, bid, support }, policy);
      if (forced.length) {
        const nulling = forced.some((r) => NULLING_REVIEW.has(r) || !isKnownReason(r));
        out = { ...out, status: "REVIEW", reasons: [...forced, ...out.reasons.filter((r) => r !== "PRESSURE_DEADZONE")] };
        if (nulling) out = { ...out, s_final: null, delta_applied: null, delta_requested: null };
      }
    }
    if (forced.some((r) => NULLING_REVIEW.has(r))) {
      dsLocal = null;
      dsGraph = null;
    }

    const bidVersion = `bid-${hhmm(cutoff)}`;
    const proposal: Proposal = {
      proposal_id: `prop-${hex.id.slice(2, 9)}-${ds.day.replaceAll("-", "")}${hhmm(cutoff)}`,
      version: `${bidVersion}.${policy.policy_version}.${scenario.id}`,
      hex_id: hex.id,
      status: out.status,
      s_bid: bid,
      s_final: out.s_final,
      delta_requested: out.delta_requested,
      delta_applied: out.delta_applied,
      reasons: out.reasons,
      severity: severityOf(out.status, out.reasons),
      priority: Math.abs(out.delta_applied ?? 0),
      trace: out.trace,
      policy_version: policy.policy_version,
    };

    const missing = (v: number | null, reason: string) => (v == null ? { value: null, reason } : { value: v });
    const forecastReason = forced.find((r) => NULLING_REVIEW.has(r)) ?? "MISSING_GRAPH_FORECAST";

    return {
      hex,
      market: {
        demand: missing(demand, "MISSING_MARKET_DATA"),
        idle_supply: missing(idle, "MISSING_MARKET_DATA"),
        effective_supply: missing(sEff, "MISSING_MARKET_DATA"),
        observed_ratio: missing(ratio, "MISSING_MARKET_DATA"),
        bidding: { ...missing(bid, "INVALID_BIDDING"), version: bidVersion },
        support,
      },
      forecast: {
        local: contractOk ? missing(dsLocal, forecastReason) : { value: null, reason: "REFERENCE_SCALE_MISMATCH" },
        graph: contractOk ? missing(dsGraph, forecastReason) : { value: null, reason: "REFERENCE_SCALE_MISMATCH" },
        reference: { value: policy.ds_ref },
        metric_id: metric.id,
      },
      proposal,
      eligibility: eligibilityFor(proposal, ctx, t, contractOk, cutoff, generatedAt, policy),
    };
  });

  return {
    envelope: {
      schema_version: "ui-snapshot.v0.2-demo",
      snapshot_id: snapshotId,
      region_id: "hcm-demo-61",
      region_label: "TP.HCM",
      node_mapping_version: "hcm_data_2.hex61",
      cutoff_ts: cutoff,
      forecast_ts: fts,
      generated_at: generatedAt,
      timezone: "Asia/Ho_Chi_Minh",
      data_kind: "SYNTHETIC",
      execution_mode: "DEMO",
    },
    model: {
      demo_model_id: DEMO_MODEL_ID,
      model_version: null,
      forecast_horizon_min: 5,
      window_note: "Heuristic: trung bình trọng số 3 bước + xu hướng + kéo về láng giềng. Không phải W4/W12 của model.",
    },
    metric,
    observation_metric: SMOOTHED_METRIC,
    contract_ok: contractOk,
    contract_issue: contractOk
      ? undefined
      : `Forecast dùng ${RAW_METRIC.id} (${RAW_METRIC.equation}) còn quan sát dùng ${SMOOTHED_METRIC.id} (${SMOOTHED_METRIC.equation}).`,
    t,
    items,
  };
}

/** Thứ tự queue công bố: severity, rồi priority |delta_applied|, rồi hex ID. Không phải xếp hạng lợi nhuận. */
export function queueOrder(a: HexSnapshot, b: HexSnapshot) {
  return (
    b.proposal.severity - a.proposal.severity ||
    b.proposal.priority - a.proposal.priority ||
    a.hex.id.localeCompare(b.hex.id)
  );
}
