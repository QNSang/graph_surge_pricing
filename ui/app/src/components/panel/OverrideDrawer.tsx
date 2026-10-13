import { useEffect, useId, useState } from "react";
import type { HexSnapshot } from "../../domain/types";
import { canonical, fmtSigned, fmtSurge } from "../../domain/format";
import { useStore } from "../../state/store";
import { Button, Dialog } from "../ui/primitives";

/** Điều chỉnh thủ công: bước, biên và độ lệch lấy từ eligibility.limits do server cấp, không tự đặt ở client. */
export function OverrideDrawer({ item, open, onClose }: { item: HexSnapshot; open: boolean; onClose: () => void }) {
  const lim = item.eligibility.limits;
  const base = item.proposal.s_bid;
  const submit = useStore((s) => s.submit);
  const [value, setValue] = useState<string>("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const vid = useId();
  const rid = useId();

  useEffect(() => {
    if (open) {
      const start = item.proposal.s_final ?? base;
      if (start == null || !lim || base == null) setValue(start != null ? start.toFixed(2) : "");
      else {
        // Model output may sit off the manual step grid (e.g. 1.61); start from the nearest valid step in range.
        const lo = Math.max(lim.min, base - lim.max_deviation), hi = Math.min(lim.max, base + lim.max_deviation);
        const snapped = Math.min(Math.floor(hi / lim.step + 1e-9) * lim.step, Math.max(Math.ceil(lo / lim.step - 1e-9) * lim.step, Math.round(start / lim.step) * lim.step));
        setValue(snapped.toFixed(lim.precision));
      }
      setReason("");
      setBusy(false);
    }
  }, [open, item, lim, base]);

  if (!lim || base == null) {
    return (
      <Dialog open={open} onClose={onClose} title="Điều chỉnh thủ công" width={460}>
        <p className="text-xs text-ink-2">Server chưa cấp giới hạn điều chỉnh hoặc thiếu bidding hợp lệ. Không thể điều chỉnh đề xuất này.</p>
      </Dialog>
    );
  }

  const lo = Math.max(lim.min, base - lim.max_deviation);
  const hi = Math.min(lim.max, base + lim.max_deviation);
  const num = Number(value);
  const onStep = Number.isFinite(num) && Math.abs(Math.round(num / lim.step) * lim.step - num) < 1e-9;
  let error: string | null = null;
  if (value.trim() === "" || !Number.isFinite(num)) error = "Nhập hệ số surge.";
  else if (num < lo - 1e-9 || num > hi + 1e-9) error = `Ngoài khoảng cho phép ×${lo.toFixed(2)} đến ×${hi.toFixed(2)}.`;
  else if (!onStep) error = `Giá trị phải theo bước ${lim.step.toFixed(2)}.`;
  const stepTo = (dir: 1 | -1) => {
    const cur = Number.isFinite(Number(value)) && value.trim() !== "" ? Number(value) : base;
    const k = cur / lim.step;
    const next = (dir > 0 ? Math.floor(k + 1e-9) + 1 : Math.ceil(k - 1e-9) - 1) * lim.step;
    setValue(Math.min(Math.floor(hi / lim.step + 1e-9) * lim.step, Math.max(Math.ceil(lo / lim.step - 1e-9) * lim.step, next)).toFixed(lim.precision));
  };
  const reasonErr = reason.trim().length < 5 ? "Lý do bắt buộc, tối thiểu 5 ký tự." : null;
  const can = !error && !reasonErr && !busy;

  const send = async () => {
    if (!can) return;
    setBusy(true);
    await submit(item, "OVERRIDE_PROPOSAL", num, reason.trim());
    setBusy(false);
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Điều chỉnh thủ công"
      width={480}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Hủy
          </Button>
          <Button variant="primary" disabled={!can} title={error ?? reasonErr ?? undefined} onClick={send}>
            {busy ? "Đang gửi" : `Ghi nhận demo ${Number.isFinite(num) ? fmtSurge(num) : ""}`}
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-xs">
        <div className="grid grid-cols-3 gap-2 rounded-[8px] bg-bg/50 p-3">
          <div>
            <div className="text-ink-2">Bidding</div>
            <div className="num text-sm text-ink">{fmtSurge(base)}</div>
          </div>
          <div>
            <div className="text-ink-2">Model đề xuất</div>
            <div className="num text-sm text-ink">{fmtSurge(item.proposal.s_final)}</div>
          </div>
          <div>
            <div className="text-ink-2">Khoảng cho phép</div>
            <div className="num text-sm text-ink">
              ×{lo.toFixed(2)} đến ×{hi.toFixed(2)}
            </div>
          </div>
        </div>

        <div>
          <label htmlFor={vid} className="mb-1 block font-medium text-ink">
            Hệ số surge
          </label>
          <div className="flex items-center gap-2">
            <Button variant="secondary" aria-label={`Giảm ${lim.step}`} onClick={() => stepTo(-1)}>
              −{lim.step.toFixed(2)}
            </Button>
            <input
              id={vid}
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-invalid={!!error}
              aria-describedby={`${vid}-hint`}
              className="num h-9 w-28 rounded-[8px] border border-line bg-bg px-3 text-center text-sm text-ink outline-none focus:border-focus"
            />
            <Button variant="secondary" aria-label={`Tăng ${lim.step}`} onClick={() => stepTo(1)}>
              +{lim.step.toFixed(2)}
            </Button>
          </div>
          <div id={`${vid}-hint`} className={`mt-1 ${error ? "text-review" : "text-ink-2"}`}>
            {error ??
              `Gửi lên server dạng "${canonical(num, lim.precision)}", lệch ${fmtSigned(num - base)} điểm so với bidding. Bước ${lim.step.toFixed(2)}, lệch tối đa ${lim.max_deviation.toFixed(2)}.`}
          </div>
        </div>

        <div>
          <label htmlFor={rid} className="mb-1 block font-medium text-ink">
            Lý do điều chỉnh <span className="font-normal text-ink-2">(bắt buộc, tối thiểu 5 ký tự)</span>
          </label>
          <textarea
            id={rid}
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-invalid={!!reasonErr}
            className="w-full resize-none rounded-[8px] border border-line bg-bg px-3 py-2 text-xs text-ink outline-none focus:border-focus"
            placeholder="Ví dụ: sự kiện tại sân vận động chưa có trong dữ liệu"
          />
          {reason.length > 0 && reasonErr && <div className="mt-1 text-review">{reasonErr}</div>}
          {reason.length > 0 && !reasonErr && <div className="mt-1 text-ink-2">{reason.trim().length} ký tự</div>}
        </div>
        <p className="text-[11px] text-ink-2">Chế độ DEMO: chỉ ghi nhận quyết định, không gửi giá tới hệ thống thật.</p>
      </div>
    </Dialog>
  );
}
