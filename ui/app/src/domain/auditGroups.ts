import type { AuditEvent } from "./types";

export type AuditGroup = { kind: "single"; event: AuditEvent } | { kind: "batch"; key: string; events: AuditEvent[] };

/**
 * Groups audit events that share a batch_key (one Accept Selected / Accept All action) into one entry,
 * placed where the first of them appears. Events without a batch_key, and batches of one, stay single.
 * Order inside each group and between groups follows the input order.
 */
export function groupAudit(events: AuditEvent[]): AuditGroup[] {
  const out: AuditGroup[] = [];
  const byKey = new Map<string, AuditEvent[]>();
  for (const e of events) {
    if (!e.batch_key) {
      out.push({ kind: "single", event: e });
      continue;
    }
    const list = byKey.get(e.batch_key);
    if (list) list.push(e);
    else {
      const fresh = [e];
      byKey.set(e.batch_key, fresh);
      out.push({ kind: "batch", key: e.batch_key, events: fresh });
    }
  }
  return out.map((g) => (g.kind === "batch" && g.events.length === 1 ? { kind: "single", event: g.events[0] } : g));
}
