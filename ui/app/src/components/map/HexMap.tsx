import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { ArrowsIn, CaretDown, CaretUp, CheckCircle, Crosshair, Minus, Plus, Stack, WarningCircle } from "@phosphor-icons/react";
import type { HexSnapshot } from "../../domain/types";
import { fmtNum, fmtSigned, fmtSurge, fmtTime, shortHex } from "../../domain/format";
import { REC_LABEL } from "../../domain/labels";
import { completedOdHour } from "../../adapters/demo/legacy";
import { useSnapshot } from "../../state/hooks";
import { DATASET, operatorStatus, useStore, type MapLayer } from "../../state/store";
import { DEMAND_MAX, DS_SCALE, SUPPLY_MAX, deltaColor, dsColor, legendGradient, seqColor } from "./scales";
import { Tabs } from "../ui/primitives";

// ---------- hình học: chiếu tọa độ [lat, lng] sang mặt phẳng, tính một lần ----------
const W = 1000;
const geo = (() => {
  const pts = DATASET.hexes.flatMap((h) => h.poly);
  const lat0 = pts.reduce((a, p) => a + p[0], 0) / pts.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const xs = pts.map((p) => p[1] * k);
  const ys = pts.map((p) => -p[0]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const s = W / (maxX - minX);
  const H = (maxY - minY) * s;
  const pad = 40;
  const proj = (lat: number, lng: number): [number, number] => [(lng * k - minX) * s + pad, (-lat - minY) * s + pad];
  const polys = DATASET.hexes.map((h) => h.poly.map(([la, ln]) => proj(la, ln)));
  const centers = polys.map((pp) => [pp.reduce((a, p) => a + p[0], 0) / pp.length, pp.reduce((a, p) => a + p[1], 0) / pp.length] as [number, number]);
  return { vbW: W + pad * 2, vbH: H + pad * 2, polys, centers, paths: polys.map((pp) => `M${pp.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L")}Z`) };
})();

const OD_LIMIT = 12;

interface View {
  k: number;
  x: number;
  y: number;
}
const FIT: View = { k: 1, x: 0, y: 0 };

function fillFor(item: HexSnapshot, layer: MapLayer, dsMode: "obs" | "fc"): string | null {
  switch (layer) {
    case "ds": {
      const v = dsMode === "obs" ? item.market.observed_ratio.value : item.forecast.graph.value;
      return v == null ? null : dsColor(v);
    }
    case "delta":
      return item.proposal.delta_applied == null ? null : deltaColor(item.proposal.delta_applied);
    case "demand":
      return item.market.demand.value == null ? null : seqColor(item.market.demand.value, DEMAND_MAX);
    case "supply":
      return item.market.effective_supply.value == null ? null : seqColor(item.market.effective_supply.value, SUPPLY_MAX);
  }
}

const LAYER_TITLE: Record<MapLayer, string> = {
  ds: "Cung cầu (D/S)",
  delta: "Hiệu chỉnh",
  demand: "Demand",
  supply: "Supply",
};

export function HexMap() {
  const snap = useSnapshot();
  const st = useStore(
    useShallow((s) => ({
      selectedHex: s.selectedHex,
      layer: s.layer,
      dsMode: s.dsMode,
      showOD: s.showOD,
      showAdj: s.showAdj,
      odExpanded: s.odExpanded,
      decisions: s.decisions,
      pending: s.pending,
    })),
  );
  const { select, set } = useStore.getState();
  const [view, setView] = useState<View>(FIT);
  const [hover, setHover] = useState<number | null>(null);
  const [legendOpen, setLegendOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1440);
  const [moreOpen, setMoreOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);

  const selIndex = snap.items.findIndex((x) => x.hex.id === st.selectedHex);
  const cutoff = snap.envelope.cutoff_ts;

  // OD: giờ đã hoàn tất trước cutoff, đúng as-of.
  const odHour = completedOdHour(cutoff);
  const od = useMemo(() => {
    if (odHour == null) return { shown: [] as [number, number, number][], total: 0 };
    const all = DATASET.raw.od[odHour] ?? [];
    const related = selIndex >= 0 ? all.filter(([a, b]) => a === selIndex || b === selIndex) : all;
    const sorted = [...related].sort((a, b) => b[2] - a[2]);
    return { shown: st.odExpanded ? sorted : sorted.slice(0, OD_LIMIT), total: sorted.length };
  }, [odHour, selIndex, st.odExpanded]);
  const odMax = od.shown.reduce((a, e) => Math.max(a, e[2]), 0) || 1;

  const toSvg = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current!;
    const r = svg.getBoundingClientRect();
    const scale = Math.max(geo.vbW / r.width, geo.vbH / r.height);
    const ox = (r.width * scale - geo.vbW) / 2;
    const oy = (r.height * scale - geo.vbH) / 2;
    return [(clientX - r.left) * scale - ox, (clientY - r.top) * scale - oy] as [number, number];
  }, []);

  const zoomAt = useCallback((factor: number, cx = geo.vbW / 2, cy = geo.vbH / 2) => {
    setView((v) => {
      const k = Math.max(0.8, Math.min(6, v.k * factor));
      const f = k / v.k;
      return { k, x: cx - (cx - v.x) * f, y: cy - (cy - v.y) * f };
    });
  }, []);

  const centerOn = useCallback((i: number, k?: number) => {
    const [cx, cy] = geo.centers[i];
    setView((v) => {
      const kk = k ?? Math.max(v.k, 1.6);
      return { k: kk, x: geo.vbW / 2 - cx * kk, y: geo.vbH / 2 - cy * kk };
    });
  }, []);

  // Auto-fit nhẹ chỉ khi vùng chọn nằm ngoài khung nhìn; không kéo ngược thao tác pan.
  useEffect(() => {
    if (selIndex < 0) return;
    const [cx, cy] = geo.centers[selIndex];
    const sx = cx * view.k + view.x;
    const sy = cy * view.k + view.y;
    if (sx < 40 || sy < 40 || sx > geo.vbW - 40 || sy > geo.vbH - 40) centerOn(selIndex, view.k);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selIndex]);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const [x, y] = toSvg(e.clientX, e.clientY);
      zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, x, y);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [toSvg, zoomAt]);

  const tipItem = hover != null ? snap.items[hover] : null;
  const tipPos = useMemo(() => {
    if (hover == null || !svgRef.current || !wrap.current) return null;
    const [cx, cy] = geo.centers[hover];
    const r = svgRef.current.getBoundingClientRect();
    const w = wrap.current.getBoundingClientRect();
    const scale = Math.max(geo.vbW / r.width, geo.vbH / r.height);
    const ox = (r.width * scale - geo.vbW) / 2;
    const oy = (r.height * scale - geo.vbH) / 2;
    const px = (cx * view.k + view.x + ox) / scale + (r.left - w.left);
    const py = (cy * view.k + view.y + oy) / scale + (r.top - w.top);
    return { left: Math.min(px + 14, w.width - 250), top: Math.max(8, Math.min(py - 20, w.height - 210)) };
  }, [hover, view]);

  const timeKind = st.layer === "ds" && st.dsMode === "fc" ? `Forecast cho ${fmtTime(snap.envelope.forecast_ts)}` : `Quan sát lúc ${fmtTime(cutoff)}`;
  const layerItems: { id: "ds" | "delta"; label: string }[] = [
    { id: "ds", label: "Cung cầu (D/S)" },
    { id: "delta", label: "Hiệu chỉnh" },
  ];

  return (
    <div ref={wrap} className="relative h-full min-h-[360px] overflow-hidden rounded-[12px] border border-line bg-[#f2f4f8]">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${geo.vbW} ${geo.vbH}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full touch-none select-none"
        role="group"
        aria-label={`Bản đồ ${snap.items.length} vùng hex, lớp ${LAYER_TITLE[st.layer]}, ${timeKind}`}
        onPointerDown={(e) => {
          if ((e.target as Element).closest("[data-hex]")) return;
          drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
          (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const r = svgRef.current!.getBoundingClientRect();
          const scale = Math.max(geo.vbW / r.width, geo.vbH / r.height);
          const dx = (e.clientX - d.x) * scale;
          const dy = (e.clientY - d.y) * scale;
          if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
          setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
      >
        <defs>
          <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="7" height="7" fill="#eff1f5" />
            <line x1="0" y1="0" x2="0" y2="7" stroke="#a9b0bc" strokeWidth="2.2" />
          </pattern>
          <marker id="od-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--od)" />
          </marker>
          <filter id="sel-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`} style={{ transition: drag.current ? "none" : "transform 200ms ease-out" }}>
          {snap.items.map((it, i) => {
            const fill = fillFor(it, st.layer, st.dsMode);
            const op = operatorStatus(st, it);
            const sel = i === selIndex;
            const rec = REC_LABEL[it.proposal.status];
            const label = `${it.hex.zone_label} ${shortHex(it.hex.id)}. ${rec.label}. ${fill == null ? "Thiếu dữ liệu" : ""}`;
            return (
              <g
                key={it.hex.id}
                data-hex
                role="button"
                tabIndex={0}
                aria-label={label}
                aria-pressed={sel}
                className="cursor-pointer outline-none"
                onClick={() => select(it.hex.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    select(it.hex.id);
                  }
                }}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover((h) => (h === i ? null : h))}
                onFocus={() => setHover(i)}
                onBlur={() => setHover((h) => (h === i ? null : h))}
              >
                <path
                  d={geo.paths[i]}
                  fill={fill ?? "url(#hatch)"}
                  stroke={hover === i ? "#4c607c" : "#f4f6f9"}
                  strokeWidth={hover === i ? 2 : 1.4}
                  vectorEffect="non-scaling-stroke"
                  style={{ transition: "fill 200ms ease" }}
                />
                {it.proposal.status === "REVIEW" && (
                  <WarningCircle x={geo.centers[i][0] - 10} y={geo.centers[i][1] - 10} size={20} weight="fill" color="var(--review)" aria-hidden />
                )}
                {(op === "RECORDED" || op === "KEPT_BIDDING") && (
                  <CheckCircle x={geo.centers[i][0] - 10} y={geo.centers[i][1] - 10} size={20} weight="fill" color={op === "RECORDED" ? "var(--recorded)" : "var(--neutral)"} aria-hidden />
                )}
              </g>
            );
          })}

          {st.showAdj && (
            <g aria-hidden>
              {DATASET.adj.map(([a, b], n) => {
                const rel = selIndex < 0 || a === selIndex || b === selIndex;
                const [x1, y1] = geo.centers[a];
                const [x2, y2] = geo.centers[b];
                return <line key={n} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#4c607c" strokeOpacity={rel ? 0.45 : 0.08} strokeWidth={1} vectorEffect="non-scaling-stroke" />;
              })}
            </g>
          )}

          {st.showOD && (
            <g aria-hidden>
              {od.shown.map(([a, b, w], n) => {
                const [x1, y1] = geo.centers[a];
                const [x2, y2] = geo.centers[b];
                const mx = (x1 + x2) / 2 - (y2 - y1) * 0.18;
                const my = (y1 + y2) / 2 + (x2 - x1) * 0.18;
                return (
                  <path
                    key={n}
                    d={`M${x1},${y1} Q${mx},${my} ${x2},${y2}`}
                    fill="none"
                    stroke="var(--od)"
                    strokeOpacity={0.35 + 0.55 * (w / odMax)}
                    strokeWidth={1 + 2.5 * (w / odMax)}
                    vectorEffect="non-scaling-stroke"
                    markerEnd="url(#od-arrow)"
                  />
                );
              })}
            </g>
          )}

          {selIndex >= 0 && (
            <path
              d={geo.paths[selIndex]}
              fill="none"
              stroke="var(--focus)"
              strokeWidth={3}
              vectorEffect="non-scaling-stroke"
              filter="url(#sel-glow)"
              pointerEvents="none"
            />
          )}
        </g>
      </svg>

      {/* Toolbar lớp */}
      <div className="absolute left-3 top-3 flex flex-wrap items-center gap-2">
        <Tabs
          label="Lớp bản đồ"
          value={st.layer === "ds" || st.layer === "delta" ? st.layer : ("" as "ds")}
          onChange={(v) => set("layer", v)}
          items={layerItems}
        />
        {st.layer === "ds" && (
          <Tabs
            label="Loại thời gian D/S"
            size="sm"
            value={st.dsMode}
            onChange={(v) => set("dsMode", v)}
            items={[
              { id: "obs", label: `Quan sát ${fmtTime(cutoff)}` },
              { id: "fc", label: `Forecast ${fmtTime(snap.envelope.forecast_ts)}` },
            ]}
          />
        )}
        <div className="relative">
          <button
            type="button"
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen((v) => !v)}
            className={`inline-flex h-8 items-center gap-1.5 rounded-[8px] border px-2.5 text-xs ${
              st.layer === "demand" || st.layer === "supply" || st.showAdj ? "border-focus/60 text-ink" : "border-line text-ink-2"
            } bg-surface/90 hover:text-ink`}
          >
            <Stack size={14} /> Lớp khác <CaretDown size={11} />
          </button>
          {moreOpen && (
            <div className="absolute left-0 z-20 mt-1.5 w-[260px] rounded-[12px] border border-line bg-surface p-2 shadow-[0_16px_40px_rgba(250,251,253,0.55)]" onKeyDown={(e) => e.key === "Escape" && setMoreOpen(false)}>
              {(["demand", "supply"] as MapLayer[]).map((l) => (
                <label key={l} className="flex cursor-pointer items-start gap-2 rounded-[8px] px-2 py-1.5 hover:bg-surface-2">
                  <input type="radio" name="layer" className="mt-0.5 accent-[var(--focus)]" checked={st.layer === l} onChange={() => set("layer", l)} />
                  <span>
                    <span className="block text-xs text-ink">{l === "demand" ? "Demand" : "Supply hiệu dụng"}</span>
                    <span className="block text-[11px] text-ink-2">{l === "demand" ? "Request mới trong cửa sổ 5 phút" : "Effective supply, proxy theo contract, không phải idle"}</span>
                  </span>
                </label>
              ))}
              <div className="my-1 border-t border-line" />
              <label className="flex cursor-pointer items-start gap-2 rounded-[8px] px-2 py-1.5 hover:bg-surface-2">
                <input type="checkbox" className="mt-0.5 accent-[var(--focus)]" checked={st.showAdj} onChange={(e) => set("showAdj", e.target.checked)} />
                <span>
                  <span className="block text-xs text-ink">Quan hệ kề</span>
                  <span className="block text-[11px] text-ink-2">Lớp kỹ thuật. Kề không phải luồng di chuyển.</span>
                </span>
              </label>
            </div>
          )}
        </div>
        <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-[8px] border border-line bg-surface/90 px-2.5 text-xs text-ink-2 hover:text-ink">
          <input type="checkbox" className="accent-[var(--od)]" checked={st.showOD} onChange={(e) => set("showOD", e.target.checked)} />
          Luồng OD
        </label>
      </div>

      {/* Zoom */}
      <div className="absolute right-3 top-3 flex flex-col overflow-hidden rounded-[8px] border border-line bg-surface/90">
        <button type="button" aria-label="Phóng to" title="Phóng to" className="flex size-8 items-center justify-center text-ink-2 hover:bg-surface-2 hover:text-ink" onClick={() => zoomAt(1.3)}>
          <Plus size={14} />
        </button>
        <button type="button" aria-label="Thu nhỏ" title="Thu nhỏ" className="flex size-8 items-center justify-center border-t border-line text-ink-2 hover:bg-surface-2 hover:text-ink" onClick={() => zoomAt(1 / 1.3)}>
          <Minus size={14} />
        </button>
        <button type="button" aria-label="Vừa toàn miền" title="Vừa toàn miền" className="flex size-8 items-center justify-center border-t border-line text-ink-2 hover:bg-surface-2 hover:text-ink" onClick={() => setView(FIT)}>
          <ArrowsIn size={14} />
        </button>
        <button
          type="button"
          aria-label="Về vùng đang chọn"
          title="Về vùng đang chọn"
          disabled={selIndex < 0}
          className="flex size-8 items-center justify-center border-t border-line text-ink-2 hover:bg-surface-2 hover:text-ink disabled:opacity-40"
          onClick={() => selIndex >= 0 && centerOn(selIndex)}
        >
          <Crosshair size={14} />
        </button>
      </div>

      {/* Chú giải */}
      <div className="absolute bottom-3 left-3 max-w-[300px] rounded-[10px] border border-line bg-surface/92 text-[11px] backdrop-blur-sm">
        <button
          type="button"
          aria-expanded={legendOpen}
          onClick={() => setLegendOpen((v) => !v)}
          className="flex w-full items-center justify-between gap-3 px-2.5 py-1.5 text-left text-ink"
        >
          <span className="font-medium">
            {LAYER_TITLE[st.layer]} · <span className="text-ink-2">{st.layer === "delta" ? "điểm hệ số surge, chưa thực thi" : timeKind}</span>
          </span>
          {legendOpen ? <CaretDown size={11} /> : <CaretUp size={11} />}
        </button>
        {legendOpen && (
          <div className="space-y-1.5 border-t border-line px-2.5 pb-2 pt-1.5">
            <div className="h-2 rounded-full" style={{ background: st.layer === "ds" ? legendGradient.ds : st.layer === "delta" ? legendGradient.delta : legendGradient.seq }} />
            <div className="num flex justify-between text-ink-2">
              {st.layer === "ds" && (
                <>
                  <span>{DS_SCALE.min.toFixed(1)} dư cung</span>
                  <span>mốc {DS_SCALE.ref.toFixed(2)}</span>
                  <span>{DS_SCALE.max.toFixed(1)} thiếu cung</span>
                </>
              )}
              {st.layer === "delta" && (
                <>
                  <span>−0.40 giảm</span>
                  <span>0</span>
                  <span>+0.40 tăng</span>
                </>
              )}
              {(st.layer === "demand" || st.layer === "supply") && (
                <>
                  <span>0</span>
                  <span>{st.layer === "demand" ? `${DEMAND_MAX} request/5 phút` : `${SUPPLY_MAX.toFixed(0)} xe hiệu dụng`}</span>
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-2">
              <span className="inline-flex items-center gap-1">
                <span className="inline-block size-2.5 rounded-[2px]" style={{ background: "repeating-linear-gradient(45deg,#a9b0bc 0 2px,#eff1f5 2px 5px)" }} /> Thiếu dữ liệu
              </span>
              <span className="inline-flex items-center gap-1">
                <WarningCircle size={11} weight="fill" color="var(--review)" /> Cần xem xét
              </span>
              <span className="inline-flex items-center gap-1">
                <CheckCircle size={11} weight="fill" color="var(--recorded)" /> Đã ghi nhận
              </span>
            </div>
            {st.showOD && (
              <div className="text-ink-2">
                <span className="text-od">Luồng yêu cầu OD · trung bình theo giờ</span>, giờ{" "}
                {odHour == null ? "chưa có giờ hoàn tất" : `${String(odHour).padStart(2, "0")}:00 đến ${String(odHour + 1).padStart(2, "0")}:00`}, hướng nguồn tới đích. Không phải số tài xế đang đến.
              </div>
            )}
            <div className="text-[10px] text-[#717d90]">Không có nền đường phố. Vị trí hex theo tọa độ hcm_data_2. Thang {DS_SCALE.version}.</div>
          </div>
        )}
      </div>

      {/* Đếm cạnh OD */}
      {st.showOD && (
        <div className="absolute bottom-3 right-3 flex items-center gap-2 rounded-[8px] border border-line bg-surface/92 px-2.5 py-1.5 text-[11px] text-ink-2">
          <span className="num">
            {odHour == null ? "Chưa có OD giờ hoàn tất" : `Đang xem ${od.shown.length}/${od.total} cạnh${selIndex >= 0 ? " liên quan vùng chọn" : ""}`}
          </span>
          {od.total > OD_LIMIT && (
            <button type="button" className="text-focus hover:underline" onClick={() => set("odExpanded", !st.odExpanded)}>
              {st.odExpanded ? "Thu gọn" : "Xem thêm"}
            </button>
          )}
        </div>
      )}

      {/* Tooltip, cả khi hover lẫn focus */}
      {tipItem && tipPos && (
        <div role="tooltip" className="pointer-events-none absolute z-30 w-[236px] rounded-[10px] border border-line bg-surface/97 p-2.5 text-[11px] shadow-[0_12px_32px_rgba(250,251,253,0.6)]" style={tipPos}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-ink">
              {tipItem.hex.zone_label} · <span className="num">{shortHex(tipItem.hex.id)}</span>
            </span>
            <span style={{ color: `var(--${REC_LABEL[tipItem.proposal.status].tone === "up" ? "increase" : REC_LABEL[tipItem.proposal.status].tone === "down" ? "decrease" : REC_LABEL[tipItem.proposal.status].tone === "review" ? "review" : "neutral"})` }} className="font-semibold">
              {REC_LABEL[tipItem.proposal.status].label}
            </span>
          </div>
          <div className="mb-1 text-ink-2">{timeKind}</div>
          <div className="num grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5">
            <span className="font-sans text-ink-2">D/S quan sát</span>
            <span>{fmtNum(tipItem.market.observed_ratio.value)}</span>
            <span className="font-sans text-ink-2">Graph t+5</span>
            <span>{fmtNum(tipItem.forecast.graph.value)}</span>
            <span className="font-sans text-ink-2">Demand</span>
            <span>{fmtNum(tipItem.market.demand.value, 0)}</span>
            <span className="font-sans text-ink-2">Supply hiệu dụng</span>
            <span>{fmtNum(tipItem.market.effective_supply.value, 1)}</span>
            <span className="font-sans text-ink-2">Bidding</span>
            <span>{fmtSurge(tipItem.proposal.s_bid)}</span>
            <span className="font-sans text-ink-2">Đề xuất</span>
            <span>
              {fmtSurge(tipItem.proposal.s_final)} ({fmtSigned(tipItem.proposal.delta_applied)})
            </span>
          </div>
          {fillFor(tipItem, st.layer, st.dsMode) == null && <div className="mt-1 text-review">Thiếu dữ liệu cho lớp này</div>}
        </div>
      )}
    </div>
  );
}
