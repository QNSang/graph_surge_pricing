// Controller DEMO theo Technical Report mục 10 (Eq. 17-23).
// Chỉ chạy trong adapter DEMO tách biệt; mọi output được gắn nhãn demo.

import type { CapStage, ControllerTrace, Recommendation } from "../../domain/types";
import type { DemoPolicy } from "./policy";

export interface ControllerInput {
  dsLocal: number | null;
  dsGraph: number | null;
  bid: number | null;
  support: number;
}

export interface ControllerOutput {
  status: Recommendation;
  s_final: number | null;
  delta_requested: number | null;
  delta_applied: number | null;
  reasons: string[];
  trace: ControllerTrace;
}

const EMPTY_TRACE: ControllerTrace = {
  pressure: null,
  revision: null,
  pressure_dz: null,
  revision_dz: null,
  a_P: null,
  a_R: null,
  a: null,
  direction_gate: null,
  requested_cap_hit: false,
  price_cap_hit: false,
  cap_stage: "NONE",
};

export const deadZone = (x: number, tau: number) => Math.sign(x) * Math.max(Math.abs(x) - tau, 0);
const clip = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));
const round = (x: number, p: number) => Number(x.toFixed(p));

function review(reasons: string[]): ControllerOutput {
  return { status: "REVIEW", s_final: null, delta_requested: null, delta_applied: null, reasons, trace: { ...EMPTY_TRACE } };
}

export function runController(input: ControllerInput, policy: DemoPolicy): ControllerOutput {
  const { dsLocal, dsGraph, bid, support } = input;

  if (bid == null || !Number.isFinite(bid) || bid < policy.price_min || bid > policy.price_max) {
    return review(["INVALID_BIDDING"]);
  }
  if (dsGraph == null) return review(["MISSING_GRAPH_FORECAST"]);
  if (!Number.isFinite(dsGraph) || dsLocal == null || !Number.isFinite(dsLocal)) {
    return review(["NONFINITE_FORECAST"]);
  }
  if (dsLocal < policy.ds_min) return review(["LOCAL_RATIO_TOO_SMALL"]);

  const pressure = (dsGraph - policy.ds_ref) / policy.ds_ref;
  const revision = (dsGraph - dsLocal) / dsLocal;
  const pDz = deadZone(pressure, policy.tau_press);
  const rDz = deadZone(revision, policy.tau_rev);
  const aP = policy.k_press * pDz;
  const aR = policy.k_rev * rDz;
  const a = aP + aR;

  const reasons: string[] = [];
  let req = 0;
  let gate: ControllerTrace["direction_gate"];
  let reqCapHit = false;
  if (pressure > policy.tau_press) {
    req = clip(a, 0, policy.delta_max);
    gate = a < 0 ? "BLOCKED" : "PASS";
    reqCapHit = a > policy.delta_max;
  } else if (pressure < -policy.tau_press) {
    req = clip(a, -policy.delta_max, 0);
    gate = a > 0 ? "BLOCKED" : "PASS";
    reqCapHit = a < -policy.delta_max;
  } else {
    gate = "DEADZONE";
  }
  if (gate === "DEADZONE") reasons.push("PRESSURE_DEADZONE");
  if (gate === "BLOCKED") reasons.push("DIRECTION_BLOCKED");
  if (reqCapHit) reasons.push("REQUESTED_CAP_CLIPPED");

  const rawFinal = bid + req;
  const sFinal = round(clip(rawFinal, policy.price_min, policy.price_max), policy.precision);
  const priceCapHit = Math.abs(sFinal - round(rawFinal, policy.precision)) > 1e-9;
  if (priceCapHit) reasons.push("GLOBAL_CAP_CLIPPED");
  const applied = round(sFinal - bid, policy.precision);

  const capStage: CapStage = priceCapHit ? "PRICE_CAP" : reqCapHit ? "REQUESTED_CAP" : "NONE";
  const trace: ControllerTrace = {
    pressure,
    revision,
    pressure_dz: pDz,
    revision_dz: rDz,
    a_P: aP,
    a_R: aR,
    a,
    direction_gate: gate,
    requested_cap_hit: reqCapHit,
    price_cap_hit: priceCapHit,
    cap_stage: capStage,
  };

  if (support < policy.low_support_lt) {
    return { status: "REVIEW", s_final: sFinal, delta_requested: req, delta_applied: applied, reasons: ["LOW_SUPPORT", ...reasons], trace };
  }

  const status: Recommendation = applied > 0 ? "INCREASE" : applied < 0 ? "DECREASE" : "HOLD";
  if (status === "HOLD" && reasons.length === 0) reasons.push("PRESSURE_DEADZONE");
  return { status, s_final: sFinal, delta_requested: req, delta_applied: applied, reasons, trace };
}
