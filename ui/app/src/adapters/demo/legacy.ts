// Adapter cho payload prototype v0.1 (ui/data.json, spec mục 6.1).
// Payload chỉ có HH:MM; adapter dựng full timestamp +07:00 và xử lý 00:00 đóng cửa sổ cuối thuộc ngày kế tiếp.

import type { Hex } from "../../domain/types";

export interface LegacyPayload {
  day: string;
  ts: string[];
  hexes: { id: string; zone: string; ring: number; lat: number; lng: number; poly: [number, number][] }[];
  D: number[][];
  S: number[][];
  I: number[][];
  surge: number[][];
  npress: number[][];
  eta: number[][];
  adj: [number, number][];
  od: [number, number, number][][];
}

export interface LegacyDataset {
  day: string;
  stamps: string[];
  hexes: Hex[];
  neighbors: number[][];
  adj: [number, number][];
  raw: LegacyPayload;
}

export const ZONE_LABEL: Record<string, string> = {
  cbd: "Trung tâm",
  airport: "Sân bay",
  office: "Văn phòng",
  residential: "Dân cư",
  suburb: "Ngoại ô",
  venue: "Sự kiện",
};

const OFFSET = "+07:00";

function addDays(day: string, n: number) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** HH:MM theo thứ tự -> ISO có offset. Khi giờ quay ngược (00:00 sau 23:55) thì sang ngày kế. */
export function toStamps(day: string, hhmm: string[]): string[] {
  let dayOffset = 0;
  let prev = -1;
  return hhmm.map((s) => {
    const [h, m] = s.split(":").map(Number);
    const minutes = h * 60 + m;
    if (minutes <= prev) dayOffset += 1;
    prev = minutes;
    return `${addDays(day, dayOffset)}T${s}:00${OFFSET}`;
  });
}

export function loadLegacy(raw: LegacyPayload): LegacyDataset {
  const hexes: Hex[] = raw.hexes.map((h, index) => ({
    ...h,
    index,
    zone_label: ZONE_LABEL[h.zone] ?? h.zone,
  }));
  const neighbors = hexes.map(() => [] as number[]);
  for (const [a, b] of raw.adj) {
    if (!neighbors[a].includes(b)) neighbors[a].push(b);
    if (!neighbors[b].includes(a)) neighbors[b].push(a);
  }
  return { day: raw.day, stamps: toStamps(raw.day, raw.ts), hexes, neighbors, adj: raw.adj, raw };
}

/** Giờ OD đã kết thúc trước cutoff (as-of đúng), tránh dùng cả giờ chưa xong. */
export function completedOdHour(stamp: string): number | null {
  const [h, m] = stamp.slice(11, 16).split(":").map(Number);
  const minutes = h * 60 + m;
  const hour = Math.floor(minutes / 60) - 1;
  if (stamp.slice(11, 16) === "00:00") return 23; // 00:00 ngày kế đóng giờ 23
  return hour >= 0 ? hour : null;
}
