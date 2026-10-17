# Response Artifact Contract

Status: draft serialization contract, chưa tạo artifact/code. Equations/required coefficient groups từ [S1 §4/6, S2 §4.2/Appendix B](../technical_report/README.md); field names/metadata dưới đây là integration proposal.

## 1. Envelope

| Nhóm | Trường đề xuất | Ý nghĩa |
|---|---|---|
| Identity | schema_version, artifact_version, created_at | Version độc lập với forecast checkpoint |
| Scope | required_hex_ids, node_mapping_version, semantic_profile_id | Cell coverage và demand/completion/capacity semantics |
| Training | dataset_id, train_window, validation_window, data_fingerprint | Provenance và chronological evaluation |
| Context | demand_context_feature_names, fulfillment_context_feature_names, context_schema_version, preprocessing | Demand/Fulfillment dùng ordered tabular contexts riêng; transform và missing policy phải reproducible |
| Numerical | nb_parameterization, epsilon, fitting_method_version | NB convention/library mapping, ổn định số học và estimator |
| Validation | validation_status, evidence_refs, eligibility_rules_version | Không tự approved nếu fit converged |
| Per-cell | cells | Một model record cho mỗi required cell |

Không ép forecast và response dùng cùng training dataset, nhưng semantic definitions và horizon phải tương thích. Artifact không cần nhúng secret/credential hoặc raw personal events.

## 2. Per-cell record

| Trường logic | Kiểu/domain | Mục đích |
|---|---|---|
| hex_id | unique H3 string | Identity |
| demand_intercept | finite real | alpha_i |
| demand_context_coefficients | ordered real vector | w_i; khớp context features |
| beta | real trong [0,4] | Demand elasticity |
| nb_dispersion | value theo declared convention | k_i; domain/mapping phải được estimator specification chốt |
| fulfillment_intercept | finite real | a_i |
| fulfillment_context_coefficients | ordered real vector | v_i |
| gamma | real trong [0,1] | Fulfillment sensitivity |
| training_support | structured counts/windows/ranges | Data/price/context support, không suy từ số rows đơn lẻ |
| fit_status, calibration_summary | structured evidence | Convergence, held-out evaluation và eligibility |
| parameter_scenarios | list hoặc referenced artifact | Paired beta/gamma scenarios có provenance |

Chỉ lưu beta/gamma là thiếu baseline fulfillment/context và training reproducibility. Không mượn model từ cell khác nếu thiếu record.

### 2.1. Training objective và tabular context contract — GGSO v1

- `context_representation_type = tabular_v1` (proposed identifier): hai GLMs dùng structured **pre-decision** tabular features, không đưa DuoCast GNN embeddings vào artifact/online context v1.
- Lưu **riêng** `demand_context_feature_names` và `fulfillment_context_feature_names`, ordered coefficient vectors, transforms/scalers/missing policy và `context_schema_version`; feature order tại inference phải trùng khi fit.
- `training_objective_demand = negative_binomial_nll`, `training_objective_fulfillment = binomial_nll` (proposed metadata strings); kèm `estimation_method`, numerical convention/dispersion parameterization, optional regularization settings, `epsilon` version, fitted train/validation windows và support/calibration evidence.
- Learned values gồm `alpha,w,beta,k` và `a,v,gamma`. **Beta/gamma là parameters được fit**, không phải hyperparameters. Prediction outputs của hai models lần lượt là expected demand `mu` và fulfillment probability `pi`.
- Context của cả baseline/candidates phải reproducible từ cùng approved decision snapshot. Không dùng future outcomes, post-decision features hay silently derived GNN embedding.
- Contract này định nghĩa metadata cần lưu, **không xác nhận** estimator, threshold, context feature list hoặc fitted artifacts đã được implement.

## 3. Scenario contract

Mỗi scenario có stable ID, beta/gamma trong bounds và generation method/provenance. Metadata phải nói rõ số scenarios, weighting nếu có, quantile method và seed nếu thuật toán ngẫu nhiên.

Bootstrap parameter scenarios đã chọn ở mức hướng thiết kế GD-04, nhưng chưa chốt bootstrap scheme/blocks/replicates, weighting hoặc quantile interpolation. Không gọi scenario coverage là 95% confidence guarantee. Nếu scenarios chỉ biến beta/gamma, các coefficients khác giữ nominal; việc mở rộng uncertainty sang coefficients/forecast/K cần quyết định riêng.

Candidate và baseline dùng cùng scenario; baseline FR được recompute với gamma tương ứng. Không shuffle pair, không drop invalid scenarios rồi âm thầm renormalize. Rejection làm artifact không eligible; GGSO run nhận technical INVALID, không recommendations/policy/execution request; không xuất fallback policy.

## 4. Acceptance và compatibility

RA-01: đủ unique required cells, finite/bounded parameters, vector dimensions và feature ordering chính xác.

RA-02: schema/semantic/preprocessing versions tương thích consumer; unknown NB convention hoặc context transform không được tự đoán.

RA-03: validation status có evidence và support rule; missing/invalid cell làm toàn artifact không eligible cho required network.

RA-04: serialization round-trip giữ scenario IDs/coefficients/order; candidate và baseline tái tạo cùng kết quả theo numerical tolerance đã duyệt.

Support/calibration thresholds, artifact storage format cuối và estimator configuration thuộc GD-04/G01/G03. Chưa có artifact đã train hoặc test PASS trong lần cập nhật tài liệu.
