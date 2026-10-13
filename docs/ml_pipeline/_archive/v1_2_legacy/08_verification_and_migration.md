# 08. Kế hoạch triển khai, verification và migration

## 1. Definition of Done

Implementation hoàn tất khi nguồn HCM v2 resolve và verify đúng; derivative W12/H5 có manifests/masks/norm đã kiểm; dual-head train/validation tracking chạy; selected candidate/comparators được đánh giá holdout theo receipt; eager bundle reload được trong serving environment; registry nghiên cứu quản lý candidate/champion/rollback có audit; service persistence/restore được kiểm. `.pt2` và phân tích nâng cao có trạng thái riêng, không ghi thành công nếu chưa pass.

Hoàn tất **specs** chỉ có nghĩa contracts/examples/acceptance đã được viết và rà soát. Không chuyển trạng thái implementation hoặc model quality sang done bằng việc tạo thư mục tài liệu.

## 2. Migration theo milestones

| Mốc | Files/modules cần làm | Acceptance đầu ra | Phụ thuộc |
|---|---|---|---|
| M0 — Khóa contracts | config/Pydantic, source resolver, model/target/graph IDs | Config examples validate; CURRENT/identity đúng, stale manifest path được báo; receipt skeleton | Specs này |
| M1 — Environment + tracking | dependency groups/locks, CLI doctor, Compose, MLflow adapter | CPU imports, artifact roundtrip, version3.16.1, persistence qua recreate | M0 |
| M2 — Data V1.2 | Parquet inventory/reader → derivative mmap/index/scaler/graph batch | DATA requirements pass; source Parquet digest, candidate counts và coverage report | M0 |
| M3 — Model/trainer | GRU local+graph heads, loss/grad/optimizer/checkpoint | Small-batch overfit, gradient/shape tests, resume boundary | M1,M2 |
| M4 — Evaluation/baselines | metrics, LGBM/GRU29/40, selection receipts | Same-population val benchmark; no test in train/HPO | M3 |
| M5 — Bundle/registry | eager package, fresh load, model metadata, management CLI | Compatible bundle version, alias receipt/reconcile/rollback checks | M4 |
| M6 — Full research benchmark | Frozen seeds/configs, selected final evaluation | Model card + honest quality decision, all baseline evidence | M4,M5 |
| M7 — Optional exports/analysis | pt2, SHAP/permutation, AutoGluon/tsfresh, rich reports | Plugin/export success hoặc explicit failure; core preserved | M5 |
| M8 — Serving/shadow extension | Feature freshness, inference API, controller audit | Contract/fallback parity; policy config reviewed | M6 và data/runtime thật |

M1 và M2 có thể thực hiện song song sau M0. M7 không chặn eager research lifecycle. M8 là extension khi có requirement triển khai; synthetic data không cấp phép production pricing. Không cần đưa Airflow/Kubernetes vào M0–M7 để gọi hệ thống hoàn chỉnh.

## 3. Migration không phá baseline

1. Chụp source/code/config identities và Git state trước thay đổi. Source `data/hcm_data_2` giữ bất biến; không rewrite manifest/target arrays cũ.
2. Viết mới package `surge_ml`; giữ provenance legacy làm bằng chứng. Nếu cần replay, triển khai adapter riêng từ contract/archive đã xác minh; active legacy scripts đã bị gỡ, không tạo import dependency vào file mất.
3. Implement `validate-data` với explicit source path, expected identity, Parquet inventory và training fingerprint đúng scope. Kiểm riêng root và manifest reference sau reorganization; dùng explicit meta/manifest.json và source schema, ghi pointer discrepancy. Không fallback sang dataset V1.
4. Đọc trực tiếp Parquet features/raw/burn_in theo02, tạo `data/derived/<derived_id>` với mmap arrays, target/mask/index/norm mới. Write temp và finalize inventory/hashes; không đánh dấu training-ready trước checks.
5. Train V1.2 checkpoint mới. Legacy replay được tracking trong experiment riêng, `target_contract=legacy_smoothed_logratio_h5_h10_h15_eps1`, `controller_compatible=false`.
6. Thay public entrypoint sau khi CLI/integration parity cần thiết pass. Không giữ script cũ có tên v2 nhưng silently đổi nghĩa target cho những run commands trước.
7. Publish pointer/entrypoint chỉ bằng explicit management command với expected old-pointer hash. Ghi dataset manifest reference/compatibility rõ; legacy replay adapter không được đọc pointer V1.2 rồi dùng W4 cố định.
8. Deprecate legacy cùng hướng dẫn/checkpoint identity sau khi đã giữ replay; không xóa old runs/dataset để dọn trong task migration.

Rollback training dùng prior verified package/bundle/source. Replay legacy cần adapter mới hoặc archived environment đã được khôi phục và kiểm chứng; không giả định old CLI còn tồn tại, không biến weights V1.2 sang legacy. Rollback inference pin complete prior bundle, không chỉ thay weight file.

## 4. Test matrix theo rủi ro cụ thể

Test hướng tới ranh giới semantics, failure/recovery và compatibility; không viết test chỉ đọc constants rồi assert lại cùng constants.

| ID | Tình huống | Bằng chứng pass |
|---|---|---|
| CFG-01 | YAML unknown key/type sai/cross-field mismatch | Fail trước tạo model hoặc GPU allocation |
| CFG-02 | Source path đúng nhưng expected fingerprint sai | DATA_INVALID, không tự rewrite expected |
| CFG-03 | Output folder tồn tại hoặc nằm trong source | Reject overwrite/path collision |
| CFG-04 | Legacy W4 checkpoint đưa vào V1.2 | Contract mismatch trước inverse/predict |
| DATA-CORE | Theo DATA-01..18 ở02 | Hash/time/feature/target/mask/norm/batch pass |
| MOD-CORE | Theo M-01..19 ở04 | Shape/graph/loss/gradient/metric/selection pass |
| TRK-CORE | Theo MLF-01..14 ở05 | Tracking/registry/failure consistency pass |
| RUN-01 | Process crash sau epoch durable | New attempt resume giữ next_epoch/optimizer/RNG |
| RUN-02 | Cancel giữa epoch | Không ghi FINISHED; checkpoint boundary và KILLED mapping |
| RUN-03 | Tracking mất kết nối rồi hồi phục | Journal reconcile không tạo duplicate trials; sync verified |
| RUN-04 | Hai invocations cùng request_id | Một owner; return same execution hoặc conflict deterministic |
| RUN-05 | OOM hoặc nonfinite gradient | Fail rõ, không silently alter config/continue |
| RUN-06 | Empty valid train epoch/all val NaN | NO_VALID_CHECKPOINT; không fake best weights |
| ART-01 | Fresh serving env không có analysis packages | Eager bundle vẫn load/predict đúng |
| ART-02 | Weights/norm/feature-order/head-order bị thay | Hash/schema/parity gate fail |
| ART-03 | Last optimizer ghép best weights để resume | Incompatible checkpoint rejected |
| ART-04 | Bundle thiếu one required artifact | Không registration |
| EXP-01 | Export pt2 mixed float/int graph inputs | Dtype preserved; documented shapes/domain pass |
| EXP-02 | E/B ngoài miền export | Clear reject; không crash/implicit reshape |
| EXP-03 | Export failure | Eager preserved, pt2 FAILED, no fake file/format fallback |
| OPS-01 | Recreate MLflow container | Run/registry/artifact còn đọc được và hashes đúng |
| OPS-02 | Restore DB+artifacts sang test instance | Numeric version load và sample prediction parity |
| OPS-03 | Unauthorized/hostname-invalid request trong team | Gate/network policy đúng; no public unauth port |
| REG-01 | Champion đổi sau read trước promotion | Expected-version conflict, không overwrite |
| REG-02 | Crash giữa previous/champion alias writes | Receipt reconciliation đạt trạng thái có thể audit |
| REG-03 | Synthetic candidate nhắm namespace production | Denied independent of score |
| EVAL-01 | Trial train/tune truy cập test labels | Boundary test fail; test metrics absent trial run |
| EVAL-02 | Candidate/comparators đổi sau selection | Frozen receipt mismatch; không reuse holdout key |
| EVAL-03 | Duplicate prediction keys/no eligible pairs | Duplicate reject; no pairs null+reason |
| EVAL-04 | Invalid prediction bị bỏ khỏi score | Coverage gate fail, fixed denominator không đổi |
| ANA-01 | SHAP/AutoGluon/Quarto absent hoặc timeout | SUCCEEDED_WITH_WARNINGS nếu core pass; report ghi rõ |
| CTRL-01 | Các boundary tests report V1.2 | P/R/sign/dead zone/caps/requested-applied đúng |

## 5. Fixture và quy trình kiểm tra

### 5.1. Unit/contract fixtures nhỏ

Tạo graph3–4 nodes, typed adjacency+OD cùng endpoints, genuine OD self, synthetic self, isolated node và batch2 để phát hiện cross-sample message. Dữ liệu ít ngày có timestamp midnight, missing event, active censored trip và zero-supply/zero-demand. Small numeric example D=2,S=1 làm rõ `log1p(2)` khác `log(3/2)`.

Kiểm prefix invariance bằng hide events sau cutoff và so inputs trước cutoff; label có thể đổi theo tương lai nhưng input graph không được đổi vì label mask. Target valid=false không cắt node khỏi message passing. Test same sample offline/serving normalization và hex ordering.

### 5.2. Integration smoke

CPU smoke sử dụng dataset derivative contract thật nhưng subset deterministic train/val,2 epochs, full artifact path/tracking. Nó xác nhận plumbing, không được dùng score để so model hoặc chọn champion. Include source checksum verification và boundary batch ở từng split mà không đọc test labels trong train; holdout integrity kiểm structure/hash riêng với boundary quyền dữ liệu.

Tiny synthetic fixture ở test suite có thể include train/val/test đầy đủ để kiểm final-eval API. Không dùng validation/test thật của HCM để viết unit tests có hardcoded expected predictions và vô tình tuning vào holdout.

GPU smoke chạy riêng nếu có GPU profile; PyG/Torch import, forward/backward, finite checks, checkpoint reload. Exact device lock và kernel metadata nằm trong evidence. Không gọi GPU verified khi chỉ chạy CPU.

### 5.3. Research benchmark đầy đủ

Freeze plan trước chạy: source/derived IDs, feature/graph variants, primary metric, comparator list, seeds42/43/44, training budget, local-regression tolerance và selection rule. Validation dùng để chọn architecture/config/seed; ghi cả runs lỗi. Nếu chỉ chạy seed42, report scope single-seed, không giả multi-seed robustness.

Selected-final-eval chạy candidate và frozen comparator versions trên cùng holdout. Eval key là hash của holdout fingerprint+selection receipt+evaluator version. Retry đúng eval key có thể reuse deterministic result; candidate mới không tự có quyền gọi cùng holdout như test mới độc lập. Sau xem test, mọi tuning tiếp theo phải mang nhãn exploratory hoặc dùng holdout mới.

Results report MUST có actual point estimates, per-day paired errors, prediction/target coverage và missing metric reasons. Statistical interval trên4 validation/5 test days có giới hạn; không nâng conclusion chỉ vì có rất nhiều correlated hex rows.

## 6. Gates và quyền kết luận

| Gate | Kiểm cái gì? | Cho phép kết luận |
|---|---|---|
| G0 Data integrity | Hash/shape/time/order/cutoff/masks | Input kỹ thuật hợp lệ trong phạm vi đã kiểm |
| G1 Training correctness | Loss/gradient/checkpoint/resume | Code train hoạt động đúng các invariant |
| G2 Forecast quality | Baselines, fixed population, val/test receipt | Chất lượng dự báo ngoài mẫu trong dataset này |
| G3 Bundle compatibility | Fresh load, parity, runtime/schema | Artifact dùng được trong serving profile đã kiểm |
| G4 Research registry | Evidence complete, synthetic namespace, receipts | Candidate/champion nghiên cứu truy vết được |
| G5 Business/online | Real data, operational guardrails, controlled experiment | Chỉ gate này mới hỗ trợ quyết định tác động kinh doanh |

G0/G1 của legacy HCM source không tự làm G0/G1 của derivative pass. G2 pass không tự làm G5 pass. Nếu graph không thắng GRU40/LGBM40, system vẫn có thể hoàn tất training; report ghi không đủ bằng chứng message passing cải thiện và không đổi champion theo một claim sai.

## 7. Expected results — cấu trúc báo cáo, chưa có số thực nghiệm

| Model | Target/feature | Val MAE q | Test MAE q | Invalid predictions | Verdict |
|---|---|---|---|---|---|
| Persistence | Exact q H5, current D/Seff | Chưa chạy V1.2 | Chưa finalize | Chưa đo | UNASSESSED |
| GRU29 | W12/local-context29 | Chưa chạy | Chưa finalize | Chưa đo | UNASSESSED |
| GRU40 | W12/aggregate40 | Chưa chạy | Chưa finalize | Chưa đo | UNASSESSED |
| LGBM29/40 | Current rolling feature view | Chưa chạy | Chưa finalize | Chưa đo | UNASSESSED |
| Dual local head | Shared GRU29 H5 | Chưa chạy | Chưa finalize | Chưa đo | UNASSESSED |
| Dual graph head | Directed typed graph H5 | Chưa chạy | Chưa finalize | Chưa đo | UNASSESSED |

Sau implementation thay mỗi `Chưa chạy` bằng metric thật kèm run/derived fingerprint/eval receipt. Không dùng số smoke legacy hoặc số liệu kỳ vọng tự tạo để điền bảng.

## 8. Bàn giao cho người code

Người triển khai nên làm M0 → M1/M2 → M3; mỗi milestone có small PR và evidence path. PR mô tả vấn đề hiện tại, contract thay đổi, behavior mới và test risks. Không gộp thêm thay đổi generator/calibration/production bidding vào training infrastructure khi chưa cần cho requirement.

Các artifacts bắt buộc lúc bàn giao implementation: commands đã chạy, versions/hardware, dataset/derived manifests, run links, validation/final eval receipts, model-card, bundle hashes, backup/restore result, unresolved quality/export flags. Credentials/actual customer data không nằm trong report.
