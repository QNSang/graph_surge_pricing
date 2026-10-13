# 10. Study plan, trial materialization và quality gates

## 1. Hai cấp config

[train_v12.yaml](examples/train_v12.yaml) khóa **base configuration của model chính**, source, target, split và tracking. Nó không được sửa `model_id` thành GRU40 trong khi vẫn giữ selected29 chỉ để chạy baseline. [benchmark_plan.json](contracts/benchmark_plan.json) là study plan versioned cho các trial/comparator/ablation. [Study schema](schemas/study_plan.schema.json) và [effective trial schema](schemas/trial_config.schema.json) kiểm tra các cấp này riêng.

**[Confidence: Medium — hợp đồng orchestration bổ sung để suite thực thi được.]** Materializer nhận base config đã validate + một trial specification trong study plan + derived dataset ref, tạo `effective_trial_config.json` bất biến. Mỗi trường được materialize theo rules dưới đây, không có free-form overrides tùy tiện. Model factory reject model ID/kind/feature profile/hyperparameters không phù hợp.

| Model kind | Feature view | Target/output | Hyperparameters có nghĩa |
|---|---|---|---|
| `persistence` | Raw D_t và S_eff_t sidecars | Exact q_t; y=log1p(q_t) nếu S_eff_t>0 | Không optimizer/epochs; output invalid có lý do khi denominator không hợp lệ |
| `lgbm` | Current29 hoặc current40 tại cutoff; dùng rolling/momentum đã có | Direct log1pH5; negative output rejected theo baseline policy | Trees, learning rate, leaves, min_child_samples, feature/bagging parameters, early stopping |
| `gru` | W12×29 hoặc W12×40 | Một main head Softplus log1pH5 | GRU/head hidden, dropout, AdamW và training budget |
| `dual` | W12×29 + graph typed/self | Local+graph Softplus log1pH5 | GRU/GAT/head hyperparameters, two-head loss |
| `ablation` | Declared variant của dual | Local+graph, research diagnostic | Chỉ variant IDs allowlisted ở §3 |

LGBM default dùng **29 hoặc40 cột tại timestamp hiện tại**, không flatten12 và không thêm feature discovery trong run. `feature_view_id=current_context29_v1` hoặc `current_aggregate40_v1`. Model không đọc future volume; PairAcc có thể dùng volume trong evaluation mask theo04.

## 2. Materialization rules bắt buộc

1. Data reference gồm source training fingerprint, source_parquet_sha256, source_schema_sha256 và derived fingerprint, target, split/candidate manifests và node mapping giống nhau cho mọi trial trong suite. Nhãn q float64/y float32 từ cùng derivation được reuse.
2. Input profiles: context29 indices0..28, aggregate40 indices0..39. Feature contract aggregate view có ID `hex40_edge10_v1_2`; nó **khác** source legacy `hex40_edge10_v2.1` vì gắn W12/H5/new target/norm. Derivative MUST giữ unnormalized full40 mmap cache để materialize cả hai views; chọn29 khi batching main model, không xóa11 cột cần cho baseline. Trainer chỉ đọc finalized derivative qua split views, không tự mở raw source để bù cột thiếu.
3. GRU/dual dùng scaler riêng29/40 fit theo cùng train-input population. LightGBM view dùng raw current values; `normalizer_ref=null` với `normalization_policy=identity_raw_v1`, không nhận scaler29 của dual. Persistence cũng không dùng scaler.
4. Base `model_id`, `node_dim`, `output_domain`, `primary_metric` được thay theo declared model kind. Baseline key `val/main/mae_q/h5`; dual/ablation key `val/graph/mae_q/h5`. Primary **study selection** vẫn graph MAE của main dual.
5. Baseline single-head dùng direct masked SmoothL1 cho GRU hoặc estimator loss `regression_l2` cho LGBM; không cộng local auxiliary loss vào model chỉ có main head. LGBM và neural objective khác nhau được ghi trong effective config; common comparison metric vẫn rawqMAE.
6. Run materializer MUST copy only kind-applicable hyperparameters. Loss/local fields không áp lên LGBM; GAT fields không áp lên GRU. Tất cả resolved defaults được ghi, không chỉ user overrides.
7. LGBM/GRU independent train bằng train data, early stop/select bằngval. Derived target/input population và evaluation masks không đổi giữa models. Persistence không có fit nhưng có evaluation run và config/provenance.
8. Seed list của study mặc định42/43/44 và MUST khớp evaluation.seeds của baseconfig; mismatch là CONFIG_INVALID; each `(variant_id,seed)` có `trial_id` ổn định. Retry/resume giữ trial_id, tạo `attempt_id` và MLflow run_id mới. Khi chỉ chạy một trial bằng `train`, dùng experiment.seed; `benchmark` materialize tất cả seeds củaplan.
9. `effective_config_sha256` hash sau materialization, bao gồm variant/head/feature/norm/budget. Base config digest cũng giữ riêng để truy nguồn. Không sửa effective config sau khi train.
10. Only main dual with exact primary contracts and positive supervised local head can be eligible for primary research registry. Baselines/ablations vẫn lưu artifacts/evidence, `primary_registry_eligible=false`.

## 3. Ablation variants

Default comparator suite là persistence, LGBM29/40, GRU29/40 và dual. Các ablation bên dưới được khai báo nhưng `enabled=false` trong mẫu để giới hạn compute; nghiệm thu model-quality claim cần bật các ablation được freeze trong plan tương ứng.

| variant_id | Thay đổi được phép | Identity/version |
|---|---|---|
| `dual_no_od` | Giữ adjacency+syntheticself, bỏ quan hệ OD bằng type trước normalization/model | `directed_adj_only_self_v1` |
| `dual_no_travel_eta` | Remove information từ raw edge idx3,8 bằng adapter mask đã version; không dùng test để chọn | `edge_mask_travel_eta_v1`, normalized masked values0 |
| `dual_reverse` | Add synthetic reverse có provenance/flags, giữ genuine OD; không kể reverse như quan sát thật | `directed_relations_reverse_self_v1` |
| `dual_lambda_local_zero` | lambda_local=0, no controller/promotion eligibility | `unsupervised_local_ablation_v1` |
| `dual_lambda_local_03` | lambda_local=0.3, mọi phần khác giữ | Same architecture + effective config hash khác |

TrialConfig schema cho phép0 auxiliary loss **chỉ trong ablation**; primary TrainConfig vẫn chặn0. Graph variant có contract ID riêng; không sửa constant `directed_relations_self_v1`. Feature-discovery hoặc arbitrary HPO space không nằm trong allowlist; muốn thêm thì nâng study schema/plan với tests phù hợp.

## 4. Study state khác worker attempt state

`study_id` là slug/identifier do người dùng đặt, ví dụ `hcm-v12-pilot-001`, không bắt buộc UUID. `pipeline_run_id`, `trial_id`, `attempt_id`, `request_id` là machine IDs. Một study có một MLflow parent `run_role=study`; nó là aggregate record, không là GPU worker.

| Study status | Diễn giải | MLflow parent |
|---|---|---|
| `OPEN` | Plan được freeze, có trial đang/chuẩn bị chạy | RUNNING |
| `WAITING_SELECTION` | Trials đã xong, chờ explicit select | RUNNING; tag planned_state |
| `WAITING_FINALIZE` | Candidate/comparators frozen, chưa mở holdout | RUNNING; tag planned_state |
| `FINALIZING` | Worker final eval đang chạy | RUNNING |
| `COMPLETED` | Required evaluation/bundle/evidence xong | FINISHED |
| `FAILED` | Required workflow không thể hoàn tất | FAILED |
| `CANCELLED` | Study đóng do người vận hành | KILLED |

`train`/`benchmark` có thể exit0 khi child execution thành công dù study đang WAITING_SELECTION. `select` chuyển WAITING_FINALIZE; `finalize` hoàn tất required stages và close parent. Parent không cần worker heartbeat; stale180s/reconcile INTERRUPTED chỉ áp **attempt có worker ownership**. CLI `runs list` hiển thị study chờ thao tác và running worker riêng, không báo một study chờ selection là job mắc kẹt.

State file study gồm `study_id`, `study_plan_sha256`, `parent_mlflow_run_id`, status, frozen trial IDs, selected trial/attempt/checkpoint, comparator refs, holdout access/eval receipt, timestamps UTC. `run_state.json` ởschema là worker execution có `study_id`, `run_role`, `parent_mlflow_run_id`; không ép study WAITING_FINALIZE vào enum workerTRAINING.

Resume attempt là child mới của cùngstudy, không child lồng vào attempt cũ; liên kết `resume_from_run_id`/`resume_parent_attempt_id` và trial_id. Optional analyses chạy sau completed study có thể tạo child linked artifact report; không sửa immutable core bundle hoặc pretend mở lại training. Summary mới là annotation/receipt mới, original evaluation hashes giữ nguyên.

## 5. Quality gates định lượng

Đây là pilot engineering rules, **[Confidence: Medium — lựa chọn review, chưa được xác nhận là ngưỡng nghiệp vụ]**. Plan MUST freeze trước xemholdout. Test chỉ confirm selected plan; không chọn version qua retry đến khi gatepass.

### 5.1. Population và coverage

Candidate prediction coverage=1 trên toàn data-eligible labels của mỗi split, local vàgraph đều finite/nonnegative. Invalid target được báo riêng; timestamp không có label vẫn có forecast/input-coverage record nhưng không vào MAE. Invalid candidate prediction không được loại để làm score thấp.

Required strong comparators: `gru_context29_h5_v1`, `gru_aggregate40_h5_v1`, `lgbm_aggregate40_h5_v1`. Chúng phải có finite predictions trên fixed eligible population; comparator failure làm quality UNASSESSED/FAILED với reason, không tính như đối thủ điểm vô hạn cho graph dễ thắng. Persistence khi S_eff_t<=0 có coverage thấp hơn; báo common-support comparison riêng, không ép nó coverage1 bằng sửa denominator.

### 5.2. Local gate

Đặt L = MAE_local_dual, B = MAE_independent_GRU29 trên cùng eligible rows. Với B≥`baseline_error_floor=1e-8`:

```text
local_pass = L <= B*(1 + local_regression_relative_tolerance) + tie_tolerance
```

Với B<floor, dùng `L <= B + local_regression_absolute_tolerance`. Default relative0.05, absolute0.01, tie1e-10; log cả metric, threshold và pass/fail. Đây không phải guarantee local denominator an toàn cho pricing; q_min vẫn thuộc controller.

### 5.3. Graph value gate

Với mỗi required strong comparator c, trên **cùng fixed eligible row keys**, B_c là MAE của comparator, G là MAE_graph. Khi B_c≥floor:

```text
improvement_c = (B_c-G)/B_c
graph_pass_c = improvement_c > graph_min_relative_improvement
               AND G < B_c - tie_tolerance
```

Default `graph_min_relative_improvement=0.0`: yêu cầu cải thiện strict, equality không đủ. Khi B_c<floor, không chia số gần0; muốn claim added value phải có `G < B_c - tie_tolerance`, nếu không ghi `NO_MEASURABLE_GAIN`. Không tự dùng local absolute tolerance để nới graph-value gate. Overall graph gate là AND trên required comparators; report thêm persistence/LGBM29 và ablations.

Passpoint estimates trên30 ngày chỉ hỗ trợ dataset-scope result; nếu confidence interval theo ngày còn rộng, report uncertainty. Quality gate có thể pass point thresholds nhưng business_gate vẫn NOT_EVALUATED và deployment_eligible=false.

### 5.4. Registration, champion và false-pass prevention

`registry register` default đòi required evidence complete, qualityPASSED, eager roundtrip và trackingCOMPLETE trong research namespace. Nếu chỉ muốn giữ một trained-but-not-qualified model, lưu bundle trong run artifacts với qualityFAILED/UNASSESSED; không gọi đó là registry candidate approved.

Promotion kiểm lại immutable final gate report + expected current numericchampion. Changing an alias không thay đổi model/data readiness. User muốn nghiên cứu một model qualityfail có thể inspect/run local, nhưng nó không đi qua default promotion workflow bằng cách sửa tagsPASSED.

## 6. Acceptance bổ sung

- Materialize plan cho6 primary model variants ×3 seeds; modelkind/featuredim/inputview/loss/selectionmetric đúng.
- All40 baseline đọc40 source features và scaler40, target/index không khác dual.
- LGBMcurrent viewdim29/40, không flatten12 ngầm.
- Lambda0/reverse chỉ materialize từ allowlisted ablation, primary registry eligibilityfalse.
- Resume giữ trial_id và new attempt, study parent không bị stale heartbeat xử lý nhưworker.
- Equal graph/baseline MAE không pass strict graphvalue; nearzero errors dùng nhánh đã định nghĩa.
- Registry fail khi missingstrong comparator, invalidpredictioncoverage hoặc metricpopulation keys khác.
