// Reason code -> copy hiển thị (spec mục 6.6). Mã lạ không bao giờ được map sang thành công/HOLD.

export interface ReasonCopy {
  title: string;
  detail: string;
  blocking: boolean;
  tone: "neutral" | "review" | "info";
}

const MODEL_REASONS: Record<string, ReasonCopy> = {
  PRESSURE_DEADZONE: {
    title: "Áp lực trong vùng không điều chỉnh",
    detail: "Áp lực nằm trong vùng không điều chỉnh của policy nên giữ HOLD.",
    blocking: false,
    tone: "neutral",
  },
  DIRECTION_BLOCKED: {
    title: "Hướng hiệu chỉnh bị chặn",
    detail: "Tổng hiệu chỉnh ngược hướng Pressure nên bị đưa về 0. Xem trace trong Chi tiết.",
    blocking: false,
    tone: "neutral",
  },
  REQUESTED_CAP_CLIPPED: {
    title: "Đã chạm giới hạn hiệu chỉnh",
    detail: "Mức yêu cầu bị giới hạn bởi biên hiệu chỉnh của policy.",
    blocking: false,
    tone: "info",
  },
  GLOBAL_CAP_CLIPPED: {
    title: "Đã chạm giới hạn giá",
    detail: "Giá sau hiệu chỉnh bị giới hạn bởi khoảng giá của policy. Mức yêu cầu đầy đủ nằm trong Chi tiết.",
    blocking: false,
    tone: "info",
  },
  OUT_OF_VALIDATED_RANGE: {
    title: "Dự báo ngoài miền đã kiểm",
    detail: "Dự báo nằm ngoài miền đã kiểm định. Mặc định chặn thao tác.",
    blocking: true,
    tone: "review",
  },
  LOCAL_RATIO_TOO_SMALL: {
    title: "Local quá nhỏ",
    detail: "Dự báo Local dưới ngưỡng tối thiểu nên không tính được Revision hợp lệ.",
    blocking: true,
    tone: "review",
  },
  REFERENCE_SCALE_MISMATCH: {
    title: "Mốc tham chiếu khác thang",
    detail: "Mốc tham chiếu không cùng thang với dự báo. Thao tác bị chặn.",
    blocking: true,
    tone: "review",
  },
  INVALID_TARGET_TRANSFORM: {
    title: "Sai phép biến đổi target",
    detail: "Lỗi train và serve: target transform không khớp. Khóa xác nhận và batch.",
    blocking: true,
    tone: "review",
  },
  FEATURE_ROUTING_MISMATCH: {
    title: "Sai định tuyến feature",
    detail: "Lỗi train và serve: feature routing không khớp. Khóa xác nhận và batch.",
    blocking: true,
    tone: "review",
  },
  INVALID_HORIZON: {
    title: "Sai horizon",
    detail: "Horizon dự báo không khớp hợp đồng. Khóa xác nhận và batch.",
    blocking: true,
    tone: "review",
  },
  NONFINITE_FORECAST: {
    title: "Dự báo không hữu hạn",
    detail: "Model trả về giá trị không hữu hạn. Khóa xác nhận và batch.",
    blocking: true,
    tone: "review",
  },
  MISSING_GRAPH_FORECAST: {
    title: "Thiếu dự báo Graph",
    detail: "Không có dự báo Graph cho vùng này. Quan sát vẫn hiển thị, đề xuất bị chặn.",
    blocking: true,
    tone: "review",
  },
  INVALID_BIDDING: {
    title: "Bidding không hợp lệ",
    detail: "Không có bidding hợp lệ nên không tạo được đề xuất và không ghi nhận giữ bidding.",
    blocking: true,
    tone: "review",
  },
  MISSING_MARKET_DATA: {
    title: "Thiếu dữ liệu thị trường",
    detail: "Thiếu Demand hoặc Supply tại cutoff. Không thay bằng 0, đề xuất bị chặn.",
    blocking: true,
    tone: "review",
  },
  LOW_SUPPORT: {
    title: "Ít quan sát",
    detail: "Số quan sát thấp (quy tắc D+S < 4 chỉ áp dụng trong DEMO). Cần xem xét thủ công.",
    blocking: true,
    tone: "review",
  },
};

export function reasonCopy(code: string): ReasonCopy {
  return (
    MODEL_REASONS[code] ?? {
      title: `Mã chưa biết: ${code}`,
      detail: "Không đủ thông tin để duyệt. Mã gốc được giữ nguyên để tra cứu.",
      blocking: true,
      tone: "review",
    }
  );
}

export const isKnownReason = (code: string) => code in MODEL_REASONS;

// Lỗi vòng đời sản phẩm, tách khỏi reason của model.
export const LIFECYCLE_COPY: Record<string, string> = {
  REPLAY_READ_ONLY: "Đang xem replay. Về snapshot mới nhất để xử lý.",
  SUPERSEDED: "Đã có snapshot mới. Đề xuất này không còn hiệu lực, tải snapshot mới để xem lại.",
  EXPIRED: "Đề xuất đã hết hạn.",
  OFFLINE: "Mất kết nối. Thao tác thay đổi giá bị khóa, đang giữ snapshot cuối.",
  CONTRACT_MISMATCH: "Hợp đồng metric không khớp. Mọi đề xuất bị chặn.",
  HOLD_NO_ACTION: "Model kết luận giữ nguyên, không cần xác nhận giá.",
  REVIEW_BLOCKED: "Đề xuất cần xem xét, không thể xác nhận hoặc đưa vào batch.",
  REVIEW_MANUAL_ONLY: "Đề xuất cần xem xét: chỉ được đặt giá thủ công, không xác nhận hoặc đưa vào batch.",
  ALREADY_DECIDED: "Đề xuất này đã có quyết định.",
  NO_PERMISSION: "Tài khoản không có quyền thao tác này.",
};
