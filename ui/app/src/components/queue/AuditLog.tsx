import { CaretRight, ClockCounterClockwise, Stack } from "@phosphor-icons/react";
import { groupAudit } from "../../domain/auditGroups";
import { fmtTime, shortHex } from "../../domain/format";
import { ACTION_LABEL, OP_LABEL } from "../../domain/labels";
import type { AuditEvent, OperatorStatus } from "../../domain/types";
import { DATASET, useStore } from "../../state/store";
import { Chip, EmptyState } from "../ui/primitives";

const zoneOf = new Map(DATASET.hexes.map((h) => [h.id, h.zone_label]));

/** Display only: drops the "demo" markers from ids and labels (the shell already shows the DEMO badge). Full values stay in tooltips. */
const noDemo = (v: string) => v.replace(/\bdemo[./-]|[_-]demo\b|\s+demo(?![./-])\b/gi, "");
const statusText = (st: OperatorStatus) => noDemo(OP_LABEL[st].label);

/** "Xác nhận tăng/giảm" when base and requested surge are both known; otherwise the plain action label. */
function actionText(e: AuditEvent): string {
  const base = e.base_surge;
  const req = e.requested_surge == null ? NaN : Number(e.requested_surge);
  if ((e.action === "ACCEPT_PROPOSAL" || e.action === "OVERRIDE_PROPOSAL") && base != null && Number.isFinite(base) && Number.isFinite(req)) {
    const verb = e.action === "ACCEPT_PROPOSAL" ? "Xác nhận" : "Điều chỉnh";
    return req > base ? `${verb} tăng` : req < base ? `${verb} giảm` : `${verb} giữ`;
  }
  return noDemo(ACTION_LABEL[e.action]);
}

function AuditRow({ e, select, nested = false }: { e: AuditEvent; select: (id: string) => void; nested?: boolean }) {
  return (
    <li className={`flex flex-wrap items-start gap-x-3 gap-y-1 ${nested ? "py-1.5 pl-2 pr-3" : "px-3 py-2"}`}>
      <span className="num w-11 shrink-0 text-ink-2">{fmtTime(e.at)}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="num text-ink hover:underline" title={`${zoneOf.get(e.hex_id) ?? "Vùng"} · ${e.hex_id}`} onClick={() => select(e.hex_id)}>
            {shortHex(e.hex_id)}
          </button>
          <span className="-ml-2 text-ink">: {actionText(e)}</span>
          {e.requested_surge && e.action !== "CANCEL" && (
            <span className="num text-ink">
              {e.base_surge != null && Number.isFinite(e.base_surge) && <>{e.base_surge.toFixed(2)} → </>}
              {Number(e.requested_surge).toFixed(2)}
            </span>
          )}
          <Chip tone={OP_LABEL[e.status].tone}>{statusText(e.status)}</Chip>
        </div>
        <div className="mt-0.5 text-[11px] text-ink-2">
          {!nested && <>cutoff <span className="num">{fmtTime(e.cutoff_ts)}</span> · <span title={e.actor}>{noDemo(e.actor)}</span> · </>}
          <span className="num">{e.decision_id}</span>
          {e.reason && <> · Lý do: {e.reason}</>}
          {e.note && <> · {e.note}</>}
        </div>
        {!nested && (
          <div className="num mt-0.5 truncate text-[10px] text-[#717d90]" title={e.versions}>
            {noDemo(e.versions)}
          </div>
        )}
      </div>
    </li>
  );
}

function BatchGroup({ events, select }: { events: AuditEvent[]; select: (id: string) => void }) {
  const first = events[0];
  const statusCounts = new Map<OperatorStatus, number>();
  for (const e of events) statusCounts.set(e.status, (statusCounts.get(e.status) ?? 0) + 1);
  const cutoffs = new Set(events.map((e) => e.cutoff_ts));
  const versions = new Set(events.map((e) => e.versions));
  return (
    <li className="px-3 py-2">
      <details className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-start gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
          <span className="num w-11 shrink-0 text-ink-2">{fmtTime(first.at)}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <CaretRight size={12} weight="bold" className="text-ink-2 transition-transform group-open:rotate-90" aria-hidden="true" />
              <Stack size={14} className="text-ink-2" aria-hidden="true" />
              <span className="font-semibold text-ink">Xác nhận hàng loạt</span>
              <span className="num text-ink-2">{events.length} hex</span>
              {[...statusCounts].map(([status, n]) => (
                <Chip key={status} tone={OP_LABEL[status].tone}>
                  {statusText(status)} · {n}
                </Chip>
              ))}
            </div>
            <div className="mt-0.5 text-[11px] text-ink-2">
              cutoff <span className="num">{cutoffs.size === 1 ? fmtTime(first.cutoff_ts) : `${cutoffs.size} mốc`}</span> · <span title={first.actor}>{noDemo(first.actor)}</span> · cùng một lần gửi
            </div>
            {versions.size === 1 && (
              <div className="num mt-0.5 truncate text-[10px] text-[#717d90]" title={first.versions}>
                {noDemo(first.versions)}
              </div>
            )}
          </div>
        </summary>
        <ol className="ml-[3.4rem] mt-1.5 divide-y divide-line/50 border-l-2 border-line/70" aria-label={`${events.length} quyết định trong lô`}>
          {events.map((e) => (
            <AuditRow key={e.id} e={e} select={select} nested />
          ))}
        </ol>
      </details>
    </li>
  );
}

/** Nhật ký chỉ thêm: không sửa, không xóa; hủy là một sự kiện mới. Các quyết định gửi cùng một lô được gom lại. */
export function AuditLog() {
  const audit = useStore((s) => s.audit);
  const select = useStore((s) => s.select);
  if (audit.length === 0) {
    return (
      <EmptyState
        icon={<ClockCounterClockwise size={24} />}
        title="Chưa có sự kiện trong phiên"
        body="Mọi xác nhận, giữ bidding, điều chỉnh và hủy trong phiên DEMO sẽ ghi ở đây theo thứ tự, không sửa và không xóa."
      />
    );
  }
  return (
    <ol className="scroll-thin min-h-0 flex-1 divide-y divide-line/60 overflow-y-auto text-xs" aria-label="Nhật ký quyết định">
      {groupAudit([...audit].reverse()).map((g) =>
        g.kind === "single" ? <AuditRow key={g.event.id} e={g.event} select={select} /> : <BatchGroup key={g.key} events={g.events} select={select} />,
      )}
    </ol>
  );
}
