import { useEffect, useRef, useState } from "react";
import { ArrowRight, CaretDown, CheckCircle, Info, Lock, MapPin, SpinnerGap, WarningCircle } from "@phosphor-icons/react";
import type { HexSnapshot, Snapshot, Valued } from "../../domain/types";
import { fmtDateTime, fmtNum, fmtSigned, fmtSurge, fmtTime, shortHex } from "../../domain/format";
import { ELIG_LABEL, OP_LABEL, REC_LABEL, TONE_VAR } from "../../domain/labels";
import { LIFECYCLE_COPY, reasonCopy } from "../../domain/reasons";
import { DEMO_MODEL_ID } from "../../adapters/demo/forecast";
import { isDecided, useOpStatus, useSelected, useSnapshot } from "../../state/hooks";
import { decisionKey, isActionable, useStore } from "../../state/store";
import { Button, Chip, Dialog, EmptyState, Kv, Tabs } from "../ui/primitives";
import { HistoryChart } from "./HistoryChart";
import { OverrideDrawer } from "./OverrideDrawer";

function explain(it: HexSnapshot): string {
  const p = it.proposal;
  const g = it.forecast.graph.value;
  const l = it.forecast.local.value;
  const r = it.forecast.reference.value;
  if (p.status === "REVIEW") {
    const first = p.reasons[0];
    return first ? `${reasonCopy(first).detail}` : "Không đủ thông tin để duyệt.";
  }
  if (g == null || r == null) return "Thiếu dự báo nên không giải thích được đề xuất.";
  const pressWord = g > r ? "cao hơn" : g < r ? "thấp hơn" : "bằng";
  const revWord = l == null ? "" : g > l ? ", và Graph cao hơn Local (lân cận đang nóng hơn)" : g < l ? ", và Graph thấp hơn Local (lân cận đang dịu hơn)" : "";
  const base = `Graph dự báo D/S t+5 là ${g.toFixed(2)}, ${pressWord} mốc ${r.toFixed(2)}${revWord}.`;
  if (p.status === "HOLD") {
    if (p.trace.direction_gate === "BLOCKED") return `${base} Revision ngược hướng Pressure nên tổng hiệu chỉnh bị đưa về 0, giữ bidding.`;
    return `${base} Chênh lệch nằm trong vùng không điều chỉnh nên giữ bidding.`;
  }
  const verb = p.status === "INCREASE" ? "tăng" : "giảm";
  const cap = p.trace.price_cap_hit ? " Giá đã bị giới hạn bởi khoảng giá của policy." : p.trace.requested_cap_hit ? " Mức yêu cầu đã chạm biên hiệu chỉnh." : "";
  return `${base} Controller đề xuất ${verb} ${fmtSigned(p.delta_applied)} điểm hệ số surge.${cap}`;
}

function ScaleBar({ it }: { it: HexSnapshot }) {
  // Local, Graph, Ref và quan sát trên cùng một thang log.
  const pts = [
    { k: "Quan sát", v: it.market.observed_ratio.value, c: "#0f1827" },
    { k: "Local", v: it.forecast.local.value, c: "#516179" },
    { k: "Graph", v: it.forecast.graph.value, c: "var(--od)" },
    { k: "Mốc", v: it.forecast.reference.value, c: "var(--neutral)" },
  ];
  const lo = 0.3;
  const hi = 3;
  const pos = (v: number) => `${(Math.log(Math.min(hi, Math.max(lo, v)) / lo) / Math.log(hi / lo)) * 100}%`;
  return (
    <div>
      <div className="relative mx-1 h-8">
        <div className="absolute inset-x-0 top-3.5 h-1 rounded-full bg-surface-2" />
        {pts.map((p) =>
          p.v == null ? null : (
            <span key={p.k} className="absolute top-1.5 -translate-x-1/2" style={{ left: pos(p.v) }} title={`${p.k} ${p.v.toFixed(2)}`}>
              <span className="block size-3 rounded-full border-2 border-surface" style={{ background: p.c }} />
            </span>
          ),
        )}
      </div>
      <div className="grid grid-cols-4 gap-2">
        {pts.map((p) => (
          <div key={p.k} className="min-w-0">
            <div className="flex items-center gap-1 text-[11px] text-ink-2">
              <span className="inline-block size-2 rounded-full" style={{ background: p.c }} />
              {p.k}
            </div>
            <div className="num text-sm text-ink">{fmtNum(p.v)}</div>
          </div>
        ))}
      </div>
      <div className="mt-1 text-[10px] text-[#717d90]">Cùng thang D/S smoothed (log), 0.3 đến 3.0. Local và Graph là dự báo cho t+5.</div>
    </div>
  );
}

function ValuedRow({ k, v, digits = 2 }: { k: string; v: Valued; digits?: number }) {
  return <Kv k={k} v={v.value == null ? <span className="text-review">Thiếu{v.reason ? ` · ${reasonCopy(v.reason).title}` : ""}</span> : v.value.toFixed(digits)} />;
}

function ActionBar({ it, snap }: { it: HexSnapshot; snap: Snapshot }) {
  const op = useOpStatus(it);
  const decision = useStore((s) => s.decisions[decisionKey(it.proposal)]);
  const pending = useStore((s) => s.pending[decisionKey(it.proposal)]);
  const submit = useStore((s) => s.submit);
  const cancel = useStore((s) => s.cancel);
  const [menu, setMenu] = useState(false);
  const [override, setOverride] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => !menuRef.current?.contains(e.target as Node) && setMenu(false);
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menu]);

  const el = it.eligibility;
  const caps = el.capabilities;
  const decided = isDecided(op);
  const busy = op === "SUBMITTING";
  const lockText = decided
    ? null
    : el.state !== "ELIGIBLE"
      ? el.blocked_reasons.map((r) => LIFECYCLE_COPY[r] ?? reasonCopy(r).detail).join(" ")
      : el.blocked_reasons.includes("HOLD_NO_ACTION")
        ? LIFECYCLE_COPY.HOLD_NO_ACTION
        : el.blocked_reasons.includes("REVIEW_MANUAL_ONLY")
          ? LIFECYCLE_COPY.REVIEW_MANUAL_ONLY
          : null;

  return (
    <div className="sticky bottom-0 z-10 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur-sm">
      {decided || op === "FAILED" || op === "CANCELLED" ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <Chip tone={OP_LABEL[op].tone}>
            {op === "UNKNOWN" ? <SpinnerGap size={12} className="animate-spin" /> : op === "RECORDED" ? <CheckCircle size={12} weight="fill" /> : null}
            {OP_LABEL[op].label}
          </Chip>
          {decision?.requested_surge && <span className="num text-ink">{fmtSurge(Number(decision.requested_surge))}</span>}
          {decision?.accepted_at && <span className="text-ink-2">lúc {fmtTime(decision.accepted_at)}</span>}
          {op === "UNKNOWN" && <span className="text-ink-2">Đang tra cứu theo idempotency key {pending?.idempotency_key.slice(-6)}. Không gửi lại.</span>}
          {decision?.error && <span className="text-review">{decision.error}</span>}
          {op === "RECORDED" && <span className="text-ink-2">Chưa thực thi, DEMO không gửi giá thật.</span>}
        </div>
      ) : null}

      {lockText && (
        <div className="mb-2 flex items-start gap-1.5 text-xs text-ink-2">
          <Lock size={13} className="mt-0.5 shrink-0" />
          <span>{lockText}</span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {op === "RECORDED" ? (
          <Button variant="danger" onClick={() => setCancelOpen(true)}>
            Hủy lệnh demo
          </Button>
        ) : (
          <>
            {isActionable(it) && (
              <Button
                variant="primary"
                disabled={!caps.confirm || decided || busy || snap.envelope.execution_mode !== "DEMO"}
                onClick={() => submit(it, "ACCEPT_PROPOSAL", it.proposal.s_final, null)}
              >
                {busy && pending?.action === "ACCEPT_PROPOSAL" ? <SpinnerGap size={14} className="animate-spin" /> : null}
                Xác nhận demo {fmtSurge(it.proposal.s_final)}
              </Button>
            )}
            {isActionable(it) && (
              <Button disabled={!caps.keep_bidding || decided || busy} onClick={() => submit(it, "KEEP_BIDDING", it.proposal.s_bid, null)}>
                Giữ bidding {fmtSurge(it.proposal.s_bid)}
              </Button>
            )}
            <div className="relative ml-auto" ref={menuRef}>
              <Button variant="ghost" aria-haspopup="menu" aria-expanded={menu} disabled={!caps.override || decided || busy} onClick={() => setMenu((v) => !v)}>
                Thao tác khác <CaretDown size={12} />
              </Button>
              {menu && (
                <div
                  role="menu"
                  className="absolute bottom-full right-0 z-20 mb-1.5 w-[240px] rounded-[12px] border border-line bg-surface p-1.5 shadow-[0_16px_40px_rgba(250,251,253,0.55)]"
                  onKeyDown={(e) => e.key === "Escape" && setMenu(false)}
                >
                  <button
                    role="menuitem"
                    type="button"
                    autoFocus
                    className="w-full rounded-[8px] px-2.5 py-2 text-left text-xs hover:bg-surface-2"
                    onClick={() => {
                      setMenu(false);
                      setOverride(true);
                    }}
                  >
                    <span className="block text-ink">Điều chỉnh thủ công</span>
                    <span className="block text-[11px] text-ink-2">Đặt hệ số khác trong biên policy, bắt buộc ghi lý do</span>
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <OverrideDrawer item={it} open={override} onClose={() => setOverride(false)} />
      <Dialog
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title="Hủy lệnh demo"
        width={440}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCancelOpen(false)}>
              Giữ lệnh
            </Button>
            <Button
              variant="danger"
              disabled={cancelReason.trim().length < 5}
              onClick={async () => {
                await cancel(it, cancelReason.trim());
                setCancelOpen(false);
                setCancelReason("");
              }}
            >
              Hủy lệnh
            </Button>
          </>
        }
      >
        <div className="space-y-2 text-xs">
          <p className="text-ink-2">Hủy tạo sự kiện mới trong nhật ký. Bản ghi cũ được giữ nguyên, không xóa.</p>
          <label className="block font-medium text-ink" htmlFor="cancel-reason">
            Lý do hủy
          </label>
          <textarea
            id="cancel-reason"
            rows={3}
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
            className="w-full resize-none rounded-[8px] border border-line bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-focus"
          />
        </div>
      </Dialog>
    </div>
  );
}

export function DecisionPanel() {
  const snap = useSnapshot();
  const it = useSelected();
  const tab = useStore((s) => s.panelTab);
  const set = useStore((s) => s.set);

  if (!it) {
    return (
      <aside aria-label="Panel quyết định" className="flex h-full flex-col rounded-[12px] border border-line bg-surface">
        <EmptyState icon={<MapPin size={28} />} title="Chưa chọn vùng" body="Chọn một hex trên bản đồ hoặc một dòng trong hàng đợi để xem đề xuất." />
      </aside>
    );
  }

  const p = it.proposal;
  const rec = REC_LABEL[p.status];
  const elig = ELIG_LABEL[it.eligibility.state];
  const tone = TONE_VAR[rec.tone];

  return (
    <aside aria-label={`Panel quyết định, ${it.hex.zone_label} ${shortHex(it.hex.id)}`} className="flex h-full min-h-0 flex-col overflow-hidden rounded-[12px] border border-line bg-surface">
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {/* Tầng 1 */}
        <section className="border-b border-line px-4 pb-4 pt-3.5">
          <div className="mb-2 flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 className="truncate text-[15px] font-semibold">{it.hex.zone_label}</h2>
              <div className="num text-[11px] text-ink-2">
                {shortHex(it.hex.id)} · vòng {it.hex.ring} · {p.proposal_id}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <Chip tone={rec.tone} solid={p.status !== "HOLD"}>
                {p.status === "REVIEW" && <WarningCircle size={12} weight="fill" />}
                {rec.label}
              </Chip>
              <Chip tone={elig.tone}>{elig.label}</Chip>
            </div>
          </div>

          <div className="flex items-end gap-3">
            <div>
              <div className="text-[11px] text-ink-2">Bidding</div>
              <div className="num text-2xl font-semibold text-ink-2">{fmtSurge(p.s_bid)}</div>
            </div>
            <ArrowRight size={18} className="mb-2 text-ink-2" />
            <div>
              <div className="text-[11px] text-ink-2">Đề xuất cho {fmtTime(snap.envelope.forecast_ts)}</div>
              <div className="num text-[32px] font-semibold leading-none" style={{ color: p.s_final == null ? "var(--text-2)" : tone }}>
                {fmtSurge(p.s_final)}
              </div>
            </div>
            <div className="mb-1 ml-auto text-right">
              <div className="num text-base font-semibold" style={{ color: tone }}>
                {fmtSigned(p.delta_applied)}
              </div>
              <div className="text-[10px] text-ink-2">điểm hệ số surge</div>
            </div>
          </div>
          {p.trace.price_cap_hit && p.delta_requested != null && (
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-2">
              <Info size={12} /> Yêu cầu {fmtSigned(p.delta_requested)}, áp dụng {fmtSigned(p.delta_applied)} do giới hạn giá.
            </div>
          )}
        </section>

        {/* Tầng 2 */}
        <section className="space-y-3 border-b border-line px-4 py-3.5">
          <p className="text-[13px] leading-relaxed text-ink">{explain(it)}</p>
          {p.reasons.length > 0 && (
            <ul className="space-y-1.5">
              {p.reasons.map((r) => {
                const c = reasonCopy(r);
                return (
                  <li key={r} className="flex items-start gap-2 rounded-[8px] bg-bg/50 px-2.5 py-2 text-xs">
                    {c.blocking ? <WarningCircle size={14} weight="fill" className="mt-0.5 shrink-0 text-review" /> : <Info size={14} className="mt-0.5 shrink-0 text-ink-2" />}
                    <span>
                      <span className="font-medium text-ink">{c.title}</span>
                      <span className="num ml-1.5 text-[10px] text-ink-2">{r}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          <ScaleBar it={it} />
          <div className="grid grid-cols-3 gap-2 rounded-[8px] bg-bg/50 p-2.5">
            {[
              { k: "Pressure", v: p.trace.pressure, d: "log(Graph/Mốc)" },
              { k: "Revision", v: p.trace.revision, d: "log(Graph/Local)" },
              { k: "Delta", v: p.delta_applied, d: "điểm hệ số" },
            ].map((m) => (
              <div key={m.k}>
                <div className="text-[11px] text-ink-2">{m.k}</div>
                <div className="num text-sm text-ink">{fmtSigned(m.v, 3)}</div>
                <div className="text-[10px] text-[#717d90]">{m.d}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Tầng 3 */}
        <section className="px-4 py-3.5">
          <div className="mb-3">
            <Tabs
              label="Chi tiết đề xuất"
              value={tab}
              onChange={(v) => set("panelTab", v)}
              items={[
                { id: "history", label: "Lịch sử" },
                { id: "detail", label: "Chi tiết" },
                { id: "data", label: "Dữ liệu" },
              ]}
            />
          </div>
          {tab === "history" && <HistoryChart item={it} snap={snap} />}
          {tab === "detail" && (
            <div className="divide-y divide-line">
              <Kv k="Pressure sau vùng chết" v={fmtSigned(p.trace.pressure_dz, 3)} />
              <Kv k="Revision sau vùng chết" v={fmtSigned(p.trace.revision_dz, 3)} />
              <Kv k="a_P (k_P · Pressure)" v={fmtSigned(p.trace.a_P, 3)} />
              <Kv k="a_R (k_R · Revision)" v={fmtSigned(p.trace.a_R, 3)} />
              <Kv k="Tổng a" v={fmtSigned(p.trace.a, 3)} />
              <Kv k="Cổng hướng" v={p.trace.direction_gate ?? "Thiếu"} />
              <Kv k="Delta yêu cầu" v={fmtSigned(p.delta_requested)} />
              <Kv k="Chạm biên hiệu chỉnh" v={p.trace.requested_cap_hit ? "Có" : "Không"} />
              <Kv k="Chạm giới hạn giá" v={p.trace.price_cap_hit ? "Có" : "Không"} />
              <Kv k="Delta áp dụng" v={fmtSigned(p.delta_applied)} />
              <Kv k="Policy" v={p.policy_version} />
              <Kv k="Version đề xuất" v={<span className="break-all">{p.version}</span>} />
              <Kv k="Hết hạn" v={it.eligibility.expires_at ? fmtDateTime(it.eligibility.expires_at) : "Thiếu"} />
            </div>
          )}
          {tab === "data" && (
            <div className="divide-y divide-line">
              <ValuedRow k="Demand (request/5 phút)" v={it.market.demand} digits={0} />
              <ValuedRow k="Supply hiệu dụng" v={it.market.effective_supply} digits={1} />
              <ValuedRow k="Xe rảnh" v={it.market.idle_supply} digits={0} />
              <ValuedRow k={`D/S quan sát lúc ${fmtTime(snap.envelope.cutoff_ts)}`} v={it.market.observed_ratio} />
              <Kv k="Số quan sát (D+S)" v={it.market.support} />
              <ValuedRow k="Bidding" v={it.market.bidding} />
              <Kv k="Metric dự báo" v={`${snap.metric.id} · ${snap.metric.version}`} />
              <Kv k="Công thức" v={snap.metric.equation} />
              <Kv k="Model" v={snap.model.demo_model_id ?? DEMO_MODEL_ID} />
              <Kv k="Model version" v={snap.model.model_version ?? "Chưa có, forecast giả lập"} />
              <Kv k="Snapshot" v={<span className="break-all">{snap.envelope.snapshot_id}</span>} />
              <Kv k="Loại dữ liệu" v={snap.envelope.data_kind} />
            </div>
          )}
        </section>
      </div>
      <ActionBar it={it} snap={snap} />
    </aside>
  );
}
