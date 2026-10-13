# 06. Artifact bundle, checkpoint và serving contract

## 1. Ba loại artifact có trách nhiệm khác nhau

| Loại | Mục đích | Điều kiện |
|---|---|---|
| Training checkpoint | Tiếp tục optimizer đúng epoch/trial | Cùng data/config/code compatibility và runtime |
| Eager inference bundle | Load weights bằng code class versioned và dự báo | Contract/schema/normalization đủ, fresh-process parity |
| `.pt2` export | Inference bằng exported program trên profile đã kiểm | Export success, dynamic-shape/device/dtype constraints pass |

**[Confidence: High — PyTorch serialization guidance; Medium — layout bundle đề xuất.]** Không dùng `.pt2` thay optimizer checkpoint. Model file một mình không đủ tái dựng feature/target mapping. [PyTorch saving/loading](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html).

## 2. Checkpoint bắt buộc

`last.pt` được ghi ở cuối mỗi epoch có state finite; `best.pt` ghi khi validation selection cải thiện. Tạo file tạm rồi atomic replace; copy/serialize ngay, không giữ reference `state_dict()` rồi tiếp tục cập nhật model. Best checkpoint lưu model weights của best epoch; last chứa trạng thái tiếp tục mới nhất.

| Key | Ý nghĩa |
|---|---|
| `checkpoint_schema_version`, `model_id`, `target_contract_id` | Kiểm tra format/behavior |
| `pipeline_run_id`, `trial_id`, `attempt_id`, `resume_parent` | Provenance |
| `source_fingerprint`, `source_parquet_sha256`, `source_schema_sha256`, `derived_fingerprint`, `config_sha256`, `code_digest` | Compatibility identities |
| `feature_contract_sha256`, `graph_contract_sha256`, `normalizer_sha256` | Semantic transforms |
| `model_state`, `optimizer_state`, `scheduler_state`, `amp_scaler_state` | Trạng thái train; absent component phải null có nghĩa rõ |
| `epoch_completed`, `next_epoch`, `global_optimizer_step` | Không đếm lại epoch cũ thành epoch mới |
| `best_metric`, `best_epoch`, `early_stop_bad_epochs` | Resume đúng early stopping |
| `python_rng`, `numpy_rng`, `torch_cpu_rng`, `torch_cuda_rng`, `shuffle_generator_state` | Reproducibility |
| `runtime_versions`, `device_profile`, `precision`, `deterministic_policy` | Compatibility runtime |

Default resume ở epoch boundary, DataLoader `num_workers=0` trên Windows pilot. Mid-epoch resume/prefetch queue không nằm trong baseline. Nếu checkpoint tồn tại nhưng checksum không khớp, reject; không chọn một file khác chỉ vì có tên gần giống.

Inference weights SHOULD chỉ chứa tensors/primitive metadata nạp bằng weights-only path của Torch nếu format đã xác nhận tương thích. Full resume checkpoint chỉ nạp từ artifact do pipeline kiểm soát và đã xác minh digest; không tắt safe loader tự động khi thấy lỗi. Legacy pickle/state checkpoints không được load như V1.2.

## 3. Nội dung bundle chuẩn

| Path trong bundle | Bắt buộc | Nội dung |
|---|---|---|
| `bundle_manifest.json` | Có | File list, SHA256 từng file, contract/version/runtime, scopes |
| `model/model_metadata.json` | Có | Model ID, target inverse, head order, feature/graph shape, dataset kind |
| `model/weights.pt` | Có | Eager weights best epoch |
| `code/surge_ml-<version>.whl` hoặc code snapshot manifest | Có | Định nghĩa model/preprocessor thực sự chạy |
| `contracts/feature_contract.json` | Có | Node/edge order, hex mapping/hash, units/time semantics |
| `contracts/target_contract.json` | Có | `ds_log1p_h5_v1_2`, exact denominator, masks, horizon |
| `contracts/graph_contract.json` | Có | Direction, relation identity, self/reverse, offsets |
| `preprocessing/normalization.npz`, `normalization.json` | Có | Numeric stats + feature names/fitting scope/hash |
| `config/resolved_config.yaml`, `environment/runtime.json`, locks | Có | Nonsecret config/runtime đủ tái lập |
| `lineage/source_manifest.json`, `derived_manifest.json` | Có | Identity source/derivative và checksum scope |
| `lineage/source_schema.yaml` | Có cho V1.2 | Schema nguồn đã dùng, byte hash trong metadata; giữ decision record cho schema discrepancies |
| `lineage/source_parquet_manifest.json` | Có cho V1.2 | Frozen public Parquet inventory và `source_parquet_sha256`; đủ truy ra source bytes đã dùng |
| `evaluation/validation.json`, `validation_predictions.parquet` | Có | Best checkpoint evidence |
| `evaluation/final_eval.json`, test predictions | Khi finalize | Frozen candidate/comparator holdout evidence |
| `verification/eager_roundtrip.json` | Có | Fresh-process load/predict parity |
| `examples/input.npz`, `expected_output.npz` | Có | Tiny valid graph batch, no private user data |
| `exports/model_cpu.pt2`, `export_manifest.json` | Khi yêu cầu và pass | Export profile-specific, không placeholder model |
| `reports/model_card.md`, `analysis_status.json` | Có | Intended use, limitations, core/optional result statuses |

Không nhúng toàn bộ dataset 30 ngày vào mỗi run; giữ immutable dataset store một lần, content hashes, reference và sample reproducer. Critical reproduction source MUST có cơ chế lưu giữ bền vững trên máy khác/backup; hash và một path `D:\...` không tự giữ được bytes khi máy mất.

Bundle finalize: build temp directory → verify all required files → create file checksum map → compute canonical digest của map không chứa chính manifest → ghi manifest → rename thành final content-addressed path. Store `bundle_sha256` ở registry receipt; không cho update một registered version trỏ sang bundle bị rewrite.

`quality_status=UNASSESSED` trước final evaluation; `deployment_eligible=false` cho source synthetic. Model card nêu W12/H5, 29/10→12 input, target exact D/S, information sets, invalid-target/prediction coverage, source dates, baselines, score scope, known absent booking/GMV labels và reproducibility limits.

## 4. Tensor boundary và JSON signature

Core input gồm ba tensor; normalizer và graph augmentation chạy ở adapter ngoài model:

| Tên | Dtype / shape | Ràng buộc |
|---|---|---|
| `x` | float32 `[B,12,N,29]` | N theo bundle node contract; 61 cho release này |
| `edge_index` | int64 `[2,E]` | Sau offsets batch; `0 <= index < B*N` |
| `edge_attr` | float32 `[E,12]` | 10 normalized + reverse/self flags |
| output `forecast_log1p` | float32 `[B,N,2]` | Head order `[local,graph]`, cùng H5 |

Wrapper concat output `[B,N,1]` của từng head thành `[B,N,2]` khi export. `q=expm1(log1p_output)` được adapter thực hiện bằng float64 để kiểm domain/overflow; JSON có named `ds_local`, `ds_graph` (aliases nội bộ q_local/q_graph), không để consumer đoán cột số0/1. Không đưa `input_valid`, y hoặc future volume vào model trừ khi tạo model signature mới; input validity được validator kiểm trước forward.

MLflow signature ghi dtype và dimension phù hợp; `TensorSpec` không thay các semantic validators: shared E, node IDs, timestep=5m, head order, no cross-batch edge, target inverse và data cutoff. [Model signature reference](https://mlflow.org/docs/latest/ml/model/signatures/).

N mặc định **bind=61 theo hex mapping của bundle này**. Core eager architecture không hard-code N; nếu rollout sang region/node set khác cần bundle/contract/mapping mới. Nếu `.pt2` khai báo dynamic N thì phải test nhiều N thật; không gắn dynamic support chỉ vì eager model chạy N khác. B/E dynamic hoặc static đều phải thể hiện rõ trong export manifest; runtime reject ngoài miền đã kiểm.

## 5. `.pt2` export và MLflow flavor

MLflow API hiện tại có `serialization_format='pt2'`, dùng `name=` và example tensor(s). Default serialization có thể phụ thuộc environment; implementation MUST chọn explicit format và kiểm API trên đúng pin3.16.1. Docs latest có thể thay đổi; không xem việc source docs latest có keyword là bằng chứng môi trường local đã hỗ trợ. [MLflow PyTorch API](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.pytorch.html).

GNN nhiều input, edge indices int64 và graph size biến đổi cần wrapper riêng. Truyền native model tuple/list tensor đúng forward; không cast edge indices sang float để gom một input array. Exported artifact có thể chỉ có native PyTorch flavor; MUST inspect `MLmodel.flavors` và test load path thực tế. Không mặc định `mlflow.pyfunc.load_model` hoặc `mlflow models serve` chạy được model vừa log.

Export contract gồm Torch/PyG/MLflow exact versions, wheel/container digest, export device, accepted B/N/E domains, dimension relations, input order, preprocessing versions và output head order. Tài liệu MLflow nêu giới hạn di chuyển device của `.pt2`; CPU serving phải có CPU export và kiểm tra bằng CPU runtime. [Pickle-free models](https://mlflow.org/docs/latest/ml/tracking/pickle-free-models/).

Gates bắt buộc cho `.pt2`:

1. Eager eval và exported program dùng cùng fixed weights, normalization và prepared graph.
2. Fresh-process load trên đúng target device; FP32 parity `rtol=1e-5, atol=1e-6` cùng environment. Khác device/precision cần tolerance version riêng.
3. B=1 và B>1 nếu tuyên bố dynamic batch; nhiều E gồm observed-empty graph đã được thêm N identity loops, E nhỏ/lớn và isolated nodes. Export example B=1 không đủ chứng minh B động.
4. Giữ int64 indices; kiểm `edge_index.shape[1]==edge_attr.shape[0]`, correct offsets, genuine OD-self và synthetic-self không mất.
5. Node permutation + mapping inverse, edge-order permutation, relation duplicates handling đúng semantics; không đòi numeric bitwise equality do reduction order.
6. Positive domain và head order giữ sau reload; invalid inputs bị reject trước inference.
7. Đo latency/memory trên workload của serving profile và ghi benchmark method; không suy ra tốc độ từ tên format.
8. Nếu fail: giữ eager bundle đã valid, `export_status=FAILED`, registry ghi eager-only. Không silently fallback pickle rồi ghi export pt2 passed.

`torch.compile` support không bảo đảm `torch.export` cho mọi GNN. Với operator không export được, chốt eager serving hoặc thay implementation bằng version mới; không patch raw dataset hoặc bỏ edge features để làm export qua. [PyG compiled GNN guide](https://pytorch-geometric.readthedocs.io/en/stable/tutorial/compile.html).

## 6. Serving adapter

Trong scope này cần bundle contract và local `predict-batch`/smoke integration; online HTTP service là bước tiếp theo khi có rollout requirement. API đề xuất nếu dựng service: `POST /v1/forecasts`, request contract_version, request_id, decision_ts, input batch reference/tensors, hex_ids, feature/graph digests. Response request_id, numeric model_version, bundle hash, decision_ts/forecast_ts, head forecasts, prediction_valid và reason_codes. Không trả model raw tensor như response nghiệp vụ mà thiếu units/horizon.

Serving resolve `champion` một lần lúc startup/rollout, pin numeric registry version và bundle digest trong process. Không re-resolve alias mỗi request. Load bundle mới → verify/smoke → atomic pointer swap cho request mới; request đang chạy dùng bản cũ. Rollback về known-good complete bundle, gồm cả normalizer và target transform.

Nếu features thiếu/freshness lỗi, adapter trả input invalid và reason; controller dùng valid latest bidding để REVIEW/zero correction. Nếu bidding không hợp lệ thì error upstream; không giả vờ giữ base khi thực tế clipping base làm đổi giá.

## 7. Controller V1.2 là thành phần tách biệt

[Controller mẫu](examples/controller_v12.example.yaml) disabled mặc định. Khi bật trong nghiên cứu, MUST có ds_ref>0, ds_min>0, finite gains/thresholds, versioned global bounds và giá bidding hiện tại hợp lệ. Công thức trong [model report](../model/technical_report.md) được giữ:

```text
Pressure = (ds_graph - ds_ref) / ds_ref
Revision = (ds_graph - ds_local) / ds_local
dead(x,tau) = sign(x) * max(abs(x)-tau, 0)
corr = k_press*dead(Pressure,tau_press) + k_rev*dead(Revision,tau_rev)
delta_requested = clip(corr,0,0.4) if Pressure>tau_press
                = clip(corr,-0.4,0) if Pressure<-tau_press
                = 0 otherwise
surge_final = clip(surge_bid + delta_requested, surge_min, surge_max)
delta_applied = surge_final - surge_bid
```

ds_local<ds_min, negative/nonfinite forecast, wrong target version hoặc insufficient input validity → REVIEW, delta_requested=0. Controller không sửa một forecast sai thành value hợp lệ rồi che lỗi trong audit. Không cộng correction lên giá final vòng trước. Không coi ds_ref=1 là định lý thị trường. Các aliases q_star/q_min trong giải thích nội bộ lần lượt là ds_ref/ds_min; không chấp nhận đồng thời hai bộ key trong cùng controller config.

Audit MUST lưu raw D/S support, ds_local/ds_graph, Pressure/Revision, threshold/gain/reference versions, requested/applied, bid/final, saturation và reasons, numeric model version, decision time/feature ages. Guardrail algebraic |delta_applied|≤0.4 không chứng minh guardrail kinh doanh.

## 8. Artifact acceptance

- Bundle fresh-process eager load được trên serving environment thiếu SHAP/AutoGluon/tsfresh.
- Hoán đổi feature order, target version, norm hoặc node mapping làm load/predict fail rõ.
- Người nhận có thể reconstruct forecast cho input example từ bundle; prediction parity được lưu.
- Checkpoint resume giữ optimizer step và epoch monotonic, không lấy optimizer của last ghép weights best rồi gọi exact resume.
- Required artifacts thiếu hoặc hash mismatch chặn registration/promotion.
- Chỉ consumer tương thích target `ds_log1p_h5_v1_2` được đọc output bằng expm1; legacy output không đi qua adapter này.
