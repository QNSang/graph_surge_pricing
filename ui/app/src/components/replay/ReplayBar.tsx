import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { ArrowLineRight, CaretLeft, CaretRight, Eye, Pause, Play } from "@phosphor-icons/react";
import { fmtTime, fmtWeekdayDate } from "../../domain/format";
import { DATASET, useStore, type Speed } from "../../state/store";
import { Button, IconButton } from "../ui/primitives";

const LAST = DATASET.stamps.length - 1;
const pct = (i: number) => `${(i / LAST) * 100}%`;
const HOURS = [0, 3, 6, 9, 12, 15, 18, 21];

export function ReplayBar() {
  const { t, head, viewMode, playing, speed, lookAhead, audit } = useStore(
    useShallow((s) => ({ t: s.t, head: s.head, viewMode: s.viewMode, playing: s.playing, speed: s.speed, lookAhead: s.lookAhead, audit: s.audit })),
  );
  const { seek, step, setPlaying, setSpeed, goLatest, setLookAhead } = useStore.getState();

  // Mốc quyết định chỉ lấy từ audit của phiên demo, không tạo mốc giả.
  const markers = useMemo(() => {
    const m = new Map<number, number>();
    for (const e of audit) {
      const i = DATASET.stamps.indexOf(e.cutoff_ts);
      if (i >= 0) m.set(i, (m.get(i) ?? 0) + 1);
    }
    return [...m.entries()];
  }, [audit]);

  const stamp = DATASET.stamps[t];
  const canLook = t + 1 <= head;

  const onKey = (e: React.KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (e.key === " " && tag !== "BUTTON" && tag !== "INPUT") {
      e.preventDefault();
      setPlaying(!playing);
    }
  };

  return (
    <section
      aria-label="Replay"
      onKeyDown={onKey}
      tabIndex={-1}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-surface px-4 py-2.5 outline-none min-[1100px]:min-h-[84px] min-[1100px]:flex-nowrap"
    >
      <div className="flex items-center gap-2">
        <span
          className="rounded-[6px] px-1.5 py-0.5 text-[10px] font-bold tracking-wider"
          style={{ color: viewMode === "REPLAY" ? "var(--focus)" : "var(--text-2)", background: viewMode === "REPLAY" ? "color-mix(in srgb, var(--focus) 16%, transparent)" : "var(--surface-2)" }}
        >
          {viewMode === "REPLAY" ? "REPLAY" : "MỚI NHẤT"}
        </span>
        <div className="flex items-center">
          <IconButton label="Lùi 5 phút" onClick={() => step(-1)} disabled={t <= 0}>
            <CaretLeft size={16} />
          </IconButton>
          <IconButton label={playing ? "Dừng" : "Phát"} onClick={() => setPlaying(!playing)} className="text-ink">
            {playing ? <Pause size={16} weight="fill" /> : <Play size={16} weight="fill" />}
          </IconButton>
          <IconButton label="Tiến 5 phút" onClick={() => step(1)} disabled={t >= head}>
            <CaretRight size={16} />
          </IconButton>
        </div>
        <div className="min-w-[132px] leading-tight">
          <div className="num text-[15px] font-semibold">{fmtTime(stamp)}</div>
          <div className="text-[11px] capitalize text-ink-2">{fmtWeekdayDate(stamp)}</div>
        </div>
      </div>

      <div className="relative order-last min-w-[240px] flex-1 basis-full pb-4 min-[1100px]:order-none min-[1100px]:basis-auto">
        <div className="relative h-6">
          {/* Track: phần đã có dữ liệu tới snapshot mới nhất; sau đó là tương lai, không chọn được. */}
          <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-surface-2" />
          <div className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[#d4dae3]" style={{ width: pct(head) }} />
          <div className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-focus/70" style={{ width: pct(t) }} />
          {markers.map(([i, n]) => (
            <span
              key={i}
              title={`${n} sự kiện quyết định lúc ${fmtTime(DATASET.stamps[i])}`}
              className="absolute top-0 h-2 w-0.5 -translate-x-1/2 rounded-full bg-ok"
              style={{ left: pct(i) }}
            />
          ))}
          <span className="absolute top-1/2 h-3.5 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-ink-2" style={{ left: pct(head) }} title="Snapshot mới nhất" />
          <input
            type="range"
            min={0}
            max={LAST}
            step={1}
            value={t}
            aria-label="Thời điểm xem"
            aria-valuetext={`${fmtTime(stamp)}, ${fmtWeekdayDate(stamp)}`}
            onChange={(e) => seek(Math.min(head, Number(e.target.value)))}
            className="replay-range absolute inset-0 w-full cursor-pointer appearance-none bg-transparent"
          />
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-3.5 text-[10px] text-ink-2">
          {HOURS.map((h) => (
            <span key={h} className="num absolute -translate-x-1/2" style={{ left: pct(h * 12 - 1 < 0 ? 0 : h * 12 - 1) }}>
              {String(h).padStart(2, "0")}:00
            </span>
          ))}
          <span className="num absolute -translate-x-1/2 text-ink" style={{ left: pct(head) }}>
            {fmtTime(DATASET.stamps[head])}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-[8px] bg-bg/60 p-0.5" role="radiogroup" aria-label="Tốc độ phát" title="1× là một snapshot mỗi giây, không phải thời gian thật">
          {([1, 4, 12] as Speed[]).map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={speed === s}
              onClick={() => setSpeed(s)}
              className={`num h-7 rounded-[6px] px-2 text-xs ${speed === s ? "bg-surface-2 text-ink shadow-[inset_0_0_0_1px_var(--border)]" : "text-ink-2 hover:text-ink"}`}
            >
              {s}×
            </button>
          ))}
        </div>
        <span className="text-[11px] text-ink-2 max-[1439px]:hidden">1× = 1 snapshot/giây</span>
        <Button
          size="sm"
          variant={lookAhead ? "primary" : "secondary"}
          aria-pressed={lookAhead}
          onClick={() => setLookAhead(!lookAhead)}
          disabled={!canLook && !lookAhead}
          title={canLook ? "Giữ forecast và cutoff, mở quan sát tại thời điểm dự báo" : "Chưa có quan sát sau 5 phút cho thời điểm này"}
        >
          <Eye size={14} /> Xem lại sau 5 phút
        </Button>
        {viewMode === "REPLAY" && (
          <Button size="sm" variant="secondary" onClick={goLatest}>
            <ArrowLineRight size={14} /> Về mới nhất
          </Button>
        )}
      </div>
    </section>
  );
}
