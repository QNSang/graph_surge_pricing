export const TZ = "Asia/Ho_Chi_Minh";

const timeFmt = new Intl.DateTimeFormat("vi-VN", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const dateFmt = new Intl.DateTimeFormat("vi-VN", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric" });
const wdFmt = new Intl.DateTimeFormat("vi-VN", { timeZone: TZ, weekday: "short" });

export const fmtTime = (iso: string) => timeFmt.format(new Date(iso));
export const fmtDate = (iso: string) => dateFmt.format(new Date(iso));
export const fmtDateTime = (iso: string) => `${fmtTime(iso)} ${fmtDate(iso)}`;
export const fmtWeekdayDate = (iso: string) => `${wdFmt.format(new Date(iso))}, ${fmtDate(iso)}`;

export const fmtSurge = (v: number | null | undefined, digits = 2) =>
  v == null || !Number.isFinite(v) ? "Thiếu" : `×${v.toFixed(digits)}`;

export const fmtSigned = (v: number | null | undefined, digits = 2) => {
  if (v == null || !Number.isFinite(v)) return "Thiếu";
  const r = Number(v.toFixed(digits));
  if (r === 0) return (0).toFixed(digits);
  return `${r > 0 ? "+" : "−"}${Math.abs(r).toFixed(digits)}`;
};

export const fmtPct = (v: number | null | undefined, digits = 1) =>
  v == null || !Number.isFinite(v) ? "Thiếu" : `${fmtSigned(v * 100, digits)}%`;

export const fmtNum = (v: number | null | undefined, digits = 2) =>
  v == null || !Number.isFinite(v) ? "Thiếu" : v.toFixed(digits);

/** Canonical decimal string gửi lên server; tách khỏi định dạng hiển thị. */
export const canonical = (v: number, precision: number) => v.toFixed(precision);

export const shortHex = (id: string) => id.slice(2, 9);

export const uid = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
