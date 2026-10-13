import { useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import type { HexSnapshot, Snapshot } from "../../domain/types";
import { fmtDateTime, fmtSigned, fmtSurge, fmtTime } from "../../domain/format";
import { scenarioById } from "../../adapters/demo/scenarios";
import { buildSurgeHistory, SURGE_STEP_MS, surgeStepPath, type SurgePoint } from "../../adapters/demo/surgeHistory";
import { DATASET, useStore } from "../../state/store";

const W = 520;
const H = 210;
const M = { l: 50, r: 18, t: 24, b: 28 };

/** Uses shared replay/selection state; no independent timer or price-policy computation. */
export function SurgeBaseChart({ item, snap }: { item: HexSnapshot; snap: Snapshot }) {
  const { win, viewMode, head, scenarioId } = useStore(useShallow((s) => ({
    win: s.chartWindow, viewMode: s.viewMode, head: s.head, scenarioId: s.scenarioId,
  })));
  const seek = useStore((s) => s.seek);
  const setPlaying = useStore((s) => s.setPlaying);
  const [hover, setHover] = useState<number | null>(null);
  const data = useMemo(() => buildSurgeHistory(DATASET, item, snap, scenarioById(scenarioId), {
    window: win, viewMode, head,
  }), [item, snap, scenarioId, win, viewMode, head]);
  const points = [...data.observed, ...data.future];
  const hovered = points.find((p) => p.index === hover);
  const fromMs = Date.parse(points[0].timestamp);
  const cutoffMs = Date.parse(snap.envelope.cutoff_ts);
  const toMs = Math.max(cutoffMs + SURGE_STEP_MS, Date.parse(points.at(-1)!.timestamp));
  const values = points.flatMap((p) => p.value == null ? [] : [p.value]);
  const min = values.length ? Math.min(...values) : 1;
  const max = values.length ? Math.max(...values) : 1;
  const padding = Math.max(0.1, max - min) * 0.15;
  const lo = Math.max(0, min - padding);
  const hi = max + padding;
  const x = (stamp: string) => M.l + (Date.parse(stamp) - fromMs) / Math.max(SURGE_STEP_MS, toMs - fromMs) * (W - M.l - M.r);
  const y = (value: number) => M.t + (1 - (value - lo) / (hi - lo)) * (H - M.t - M.b);
  const path = (ps: SurgePoint[]) => surgeStepPath(ps.map((p) => ({
    x: x(p.timestamp), y: p.value == null ? null : y(p.value), breakBefore: p.breakBefore,
  })));
  const tickEvery = Math.max(1, Math.ceil((points.length - 1) / 4));
  const timeTicks = points.filter((_, j) => j % tickEvery === 0);
  const end = points.at(-1)!;
  const shownPoint = hovered ?? data.current;

  function selectTime(index: number) {
    // Explicit inspection pauses playback, and seek() switches to read-only REPLAY.
    setPlaying(false);
    seek(index);
    setHover(null);
  }

  function pointUnder(svg: SVGSVGElement, clientX: number, clientY: number): SurgePoint | undefined {
    const matrix = svg.getScreenCTM();
    if (!matrix) return undefined;
    // Transform pointer coordinates through the real SVG viewBox, including letterboxing.
    const cursor = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    if (cursor.x < M.l || cursor.x > W - M.r || cursor.y < M.t || cursor.y > H - M.b) return undefined;
    const ms = fromMs + (cursor.x - M.l) / (W - M.l - M.r) * (toMs - fromMs);
    const nearest = points.reduce((best, p) => Math.abs(Date.parse(p.timestamp) - ms) < Math.abs(Date.parse(best.timestamp) - ms) ? p : best);
    // Do not silently jump across a missing interval or into unobserved future time.
    return Math.abs(Date.parse(nearest.timestamp) - ms) <= SURGE_STEP_MS / 2 ? nearest : undefined;
  }

  return (
    <div className="space-y-2.5" data-testid="surge-base-chart" data-hex-id={item.hex.id} data-cutoff={snap.envelope.cutoff_ts}>
      <div className="flex flex-wrap items-end justify-between gap-2 rounded-[8px] bg-bg/50 px-3 py-2">
        <div>
          <div className="text-xs text-ink-2">Surge Base · Bidding tại {fmtTime(snap.envelope.cutoff_ts)}</div>
          <div className="num text-xl font-semibold text-ink" data-testid="surge-base-current">{fmtSurge(data.current.value)}</div>
        </div>
        <div className="text-right text-[11px] text-ink-2">
          <div><span className="num text-ink">{fmtSigned(data.delta5m)}</span> điểm so với 5 phút trước</div>
          <div>Trong cửa sổ đến cutoff: <span className="num">{fmtSurge(data.min)} – {fmtSurge(data.max)}</span></div>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full cursor-crosshair rounded-[8px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        role="slider"
        tabIndex={0}
        aria-label={`Thời điểm Surge Base của vùng ${item.hex.zone_label}; dùng mũi tên trái phải để xem từng bước`}
        aria-valuemin={data.from}
        aria-valuemax={end.index}
        aria-valuenow={snap.t}
        aria-valuetext={`${fmtDateTime(snap.envelope.cutoff_ts)}; bidding ${fmtSurge(data.current.value)}`}
        onPointerLeave={() => setHover(null)}
        onPointerMove={(e) => setHover(pointUnder(e.currentTarget, e.clientX, e.clientY)?.index ?? null)}
        onClick={(e) => {
          const point = pointUnder(e.currentTarget, e.clientX, e.clientY);
          if (point) selectTime(point.index);
        }}
        onKeyDown={(e) => {
          const target = e.key === "ArrowLeft" ? snap.t - 1 : e.key === "ArrowRight" ? snap.t + 1
            : e.key === "Home" ? data.from : e.key === "End" ? end.index : null;
          if (target == null) return;
          e.preventDefault();
          e.stopPropagation();
          selectTime(Math.max(data.from, Math.min(end.index, target)));
        }}
      >
        <title>Surge Base theo thời gian — hệ số bidding gốc, không phải giá đề xuất hay giá đã thực thi</title>
        {Array.from({ length: 5 }, (_, j) => lo + (hi - lo) * j / 4).map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="#e1e5eb" />
            <text x={M.l - 7} y={y(v) + 3} textAnchor="end" fontSize="10" fill="#39465c" className="num">×{v.toFixed(2)}</text>
          </g>
        ))}
        {timeTicks.map((p) => (
          <text key={p.index} x={x(p.timestamp)} y={H - 9} textAnchor="middle" fontSize="10" fill="#39465c" className="num">{fmtTime(p.timestamp)}</text>
        ))}
        <line x1={x(snap.envelope.cutoff_ts)} x2={x(snap.envelope.cutoff_ts)} y1={M.t - 4} y2={H - M.b} stroke="var(--focus)" strokeWidth={1.5} />
        <text x={x(snap.envelope.cutoff_ts)} y={M.t - 9} textAnchor="middle" fontSize="10" fill="var(--focus)">{fmtTime(snap.envelope.cutoff_ts)}</text>
        <path data-testid="surge-base-observed" d={path(data.observed)} fill="none" stroke="#0f1827" strokeWidth={2} />
        {data.future.length > 0 && <path data-testid="surge-base-replay" d={path([data.current, ...data.future])} fill="none" stroke="#516179" strokeOpacity={0.65} strokeWidth={1.5} strokeDasharray="2 4" />}
        {/* Dots keep isolated valid samples visible even when both neighbours are missing. */}
        {points.filter((p, j) => p.value != null && (j === 0 || p.breakBefore || points[j - 1]?.value == null || points[j + 1]?.value == null || p.index === snap.t)).map((p) => (
          <circle key={p.index} cx={x(p.timestamp)} cy={y(p.value!)} r={p.index === snap.t ? 4 : 2} fill={p.index > snap.t ? "#516179" : "#0f1827"} />
        ))}
        {hovered && <line x1={x(hovered.timestamp)} x2={x(hovered.timestamp)} y1={M.t} y2={H - M.b} stroke="#516179" strokeDasharray="3 3" />}
      </svg>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[#0f1827]" />Bidding đến cutoff</span>
        {data.future.length > 0 && <span className="inline-flex items-center gap-1.5"><span className="h-0 w-4 border-t border-dashed border-[#516179]" />Bidding sau cutoff · chỉ replay</span>}
      </div>
      <div className="num rounded-[8px] bg-bg/50 px-3 py-2 text-xs text-ink" data-testid="surge-base-inspection">
        {fmtDateTime(shownPoint.timestamp)} · {fmtSurge(shownPoint.value)}
        {shownPoint.index > snap.t ? " · quan sát sau cutoff, không phải dự báo" : " · bidding gốc"}
        {shownPoint.reason && <div className="mt-1 text-review">
          {shownPoint.reason === "HISTORY_SNAPSHOT_MISMATCH"
            ? "Lịch sử không khớp vùng hoặc thời điểm đang xem."
            : "Thiếu giá nền hoặc giá trị không hợp lệ."}
          <span className="ml-1 text-[10px]">({shownPoint.reason})</span>
        </div>}
      </div>
      {(data.missing > 0 || data.gaps > 0) && <div className="text-xs text-review">{data.missing} điểm thiếu/không hợp lệ; {data.gaps} khoảng thời gian bị thiếu. Không nội suy hoặc thay bằng 0.</div>}
      <p className="text-[11px] leading-relaxed text-ink-2">
        Nguồn DEMO: chuỗi surge replay{scenarioId === "day" ? "" : " và bidding của kịch bản"}. Không làm mượt, không cộng correction.
        Giá tại t là bidding dùng cho quyết định tại t; đây không phải xác nhận giá đã thực thi.
        Bấm biểu đồ hoặc dùng ← / → để dừng và xem một thời điểm.
      </p>
    </div>
  );
}
