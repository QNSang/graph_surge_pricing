// Policy DEMO có version. Tham số minh họa từ Technical Report mục 11, CHƯA calibration.
// Không phải policy production; frontend production không tự tính các giá trị này.

export interface DemoPolicy {
  policy_version: string;
  reference_version: string;
  ds_ref: number;
  tau_press: number;
  tau_rev: number;
  k_press: number;
  k_rev: number;
  delta_max: number;
  ds_min: number;
  price_min: number;
  price_max: number;
  precision: number;
  /** Ngưỡng support của prototype; chỉ có hiệu lực trong DEMO. */
  low_support_lt: number;
  override_step: number;
  override_max_deviation: number;
  ttl_min: number;
}

export const DEMO_POLICY: DemoPolicy = {
  policy_version: "demo-policy.v1.2-illustrative",
  reference_version: "demo-ref.smoothed.1_20",
  ds_ref: 1.2,
  tau_press: 0.1,
  tau_rev: 0.05,
  k_press: 0.6,
  k_rev: 0.4,
  delta_max: 0.4,
  // Report không chốt q_min; 0.05 là giá trị minh họa gần cận dưới quan sát 1/(S_eff+1).
  ds_min: 0.05,
  price_min: 1.0,
  price_max: 3.0,
  precision: 2,
  low_support_lt: 4,
  override_step: 0.05,
  override_max_deviation: 0.2,
  ttl_min: 5,
};
