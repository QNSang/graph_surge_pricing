# Current State — GGSO and DuoCast

Cập nhật: 2026-10-18.

## Active implementation

Pipeline active nằm trong:

- `pipeline/src/surge_ml/train/duocast/`
- `pipeline/src/surge_ml/train/responses/`
- `pipeline/src/surge_ml/inferences/`
- `pipeline/src/surge_ml/contracts/`
- `pipeline/src/surge_ml/datasets/`
- `pipeline/src/surge_ml/reports/`

Default CLI sử dụng các module này. Forecast checkpoint contract hiện hành là `duocast_ds_h5_v1`.

Backend có GGSO JSON bridge cho DEMO/test workflows. Việc nối production provider, DB receipt, API publication và live pricing chưa được phê duyệt.

## Verified behavior

Lần kiểm tra gần nhất:

- Backend unit tests: 49 passed.
- Pipeline tests: 177 passed, 4 library warnings.
- Secret-pattern scan trên phạm vi commit: không phát hiện kết quả.

Các test xác nhận synthetic training/checkpoint flow, forecasting contracts, response fitting, candidate construction, MILP validation, replay và fail-closed behavior. Đây không phải bằng chứng official-data accuracy hoặc production readiness.

## Decision flow

Ở mỗi cutoff năm phút:

1. Hệ thống đóng băng một complete network snapshot.
2. DuoCast forecast demand và supply cho mọi required cell bằng một batched inference.
3. Response layer đánh giá eligible pricing candidates.
4. MILP chọn một coordinated full-network policy.
5. Independent validator tính lại coverage, hard constraints và objective components.
6. Policy hợp lệ được áp dụng tự động; policy không hợp lệ không tạo write mới.

Dashboard chỉ monitoring và không có human pricing actions.

## Pending evidence

- Official source semantics và lineage.
- Real dataset manifests và frozen splits.
- Official checkpoint eligibility.
- Real-data forecast accuracy và calibration.
- Response-model fit trên dữ liệu thực.
- Approved shadow hoặc production rollout.
- Prospective switchback experiment cho realized GMV.

## Operational boundary

Synthetic estimates, modeled utility và nominal modeled GMV không phải realized causal uplift. Không deploy, publish policy hoặc bật production pricing chỉ dựa trên trạng thái tài liệu và test hiện tại.
