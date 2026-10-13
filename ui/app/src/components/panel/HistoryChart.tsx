import { useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import type { HexSnapshot, Snapshot } from "../../domain/types";
import { fmtNum, fmtSigned, fmtTime } from "../../domain/format";
import { observedRatio } from "../../adapters/demo/forecast";
import { DATASET, useStore } from "../../state/store";
import { Tabs } from "../ui/primitives";
import { SurgeBaseChart } from "./SurgeBaseChart";

const W = 520;
const H = 190;
const M = { l: 40, r: 14, t: 14, b: 26 };

type Sub = "ds" | "demand" | "supply";

function valueAt(sub: Sub, t: number, i: number): number | null {
  if (t < 0 || t >= DATASET.stamps.length) return null;
  if (sub === "ds") return observedRatio(DATASET, t, i);
  const v = (sub === "demand" ? DATASET.raw.D : DATASET.raw.S)[t]?.[i];
  return v == null || !Number.isFinite(v) ? null : v;
}

/** Đường quan sát có gap: không nối qua null, không backfill. */
function pathOf(pts: { x: number; y: number | null }[]) {
  let d = "";
  let pen = false;
  for (const p of pts) {
    if (p.y == null) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

export function HistoryChart(props: { item: HexSnapshot; snap: Snapshot }) {
  const { sub, win } = useStore(useShallow((s) => ({ sub: s.chartSub, win: s.chartWindow })));
  const set = useStore((s) => s.set);
  // Keep the toolbar mounted when switching chart type so keyboard focus is preserved.
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs label="Chỉ số biểu đồ" size="sm" value={sub} onChange={(v) => set("chartSub", v)} items={[
          { id: "surge", label: "Surge Base" }, { id: "ds", label: "D/S" },
          { id: "demand", label: "Demand" }, { id: "supply", label: "Supply" },
        ]} />
        <Tabs label="Khoảng thời gian" size="sm" value={win} onChange={(v) => set("chartWindow", v)} items={[
          { id: "60", label: "60 phút" }, { id: "day", label: "Cả ngày" },
        ]} />
      </div>
      {sub === "surge" ? <SurgeBaseChart {...props} /> : <MetricHistoryChart {...props} />}
    </div>
  );
}

function MetricHistoryChart({ item, snap }: { item: HexSnapshot; snap: Snapshot }) {
  const { sub, win, viewMode, lookAhead, head } = useStore(
    useShallow((s) => ({ sub: s.chartSub === "surge" ? "ds" as const : s.chartSub, win: s.chartWindow, viewMode: s.viewMode, lookAhead: s.lookAhead, head: s.head })),
  );
  const [hoverT, setHoverT] = useState<number | null>(null);
  const i = item.hex.index;
  const t = snap.t;

  const data = useMemo(() => {
    const from = win === "60" ? Math.max(0, t - 12) : 0;
    // Sau cutoff chỉ hiện khi replay (dữ liệu đã có tới snapshot mới nhất), và chỉ trong cửa sổ 60'.
    const postTo = viewMode === "REPLAY" ? Math.min(head, win === "60" ? t + 6 : head) : t;
    const to = Math.max(t + 1, postTo);
    const obs: { t: number; v: number | null }[] = [];
    for (let k = from; k <= t; k++) {
      // Điểm tại cutoff lấy đúng giá trị snapshot (có thể thiếu theo fixture).
      const v =
        k === t
          ? sub === "ds"
            ? item.market.observed_ratio.value
            : sub === "demand"
              ? item.market.demand.value
              : item.market.effective_supply.value
          : valueAt(sub, k, i);
      obs.push({ t: k, v });
    }
    const post: { t: number; v: number | null }[] = [];
    for (let k = t + 1; k <= postTo; k++) post.push({ t: k, v: valueAt(sub, k, i) });
    const fc = sub === "ds" ? item.forecast.graph.value : null;
    const fcLocal = sub === "ds" ? item.forecast.local.value : null;
    const actual = lookAhead && t + 1 <= head ? valueAt(sub, t + 1, i) : null;
    const vals = [...obs, ...post].map((p) => p.v).filter((v): v is number => v != null);
    if (fc != null) vals.push(fc);
    if (fcLocal != null) vals.push(fcLocal);
    if (sub === "ds") vals.push(item.forecast.reference.value ?? 1.2);
    let lo = vals.length ? Math.min(...vals) : 0;
    let hi = vals.length ? Math.max(...vals) : 1;
    if (sub !== "ds") lo = 0;
    if (hi - lo < 1e-6) hi = lo + 1;
    const padY = (hi - lo) * 0.12;
    return { from, to, obs, post, fc, fcLocal, actual, lo: sub === "ds" ? Math.max(0, lo - padY) : 0, hi: hi + padY };
  }, [win, t, viewMode, head, sub, item, i, lookAhead]);

  const x = (k: number) => M.l + ((k - data.from) / Math.max(1, data.to - data.from)) * (W - M.l - M.r);
  const y = (v: number) => M.t + (1 - (v - data.lo) / (data.hi - data.lo)) * (H - M.t - M.b);
  const ticks = useMemo(() => {
    const n = 4;
    return Array.from({ length: n + 1 }, (_, j) => data.lo + ((data.hi - data.lo) * j) / n);
  }, [data.lo, data.hi]);
  const xTicks = useMemo(() => {
    const span = data.to - data.from;
    const step = span <= 20 ? 3 : 36;
    const out: number[] = [];
    for (let k = data.from; k <= data.to; k++) if ((k - data.from) % step === 0) out.push(k);
    return out;
  }, [data.from, data.to]);

  const ref = item.forecast.reference.value;
  const missingCount = data.obs.filter((p) => p.v == null).length;
  const digits = sub === "ds" ? 2 : 0;
  const unit = sub === "ds" ? "D/S" : sub === "demand" ? "request/5 phút" : "xe hiệu dụng";
  const hoverVal = hoverT == null ? null : hoverT <= t ? data.obs.find((p) => p.t === hoverT)?.v ?? null : data.post.find((p) => p.t === hoverT)?.v ?? null;

  return (
    <div className="space-y-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full max-h-[230px]"
        role="img"
        aria-label={`Biểu đồ ${unit} của vùng ${item.hex.zone_label}, cutoff ${fmtTime(snap.envelope.cutoff_ts)}`}
        onMouseLeave={() => setHoverT(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * W;
          const k = Math.round(data.from + ((px - M.l) / (W - M.l - M.r)) * (data.to - data.from));
          setHoverT(k >= data.from && k <= Math.max(t, data.post.at(-1)?.t ?? t) ? k : null);
        }}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="#e1e5eb" />
            <text x={M.l - 6} y={y(v) + 3} textAnchor="end" className="num" fontSize="10" fill="#607089">
              {v.toFixed(digits === 0 ? 0 : 1)}
            </text>
          </g>
        ))}
        {xTicks.map((k) => (
          <text key={k} x={x(k)} y={H - 8} textAnchor="middle" className="num" fontSize="10" fill="#607089">
            {DATASET.raw.ts[k] ?? ""}
          </text>
        ))}

        {sub === "ds" && ref != null && (
          <g>
            <line x1={M.l} x2={W - M.r} y1={y(ref)} y2={y(ref)} stroke="#8c94a1" strokeDasharray="2 4" />
            <text x={W - M.r} y={y(ref) - 4} textAnchor="end" fontSize="10" fill="#516179">
              mốc {ref.toFixed(2)}
            </text>
          </g>
        )}

        {/* vạch cutoff */}
        <line x1={x(t)} x2={x(t)} y1={M.t - 4} y2={H - M.b} stroke="var(--focus)" strokeWidth={1.5} />
        <text x={x(t) - 4} y={M.t + 2} textAnchor="end" fontSize="10" fill="var(--focus)">
          cutoff
        </text>

        <path d={pathOf(data.obs.map((p) => ({ x: x(p.t), y: p.v == null ? null : y(p.v) })))} fill="none" stroke="#0f1827" strokeWidth={1.8} strokeLinejoin="round" />
        {data.post.length > 0 && (
          <path
            d={pathOf([data.obs.at(-1)!, ...data.post].map((p) => ({ x: x(p.t), y: p.v == null ? null : y(p.v) })))}
            fill="none"
            stroke="#516179"
            strokeOpacity={0.6}
            strokeWidth={1.4}
            strokeDasharray="2 3"
          />
        )}
        {data.obs.at(-1)?.v != null && <circle cx={x(t)} cy={y(data.obs.at(-1)!.v!)} r={3} fill="#0f1827" />}

        {/* forecast H5: điểm riêng tại forecast_ts, không nối vào đường quan sát */}
        {data.fcLocal != null && <circle cx={x(t + 1)} cy={y(data.fcLocal)} r={3.5} fill="none" stroke="#516179" strokeWidth={1.4} />}
        {data.fc != null && <rect x={x(t + 1) - 4} y={y(data.fc) - 4} width={8} height={8} transform={`rotate(45 ${x(t + 1)} ${y(data.fc)})`} fill="var(--od)" />}
        {data.actual != null && <circle cx={x(t + 1)} cy={y(data.actual)} r={3.5} fill="var(--review)" />}

        {hoverT != null && (
          <line x1={x(hoverT)} x2={x(hoverT)} y1={M.t} y2={H - M.b} stroke="#4c607c" strokeOpacity={0.4} />
        )}
      </svg>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-[#0f1827]" /> Quan sát
        </span>
        {sub === "ds" && (
          <>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block size-2 rotate-45 bg-od" /> Graph t+5
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block size-2 rounded-full border border-[#516179]" /> Local t+5
            </span>
          </>
        )}
        {viewMode === "REPLAY" && data.post.length > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0 w-4 border-t border-dashed border-[#516179]" /> Sau cutoff (chỉ replay)
          </span>
        )}
        {hoverT != null && (
          <span className="num ml-auto text-ink">
            {DATASET.raw.ts[hoverT]} · {hoverVal == null ? "Thiếu" : fmtNum(hoverVal, digits)}
          </span>
        )}
      </div>

      {missingCount > 0 && <div className="text-[11px] text-review">{missingCount} điểm thiếu dữ liệu, để trống, không nội suy.</div>}

      {sub === "ds" && (
        <div className="rounded-[8px] bg-bg/50 px-3 py-2 text-xs">
          {lookAhead ? (
            data.actual != null && data.fc != null ? (
              <span>
                Đối chiếu sau 5 phút: thực tế <span className="num text-review">{fmtNum(data.actual)}</span>, Graph dự báo{" "}
                <span className="num text-od">{fmtNum(data.fc)}</span>, sai số <span className="num">{fmtSigned(data.fc - data.actual)}</span>. Chỉ để tham
                khảo, không đổi đề xuất.
              </span>
            ) : (
              <span className="text-ink-2">Chưa thể đối chiếu: chưa có quan sát hoặc dự báo tại thời điểm dự báo.</span>
            )
          ) : (
            <span className="text-ink-2">Dự báo cho {fmtTime(snap.envelope.forecast_ts)} chưa có quan sát để đối chiếu tại cutoff. Bật "Xem lại sau 5 phút" ở thanh replay.</span>
          )}
        </div>
      )}
    </div>
  );
}
