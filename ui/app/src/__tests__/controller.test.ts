import { describe, expect, it } from "vitest";
import { runController } from "../adapters/demo/controller";
import { DEMO_POLICY } from "../adapters/demo/policy";

const run = (dsLocal: number, dsGraph: number, bid = 1.3, policy = DEMO_POLICY) =>
  runController({ dsLocal, dsGraph, bid, support: 50 }, policy);

describe("demo controller, Technical Report §10-11", () => {
  it("§11.1: L=2.0, G=1.6, bid 1.30 -> 1.38", () => {
    const o = run(2.0, 1.6);
    expect(o.trace.pressure).toBeCloseTo(1 / 3, 6);
    expect(o.trace.revision).toBeCloseTo(-0.2, 6);
    expect(o.trace.a_P).toBeCloseTo(0.14, 6);
    expect(o.trace.a_R).toBeCloseTo(-0.06, 6);
    expect(o.delta_requested).toBeCloseTo(0.08, 6);
    expect(o.s_final).toBe(1.38);
    expect(o.delta_applied).toBe(0.08);
    expect(o.status).toBe("INCREASE");
  });

  it("FE-14: requested +0.40 clipped by price cap 1.50", () => {
    const o = run(1.4, 2.4, 1.3, { ...DEMO_POLICY, price_max: 1.5 });
    expect(o.delta_requested).toBeCloseTo(0.4, 6);
    expect(o.s_final).toBe(1.5);
    expect(o.delta_applied).toBe(0.2);
    expect(o.trace.price_cap_hit).toBe(true);
    expect(o.trace.cap_stage).toBe("PRICE_CAP");
    expect(o.reasons).toContain("GLOBAL_CAP_CLIPPED");
  });

  // Bảng 7 dòng §11, số chép nguyên từ Technical Report: (q_L, q_G, P, R, a_P, a_R, delta requested).
  const table: [number, number, number, number, number, number, number][] = [
    [1.2, 1.6, 0.333333, 0.333333, 0.14, 0.113333, 0.253333],
    [1.6, 1.6, 0.333333, 0, 0.14, 0, 0.14],
    [2.0, 1.6, 0.333333, -0.2, 0.14, -0.06, 0.08],
    [0.8, 1.2, 0, 0.5, 0, 0.18, 0],
    [1.2, 0.8, -0.333333, -0.333333, -0.14, -0.113333, -0.253333],
    [1.4, 2.4, 1.0, 0.714286, 0.54, 0.265714, 0.4],
    [2.0, 1.35, 0.125, -0.325, 0.015, -0.11, 0],
  ];
  it.each(table)("q_L=%s q_G=%s", (L, G, P, R, aP, aR, req) => {
    const o = run(L, G, 1.6);
    expect(o.trace.pressure).toBeCloseTo(P, 5);
    expect(o.trace.revision).toBeCloseTo(R, 5);
    expect(o.trace.a_P).toBeCloseTo(aP, 5);
    expect(o.trace.a_R).toBeCloseTo(aR, 5);
    expect(o.delta_requested).toBeCloseTo(req, 5);
  });

  it("row 4 is dead zone, row 7 is direction blocked", () => {
    expect(run(0.8, 1.2, 1.6).reasons).toContain("PRESSURE_DEADZONE");
    expect(run(2.0, 1.35, 1.6).reasons).toContain("DIRECTION_BLOCKED");
    expect(run(2.0, 1.35, 1.6).status).toBe("HOLD");
  });

  it("missing graph and invalid bidding go to REVIEW without numbers", () => {
    const g = runController({ dsLocal: 1.2, dsGraph: null, bid: 1.3, support: 50 }, DEMO_POLICY);
    expect(g.status).toBe("REVIEW");
    expect(g.s_final).toBeNull();
    const b = runController({ dsLocal: 1.2, dsGraph: 1.6, bid: null, support: 50 }, DEMO_POLICY);
    expect(b.reasons).toEqual(["INVALID_BIDDING"]);
  });

  it("low support keeps computed values but blocks", () => {
    const o = runController({ dsLocal: 2.0, dsGraph: 1.6, bid: 1.3, support: 2 }, DEMO_POLICY);
    expect(o.status).toBe("REVIEW");
    expect(o.reasons[0]).toBe("LOW_SUPPORT");
    expect(o.s_final).toBe(1.38);
  });
});
