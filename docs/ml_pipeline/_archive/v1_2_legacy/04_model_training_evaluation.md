# 04 — Model, training objective và evaluation

**Trạng thái:** đặc tả triển khai; chưa phải implementation hoặc kết quả benchmark.  
**Model chính:** dual_gru_gatv2_h5_v1_2.  
**Contract:** hex29_edge10_v1_2; target ds_log1p_h5_v1_2; graph directed_relations_self_v1.  
**Nguồn chuẩn:** docs/model/technical_report.md V1.2 bản đối chiếu mới nhất ngày 2026-10-09; metadata/feature_contract của HCM mock v2; archive và các snapshot code đã đọc trong lần khảo sát. SHA-256 report mới nhất: 7cd8bfecd96825710a848a66eeabb730f1328f28c00927bcdf5f7311922212fa.

## 1. Kết quả cần tạo ra

Pipeline mới huấn luyện một shared temporal encoder và hai prediction head. Head local dự báo bằng representation của chính node; head graph nhận thêm message từ các node liên quan. Hai head dự báo cùng tỷ lệ demand/effective supply tại t+5 phút, cùng target transform, cùng cutoff, cùng bộ mẫu hợp lệ. Controller nhận hai forecast sau inverse transform, nhưng không tham gia loss training.

Bidding hiện tại đang có lợi nhuận theo chủ dự án; tác động đến cân bằng marketplace chưa được xác minh. Forecast tốt hơn chưa chứng minh correction mới tốt hơn về GMV, lợi nhuận hoặc chất lượng dịch vụ. Relative Graph Revision là chênh lệch prediction, không phải network effect nhân quả. [Confidence: Cao — yêu cầu và ranh giới thiết kế trong M1; hiệu quả kinh doanh chưa được đo.]

Các model, scaler, inverse transform, danh sách feature, mapping node và graph contract phải được đóng gói cùng nhau. Model chỉ được so sánh trên cùng dataset derivative, split và evaluation population. Không tận dụng nhãn legacy bằng cách đổi tên cột.

### 1.1. Ký hiệu trong report mới nhất và aliases của pipeline

Bản report đối chiếu cuối vẫn có 843 dòng; 123 dòng thay đổi cách đặt ký hiệu so với snapshot đầu. Đối chiếu các dòng thay đổi xác nhận target, horizon, kiến trúc, loss, direction gate và các hằng số không đổi. [Confidence: Cao — so sánh trực tiếp hai snapshot report.]

| Report mới nhất | Alias nội bộ trong specs/code | Ý nghĩa không đổi |
|---|---|---|
| DS, DS_true | q, q_true, q_h5 | Tỷ lệ D/S_eff thật; q_h5 là artifact target H5 |
| DS_local | q_L, q_local, qhat_local | Forecast sau inverse của local head |
| DS_graph | q_G, q_graph, qhat_graph | Forecast sau inverse của graph head |
| DS_ref | q_star | Reference D/S của controller |
| DS_min | q_min | Ngưỡng denominator local để áp dụng Revision |
| Pressure | P | (DS_graph−DS_ref)/DS_ref |
| Revision | R, relative_revision | (DS_graph−DS_local)/DS_local |
| tau_press, tau_rev | tau_P/tau_pressure, tau_R/tau_revision | Hai dead zones |
| k_press, k_rev | k_P/k_pressure, k_R/k_revision | Hai gain chuyển sang điểm surge |
| corr_press, corr_rev, corr | a_P, a_R, a/correction_raw | Hai thành phần và tổng correction |
| L_local, L_graph | L_L, L_G | Hai supervised losses |
| theta_enc/local/GAT/graph | theta_E/L/G/H | Các nhóm parameters encoder/local/GAT/graph head |
| DZ | dead, D(x;tau) khi chỉ toán tử dead zone | Không phải raw demand D |

q trong toàn bộ phần training/evaluation này là alias của DS, không phải xác suất và không phải target legacy. Giữ tên artifact q_h5 và metric key val/graph/mae_q/h5 để contracts của bộ specs nhất quán; MAE_q và MAE_DS tính cùng đại lượng với cùng đơn vị, population và reduction. Không tạo một metric khác chỉ vì report đổi ký hiệu.

Tên public response/controller dùng ds_local, ds_graph, ds_ref và ds_min theo [06_artifacts_and_serving.md](06_artifacts_and_serving.md). Adapter ánh xạ aliases nội bộ sang các tên public một lần, không thêm công thức biến đổi. Việc đổi tên không cho phép đổi target contract hoặc áp inverse V1.2 lên checkpoint legacy.

## 2. Đối chiếu archive/snapshot legacy và migration

Tại lần recheck cuối, pipeline/ chỉ còn pyproject.toml, uv.lock và .gitignore; các script model/training/evaluation đã đọc ban đầu không còn là implementation đang có thể gọi tại những đường dẫn cũ. Archive hiện được xác nhận có model.py, prepared_data.py và train_v2.py dưới data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/. Vị trí data/hcm_data_2/provenance/pipeline/ đã được di chuyển và không còn là đường dẫn archive chuẩn. Chưa xác nhận archive cho train.py, evaluate.py, config.yaml hoặc spec.md. Không giả định ba file archive tạo thành một pipeline chạy được vì các imports/dependencies đi kèm cần được kiểm tra riêng.

Bảng sau mô tả hành vi của code/snapshots đã kiểm tra đầu task để làm rõ migration. Nó không xác nhận các entrypoint legacy vẫn chạy trong working tree cuối. Nguồn từng mục và trạng thái tồn tại được ghi tại mục 12.

| Hạng mục | Hành vi legacy đã quan sát | Yêu cầu mới |
|---|---|---|
| Model output | M2: mỗi GRUNet có một đường local hoặc graph, các head phân theo horizon, output b+residual | Một model có local head và graph head, mỗi head một horizon H5 |
| Target | M3/M4/M6: log((D+eps)/(Seff+eps)); train_v2 dùng eps=1 | log1p(D/Seff), Seff>0, không cộng eps vào target |
| Inverse | exp(output) chỉ cho smoothed ratio của legacy | expm1(output), chỉ khi checkpoint đúng target contract |
| Window/horizon | M3: W4, H5/10/15; M6 giữ nguyên | W12, H5; index/window tính lại từ derivative manifest |
| Loss | M2: Huber, log1p(volume), phạt underprediction bất đối xứng; diff/rank/short tùy config | Masked SmoothL1 hai head, không volume weighting/asymmetric term mặc định |
| Selection | M3/M5: PairAcc@10 | Validation graph MAE ở raw ratio H5, có gate local/coverage |
| Graph | M2 thêm mọi reverse edge và self-loop tự động | Directed relation rows + một synthetic identity self/node; không reverse mặc định |
| Dữ liệu prepared | M6/M7 đã có adapter cho release 30 ngày, tensor 40 node/10 edge, nhưng b/y/model vẫn legacy | Adapter mới chọn 29 encoder channels; target/scaler/sample index mới |
| Evaluation | M8 báo một output, MAE logspace, PairAcc và Spearman | Báo riêng local/graph, raw/log error, bias, coverage và paired improvement |
| Tracking | M5/M6 lưu file run cục bộ | Run/experiment/model package do phần MLflow của bộ specs quản lý |
| Test access | M5 chạy test sau mỗi fit, kể cả mỗi trial có thể được người dùng so sánh | Tuning chỉ train/val; test chỉ chạy sau khi freeze shortlist/evaluation plan |
| Reload | M6 kiểm tra finite/shape cho Torch, chưa so sánh numerical predictions | Round-trip equality trong tolerance, same cutoff/mapping/contract |
| Model factory | M2 model name lạ có thể rơi xuống GRUNet không graph | Unknown model_id phải lỗi config, không fallback ngầm |

M8 gọi PairAcc trên mọi cặp hex không thứ tự tại cùng timestamp; M4 mô tả cặp OD. Đây là khác biệt đã xác minh. Spec mới đặt tên pairacc_all_hex để biểu đạt đúng tập cặp; nếu cần OD-only metric phải dùng metric_id riêng, có edge snapshot và pair mask rõ ràng.

M8 dựng matrix bằng gán index nên duplicate (timestamp,hex,horizon) có thể ghi đè trước khi tính metric. Evaluator mới phải reject duplicate key thay vì tự giữ dòng cuối. M5 giả định best state tồn tại; nếu mọi checkpoint score NaN hoặc không có bước hợp lệ, truy cập best state sẽ hỏng. Trainer mới phải trả trạng thái FAILED với reason tương ứng.

[Confidence: Cao — hành vi đã đọc trực tiếp trong M2–M8 tại snapshot khảo sát; vị trí archive và trạng thái working tree đã được recheck riêng.] Các báo cáo smoke đã lưu chỉ mô tả plumbing của legacy adapter ở lần chạy trước. Chúng không xác nhận scripts còn tồn tại, chạy được ở working tree cuối hoặc đạt benchmark V1.2.

## 3. Model registry nội bộ và baseline

Model factory đặt tại pipeline/src/surge_ml/models/. Model ID là định danh architecture/behavior, khác MLflow run_id và registered model version.

| model_id | Inputs | Output | Mục đích |
|---|---|---|---|
| persistence_true_ds_h5_v1 | D_t, Seff_t chưa chuẩn hóa | qhat=q_t, yhat=log1p(q_t) | Baseline persistence tương thích target mới |
| lgbm_context29_h5_v1 | Current29 tại cutoff; rolling/momentum có sẵn trong source | Một forecast H5 | Tabular baseline |
| lgbm_aggregate40_h5_v1 | Current40 tại cutoff; rolling/momentum có sẵn trong source | Một forecast H5 | Baseline mạnh có network aggregates nhưng không GNN |
| gru_context29_h5_v1 | W12 × local/context29 | Một forecast H5 | Local model độc lập, không chịu joint-loss compromise |
| gru_aggregate40_h5_v1 | W12 × all40 | Một forecast H5 | Kiểm tra lợi ích từ network summaries |
| dual_gru_gatv2_h5_v1_2 | W12 × local/context29 + directed edge10/flags | Hai forecast local/graph H5 | Model chính |
| dual_gru_gatv2_h5_v1_2 + ablation config | Cùng target và split | Hai forecast | Bỏ relation/feature hoặc thay graph augmentation, có run tags riêng |

Baseline persistence không dùng source baseline.npy vì file đó mang transform legacy. Persistence invalid khi Seff_t<=0; không tự đổi denominator. Đánh giá phải ghi coverage riêng và paired intersection cố định để so sánh persistence; coverage thấp không được che bằng MAE thấp.

Local head trong model chính gọi đầy đủ là **pointwise local/context29**. 29 cột đầu không chứa 11 aggregate network tường minh của release, nhưng các feature operational như ETA có thể đã phản ánh thông tin ngoài hex. Không tuyên bố local head là baseline hoàn toàn không có ảnh hưởng địa lý/network. Hai baseline all40 là bắt buộc để kiểm tra giá trị tăng thêm của message passing trên thông tin tổng hợp sẵn có.

Những tên baseline B0/B2/B3 trong các ý tưởng trước đây chỉ được sử dụng nếu có mapping rõ sang model_id/config mới. Không dùng cùng tên cho target hoặc horizon khác.

LGBM baseline phải train target mới trực tiếp hoặc dùng residual với persistence mới dưới một model_id riêng. Default là direct log1p target. Prediction logspace âm phải đi qua output policy được khai báo: baseline_reject_negative_v1 báo invalid; nếu chọn clipping hoặc constraint cho baseline, đó là adapter version mới và phải báo tỷ lệ bị clip. Không silently áp Softplus lên một estimator đã fit với objective khác.

[Confidence: Trung bình — quyết định thiết kế phục vụ so sánh có kiểm soát. Lợi ích GNN chưa được chứng minh.]

## 4. Tensor contract và forward pass

### 4.1. Batch

| Trường | Shape/dtype | Quy tắc |
|---|---|---|
| x_local | [B,12,N,29], float32 | Theo ordered feature names; N lấy từ node mapping, không hard-code 61 |
| input_valid | [B,N], bool | Chỉ dựa trên thông tin khả dụng tại t |
| y_target | [B,N,1], float32 cho training | H5 log1p true ratio |
| q_target | [B,N,1], float64 cho evaluation | D/Seff tại t+5, giữ raw target để kiểm tra inverse |
| target_valid | [B,N,1], bool | Window hợp lệ và label thuộc domain/split |
| edge_index | [2,E_batch], int64 | Hàng 0 source, hàng 1 destination |
| edge_attr | [E_batch,12], float32 | 10 source edge features + is_reverse + is_self |
| graph_batch | [B*N] hoặc offsets | Bảo đảm không cross-sample edges |
| decision_ts, forecast_ts | [B] | forecast_ts = decision_ts + 5 phút |
| hex_ids/node_mapping_hash | N identifiers + hash | Cùng mapping train/inference |
| source_batch_keys | B sample keys | Truy ngược sample manifest |
| support_sidecars | D_t, Seff_t, volume, validity | Không tự ghép vào x_local |

Đầu vào GNN chỉ được loại/mask theo input validity đã biết tại cutoff t. **Không lọc node hoặc cạnh dựa trên target_valid của t+5**, vì graph structure như vậy có thể tiết lộ thông tin tương lai. Target mask chỉ chi phối loss/evaluation. Một node không có label tương lai vẫn có thể gửi message nếu input của nó hợp lệ.

Invalid numeric inputs phải được xử lý trước forward theo feature contract. Không đưa NaN vào GRU/GAT rồi hy vọng target mask loại được ảnh hưởng, vì NaN có thể lan sang node lân cận.

### 4.2. Encoder và heads

Với h_L = GRU(x_local), reshape [B,W,N,F] → [B*N,W,F], lấy hidden state cuối, rồi:

~~~text
raw_local = MLP_local(h_L)
h_G = GraphEncoder(h_L, edge_index, edge_attr)
raw_graph = MLP_graph(h_G)

yhat_local = softplus(raw_local)
yhat_graph = softplus(raw_graph)

qhat_local = expm1(yhat_local)
qhat_graph = expm1(yhat_graph)
~~~

- Hai MLP có parameters riêng; shared GRU chỉ chia sẻ weights giữa node/head.
- Không cộng legacy b vào hai output.
- Không detach h_L trước GNN hoặc trước local head.
- Không concatenate qhat_local vào graph head trong default architecture.
- Cả hai output shape [B,N,1]; horizon dimension không bị squeeze tùy batch size.
- Inverse cho metrics/serving tính bằng float64; finite/domain check sau inverse.
- ForecastBatch trả yhat_local, yhat_graph và metadata; inverse adapter tạo qhat và validity. Không tính Pressure/correction trong model.forward().

### 4.3. Miền dương được chốt cho implementation

Output domain mặc định là softplus_log1p_v1:

\[
\hat y=\operatorname{Softplus}(r;\beta_{\mathrm{activation}}=1,\mathrm{threshold}=20),
\qquad \hat q=\operatorname{expm1}(\hat y).
\]

Softplus tránh yhat âm về mặt kiến trúc. Giá trị thật q=0 vẫn hợp lệ; model có thể xấp xỉ 0, không phải luôn biểu diễn chính xác 0 trong số thực. qhat nhỏ không được dùng làm denominator revision khi q_local < q_min của controller; equality q_local=q_min hợp lệ nếu các preconditions khác đạt.

M1 chưa chốt positivity activation; lựa chọn này là quyết định triển khai bổ sung, phải lưu output_domain_version và retrain. Nó không phải chứng minh kiến trúc tốt hơn linear head. Không áp activation này vào output checkpoint legacy. [Confidence: Cao — domain từ công thức/R1; Trung bình — lựa chọn activation cho bài toán.]

Nếu output/inverse overflow hoặc không finite trên mẫu data-valid, ghi MODEL_NONFINITE_OUTPUT và fail gate. Không clamp forecast vào một max arbitrary để làm metric có vẻ hợp lệ. Validation range dùng trong controller là chính sách riêng, không tự sửa giá trị forecast được lưu.

## 5. Graph encoder cụ thể

Default backend đề xuất là PyTorch Geometric GATv2Conv, được pin trong lockfile khi triển khai và kiểm tra phù hợp Torch/CPU/GPU. Số layer=2, hidden_dim=64, heads=4, head_hidden=32, dropout=0.1 là pilot defaults; phải ghi là hyperparameters cần kiểm chứng.

Mỗi block:

~~~text
u = GATv2Conv(
    in_channels=gru_hidden,
    out_channels=gru_hidden // gat_heads,  # assert gru_hidden % gat_heads == 0
    heads=gat_heads,
    concat=True,
    dropout=0.1,
    edge_dim=12,
    add_self_loops=False,
    share_weights=False,
    residual=False
)(h, edge_index, edge_attr)

h_next = LayerNorm(h + Dropout(ELU(Linear(u))))
~~~

GATv2 chuẩn hóa attention trên incoming edges của từng destination/head; edge attributes tác động attention. Wrapper định nghĩa residual/activation rõ, không bật thêm residual bên trong Conv rồi vô tình cộng hai lần. Một backend custom có thể được giữ làm ablation nhưng phải mang backend_id khác; không khẳng định checkpoint custom load trực tiếp vào PyG.

### 5.1. Relation direction và self-loops

- Giữ source directed relation rows do graph adapter cung cấp, theo cutoff t.
- Default không tạo reverse synthetic. Legacy reverse-copy là ablation riêng, không tự xem như OD quan sát hướng ngược.
- Thêm đúng một synthetic identity self-loop cho mỗi input-valid node: base edge numeric values bằng 0 theo transformed-space convention của graph adapter, is_reverse=0, is_self=1.
- Observed OD self (trip origin=destination) có is_self=0; đó là relation quan sát khác synthetic identity. Nếu tồn tại cả hai thì multiplicity là chủ ý và phải giữ relation identity.
- Duplicates cùng (sample,source,destination,relation identity) phải reject hoặc aggregate bằng rule trong graph contract trước model. Không coalesce mọi parallel edge chỉ theo endpoints vì có thể mất relation semantics.
- Module GAT không tự augment edge sau loader. add_self_loops=False bảo đảm feature order và synthetic self không bị PyG thay thế.
- Chỉ hai cờ is_reverse/is_self là 0/1 và không z-score; hai cờ relation nguồn vẫn z-score trong 10 chiều source. Statistics của 10 numeric/source features lấy từ train graph cutoffs.
- Dataset chỉ có self neighborhood vẫn forward finite. Empty invalid-node graph không tự sinh score có nghĩa; input validity được giữ trong outputs.

Với edge deltas có dấu, quy ước source-minus-destination phải nhất quán với manifest. Nếu ablation reverse được bật, signed endpoint features phải recompute cho hướng message mới hoặc giữ physical-edge attributes dưới tên thể hiện provenance; không copy rồi đổi ý nghĩa vật lý.

### 5.2. Invariants

Các graph sample b được offset b*N khi N cố định; nếu N biến đổi, dùng prefix offsets. Cạnh source/destination phải nằm trong cùng sample. Attention sum kiểm tra ở eval/pre-dropout, không yêu cầu weights sau dropout trong training cộng đúng 1.

Đổi input của neighbor có thể làm graph prediction thay đổi; không ép nó phải thay đổi. Với parameters cố định và input của node i giữ nguyên, local forecast tại i phải không đổi khi chỉ sửa hàng node j khác. Kiểm tra này chỉ xác nhận computational path; không chứng minh local data tuyệt đối không chứa network information.

[Confidence: Cao — R3 và tensor semantics; Trung bình — default directed augmentation và pilot architecture được bổ sung để triển khai.]

## 6. Target và masked objective

Label H5 phải được dựng từ raw source demand và effective_supply ở next snapshot, dựa vào ordered names trong contract; vị trí đã quan sát của HCM v2 là node index 0 và 29. Vị trí không thay thế tên/schema check.

\[
q^{true}_{b,i}=\frac{D_{b,i,t+5}}{S^{eff}_{b,i,t+5}},
\quad
y_{b,i}=\log(1+q^{true}_{b,i}),
\quad S^{eff}>0,\ D\ge0.
\]

Không dùng exp(legacy_y), expm1(legacy_y), baseline.npy hoặc normalized node tensors để khôi phục true q. Target availability, split support và invalid counts do data contract quyết định.

Với mask m đã freeze từ dữ liệu, Z=sum(m)>0:

\[
\ell_\beta(e)=
\begin{cases}
e^2/(2\beta),& |e|<\beta,\\
|e|-\beta/2,& |e|\ge\beta,
\end{cases}
\]
\[
L_L=\frac{\sum m\,\ell_\beta(\hat y^L-y)}{Z},
\qquad
L_G=\frac{\sum m\,\ell_\beta(\hat y^G-y)}{Z},
\qquad
L=L_G+\lambda_L L_L.
\]

Defaults: smooth_l1_beta=1.0, lambda_local=1.0, lambda_spatial=0.0. Beta của loss khác beta của Softplus. SmoothL1(beta)=Huber(beta)/beta; không thay bằng legacy Huber khi beta khác 1 mà bỏ qua scale. [Confidence: Cao — M1 và R2.]

Implementation phải chọn phần tử valid **trước** tính error/loss:

~~~python
valid = batch.target_valid
n = valid.sum()
if n == 0:
    return LossResult(skip=True, valid_count=0)
yl = out.yhat_local[valid]
yg = out.yhat_graph[valid]
yt = batch.y_target[valid]
require_finite(yl, yg, yt)
loss_local = smooth_l1_loss(yl, yt, beta=beta, reduction="sum") / n
loss_graph = smooth_l1_loss(yg, yt, beta=beta, reduction="sum") / n
loss_total = loss_graph + lambda_local * loss_local
~~~

NaN*0 vẫn NaN; không mask bằng phép nhân sau khi loss đã nhiễm NaN. Finite prediction không được thêm vào mask để âm thầm bỏ lỗi model. Target invalid được mask; prediction invalid trên target-valid là lỗi trial.

lambda_spatial>0 phải bị config validator reject khi chưa có spatial_loss_id/formula/acceptance được phê duyệt bằng spec version mới. Không gán legacy diff/rank thành spatial loss. Legacy volume weighting, asymmetric rho, rank và multi-horizon consistency không nằm trong default loss này.

Nếu Z=0: không backward, optimizer.step hoặc scheduler optimizer-step; tăng skipped_all_masked_batches. Một epoch không có bước hợp lệ phải fail EMPTY_TRAIN_EPOCH. Log valid denominator và tổng loss numerator để aggregate epoch theo số phần tử hợp lệ; không trung bình đều batch means khi batch cuối/mask counts khác nhau. Nếu mở gradient accumulation sau này, scale theo tổng valid count của accumulation group.

lambda_local=0 chỉ được dùng như ablation tách riêng và không đủ điều kiện đóng gói controller cần local forecast. Giá trị lambda_local khác 1 được lưu trong config; không diễn giải nó thành confidence hoặc tỷ lệ parameter movement.

## 7. Gradient và train loop

Với lambda_spatial=0:

\[
\nabla_{\theta_E}L=\nabla_{\theta_E}L_G+\lambda_L\nabla_{\theta_E}L_L,\quad
\nabla_{\theta_L}L=\lambda_L\nabla_{\theta_L}L_L,
\]
\[
\nabla_{\theta_{GAT}}L=\nabla_{\theta_{GAT}}L_G,\quad
\nabla_{\theta_{graph\ head}}L=\nabla_{\theta_{graph\ head}}L_G.
\]

Một total_loss.backward() đủ tính gradient cho cả hai đường. Tổng loss giảm không bảo đảm mỗi head đạt minimum riêng; shared encoder có thể thỏa hiệp giữa objectives. Không làm local head yếu đi để tạo revision lớn. [Confidence: Cao — chain rule và kiến trúc trong M1.]

Train loop yêu cầu:

1. Seed Python/NumPy/Torch, data-order generator và CUDA khi dùng; lưu deterministic settings/hardware, không hứa bitwise equality qua mọi platform.
2. Train-only dataset/scaler; model.train() trước epoch, model.eval()+no_grad() khi validation.
3. optimizer.zero_grad(set_to_none=True) trước mỗi step.
4. Forward → masked objective → finite loss check → backward → gradient finite check → grad clipping → optimizer step.
5. Default AdamW: lr=3e-4, weight_decay=0, grad_clip_norm=1, batch_size=8, max_epochs=50, patience=10. Đây là pilot config kế thừa vài kích thước legacy, chưa phải tối ưu.
6. Nonfinite loss/gradient trên valid population làm trial FAILED; lưu diagnostic batch keys và reason. Không tiếp tục hàng loạt step lỗi rồi đánh dấu FINISHED.
7. Checkpoint tốt nhất theo metric selection đã freeze; optimizer/RNG state của resumable checkpoint khác inference bundle chỉ chứa weights/config.
8. Epoch metrics là sum/count chuẩn hóa. Log local loss, graph loss, total loss, valid labels, skipped batches, grad norm trước clip, epoch seconds, learning rate.
9. Nếu không có finite selection metric hoặc không tạo được valid best checkpoint, fail NO_VALID_CHECKPOINT. Không load best state rỗng.
10. Cuối training chỉ evaluate train/val của checkpoint được chọn. Test nằm trong evaluation stage tách, sau shortlist freeze.

Diagnostic gradient decomposition chạy trên batch nhỏ khi implement: tính gradient từng loss và gradient tổng từ cùng forward/deterministic dropout state, so sánh trong tolerance. Không đánh đồng một tensor gradient bằng 0 tại điểm đặc biệt với module bị disconnect; cấu trúc đường dẫn và tập parameters được optimizer quản lý phải được kiểm tra.

## 8. Checkpoint selection và experiment plan

Metric mặc định: val/graph/mae_q/h5, minimize. Tie tolerance và tie-break phải được freeze trong evaluation config; default dùng smaller local MAE rồi epoch sớm hơn trong numeric tolerance. Không chọn bằng min training loss hoặc test result.

Candidate selection cần kiểm tra local forecast vì local nằm trong denominator Relative Revision. Đề xuất gate pilot:

| Gate | Rule |
|---|---|
| Data/shape/transform | Contract hashes khớp; acceptance invariants pass |
| Forecast domain | Không nonfinite hoặc negative q trên required validation population |
| Coverage | Báo required_count, produced_count, invalid_count; không giảm population sau khi thấy prediction |
| Local quality | local MAE không vượt independent gru_context29 baseline quá tolerance đã freeze |
| Graph quality | Báo paired difference với persistence, GRU29, GRU40 và LGBM40 |
| Promotion về forecasting | Chỉ đủ bằng chứng kỹ thuật cho bước shadow/offline; model thắng bằng point estimate chưa được gọi significant |
| Controller use | Local trained; model+reference+policy+global bounds contract compatible; policy validation riêng |

Tolerance cho local regression phải xuất hiện trong evaluation plan trước test. Pilot có thể dùng 5% relative regression so với independent local GRU, nhưng phải ghi là engineering threshold, không được trình bày là mức an toàn kinh tế. Nếu benchmark lỗi gần 0, dùng absolute tolerance explicit thay cho chia denominator gần 0.

Tuning dùng train/val. Freeze search space, trial budget, metric, seed list và data fingerprint. Baseline đều dùng cùng cutoffs/labels/horizon; lưu training budget và parameter count để tránh so sánh capacity/time budget ngầm khác nhau. Có thể khác thuật toán và feature profile, nhưng phải ghi information set đầy đủ.

Sau tune: freeze shortlist và config; chạy các seed đã định trước, không chỉ giữ seed tốt nhất. Test evaluator chỉ được đọc frozen artifacts; mọi test access có evaluation record. Không chạy test tự động sau từng tuning trial. Nếu dùng test để sửa model/hyperparameter, test đó trở thành development evidence; cần test mới trước claim cuối.

Ablation tối thiểu: independent GRU29, GRU40, LGBM40; remove OD; remove travel-time/ETA edge group; valid graph perturbation; reverse augmentation legacy; lambda_local variants. Perturbation graph chỉ là robustness/ablation, không là causal proof.

## 9. Evaluation population và metrics

### 9.1. Prediction record

Evaluator tiêu thụ một schema chung, không import trainer/model:

| Trường | Nội dung |
|---|---|
| run_id, model_id, head | head=main cho baseline; local/graph cho dual |
| dataset_id, dataset_fingerprint, derived_contract_hash | Data lineage |
| split, sample_id, hex_id, decision_ts, forecast_ts, horizon_min | Định danh |
| y_true, q_true, y_pred, q_pred | Hai không gian, không field lambda mơ hồ |
| data_eligible, prediction_valid, invalid_reason | Coverage và domain |
| target_available_ts | Kiểm soát nhãn đến muộn |
| demand_true, effective_supply_true, volume_true | Label diagnostics, không feature input |
| input_feature_cutoff_ts, feature_age_max_sec | Replay context |
| feature_schema_version, target_transform_version, graph_contract_version | Reproducibility |

Primary key: (run_id, split, sample_id, hex_id, horizon_min, head). Duplicate reject. Evaluator phải assert q_true≈expm1(y_true) trên valid domain; inverse/version mismatches fail.

### 9.2. Denominator và missing predictions

Population chính được freeze từ sample/target manifest trước khi chạy model. Mọi mẫu phải có record, kể cả invalid target hoặc invalid prediction; không chỉ export dòng thành công.

- data_eligible=false: loại khỏi forecast accuracy nhưng báo count theo reason.
- data_eligible=true, prediction_valid=false: tính vào invalid coverage; primary score không được dùng để pass gate. Có thể báo finite-only diagnostic score với tên rõ, nhưng status FAILED_COVERAGE.
- Paired comparisons dùng cùng data-eligible key set. Nếu một baseline có domain invalid đã được định nghĩa từ inputs, báo common-support population cùng excluded counts; không thay population riêng cho mỗi model để xếp hạng chung.
- Khi không có phần tử hợp lệ hoặc không có eligible pairs: metric=null, status=UNDEFINED, numerator/denominator=0. Không dùng 0 làm một score tốt.
- Chỉ số raw q không chia cho q_true để tránh zero-demand singularity. MAPE không là metric mặc định.

### 9.3. Metrics bắt buộc

Với cùng population m:

\[
MAE_q=\frac{\sum m|\hat q-q|}{\sum m},
\quad RMSE_q=\sqrt{\frac{\sum m(\hat q-q)^2}{\sum m}},
\quad Bias_q=\frac{\sum m(\hat q-q)}{\sum m}.
\]

Báo mỗi head H5: MAE_q, RMSE_q, Bias_q, MAE_log1p, SmoothL1_log1p; số observations/timestamps/nodes; prediction invalid rate; distribution q và error quantiles. Đây là forecast metrics, không phải expected GMV hoặc surge accuracy.

Incremental forecast benefit:

\[
d_{t,i}=|\hat q^L_{t,i}-q_{t,i}|-|\hat q^G_{t,i}-q_{t,i}|.
\]

mean(d)>0 nghĩa graph error nhỏ hơn local trên population đó. Báo thêm d với independent baselines. Không dùng mean(|R|) hoặc tỷ lệ revision khác 0 làm thước đo model tốt.

Báo theo time-of-day, node/region, demand/supply volume bands, q bands, controller-eligible population, |R| lớn, pressure gần dead zone. Band thresholds được freeze bằng train/config; không chọn bins sau khi xem test để tạo kết quả đẹp. Luôn kèm count cho từng slice và gắn insufficient_support khi quá ít mẫu.

PairAcc_all_hex dùng mọi cặp i<j trong cùng timestamp, có truth finite, mask chung, volume đạt ngưỡng và |y_i-y_j|>margin_log1p. Prediction tie với true non-tie tính sai. margin đơn vị log1p phải được lưu; ngưỡng legacy 0.1 không tự có nghĩa tương đương trong transform mới. Nếu tính OD-only, deduplicate unordered pair hoặc giữ directed edge-weighted definition riêng, không trộn hai denominator.

Spearman tính theo timestamp giữa các node, sau đó mean theo timestamp; n<3 skip; constant forecast convention phải explicit (pilot=0) và báo số constant timestamps. PairAcc/Spearman chỉ là diagnostics về thứ tự không gian, không thay thế level error để controller dùng q.

### 9.4. Uncertainty trong kết quả

Các hex cùng timestamp và các windows gần nhau phụ thuộc nhau. Không bootstrap ngẫu nhiên từng row như dữ liệu i.i.d. để tạo khoảng tin cậy quá hẹp. Nếu dùng block bootstrap, resample nguyên block thời gian gồm toàn bộ hex; block length/seed/number of resamples phải freeze và báo autocorrelation assumptions.

Dataset pilot chỉ 30 ngày với số ngày val/test ít; day-block confidence interval có thể rất thiếu chính xác. Báo point estimates, paired per-day errors và khoảng bất định cùng giới hạn này. Chưa có interval đủ thuyết phục thì không kết luận GNN thắng chắc chắn. Không cam kết một improvement threshold ngoài dữ liệu. [Confidence: Cao — dependence theo thiết kế window/graph; Trung bình — bootstrap là phương pháp đánh giá đề xuất.]

## 10. Liên kết controller và giới hạn claim

Model không học q_star, dead zones, gain, correction ±0.4, global cap hoặc confidence. Các tham số đó được quản lý bởi policy artifact riêng. ForecastBatch và controller input phải cùng target/inverse version.

Evaluator forecasting không báo PricingRegret, optimal_delta_s, GMV uplift hoặc causal network effect khi dataset chỉ chứa observational/mock trajectories không có action-response oracle được chấp thuận. Không suy giá optimal từ q=1 hoặc từ sign forecast.

Controller replay trên frozen forecasts theo dõi requested/applied action distributions, cap rates, gate-block rate, REVIEW reasons, sign changes và temporal jumps. Những con số này là hành vi policy, không phải lợi ích kinh doanh. k_R=0 là ablation bắt buộc khi đánh giá giá trị Relative Revision; giữ forecasts cố định để so controller.

Confidence labels trong tài liệu này nói về bằng chứng của đặc tả; không trở thành model confidence hay hệ số nhân surge.

## 11. Acceptance criteria cho implementation

| ID | Điều kiện phải chứng minh | Loại kiểm chứng |
|---|---|---|
| M-01 | Hai heads shape [B,N,1], H5 cùng cutoff/mapping/target | Unit + contract |
| M-02 | GRU input W12 và đúng ordered29; sidecar Seff không tự nhập encoder | Fixture contract |
| M-03 | q=0,S>0 round-trip; S=0 masked; legacy target bị reject | Target unit |
| M-04 | Positive-domain metadata lưu/load đúng; nonfinite inverse bị chặn | Domain unit |
| M-05 | Graph source→destination đúng; không cross-batch; flags order đúng | Graph nhỏ tính tay |
| M-06 | Synthetic self một/node; observed OD self riêng; không reverse default | Graph contract |
| M-07 | Model graph không phụ thuộc future target mask | Input perturbation |
| M-08 | Local forward tại i không đổi khi chỉ sửa node j; graph phép đổi nhưng không bị ép | Isolation unit |
| M-09 | SmoothL1 trên valid indices; all-masked skip; invalid prediction không bị drop khỏi score | Loss/mask unit |
| M-10 | Gradient tới GRU/cả hai heads/GAT theo công thức; lambda_spatial>0 không spec bị reject | Gradient fixture |
| M-11 | Overfit một batch sạch với dropout tắt giảm cả local và graph loss đến tolerance định trước | Diagnostic, không benchmark |
| M-12 | Epoch aggregate đúng sum/count khi mask/batch size không đều | Metric fixture |
| M-13 | Duplicate keys reject; absent pairs→null; constant-rank convention đúng | Evaluation fixture |
| M-14 | Checkpoint selection theo validation H5 raw MAE; train/tune không đọc test | Integration boundary |
| M-15 | Không có finite candidate→FAILED, không crash vì best state thiếu | Failure-path test |
| M-16 | Save/load predictions bằng nhau trong tolerance và hashes match | Package round-trip |
| M-17 | Report có baseline GRU29/GRU40/LGBM40, coverage, paired sample counts, seed budget | Report validator |
| M-18 | Smoke run gắn run_kind=smoke, không eligible promotion/model-quality claim | Lifecycle integration |
| M-19 | Model/policy/schema mismatch fail trước correction; local q nhỏ có REVIEW ở controller | Integration contract |

Các test trên mô tả công việc cần triển khai và acceptance có ý nghĩa; việc viết spec không đánh dấu chúng đã pass. Không có yêu cầu mở rộng test tùy ý sau khi concrete risk đã được xác minh.

## 12. Nguồn và confidence

**Nguồn dự án và trạng thái tại lần recheck cuối:**

| ID | Nguồn đã dùng | Trạng thái / phạm vi bằng chứng |
|---|---|---|
| M1 | [docs/model/technical_report.md](../model/technical_report.md), V1.2, mục 5–9, 13–16 | Đã đối chiếu bản hash 7cd8bfecd96825710a848a66eeabb730f1328f28c00927bcdf5f7311922212fa. Bản mới thay ký hiệu DS/Pressure/Revision, không thay semantics training/controller |
| M2 | Snapshot đầu của pipeline/model.py; [archive model.py](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/model.py) hiện có | Formula, GRUNet, GATv2Layer, compute_loss và LGBMModel là code legacy; không phải model V1.2 đang runnable trong pipeline/ |
| M3 | Snapshot đã đọc của pipeline/config.yaml | Đường dẫn cũ không còn trong working tree cuối; chưa xác nhận archive. Chỉ dùng mô tả cấu hình legacy đã quan sát |
| M4 | Snapshot đã đọc của pipeline/spec.md, legacy V1 | Đường dẫn cũ không còn; chưa xác nhận archive. Không phải spec authoritative của implementation mới |
| M5 | Snapshot đã đọc của pipeline/train.py | Hành vi fit_torch, train_epoch, save_and_report, to_frame đã được khảo sát. File không còn ở đường dẫn cũ; chưa xác nhận archive |
| M6 | Snapshot đầu của pipeline/train_v2.py; [archive train_v2.py](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/train_v2.py) hiện có | Adapter/smoke legacy. Việc có archive không bảo đảm imports và runtime có đủ để chạy script |
| M7 | Snapshot đầu của pipeline/prepared_data.py; [archive prepared_data.py](../../data/_archive/hcm_data_2_v2_packed/source_snapshot_legacy_pipeline/prepared_data.py) hiện có | PreparedDataset/PreparedSplit của source W4/H5,10,15 |
| M8 | Snapshot đã đọc của pipeline/evaluate.py | pair_acc, _grids, compute_metrics đã được khảo sát. File không còn tại đường dẫn cũ; chưa xác nhận archive |
| M9 | [pipeline/pyproject.toml](../../pipeline/pyproject.toml) và pipeline/uv.lock | Dependency declarations còn ở working tree; không thay environment doctor hoặc chứng minh training entrypoint đã tồn tại |
| D1 | Active [feature_contract.json](../../data/hcm_data_2/meta/feature_contract.json), [manifest.json](../../data/hcm_data_2/meta/manifest.json); human report [metadata.md](../../data/_archive/hcm_data_2_v2_packed/metadata.md) trong archive | Dataset đã đổi layout trong lúc khảo sát; byte hashes của contract/manifest được recheck là không đổi. Human metadata được dùng như báo cáo nguồn đã lưu, không phải active machine manifest. Data contract/lineage chi tiết được khóa ở 02; path/identity conflicts được ghi riêng trong source audit |

Các đường dẫn snapshot M3/M4/M5/M8 ở trên là tên lịch sử để truy nguyên nhận xét, không phải download links hoặc lệnh yêu cầu người triển khai chạy file đã mất. Khi cần replay legacy, phải tìm đủ source archive/dependencies đã xác minh trước; không tái tạo một script từ mô tả ngắn rồi gọi đó là replay gốc.

**Nguồn kỹ thuật primary, tra ngày 2026-10-09:**

- R1: PyTorch, [Softplus](https://docs.pytorch.org/docs/stable/generated/torch.nn.Softplus.html): công thức và positive-domain transform.
- R2: PyTorch, [SmoothL1Loss](https://docs.pytorch.org/docs/stable/generated/torch.nn.SmoothL1Loss.html): beta và quan hệ scale với Huber.
- R3: PyTorch Geometric, [GATv2Conv](https://pytorch-geometric.readthedocs.io/en/latest/generated/torch_geometric.nn.conv.GATv2Conv.html): shapes, edge_dim, self-loop controls và attention.
- R4: Brody et al., [How Attentive are Graph Attention Networks?](https://arxiv.org/abs/2105.14491): nguồn kiến trúc GATv2, không là bằng chứng hiệu quả pricing.

Library docs xác nhận API/khái niệm; phiên bản chạy thật phải lấy từ lockfile và compatibility test tại implementation. Hyperparameters, Softplus choice, graph augmentation, local regression tolerance và bootstrap design là engineering choices được ghi rõ, chưa phải kết quả thực nghiệm.


## 13. Contract study bổ sung

Materialization baseline/ablation, study lifecycle và công thức quality gates canonical nằm trong [10_benchmark_and_study_contract.md](10_benchmark_and_study_contract.md). Main YAML là cấu hình dual model; benchmark plan tạo effective trial configs riêng29/40 theo model kind, không sửa tùy ý các semantic consts.
