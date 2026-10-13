import { useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { CheckCircle, Funnel, MagnifyingGlass, WarningCircle, X } from "@phosphor-icons/react";
import type { HexSnapshot, OperatorStatus } from "../../domain/types";
import { fmtSigned, fmtSurge, shortHex } from "../../domain/format";
import { OP_LABEL, REC_LABEL, TONE_VAR } from "../../domain/labels";
import { queueOrder } from "../../adapters/demo/snapshot";
import { isDecided, useSnapshot } from "../../state/hooks";
import { isActionable, operatorStatus, useStore, type QueueFilter } from "../../state/store";
import { Button, Chip, EmptyState, Tabs } from "../ui/primitives";
import { AuditLog } from "./AuditLog";
import { BatchReview } from "./BatchReview";

const canBatch = (it: HexSnapshot, op: OperatorStatus) =>
  isActionable(it) && it.eligibility.state === "ELIGIBLE" && it.eligibility.capabilities.confirm && op === "PENDING";

function matches(f: QueueFilter, it: HexSnapshot, op: OperatorStatus) {
  switch (f) {
    case "pending":
      return it.proposal.status !== "HOLD" && !isDecided(op);
    case "eligible":
      return canBatch(it, op);
    case "review":
      return it.proposal.status === "REVIEW";
    case "done":
      return isDecided(op);
  }
}

const FILTERS: { id: QueueFilter; label: string }[] = [
  { id: "pending", label: "Chờ xử lý" },
  { id: "eligible", label: "Đủ điều kiện" },
  { id: "review", label: "Cần xem xét" },
  { id: "done", label: "Đã xử lý" },
];

export function ReviewQueue() {
  const snap = useSnapshot();
  const st = useStore(
    useShallow((s) => ({
      selectedHex: s.selectedHex,
      queueTab: s.queueTab,
      queueFilter: s.queueFilter,
      search: s.search,
      batch: s.batch,
      decisions: s.decisions,
      pending: s.pending,
      auditLen: s.audit.length,
    })),
  );
  const { select, set, toggleBatch, clearBatch } = useStore.getState();
  const [reviewOpen, setReviewOpen] = useState(false);
  const interacting = useRef(false);
  const frozen = useRef<{ snapId: string; filter: QueueFilter; search: string; ids: string[] } | null>(null);

  const ops = useMemo(() => new Map(snap.items.map((it) => [it.hex.id, operatorStatus(st, it)])), [snap, st]);

  const counts = useMemo(() => {
    const c: Record<QueueFilter, number> = { pending: 0, eligible: 0, review: 0, done: 0 };
    for (const it of snap.items) for (const f of FILTERS) if (matches(f.id, it, ops.get(it.hex.id)!)) c[f.id]++;
    return c;
  }, [snap, ops]);

  const q = st.search.trim().toLowerCase();
  const live = useMemo(
    () =>
      snap.items
        .filter((it) => matches(st.queueFilter, it, ops.get(it.hex.id)!))
        .filter((it) => !q || it.hex.id.toLowerCase().includes(q) || it.hex.zone_label.toLowerCase().includes(q) || it.proposal.proposal_id.includes(q))
        .sort(queueOrder),
    [snap, st.queueFilter, ops, q],
  );

  // Không re-sort hay rút dòng khi người dùng đang trỏ/focus trong danh sách; chỉ cập nhật khi rời đi.
  const byId = new Map(snap.items.map((it) => [it.hex.id, it]));
  const f = frozen.current;
  let rows = live;
  if (interacting.current && f && f.snapId === snap.envelope.snapshot_id && f.filter === st.queueFilter && f.search === st.search) {
    rows = f.ids.map((id) => byId.get(id)).filter((x): x is HexSnapshot => !!x);
  } else {
    frozen.current = { snapId: snap.envelope.snapshot_id, filter: st.queueFilter, search: st.search, ids: live.map((x) => x.hex.id) };
  }
  const [, force] = useState(0);
  const setInteract = (v: boolean) => {
    if (interacting.current === v) return;
    interacting.current = v;
    if (!v) force((n) => n + 1);
  };

  const batchItems = snap.items.filter((it) => st.batch[it.proposal.proposal_id] === it.proposal.version);
  const filterLabel = FILTERS.find((x) => x.id === st.queueFilter)!.label;
  const selItem = st.selectedHex ? byId.get(st.selectedHex) ?? null : null;

  // Chọn từ bản đồ thì cuộn dòng tương ứng vào khung nhìn (FE-03).
  useEffect(() => {
    if (!st.selectedHex) return;
    document.getElementById(`qrow-${st.selectedHex}`)?.scrollIntoView({ block: "nearest" });
  }, [st.selectedHex]);

  return (
    <section aria-label="Hàng đợi đề xuất" className="flex h-full min-h-0 flex-col overflow-hidden rounded-[12px] border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <Tabs
          label="Hàng đợi hoặc nhật ký"
          value={st.queueTab}
          onChange={(v) => set("queueTab", v)}
          items={[
            { id: "queue", label: "Hàng đợi", count: counts.pending },
            { id: "log", label: "Nhật ký", count: st.auditLen },
          ]}
        />
        {st.queueTab === "queue" && (
          <>
            <div className="flex items-center gap-1" role="group" aria-label="Bộ lọc">
              <Funnel size={13} className="text-ink-2" aria-hidden />
              {FILTERS.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  aria-pressed={st.queueFilter === x.id}
                  onClick={() => set("queueFilter", x.id)}
                  className={`inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-xs ${
                    st.queueFilter === x.id ? "bg-surface-2 text-ink shadow-[inset_0_0_0_1px_var(--border)]" : "text-ink-2 hover:text-ink"
                  }`}
                >
                  {x.label} <span className="num text-[10px] text-ink-2">{counts[x.id]}</span>
                </button>
              ))}
            </div>
            <label className="relative ml-auto flex items-center">
              <span className="sr-only">Tìm vùng hoặc mã hex</span>
              <MagnifyingGlass size={13} className="pointer-events-none absolute left-2 text-ink-2" />
              <input
                value={st.search}
                onChange={(e) => set("search", e.target.value)}
                placeholder="Tìm vùng, mã hex"
                className="h-7 w-[180px] rounded-[8px] border border-line bg-bg pl-7 pr-2 text-xs text-ink outline-none placeholder:text-[#7e8898] focus:border-focus"
              />
            </label>
          </>
        )}
      </div>

      {st.queueTab === "log" ? (
        <AuditLog />
      ) : (
        <>
          <div
            className="scroll-thin min-h-0 flex-1 overflow-y-auto"
            onPointerEnter={() => setInteract(true)}
            onPointerLeave={() => setInteract(false)}
            onFocus={() => setInteract(true)}
            onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setInteract(false)}
          >
            {selItem && !rows.some((r) => r.hex.id === selItem.hex.id) && (
              <div className="flex items-center gap-2 border-b border-line bg-focus/8 px-3 py-1.5 text-[11px] text-ink-2">
                <span className="inline-block h-3 w-0.5 bg-focus" aria-hidden />
                Vùng đang chọn{" "}
                <span className="text-ink">
                  {selItem.hex.zone_label} <span className="num">{shortHex(selItem.hex.id)}</span>
                </span>{" "}
                ({REC_LABEL[selItem.proposal.status].label}) không thuộc bộ lọc {filterLabel}
                {q ? " hoặc từ khóa tìm" : ""}.
              </div>
            )}
            {rows.length === 0 ? (
              <EmptyState
                icon={st.queueFilter === "review" ? <CheckCircle size={24} /> : <Funnel size={24} />}
                title={q ? `Không có kết quả cho "${st.search}"` : `Không có đề xuất ở mục ${filterLabel}`}
                body={
                  q
                    ? "Thử mã hex khác hoặc xóa từ khóa."
                    : st.queueFilter === "pending"
                      ? "Mọi vùng đang giữ bidding hoặc đã có quyết định."
                      : "Đổi bộ lọc để xem các đề xuất khác."
                }
                action={
                  (q || st.queueFilter !== "pending") && (
                    <Button
                      size="sm"
                      onClick={() => {
                        set("search", "");
                        set("queueFilter", "pending");
                      }}
                    >
                      <X size={12} /> Xóa bộ lọc
                    </Button>
                  )
                }
              />
            ) : (
              <table className="w-full border-collapse text-xs">
                <thead className="sticky top-0 z-[1] bg-surface text-[11px] text-ink-2">
                  <tr className="border-b border-line">
                    <th scope="col" className="w-8 px-3 py-1.5 text-left font-normal">
                      <span className="sr-only">Chọn batch</span>
                    </th>
                    <th scope="col" className="px-1 py-1.5 text-left font-normal">
                      Vùng
                    </th>
                    <th scope="col" className="px-1 py-1.5 text-left font-normal">
                      Đề xuất
                    </th>
                    <th scope="col" className="px-1 py-1.5 text-right font-normal">
                      Bidding → đề xuất
                    </th>
                    <th scope="col" className="px-1 py-1.5 text-right font-normal">
                      Delta
                    </th>
                    <th scope="col" className="px-3 py-1.5 text-right font-normal max-[1279px]:hidden">
                      Trạng thái
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((it) => {
                    const op = ops.get(it.hex.id)!;
                    const sel = it.hex.id === st.selectedHex;
                    const rec = REC_LABEL[it.proposal.status];
                    const checkable = canBatch(it, op);
                    const checked = st.batch[it.proposal.proposal_id] === it.proposal.version;
                    return (
                      <tr
                        key={it.hex.id}
                        id={`qrow-${it.hex.id}`}
                        aria-selected={sel}
                        onClick={() => select(it.hex.id)}
                        className={`cursor-pointer border-b border-line/60 ${sel ? "bg-focus/10 shadow-[inset_3px_0_0_var(--focus)]" : "hover:bg-surface-2/60"}`}
                      >
                        <td className="px-3 py-1.5" onClick={(e) => e.stopPropagation()}>
                          {checkable ? (
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleBatch(it)}
                              aria-label={`Chọn ${it.hex.zone_label} ${shortHex(it.hex.id)} vào batch`}
                              className="size-3.5 accent-[var(--focus)]"
                            />
                          ) : (
                            <span className="block size-3.5" aria-hidden />
                          )}
                        </td>
                        <td className="px-1 py-1.5">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              select(it.hex.id);
                            }}
                            className="text-left outline-none focus-visible:underline"
                            aria-label={`Xem ${it.hex.zone_label} ${shortHex(it.hex.id)}`}
                          >
                            <span className="text-ink">{it.hex.zone_label}</span> <span className="num text-[11px] text-ink-2">{shortHex(it.hex.id)}</span>
                          </button>
                        </td>
                        <td className="px-1 py-1.5">
                          <span className="inline-flex items-center gap-1 font-medium" style={{ color: TONE_VAR[rec.tone] }}>
                            {it.proposal.status === "REVIEW" && <WarningCircle size={12} weight="fill" />}
                            {rec.label}
                          </span>
                        </td>
                        <td className="num px-1 py-1.5 text-right text-ink-2">
                          {fmtSurge(it.proposal.s_bid)} → <span className="text-ink">{fmtSurge(it.proposal.s_final)}</span>
                        </td>
                        <td className="num px-1 py-1.5 text-right" style={{ color: TONE_VAR[rec.tone] }}>
                          {fmtSigned(it.proposal.delta_applied)}
                        </td>
                        <td className="px-3 py-1.5 text-right max-[1279px]:hidden">
                          {op === "PENDING" ? (
                            <span className="text-[11px] text-ink-2">{it.eligibility.state === "ELIGIBLE" ? "Chờ xử lý" : "Bị khóa"}</span>
                          ) : (
                            <Chip tone={OP_LABEL[op].tone}>{OP_LABEL[op].label}</Chip>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2 text-xs">
            <span className="text-ink-2">
              {batchItems.length > 0 ? (
                <>
                  Đã chọn <span className="num text-ink">{batchItems.length}</span> đề xuất đủ điều kiện
                </>
              ) : (
                "Chọn các đề xuất đủ điều kiện để rà soát cùng lúc. Cần xem xét không thể đưa vào batch."
              )}
            </span>
            {batchItems.length > 0 && (
              <Button size="sm" variant="ghost" onClick={clearBatch}>
                Bỏ chọn
              </Button>
            )}
            <Button size="sm" variant="primary" className="ml-auto" disabled={batchItems.length === 0} onClick={() => setReviewOpen(true)}>
              Xem và duyệt {batchItems.length} đề xuất hợp lệ
            </Button>
          </div>
          <BatchReview open={reviewOpen} onClose={() => setReviewOpen(false)} items={batchItems} />
        </>
      )}
    </section>
  );
}
