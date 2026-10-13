import { describe, expect, it } from "vitest";
import { groupAudit } from "../domain/auditGroups";
import type { AuditEvent } from "../domain/types";

const ev = (id: string, batch_key?: string): AuditEvent => ({
  id, at: "2026-01-27T11:52:00Z", decision_id: `dec-${id}`, proposal_id: `p-${id}`, hex_id: `h-${id}`,
  action: "ACCEPT_PROPOSAL", status: "RECORDED", actor: "demo.operator", requested_surge: "1.20", reason: null,
  cutoff_ts: "2026-01-27T18:00:00Z", versions: "m · p · r", ...(batch_key ? { batch_key } : {}),
});

describe("groupAudit", () => {
  it("groups events of one batch where the first appears and keeps singles", () => {
    const g = groupAudit([ev("a"), ev("b", "k1"), ev("c", "k1"), ev("d"), ev("e", "k1")]);
    expect(g.map((x) => (x.kind === "single" ? x.event.id : x.events.map((e) => e.id).join("+")))).toEqual(["a", "b+c+e", "d"]);
  });

  it("does not group by time alone, and a batch of one stays single", () => {
    const g = groupAudit([ev("a"), ev("b"), ev("c", "k2")]);
    expect(g.every((x) => x.kind === "single")).toBe(true);
  });
});
