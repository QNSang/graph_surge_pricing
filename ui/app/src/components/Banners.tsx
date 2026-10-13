import { ArrowClockwise, ClockCounterClockwise, Plugs, Warning, WifiSlash } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";
import { fmtTime } from "../domain/format";
import { useSnapshot } from "../state/hooks";
import { DATASET, useStore } from "../state/store";
import { Button } from "./ui/primitives";

function Bar({ tone, icon, children, action }: { tone: string; icon: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-4 py-1.5 text-xs"
      style={{ borderColor: `color-mix(in srgb, ${tone} 35%, transparent)`, background: `color-mix(in srgb, ${tone} 9%, var(--bg))` }}
    >
      <span className="shrink-0" style={{ color: tone }}>
        {icon}
      </span>
      <span className="min-w-0 flex-1 text-ink">{children}</span>
      {action}
    </div>
  );
}

export function Banners() {
  const snap = useSnapshot();
  const { online, viewMode, newSnapshotAt, head, t } = useStore(
    useShallow((s) => ({ online: s.online, viewMode: s.viewMode, newSnapshotAt: s.newSnapshotAt, head: s.head, t: s.t })),
  );
  const goLatest = useStore((s) => s.goLatest);
  const loadLatest = useStore((s) => s.loadLatest);
  const setOnline = useStore((s) => s.setOnline);

  return (
    <div aria-live="polite">
      {!online && (
        <Bar
          tone="var(--review)"
          icon={<WifiSlash size={15} />}
          action={
            <Button size="sm" onClick={() => setOnline(true)}>
              Kết nối lại
            </Button>
          }
        >
          Mất kết nối. Đang giữ snapshot cuối lúc <span className="num">{fmtTime(snap.envelope.cutoff_ts)}</span>, dữ liệu có thể đã cũ. Mọi thao tác có thể đổi giá bị khóa.
        </Bar>
      )}
      {!snap.contract_ok && (
        <Bar tone="var(--increase)" icon={<Plugs size={15} />}>
          Hợp đồng metric không khớp. {snap.contract_issue} Mọi đề xuất bị chặn; UI không tự đổi thang để hợp thức hóa.
        </Bar>
      )}
      {viewMode === "LATEST" && newSnapshotAt && t < head && (
        <Bar
          tone="var(--focus)"
          icon={<ArrowClockwise size={15} />}
          action={
            <Button size="sm" variant="primary" onClick={loadLatest}>
              Tải snapshot mới
            </Button>
          }
        >
          Có đề xuất mới · <span className="num">{fmtTime(newSnapshotAt)}</span>. Đề xuất đang xem đã bị thay thế và bị khóa thao tác. Danh sách chọn batch sẽ được xóa khi tải.
        </Bar>
      )}
      {viewMode === "REPLAY" && (
        <Bar
          tone="var(--focus)"
          icon={<ClockCounterClockwise size={15} />}
          action={
            <Button size="sm" onClick={goLatest}>
              Về mới nhất
            </Button>
          }
        >
          Đang xem replay lúc <span className="num">{fmtTime(snap.envelope.cutoff_ts)}</span>, chỉ đọc. Snapshot mới nhất là{" "}
          <span className="num">{fmtTime(DATASET.stamps[head])}</span>.
        </Bar>
      )}
      {snap.items.length === 0 && (
        <Bar tone="var(--review)" icon={<Warning size={15} />}>
          Snapshot không có vùng nào.
        </Bar>
      )}
    </div>
  );
}
