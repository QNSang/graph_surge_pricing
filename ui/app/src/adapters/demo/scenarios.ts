// Scenario fixtures DEMO (spec mục 7.2). Số liệu fixture được tính qua controller demo có version,
// không chép số từ ảnh mockup.

import type { DemoPolicy } from "./policy";

export type ServiceMode = "normal" | "timeout" | "partial";

export interface HexOverride {
  dsLocal?: number | null;
  dsGraph?: number | null;
  bid?: number | null;
  support?: number;
  demand?: number | null;
  policy?: Partial<DemoPolicy> & { policy_version: string };
  forceReview?: string[];
}

export interface Scenario {
  id: string;
  label: string;
  description: string;
  service: ServiceMode;
  offline?: boolean;
  contractMismatch?: boolean;
  /** Tự phát hành snapshot mới sau N giây (kiểm stale/superseded). */
  autoAdvanceSec?: number;
  /** Chỉ số hex cố định cho fixture; adapter chọn hex đầu tiên của zone cbd. */
  override?: (hexIndex: number, featured: number, t: number) => HexOverride | null;
}

export const SCENARIOS: Scenario[] = [
  {
    id: "day",
    label: "Ngày mô phỏng 27/01",
    description: "Dữ liệu synthetic hcm_data_2, forecast heuristic DEMO. Gồm đủ tăng, giảm, giữ và cần xem xét tự nhiên.",
    service: "normal",
  },
  {
    id: "report-11-1",
    label: "Ví dụ báo cáo mục 11.1",
    description: "Local 2.00, Graph 1.60, mốc 1.20, bidding 1.30. Kỳ vọng 1.30 đến 1.38, phần Pressure +0.14, phần Revision −0.06.",
    service: "normal",
    override: (i, f) => (i === f ? { dsLocal: 2.0, dsGraph: 1.6, bid: 1.3, support: 24 } : null),
  },
  {
    id: "cap-clip",
    label: "Chạm giới hạn giá",
    description: "Yêu cầu +0.40 trên bidding 1.30 với giới hạn giá fixture 1.50. Kỳ vọng đề xuất 1.50, hiệu chỉnh chính +0.20.",
    service: "normal",
    override: (i, f) =>
      i === f
        ? { dsLocal: 1.4, dsGraph: 2.4, bid: 1.3, support: 30, policy: { price_max: 1.5, policy_version: "demo-fixture.price-cap-1_50" } }
        : null,
  },
  {
    id: "review",
    label: "Lỗi hợp đồng và dữ liệu",
    description: "Một số vùng có lỗi transform, mã lý do lạ, bidding không hợp lệ, thiếu Graph và thiếu dữ liệu.",
    service: "normal",
    override: (i, f) => {
      if (i === f) return { forceReview: ["INVALID_TARGET_TRANSFORM"] };
      if (i === (f + 7) % 61) return { forceReview: ["SERVE_DRIFT_UNMAPPED"] };
      if (i === (f + 13) % 61) return { bid: null };
      if (i === (f + 19) % 61) return { dsGraph: null };
      if (i === (f + 23) % 61) return { demand: null };
      if (i === (f + 29) % 61) return { forceReview: ["OUT_OF_VALIDATED_RANGE"] };
      return null;
    },
  },
  {
    id: "empty",
    label: "Hàng đợi rỗng",
    description: "Mọi dự báo Graph bằng mốc tham chiếu nên toàn bộ là HOLD.",
    service: "normal",
    override: () => ({ dsGraph: 1.2, dsLocal: 1.2, support: 40 }),
  },
  {
    id: "stale",
    label: "Snapshot mới khi đang xem",
    description: "Sau 20 giây sẽ phát hành snapshot mới. Đề xuất đang xem bị đánh dấu thay thế và khóa thao tác.",
    service: "normal",
    autoAdvanceSec: 20,
  },
  {
    id: "timeout",
    label: "Gửi bị timeout",
    description: "Server không phản hồi kịp. Quyết định chuyển Chưa xác định và được tra cứu lại theo idempotency key.",
    service: "timeout",
  },
  {
    id: "partial",
    label: "Batch thành công một phần",
    description: "Server từ chối một phần batch và một mục chưa xác định kết quả.",
    service: "partial",
  },
  {
    id: "offline",
    label: "Mất kết nối",
    description: "Giữ snapshot cuối với nhãn cũ, khóa mọi thao tác có thể đổi giá.",
    service: "normal",
    offline: true,
  },
  {
    id: "contract",
    label: "Hợp đồng metric không khớp",
    description: "Forecast dùng raw ratio trong khi quan sát dùng smoothed ratio. Mọi đề xuất bị chặn, không tự inverse để sửa.",
    service: "normal",
    contractMismatch: true,
  },
];

export const scenarioById = (id: string) => SCENARIOS.find((s) => s.id === id) ?? SCENARIOS[0];
