import { useEffect, useRef, useState } from "react";
import { CaretDown, Check, Flask, Hexagon, WifiHigh, WifiSlash } from "@phosphor-icons/react";
import { SCENARIOS } from "../adapters/demo/scenarios";
import { fmtTime, fmtWeekdayDate } from "../domain/format";
import { useCounts, useSnapshot } from "../state/hooks";
import { useStore } from "../state/store";
import { Button, Chip } from "./ui/primitives";

function Metric({ label, value, scope, tone }: { label: string; value: number; scope: string; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col leading-tight" title={scope}>
      <span className="truncate text-[11px] text-ink-2">{label}</span>
      <span className="num text-[15px] font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </div>
  );
}

function ScenarioMenu() {
  const [open, setOpen] = useState(false);
  const scenarioId = useStore((s) => s.scenarioId);
  const setScenario = useStore((s) => s.setScenario);
  const ref = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const current = SCENARIOS.find((s) => s.id === scenarioId)!;
  return (
    <div className="relative" ref={ref}>
      <button
        ref={btn}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 max-w-[240px] items-center gap-2 rounded-[8px] border border-line bg-surface-2 px-2.5 text-xs text-ink hover:border-[#b1bac9]"
      >
        <Flask size={14} className="shrink-0 text-ink-2" />
        <span className="truncate">Kịch bản: {current.label}</span>
        <CaretDown size={12} className="shrink-0 text-ink-2" />
      </button>
      {open && (
        <div role="menu" aria-label="Kịch bản demo" className="absolute right-0 z-40 mt-1.5 w-[340px] rounded-[12px] border border-line bg-surface p-1.5 shadow-[0_16px_40px_rgba(250,251,253,0.55)]">
          <div className="px-2.5 pb-1.5 pt-1 text-[11px] text-ink-2">Kịch bản minh họa. Số liệu tính qua controller demo có version.</div>
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              role="menuitemradio"
              aria-checked={s.id === scenarioId}
              type="button"
              onClick={() => {
                setScenario(s.id);
                setOpen(false);
                btn.current?.focus();
              }}
              className="flex w-full items-start gap-2 rounded-[8px] px-2.5 py-2 text-left hover:bg-surface-2"
            >
              <span className="mt-0.5 w-3.5 shrink-0 text-focus">{s.id === scenarioId && <Check size={14} weight="bold" />}</span>
              <span className="min-w-0">
                <span className="block text-xs font-medium text-ink">{s.label}</span>
                <span className="block text-[11px] leading-snug text-ink-2">{s.description}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Header() {
  const snap = useSnapshot();
  const { envelope } = snap;
  const counts = useCounts();
  const viewMode = useStore((s) => s.viewMode);
  const online = useStore((s) => s.online);
  const setOnline = useStore((s) => s.setOnline);
  const publishNext = useStore((s) => s.publishNext);
  const head = useStore((s) => s.head);

  return (
    <header className="flex min-h-[60px] flex-wrap items-center gap-x-5 gap-y-2 border-b border-line bg-surface px-4 py-2">
      <div className="flex items-center gap-2.5">
        <div className="flex size-8 items-center justify-center rounded-[8px] bg-surface-2 text-focus">
          <Hexagon size={18} weight="duotone" />
        </div>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold tracking-tight">Surge Control</div>
          <div className="text-[11px] text-ink-2">{envelope.region_label} · {snap.items.length} vùng hex</div>
        </div>
      </div>

      <div className="flex min-w-0 flex-col leading-tight">
        <span className="text-[12px] font-medium capitalize">{fmtWeekdayDate(envelope.cutoff_ts)}</span>
        <span className="num text-[11px] text-ink-2">
          Dữ liệu lúc {fmtTime(envelope.cutoff_ts)} · Dự báo cho {fmtTime(envelope.forecast_ts)} (+{snap.model.forecast_horizon_min} phút)
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5" aria-label="Ngữ cảnh dữ liệu">
        <Chip tone="muted">Dữ liệu mô phỏng</Chip>
        <Chip tone={viewMode === "REPLAY" ? "focus" : "muted"}>{viewMode === "REPLAY" ? "Đang xem replay" : "Snapshot mới nhất"}</Chip>
        <Chip tone="review">DEMO · forecast giả lập</Chip>
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-5 border-r border-line pr-5 max-[1279px]:hidden">
          <Metric label="Vùng cần xem xét" value={counts.review} scope="Trong snapshot đang xem" tone="var(--review)" />
          <Metric label="Đề xuất hợp lệ đang chờ" value={counts.eligiblePending} scope="Trong snapshot đang xem, chưa có quyết định" />
          <Metric label="Quyết định đã ghi nhận" value={counts.recorded} scope="Trong phiên demo này, chưa phải đã có hiệu lực" />
        </div>
        <Button size="sm" variant="ghost" onClick={publishNext} disabled={head >= 287} title="Phát hành snapshot kế tiếp như khi dữ liệu mới đến">
          Mô phỏng snapshot mới
        </Button>
        <button
          type="button"
          onClick={() => setOnline(!online)}
          aria-pressed={!online}
          title={online ? "Đang kết nối. Bấm để mô phỏng mất kết nối." : "Mất kết nối. Bấm để kết nối lại."}
          className="inline-flex h-8 items-center gap-1.5 rounded-[8px] px-2 text-xs hover:bg-surface-2"
          style={{ color: online ? "var(--recorded)" : "var(--review)" }}
        >
          {online ? <WifiHigh size={15} /> : <WifiSlash size={15} />}
          <span>{online ? "Đã kết nối" : "Mất kết nối"}</span>
        </button>
        <ScenarioMenu />
      </div>
    </header>
  );
}
