import { describe, expect, it } from "vitest";
import raw from "../../../data.json";
import { completedOdHour, loadLegacy, toStamps, type LegacyPayload } from "../adapters/demo/legacy";
import { buildSnapshot, featuredIndex, queueOrder } from "../adapters/demo/snapshot";
import { scenarioById } from "../adapters/demo/scenarios";
import { reasonCopy } from "../domain/reasons";
import { DemoDecisionService, TimeoutError, type DecisionRequest } from "../adapters/demo/decisions";

const ds = loadLegacy(raw as unknown as LegacyPayload);
const T = ds.raw.ts.indexOf("18:00");
const ctx = { head: T, viewMode: "LATEST" as const, offline: false };
const featured = (id: string) => buildSnapshot(ds, T, scenarioById(id), ctx).items[featuredIndex(ds)];

describe("legacy adapter", () => {
  it("00:00 closing the last window belongs to the next day", () => {
    const s = toStamps("2026-01-27", ["23:50", "23:55", "00:00"]);
    expect(s[2]).toBe("2026-01-28T00:00:00+07:00");
    expect(ds.stamps.at(-1)).toBe("2026-01-28T00:00:00+07:00");
    expect(ds.stamps[0]).toBe("2026-01-27T00:05:00+07:00");
  });
  it("OD uses the last completed hour only", () => {
    expect(completedOdHour("2026-01-27T18:30:00+07:00")).toBe(17);
    expect(completedOdHour("2026-01-27T00:30:00+07:00")).toBeNull();
    expect(completedOdHour("2026-01-28T00:00:00+07:00")).toBe(23);
  });
});

describe("reasons", () => {
  it("unknown codes block and keep the raw code", () => {
    const c = reasonCopy("SERVE_DRIFT_UNMAPPED");
    expect(c.blocking).toBe(true);
    expect(c.title).toContain("SERVE_DRIFT_UNMAPPED");
  });
});

describe("snapshot fixtures", () => {
  it("report §11.1 fixture", () => {
    const it = featured("report-11-1");
    expect(it.proposal.s_bid).toBe(1.3);
    expect(it.proposal.s_final).toBe(1.38);
    expect(it.proposal.status).toBe("INCREASE");
    expect(it.eligibility.state).toBe("ELIGIBLE");
  });
  it("cap fixture FE-14", () => {
    const it = featured("cap-clip");
    expect(it.proposal.s_final).toBe(1.5);
    expect(it.proposal.delta_applied).toBe(0.2);
    expect(it.proposal.trace.cap_stage).toBe("PRICE_CAP");
  });
  it("review fixture allows manual price only and nulls forecast", () => {
    const it = featured("review");
    expect(it.proposal.status).toBe("REVIEW");
    expect(it.eligibility.state).toBe("ELIGIBLE");
    expect(it.eligibility.blocked_reasons).toEqual(["REVIEW_MANUAL_ONLY"]);
    expect(it.eligibility.capabilities).toMatchObject({ confirm: false, keep_bidding: false, override: true });
    expect(it.forecast.graph.value).toBeNull();
    expect(it.forecast.graph.reason).toBe("INVALID_TARGET_TRANSFORM");
  });
  it("missing demand shows null, never 0", () => {
    const snap = buildSnapshot(ds, T, scenarioById("review"), ctx);
    const it = snap.items[(featuredIndex(ds) + 23) % 61];
    expect(it.market.demand.value).toBeNull();
    expect(it.market.observed_ratio.value).toBeNull();
    expect(it.proposal.status).toBe("REVIEW");
  });
  it("empty scenario is all HOLD", () => {
    const snap = buildSnapshot(ds, T, scenarioById("empty"), ctx);
    expect(snap.items.every((x) => x.proposal.status === "HOLD")).toBe(true);
  });
  it("replay is read-only; older cutoff in LATEST is superseded", () => {
    expect(buildSnapshot(ds, T - 1, scenarioById("day"), { ...ctx, viewMode: "REPLAY" }).items[0].eligibility.blocked_reasons).toEqual(["REPLAY_READ_ONLY"]);
    expect(buildSnapshot(ds, T - 1, scenarioById("day"), ctx).items[0].eligibility.state).toBe("SUPERSEDED");
  });
  it("contract mismatch blocks everything", () => {
    const snap = buildSnapshot(ds, T, scenarioById("contract"), ctx);
    expect(snap.contract_ok).toBe(false);
    expect(snap.items.every((x) => x.eligibility.blocked_reasons[0] === "CONTRACT_MISMATCH")).toBe(true);
  });
  it("queue puts blocking REVIEW first", () => {
    const snap = buildSnapshot(ds, T, scenarioById("review"), ctx);
    const sorted = [...snap.items].sort(queueOrder);
    expect(sorted[0].proposal.status).toBe("REVIEW");
  });
  it("day scenario has a mix at default head", () => {
    const snap = buildSnapshot(ds, T, scenarioById("day"), ctx);
    const count = (s: string) => snap.items.filter((x) => x.proposal.status === s).length;
    expect(count("INCREASE") + count("DECREASE")).toBeGreaterThan(0);
  });
});

describe("decision service", () => {
  const req = (key: string): DecisionRequest => ({
    idempotency_key: key, proposal_id: "p1", proposal_version: "v1", snapshot_id: "s", hex_id: "h", cutoff_ts: "c",
    action: "ACCEPT_PROPOSAL", requested_surge: "1.38", reason: null, policy_version: "pv", metric_id: "m", model_id: "md",
  });
  it("same idempotency key returns the same decision", async () => {
    const svc = new DemoDecisionService({ mode: () => "normal", revalidate: () => null, latencyMs: 5 });
    const [a, b] = await Promise.all([svc.submit(req("k1")), svc.submit(req("k1"))]);
    expect(a.decision_id).toBe(b.decision_id);
    expect(a.status).toBe("RECORDED");
  });
  it("timeout becomes lookup-able, never EFFECTIVE", async () => {
    const svc = new DemoDecisionService({ mode: () => "timeout", revalidate: () => null, latencyMs: 5, timeoutMs: 5 });
    await expect(svc.submit(req("k2"))).rejects.toBeInstanceOf(TimeoutError);
    const found = await svc.lookup("k2");
    expect(found?.status).toBe("RECORDED");
  });
  it("version conflict fails with the spec message", async () => {
    const svc = new DemoDecisionService({ mode: () => "normal", revalidate: () => "Đề xuất đã thay đổi, cần xem lại", latencyMs: 5 });
    const d = await svc.submit(req("k3"));
    expect(d.status).toBe("FAILED");
    expect(d.error).toBe("Đề xuất đã thay đổi, cần xem lại");
  });
  it("partial batch reports mixed outcomes", async () => {
    const svc = new DemoDecisionService({ mode: () => "partial", revalidate: () => null, latencyMs: 5 });
    const res = await svc.submitBatch("b", ["a", "b", "c", "d"].map((p) => ({ ...req(""), proposal_id: p })));
    expect(res.map((r) => r.outcome)).toEqual(["RECORDED", "FAILED", "RECORDED", "UNKNOWN"]);
  });
});
