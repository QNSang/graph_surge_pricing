import { useEffect, useState } from "react";
import { CheckCircle, Question, SpinnerGap, XCircle } from "@phosphor-icons/react";
import type { HexSnapshot } from "../../domain/types";
import { fmtSigned, fmtSurge, fmtTime, shortHex } from "../../domain/format";
import { REC_LABEL, TONE_VAR } from "../../domain/labels";
import { useStore, type BatchOutcome } from "../../state/store";
import { Button, Dialog } from "../ui/primitives";

const OUTCOME = {
  RECORDED: { label: "Đã ghi nhận demo", icon: <CheckCircle size={14} weight="fill" />, color: "var(--recorded)" },
  FAILED: { label: "Lỗi", icon: <XCircle size={14} weight="fill" />, color: "var(--increase)" },
  UNKNOWN: { label: "Chưa xác định, đang tra cứu", icon: <Question size={14} weight="fill" />, color: "var(--review)" },
} as const;

/** Rà soát đúng tập ID, giá và hạn trước khi gửi; sau đó hiện kết quả từng item, không gộp thành "thành công". */
export function BatchReview({ open, onClose, items }: { open: boolean; onClose: () => void; items: HexSnapshot[] }) {
  const submitBatch = useStore((s) => s.submitBatch);
  const [list, setList] = useState<HexSnapshot[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BatchOutcome | null>(null);

  useEffect(() => {
    if (open) {
      setList(items);
      setResult(null);
      setBusy(false);
    }
    // Chỉ chụp tập item lúc mở; thay đổi sau đó không lẳng lặng đổi nội dung rà soát.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const send = async () => {
    setBusy(true);
    const r = await submitBatch(list);
    setResult(r);
    setBusy(false);
  };

  const byId = new Map(result?.results.map((r) => [r.proposal_id, r]) ?? []);
  const n = (k: "RECORDED" | "FAILED" | "UNKNOWN") => result?.results.filter((r) => r.outcome === k).length ?? 0;
  const earliest = list.reduce<string | null>((a, it) => (it.eligibility.expires_at && (!a || it.eligibility.expires_at < a) ? it.eligibility.expires_at : a), null);

  return (
    <Dialog
      open={open}
      onClose={busy ? () => {} : onClose}
      title={result ? "Kết quả batch" : `Rà soát ${list.length} đề xuất`}
      width={640}
      footer={
        result ? (
          <Button variant="primary" onClick={onClose}>
            Đóng
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Quay lại
            </Button>
            <Button variant="primary" onClick={send} disabled={busy || list.length === 0}>
              {busy && <SpinnerGap size={14} className="animate-spin" />}
              Xác nhận demo {list.length} đề xuất
            </Button>
          </>
        )
      }
    >
      <div className="space-y-3 text-xs">
        {result ? (
          <div className="flex flex-wrap gap-3 rounded-[8px] bg-bg/50 px-3 py-2">
            {(["RECORDED", "FAILED", "UNKNOWN"] as const).map((k) => (
              <span key={k} className="inline-flex items-center gap-1.5" style={{ color: OUTCOME[k].color }}>
                {OUTCOME[k].icon}
                <span className="text-ink">
                  {OUTCOME[k].label}: <span className="num">{n(k)}</span>
                </span>
              </span>
            ))}
          </div>
        ) : (
          <p className="text-ink-2">
            Mỗi đề xuất được server kiểm lại version và điều kiện lúc gửi. Hạn sớm nhất{" "}
            <span className="num text-ink">{earliest ? fmtTime(earliest) : "Thiếu"}</span>. DEMO chỉ ghi nhận, không gửi giá thật.
          </p>
        )}
        <table className="w-full border-collapse">
          <thead className="text-[11px] text-ink-2">
            <tr className="border-b border-line">
              <th className="py-1.5 text-left font-normal">Vùng</th>
              <th className="py-1.5 text-left font-normal">Mã đề xuất</th>
              <th className="py-1.5 text-right font-normal">Bidding → đề xuất</th>
              <th className="py-1.5 text-right font-normal">Delta</th>
              <th className="py-1.5 text-right font-normal">{result ? "Kết quả" : "Hạn"}</th>
            </tr>
          </thead>
          <tbody>
            {list.map((it) => {
              const r = byId.get(it.proposal.proposal_id);
              const rec = REC_LABEL[it.proposal.status];
              return (
                <tr key={it.proposal.proposal_id} className="border-b border-line/60 align-top">
                  <td className="py-1.5">
                    {it.hex.zone_label} <span className="num text-[11px] text-ink-2">{shortHex(it.hex.id)}</span>
                  </td>
                  <td className="num py-1.5 text-[11px] text-ink-2">{it.proposal.proposal_id}</td>
                  <td className="num py-1.5 text-right">
                    <span className="text-ink-2">{fmtSurge(it.proposal.s_bid)}</span> → {fmtSurge(it.proposal.s_final)}
                  </td>
                  <td className="num py-1.5 text-right" style={{ color: TONE_VAR[rec.tone] }}>
                    {fmtSigned(it.proposal.delta_applied)}
                  </td>
                  <td className="py-1.5 text-right">
                    {r ? (
                      <span className="inline-flex flex-col items-end">
                        <span className="inline-flex items-center gap-1" style={{ color: OUTCOME[r.outcome].color }}>
                          {OUTCOME[r.outcome].icon}
                          {OUTCOME[r.outcome].label}
                        </span>
                        {r.error && <span className="text-[11px] text-ink-2">{r.error}</span>}
                      </span>
                    ) : (
                      <span className="num text-ink-2">{it.eligibility.expires_at ? fmtTime(it.eligibility.expires_at) : "Thiếu"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {result && n("FAILED") > 0 && <p className="text-ink-2">Các đề xuất lỗi vẫn ở trạng thái chờ. Mở từng vùng để xem lại trước khi gửi lại.</p>}
      </div>
    </Dialog>
  );
}
