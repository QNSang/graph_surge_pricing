# Mock Data Spec v3: Temporal OD Graph Surge

**Thay thế:** v1, v2
**Phạm vi:** 61 hex H3 res 7 × 90 ngày chính (+ 1 ngày burn-in), một thành phố, một loại xe
**Bản phát hành hiện hành:** V2, case `bounded_tail`, 90 ngày từ 2026-01-05, D/S_eff ≤ 15 (mục 13)
**Thay đổi chính so với v2:** chốt toàn bộ tham số còn thiếu bằng giá trị giả định hợp lý; thêm biến thiên ngẫu nhiên theo ngày và theo hex; tín hiệu OD biến động theo ngày để không học thuộc được theo giờ; thêm bộ đối chứng xáo trộn OD; thêm mục cơ sở lựa chọn và chỉ tiêu độ chân thực.

---

## 0. Nguyên tắc

1. **Mock chỉ xuất dữ liệu raw mà hệ thống thật ghi lại.** Mọi biến tính được bằng công thức do pipeline tính.
2. **Mô phỏng theo thời gian.** Tài xế chở khách từ i đến j thì sau thời gian chuyến xuất hiện ở j. Cơ chế bên trong (ý định, phản ứng giá, repositioning, matching) không được xuất ra.
3. **Tham số được phép giả định, nhưng phải nằm trong khoảng hợp lý của thị trường gọi xe đô thị.** Mọi con số đều kiểm tra lại bằng chỉ tiêu ở mục 8. Đây là giả định, chưa hiệu chỉnh theo dữ liệu thật.
4. **Tín hiệu OD phải không đoán được chỉ bằng giờ, thứ và hex.** Nếu một baseline có feature lịch học thuộc được tín hiệu, phép so sánh GNN với baseline mất ý nghĩa.

---

## 1. Đầu ra raw

### 1.1 `hex_snapshot_5min`

| Cột | Kiểu | Định nghĩa |
|---|---|---|
| `ts` | timestamp | cuối cửa sổ $(ts-5\text{ phút},\ ts]$ |
| `hex_id` | str | H3 res 7 |
| `demand` | int | số đơn tạo trong cửa sổ, `origin_hex = hex_id` |
| `supply` | int | tài xế **phục vụ được ngay** tại `ts` (trạng thái rảnh, trong hex); không gồm tài xế đang đi đón hoặc đang chở khách |
| `eta_sec` | float | ETA đón ước tính tại `ts` đến tài xế rảnh gần nhất (mục 4.8); luôn có giá trị |
| `surge_multiplier` | float | base surge hiện hành tại `ts` (mục 4.9) |

Ràng buộc: `demand` bằng đúng số dòng `orders` cùng origin và cửa sổ.

### 1.2 `orders`

| Cột | Kiểu | Định nghĩa | Biết lúc nào |
|---|---|---|---|
| `order_id` | int | khóa | |
| `origin_hex`, `dest_hex` | str | điểm đón, điểm đến | lúc tạo |
| `created_ts` | timestamp | lúc tạo đơn | lúc tạo |
| `est_trip_duration_min` | float | thời gian chuyến dự kiến (không nhiễu) | lúc tạo |
| `accepted_ts` | timestamp | lúc tài xế nhận; null nếu không ai nhận | |
| `pickup_ts` | timestamp | lúc đón; null nếu hủy trước khi đón | |
| `dropoff_ts` | timestamp | lúc trả khách; null nếu không hoàn thành | chỉ sau khi chuyến xong |
| `cancel_ts` | timestamp | lúc hủy; null nếu hoàn thành | |

Thứ tự: `created_ts ≤ accepted_ts ≤ pickup_ts < dropoff_ts`; `cancel_ts` sau `created_ts`, trước `pickup_ts`.

### 1.3 `weather_5min` (tùy chọn)

`ts`, `rain_intensity` (0 khi không mưa, 0.3–1.0 khi mưa).

### 1.4 `signal_truth` (chỉ debug và eval theo lát cắt)

`ts`, `hex_id`, `s1_ramp`, `s2_drain`, `s3_airport`, `s4_venue`, `s5_rain`, `s6_sparse`, `s7_boundary` (bool).

### 1.5 Kích thước

| Bảng | Số dòng (61 ngày) |
|---|---|
| `hex_snapshot_5min` | ≈ 1.07 triệu |
| `orders` | ≈ 1.5–2.5 triệu |
| `weather_5min` | 17,568 |
| `signal_truth` | ≈ 1.07 triệu |

---

## 2. Không gian

- 61 hex = `h3.grid_disk(center, 4)`, res 7. Tâm `center_lat`, `center_lng` trong config.
- Cạnh hex ≈ 1.22 km; tâm hai hex kề cách ≈ 2.1 km; diện tích hex ≈ 5.16 km²; vùng ≈ 315 km².
- $d_{ij}$: haversine giữa tâm hex.

### 2.1 Zone (nội bộ, không xuất)

| Zone | Vị trí | Số hex |
|---|---|---|
| `cbd` | ring 0–1 | 7 |
| `office` | ring 2 trừ venue | 11 |
| `venue` | 1 hex ở ring 2 | 1 |
| `residential` | ring 3 | 18 |
| `airport` | 3 hex liền nhau ở ring 4 | 3 |
| `suburb` | phần còn lại ring 4 | 21 |

### 2.2 Hệ số riêng từng hex (cố định suốt kỳ)

Để các hex cùng zone không giống hệt nhau:

$$\eta_i^{D}\sim\text{LogNormal}(0,\ 0.25),\qquad \eta_i^{A}\sim\text{LogNormal}(0,\ 0.2)$$

$\eta^D$ nhân vào cầu xuất phát, $\eta^A$ nhân vào độ hấp dẫn khi là điểm đến.

---

## 3. Thời gian và lịch

- Tick nội bộ 1 phút, snapshot 5 phút. Ngày bắt đầu: thứ Hai.
- **Split 61 ngày:** train 1–45, val 46–53, test 54–61.
- **Bộ phát triển (`n_days: 35`):** train 1–25, val 26–30, test 31–35.

### 3.1 Hệ số ngày

| T2–T5 | T6 | T7 | CN |
|---|---|---|---|
| 1.00 | 1.10 | 1.05 | 0.90 |

Cộng thêm hệ số ngẫu nhiên mỗi ngày $\delta_d\sim\text{LogNormal}(0,\ 0.08)$, áp cho toàn thành phố. Hai thứ Ba khác nhau vẫn khác nhau.

### 3.2 Lịch đặc biệt

| Sự kiện | 61 ngày | 35 ngày | Ràng buộc |
|---|---|---|---|
| Ngày mưa | 10 | 6 | ít nhất 1 ngày trong mỗi tập |
| Sự kiện venue | 7 | 4 | ít nhất 1 trong val, 1 trong test |
| Drain bất thường | ~3/tuần | ~3/tuần | xem S2b |
| Đợt hạ cánh sân bay | 6/ngày | 6/ngày | mọi ngày |

---

## 4. Cơ chế mô phỏng

### 4.1 Ý định đi xe

$$\mu_i(t)=B_{z(i)}\cdot\eta_i^{D}\cdot p_{z(i)}(t)\cdot\text{dow}(t)\cdot\delta_d\cdot\text{rain}(t)\cdot\text{event}_i(t)\cdot\text{ramp}_i(t)$$

$$\text{intent}_i(t)\sim\text{Poisson}\big(\mu_i(t)\cdot G_i(t)\big),\qquad G_i(t)\sim\text{Gamma}(8,\ 1/8)\ \text{(độc lập mỗi 5 phút)}$$

**Mức nền $B_z$ (ý định/phút/hex):** cbd 0.6, office 0.3, venue 0.3, residential 0.25, suburb 0.04, airport 0.1.

**Hồ sơ giờ $p_z$** (nội suy tuyến tính giữa tâm các khung, chuẩn hóa trung bình ngày = 1):

| Khung | cbd | office | venue | residential | suburb | airport |
|---|---|---|---|---|---|---|
| 00–05 | 0.3 | 0.1 | 0.3 | 0.2 | 0.2 | 0.6 |
| 06–09 | 1.0 | 0.6 | 0.4 | 2.2 | 1.5 | 1.0 |
| 10–15 | 1.4 | 0.9 | 0.8 | 0.8 | 0.6 | 1.0 |
| 16–19 | 1.6 | 2.4 | 1.0 | 0.9 | 0.7 | 1.0 |
| 20–23 | 1.5 | 0.4 | 1.6 | 0.8 | 0.5 | 1.0 |

**Weekend:** office và residential dùng hồ sơ phẳng (không có đỉnh sáng/chiều, giá trị khung 10–15); cbd và venue ×1.2 tối thứ Sáu, thứ Bảy.

### 4.2 Phản ứng giá (nội bộ)

$$P(\text{tạo đơn}\mid s)=\exp\big(-0.7\,(s-1)\big)$$

Surge 1.5 giữ ≈ 70% ý định, surge 2.0 giữ ≈ 50%.

### 4.3 Điểm đến

$$P(j\mid i,t)\propto A^{(g)}_{z(j)}(t)\cdot\eta_j^{A}\cdot\exp(-d_{ij}/L),\qquad L=5\text{ km}$$

Chuyến nội hex: xác suất cố định 20%.

**Độ hấp dẫn đích $A_z(t)$** (ngày làm việc; $\bar A=1.0$):

| Khung | cbd | office | venue | residential | suburb | airport |
|---|---|---|---|---|---|---|
| 00–05 | 1.0 | 0.2 | 0.5 | 2.0 | 1.5 | 0.8 |
| 06–09 | 2.0 | 2.5 | 0.3 | 0.5 | 0.4 | 0.8 |
| 10–15 | 1.8 | 1.2 | 0.6 | 0.8 | 0.6 | 0.8 |
| 16–19 | 1.2 | $a_{\text{drain}}$ | 0.8 | 2.2 | 1.8 | 0.8 |
| 20–23 | 1.8 | 0.3 | 1.5 | 1.6 | 1.2 | 0.8 |

$a_{\text{drain}}$ được bốc theo ngày (S2a). Weekend: office và residential dùng giá trị khung 10–15 cả ngày.

### 4.4 Thời gian chuyến

**Dự kiến** (ghi vào `est_trip_duration_min`):

$$\hat\tau_{ij}(t)=2+\frac{1.3\,d_{ij}}{v(t)}\cdot60,\qquad v(t)=\begin{cases}18\text{ km/h} & \text{06–09, 16–19 ngày làm việc}\\28\text{ km/h} & \text{còn lại}\end{cases}$$

**Chuyến nội hex:** coi hex như hình tròn cùng diện tích, bán kính $r=\sqrt{5.16/\pi}\approx1.28$ km. Lấy hai điểm đều ngẫu nhiên trong hình tròn, $d$ là khoảng cách giữa chúng (trung bình ≈ 1.16 km), áp cùng công thức, tối thiểu 3 phút.

**Thực tế:** $\tau=\hat\tau\times\text{LogNormal}(0,\ 0.15)$. Mưa: $v\times0.8$ cho cả dự kiến và thực tế.

### 4.5 Tài xế: ca làm việc

- Mỗi tài xế có **hex nhà** cố định: residential 60%, suburb 30%, còn lại 10%.
- **Mục tiêu online theo giờ** (nội suy tuyến tính):

| Khung | 00–05 | 06–09 | 10–15 | 16–19 | 20–23 |
|---|---|---|---|---|---|
| Online | 250 | 1800 | 1400 | 1900 | 1100 |

  Nhân $\delta_d^{0.5}$ (ngày đông khách thì tài xế cũng ra nhiều hơn một phần) và ×0.9 trong đợt mưa.

- **Lên ca:** khi thiếu so với mục tiêu, tài xế offline lên ca tại hex nhà.
- **Xuống ca:** khi thừa, chọn trong các tài xế đang rảnh, ưu tiên người đã online lâu nhất. Mỗi lần online kéo dài tối thiểu 90 phút.
- **Độ dài ca:** khi đã đủ ca $\sim\text{LogNormal}(\log 360,\ 0.4)$ phút (trung vị 6 giờ), tài xế xuống ca ở lần rảnh kế tiếp, bất kể mục tiêu.

### 4.6 Matching và hủy

**Matching** mỗi tick, đơn cũ nhất trước:
1. Tài xế rảnh cùng hex: thời gian đón $4+\text{Exp}(\text{mean } 2)$ phút.
2. Không có thì hex kề: $9+\text{Exp}(\text{mean } 3)$ phút.
3. Không có thì đơn chờ.

**Hủy:**
- Kiên nhẫn của khách $\sim\text{Exp}(\text{mean } 6)$ phút, trần 10 phút. Quá hạn chưa có tài xế thì hủy.
- Đơn đã nhận bị hủy trước khi đón: xác suất $0.02+0.002\times(\text{phút đón}-4)^+$ (đón càng lâu càng dễ hủy).

### 4.7 Repositioning (nội bộ)

Mỗi 5 phút, tài xế rảnh quá 5 phút có xác suất 0.10 sang một hex kề, chọn với xác suất $\propto s_j^{2}$. Mất ≈ 8 phút; trong lúc đi vẫn tính vào `supply` của hex xuất phát.

### 4.8 `eta_sec`

ETA đến tài xế rảnh gần nhất tại `ts`:

| Tài xế rảnh gần nhất | ETA (phút) |
|---|---|
| Cùng hex | $4+\text{Exp}(\text{mean } 1)$ |
| Ring 1 | $9+\text{Exp}(\text{mean } 2)$ |
| Ring 2 | $15+\text{Exp}(\text{mean } 3)$ |
| Xa hơn | 20 |

Mưa ×1.2. Quy đổi sang giây.

### 4.9 `surge_multiplier`

$$r_i(t)=\log\frac{\text{demand}_i(t)+\text{waiting}_i(t)+1}{\text{supply}_i(t)+1}$$

$$s^{\text{raw}}_i=\text{clip}\big(1+0.6\max(0,r_i),\ 1.0,\ 3.0\big),\qquad s_i(t)=\text{round}_{0.1}\big(0.6\,s^{\text{raw}}_i(t)+0.4\,s_i(t-5)\big)$$

### 4.10 Mưa

Mỗi ngày mưa có 1–3 đợt, giờ bắt đầu ưu tiên buổi chiều (60% trong 13:00–18:00, còn lại đều trong ngày), mỗi đợt $\text{Uniform}(60, 180)$ phút, `rain_intensity` $\sim\text{Uniform}(0.3,1.0)$.

Trong đợt mưa: cầu $\times(1+0.5\cdot\text{intensity})$, tốc độ ×0.8, ETA ×1.2, tài xế online ×0.9.

---

## 5. Tín hiệu cài sẵn (biến động theo ngày)

| ID | Tín hiệu | Cơ chế | Vì sao không học thuộc theo lịch được | Model nên bắt được |
|---|---|---|---|---|
| **S1** | Ramp trước cao điểm | `ramp` tăng 1.0 → $m_d$ trong 30 phút trước đỉnh, $m_d\sim\text{Uniform}(1.3,1.8)$ mỗi ngày | Cường độ đổi theo ngày | GRU thắng D/S tĩnh |
| **S2a** | Commuter drain thường ngày | $a_{\text{drain}}\sim\text{Uniform}(0.1,0.5)$ mỗi ngày; giờ bắt đầu khung 16–19 lệch $\text{Uniform}(-45,+45)$ phút | Cường độ và thời điểm đổi theo ngày | **GNN trên OD thắng GRU-only** |
| **S2b** | Drain bất thường | ~3 lần/tuần: chọn ngẫu nhiên 1 hex (cbd, office hoặc residential), giờ ngẫu nhiên 08:00–21:00, kéo dài 30–60 phút. Cầu xuất phát tại hex ×2.5, đích dùng $L=8$ km (đi xa), độ hấp dẫn của chính hex đó ×0.2. Tình huống thật tương ứng: tan ca nhà máy, tan trường, kết thúc hội nghị | Không có lịch cố định | **GNN trên OD** (tín hiệu mạnh nhất về giá trị của OD) |
| **S3** | Sóng sân bay | Mỗi đợt hạ cánh trễ $\text{Normal}(0,15)$ phút; tải $\sim\text{LogNormal}(0,0.4)$. Cầu tại sân bay $+1.5\times\text{tải}$ ý định/phút/hex trong 40 phút. 30 phút trước đó, độ hấp dẫn đích sân bay ×(1 + 2 × tải) | Giờ và quy mô đổi theo đợt | GNN + edge feature |
| **S4** | Sự kiện venue | Giờ kết thúc $\sim\text{Uniform}(21{:}00, 23{:}00)$; quy mô $\sim\text{Uniform}(3,8)$. Trước 1–2 giờ: độ hấp dẫn đích venue ×4. Sau khi kết thúc 45 phút: cầu venue × quy mô | Không theo lịch tuần | GNN thấy inbound OD |
| **S5** | Mưa | Mục 4.10 | Ngẫu nhiên | Outlier, kiểm tra Huber |
| **S6** | Hex thưa | Suburb, cộng $\eta^D$ thấp | Cố định (đúng ý đồ) | Trọng số volume, nhãn làm mượt |
| **S7** | Biên sắc nét | Sân bay cạnh suburb | Cố định (đúng ý đồ) | Smoothness không làm mờ |

`signal_truth.s2_drain` đánh dấu cả S2a và S2b.

### 5.1 Núm độ mạnh tín hiệu graph

$$A^{(g)}_z(t)=(1-g)\cdot\bar A+g\cdot A_z(t)$$

Đồng thời nhân các phần OD của S2b, S3, S4 với $g$ (phần cầu xuất phát giữ nguyên).

### 5.2 Các bộ dữ liệu sinh ra

| Bộ | Mô tả | Kỳ vọng |
|---|---|---|
| `g1.0` | Bộ chính | GNN thắng GRU-only ở mức vừa phải |
| `g0.5` | Tín hiệu OD giảm một nửa | Lợi thế GNN nhỏ hơn `g1.0` |
| `g0.0` | Không có luồng OD bất đối xứng | GNN không thắng GRU-only |
| `g1.0_shuffled` | Từ `g1.0`, xáo ngẫu nhiên `dest_hex` giữa các đơn cùng origin zone và cùng giờ, **sau khi mô phỏng xong** (chỉ đổi bảng xuất, không mô phỏng lại) | GNN không thắng GRU-only; nếu thắng là pipeline dùng thứ gì khác ngoài OD thật |

Bộ xáo trộn làm `orders` không còn nhất quán với vị trí tài xế; chỉ dùng để kiểm tra model, không dùng để kiểm tra pipeline.

---

## 6. Cơ sở lựa chọn phân phối

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Số ý định | Poisson trộn Gamma | Khách đến độc lập là Poisson; trộn Gamma ra Negative Binomial, khớp dữ liệu đếm thật (phương sai > trung bình, có đột biến) |
| Cấu trúc cầu | Tích các hệ số zone × giờ × ngày × thời tiết × sự kiện | Cấu trúc nhân phổ biến trong mô hình cầu theo không gian và thời gian |
| Biến thiên ngày, hex | LogNormal | Hệ số nhân dương, lệch phải nhẹ |
| Chuyển đổi theo giá | Hàm mũ | Độ co giãn bán phần cố định, luôn trong $(0,1]$, giảm đơn điệu |
| Điểm đến | Gravity | Mô hình chuẩn trong giao thông: chuyến xa ít hơn, nơi hấp dẫn thu hút nhiều hơn |
| Thời gian chuyến | Khoảng cách × 1.3 / tốc độ + hằng số | 1.3 là hệ số đường vòng điển hình ở đô thị |
| Sai số thời gian | LogNormal | Dương, lệch phải (kẹt xe làm chậm nhiều hơn làm nhanh), tỷ lệ theo độ dài chuyến |
| Thời gian đón, kiên nhẫn | Hằng số + Exp, Exp | Có mức tối thiểu vật lý; thời gian kiên nhẫn kiểu mũ là giả định chuẩn trong hàng đợi có khách bỏ đi |
| Độ dài ca | LogNormal | Dương, đa số ca 4–8 giờ, một ít ca rất dài |
| Base surge | Log D/S, clip, EMA, làm tròn | Hệ thống surge thật có ngưỡng, giới hạn, làm mượt và bậc giá rời rạc |
| Repositioning | Xác suất $\propto s^2$ | Lựa chọn kiểu logit, tài xế bị hút về nơi giá cao |

---

## 7. Hợp đồng với pipeline

### 7.1 Node features

| Feature | Công thức |
|---|---|
| `demand`, `supply`, `eta`, `base_surge` | lấy thẳng từ snapshot |
| `effective_supply` | $\text{supply}+\sum w(\text{ETA})$ trên đơn đang chạy về hex; $\text{ETA}=\text{pickup\_ts}+\text{est\_trip\_duration\_min}-ts$; $w$: ≤ 5 → 1.0, 5–10 → 0.5, 10–15 → 0.2, > 15 → 0 |
| `ds_ratio` | $(\text{demand}+1)/(\text{effective\_supply}+1)$ |
| `backlog` | đơn đã tạo, chưa nhận, chưa hủy tại `ts` |
| `driver_inflow` | đơn có `dropoff_ts` trong cửa sổ, `dest_hex = i` |
| `driver_outflow` | đơn có `pickup_ts` trong cửa sổ, `origin_hex = i` |
| Thời gian | giờ (sin/cos), thứ, weekend |

### 7.2 Edge features

`request_count`, `completed_trip_count`, `in_trip_count`, `travel_time` (trung vị chuyến đã hoàn thành trước `ts` trong 30 phút qua, fallback `est_trip_duration_min`), `distance`, `dest_eta`.

### 7.3 Nhãn

$$y_{i,t+h}=\log\frac{\text{demand}_{i,t+h}+1}{S^{\text{eff}}_{i,t+h}+1},\qquad h\in\{5,10,15,30\}$$

Cùng một hàm $S^{\text{eff}}$ cho feature và nhãn. Prior cho nhãn làm mượt chỉ tính từ train.

### 7.4 Chống rò rỉ

- Chuyến đang chạy: chỉ dùng `est_trip_duration_min`, không dùng `dropoff_ts`.
- `dropoff_ts` chỉ dùng cho chuyến đã kết thúc trước `ts` và cho nhãn.
- `signal_truth` không vào feature.

---

## 8. Chỉ tiêu độ chân thực (kiểm tra tự động)

Mock chỉ được dùng khi mọi chỉ tiêu nằm trong khoảng. Nếu lệch, chỉnh tham số theo cột cuối.

| Chỉ tiêu | Khoảng mục tiêu | Chỉnh bằng |
|---|---|---|
| Khoảng cách chuyến trung bình | 4–7 km | $L$, xác suất nội hex |
| Trung vị thời gian chuyến | 15–25 phút (cao điểm dài hơn) | tốc độ $v$ |
| Tỷ lệ chuyến nội hex | 15–25% | xác suất nội hex |
| Trung vị thời gian đón | 4–8 phút | số tài xế, tham số đón |
| Tỷ lệ hoàn thành | 75–90% toàn kỳ; thấp hơn rõ giờ cao điểm và khi mưa | số tài xế, kiên nhẫn |
| Tỷ lệ hủy do không có tài xế trong tổng hủy | > 50% giờ cao điểm | số tài xế |
| Utilization | 65–80% giờ cao điểm; 35–55% thấp điểm | mục tiêu online |
| `surge_multiplier` > 1 | 15–30% dòng snapshot | `gain` của base surge |
| `surge_multiplier` ≥ 2 | < 5% dòng | `gain`, số tài xế |
| Tỷ lệ chuyến từ/đến sân bay | 3–6% | $B_{\text{airport}}$, tải đợt bay |
| Phương sai / trung bình của `demand` theo hex-giờ | 1.2–3 | Gamma $k$ |
| Hệ số biến thiên tổng cầu giữa các ngày cùng thứ | 5–12% | $\delta_d$ |
| Suburb: trung vị `demand + supply` mỗi 5 phút | < 6 | $B_{\text{suburb}}$, phân bố hex nhà |
| Sai số `est_trip_duration_min` so với thực tế | trung vị tuyệt đối ≈ 10% | $\sigma$ LogNormal |
| Tỷ lệ chuyến đang chạy có ETA còn lại > 15 phút | báo cáo (quyết định có cần bucket 15–30 phút) | |

### 8.1 Kiểm tra tín hiệu (trước khi train)

- S2a, S2b: tại các hex đang drain, tương quan giữa outflow OD lúc $t$ và $y_{t+15}$ mạnh hơn tương quan giữa `ds_ratio` lúc $t$ và $y_{t+15}$.
- S2a: tương quan giữa feature giờ và cường độ drain thấp (biến động theo ngày đủ lớn).
- S3, S4: in-trip đổ vào sân bay/venue tăng trước sự kiện, $y$ tại đó âm trong khoảng ấy.
- Bộ `g0.0` và `g1.0_shuffled`: các tương quan S2 biến mất.
- Báo cáo $\text{corr}(b_{i,t},\ y_{i,t+10})$ để biết persistence baseline mạnh đến đâu.

### 8.2 Hiệu chỉnh độ mạnh tín hiệu (sau lần train đầu)

| Bộ | Mục tiêu: PairAcc của GNN trừ GRU-only |
|---|---|
| `g1.0` | +2 đến +6 điểm phần trăm |
| `g0.5` | nhỏ hơn `g1.0` |
| `g0.0`, `g1.0_shuffled` | khoảng tin cậy chứa 0 |

Lợi thế lớn hơn mục tiêu thì giảm cường độ S2b, S3, S4. Lợi thế ở `g0.0` khác 0 thì kiểm tra rò rỉ trước khi làm gì khác.

---

## 9. Config mẫu

```yaml
seed: 42
center_lat: <điền>
center_lng: <điền>
h3_res: 7
ring_radius: 4
n_days: 61                      # 35 cho bộ phát triển
start_date: "2026-01-05"        # thứ Hai
tick_minutes: 1
snapshot_minutes: 5
split: {train: [1, 45], val: [46, 53], test: [54, 61]}

heterogeneity:
  hex_demand_sigma: 0.25
  hex_attract_sigma: 0.20
  day_sigma: 0.08
  dow: {mon: 1.0, tue: 1.0, wed: 1.0, thu: 1.0, fri: 1.10, sat: 1.05, sun: 0.90}

demand:
  base_per_min: {cbd: 0.6, office: 0.3, venue: 0.3, residential: 0.25, suburb: 0.04, airport: 0.1}
  gamma_k: 8
  price_sensitivity: 0.7
  gravity_L_km: 5.0
  intra_hex_prob: 0.20
  patience_mean_min: 6
  patience_max_min: 10
  post_accept_cancel: {base: 0.02, per_min_over_4: 0.002}

trip:
  speed_kmh: {peak: 18, offpeak: 28}
  road_factor: 1.3
  fixed_min: 2
  duration_noise_sigma: 0.15
  intra_hex_min_floor: 3

drivers:
  home_zone_share: {residential: 0.6, suburb: 0.3, other: 0.1}
  online_target: {"0-5": 250, "6-9": 1800, "10-15": 1400, "16-19": 1900, "20-23": 1100}
  day_elasticity: 0.5
  min_session_min: 90
  shift_lognormal: {median_min: 360, sigma: 0.4}
  pickup_same_hex: {fixed: 4, exp_mean: 2}
  pickup_neighbor: {fixed: 9, exp_mean: 3}
  reposition: {prob: 0.10, power: 2, minutes: 8}

base_surge: {gain: 0.6, ema: 0.4, min: 1.0, max: 3.0, step: 0.1}

rain:
  days: 10
  episodes_per_day: [1, 3]
  afternoon_share: 0.6
  episode_min: [60, 180]
  demand_per_intensity: 0.5
  speed_factor: 0.8
  eta_factor: 1.2
  driver_factor: 0.9

signals:
  graph_signal_strength: [1.0, 0.5, 0.0]
  shuffled_control: true
  s1_ramp_range: [1.3, 1.8]
  s2a: {attract_range: [0.1, 0.5], start_jitter_min: 45}
  s2b: {per_week: 3, zones: [cbd, office, residential], hours: ["08:00", "21:00"],
        duration_min: [30, 60], demand_mult: 2.5, dest_L_km: 8.0, self_attract_mult: 0.2}
  s3: {banks: ["07:30", "10:00", "13:00", "16:30", "19:00", "22:30"],
       delay_sd_min: 15, load_sigma: 0.4, wave_per_min: 1.5, wave_min: 40,
       pre_inbound_min: 30, pre_inbound_mult: 2.0}
  s4: {events: 7, end_range: ["21:00", "23:00"], size_range: [3, 8],
       pre_hours: [1, 2], pre_attract_mult: 4.0, post_min: 45}

output:
  format: parquet
  partition_by: date
  weather: true
```

---

## 10. Cấu trúc thư mục

```
mock_data/
  config.yaml
  g1.0/  g0.5/  g0.0/  g1.0_shuffled/
    hex_snapshot_5min/date=YYYY-MM-DD/part.parquet
    orders/date=YYYY-MM-DD/part.parquet
    weather_5min/date=YYYY-MM-DD/part.parquet
    signal_truth/date=YYYY-MM-DD/part.parquet
  validation_report.md      # kết quả mục 8 cho từng bộ
```

---

## 11. Thứ tự thực hiện

1. Sinh bộ 35 ngày `g1.0`, chạy kiểm tra mục 8, chỉnh tham số đến khi đạt.
2. Chạy hết pipeline: raw → feature → nhãn → D/S → LightGBM → GRU-only → GNN.
3. Sinh `g0.0` và `g1.0_shuffled`, xác nhận GNN không thắng.
4. Hiệu chỉnh độ mạnh tín hiệu theo mục 8.2.
5. Sinh bộ 61 ngày đầy đủ.

---

## 12. Giới hạn

- Tham số là giả định hợp lý, chưa hiệu chỉnh theo dữ liệu thật. Kết quả trên mock chứng minh pipeline đúng và model bắt được tín hiệu đã cài, không chứng minh hiệu quả trên dữ liệu thật.
- Hành vi khách và tài xế là luật đơn giản; không có cạnh tranh giữa các nền tảng, tài xế chạy nhiều app, hay khuyến mãi.
- Hex res 7 lớn, nên D/S trong hex mượt hơn thực tế ở res 8–9.
- Định nghĩa `demand` và `supply` là lý tưởng; dữ liệu thật cần đối chiếu (unique users, đơn lặp, tài xế rảnh nhưng không nhận chuyến).

## 13. Bản phát hành V2 (90 ngày, `bounded_tail`)

- **Phạm vi:** 61 hex (H3 res 7, ring 4), 90 ngày chính từ 2026-01-05 đến 2026-04-04, cộng 1 ngày burn-in chỉ giữ trong `context/`. Snapshot cuối là 2026-04-05 00:00. Mỗi bảng snapshot có 25.920 mốc × 61 hex = 1.581.120 dòng.
- **Sinh dữ liệu:** `tools/mock_v3/run.py --mode release --days 90 --seed 42`. Ngày mưa là `round(days/6)` = 15, sự kiện venue là `round(days/8)` = 11. Chia 70/15/15 ngày (63/13/14) chỉ dùng để rải mưa và sự kiện; split của model do DS quyết định.
- **D/S_eff:** = demand_5m / effective_supply, tính trên dòng S_eff > 0 (S_eff làm tròn 4 chữ số). Giá trị nằm trong [0, 15], p50 ≈ 0,2, p90 ≈ 1,4, p99 ≈ 4–5, tỷ lệ > 10 khoảng 0,005%. Giới hạn đạt được bằng mô phỏng, không clip. Dòng S_eff = 0 và D > 0 (khoảng 2%) được giữ và báo cáo riêng.
- **Bộ lọc "hết xe"** (`demand.no_cars_filter`, `theta` = 12, `beta` = 3, `floor` = 0,2): với mỗi ý định đặt xe, supply sống tại hex là effective supply của snapshot sắp tới, tính theo phút, bỏ tài xế sắp hết ca và trừ đơn đang chờ của chính hex. Áp lực = (yêu cầu trong cửa sổ + đã giữ + 1) / max(supply sống − 1, floor). Khi áp lực vượt `theta`, đơn được đặt với xác suất exp(−beta × (áp lực − theta)). Cùng phép thử này chặn láng giềng điều tài xế, cắt đội xe và reposition khi hex không còn xe để nhả.
- **Kiểm tra:** bản phát hành dừng trước khi lưu nếu có dòng D/S_eff > 15. Manifest ghi `ds_effective_ratio` và các check `exact_day_grid`, `ds_effective_ratio_le_15`, `ds_effective_ratio_finite`.
