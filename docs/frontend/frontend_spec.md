# Frontend Spec — Surge Control (Pricing/Ops Console)

**Phiên bản:** 0.3 — bổ sung biểu đồ Surge Base theo thời gian.

**Cập nhật:** 09/10/2026, Asia/Ho_Chi_Minh.

**Trạng thái:** giữ hướng giao diện v0.2 đã được chủ dự án duyệt. V0.3 bổ sung code biểu đồ Surge Base vào app React hiện có tại `ui/app` và đặc tả tương ứng. Việc có mã nguồn không xác nhận mọi yêu cầu v0.2/v0.3, build hoặc kiểm thử đã đạt.

**Phạm vi cập nhật v0.3:** biểu đồ bidding gốc, tích hợp tab/state frontend, kiểm thử và tài liệu. Không thay model, controller, dataset, giới hạn giá hoặc checkpoint; không sửa prototype HTML legacy. Lệnh `npm run test` trên máy dự án đang yêu cầu phê duyệt CodeLocal, chưa có kết quả test/build cho phần bổ sung này.

**Tham chiếu hiện có:** [prototype HTML](../../ui/dashboard.html), [template](../../ui/dashboard.template.html), [data builder](../../ui/build_data.py), [Technical Report](../model/technical_report.md), [data contract ML](../ml_pipeline/02_data_contract.md), [serving contract ML](../ml_pipeline/06_artifacts_and_serving.md), [analysis contract ML](../ml_pipeline/11_post_training_analysis.md).

**Tham chiếu hình ảnh:** mockup Surge Control nền navy tối được duyệt ngày 09/10/2026 trong hội thoại: bản đồ bên trái, panel bên phải, hàng đợi dưới bản đồ, replay toàn chiều ngang ở đáy. Ảnh chưa được lưu thành asset trong repo. Ảnh xác định bố cục và phong cách; số liệu, ngày giờ, tên vùng, trạng thái Live và phép tính trong ảnh không phải dữ liệu hay policy có hiệu lực.

**Quy ước:** MUST là điều kiện bắt buộc để nghiệm thu; SHOULD là lựa chọn mặc định có thể thay nếu ghi rõ lý do. Nhãn Confidence mô tả căn cứ của tài liệu, không phải confidence do model trả về. Yêu cầu bố cục/luồng mới có căn cứ là hướng được người dùng duyệt và quyết định PO/BA; độ hiệu quả sử dụng chưa được đo.

## Mục lục

1. [Mục tiêu và phạm vi](#1-mục-tiêu-và-phạm-vi)
2. [Người dùng và tác vụ chính](#2-người-dùng-và-tác-vụ-chính)
3. [Bố cục màn hình](#3-bố-cục-màn-hình)
4. [Thành phần chi tiết](#4-thành-phần-chi-tiết)
5. [Trạng thái và hành động](#5-trạng-thái-và-hành-động)
6. [Data contract](#6-data-contract)
7. [Trạng thái prototype so với hệ thống thật](#7-trạng-thái-prototype-so-với-hệ-thống-thật)
8. [Thiết kế hình ảnh](#8-thiết-kế-hình-ảnh)
9. [Phi chức năng](#9-phi-chức-năng)
10. [Tiêu chí chấp nhận](#10-tiêu-chí-chấp-nhận)
11. [Ngoài phạm vi và câu hỏi mở](#11-ngoài-phạm-vi-và-câu-hỏi-mở)
12. [Thứ tự triển khai và thay đổi phiên bản](#12-thứ-tự-triển-khai-và-thay-đổi-phiên-bản)
13. [Nguồn và ranh giới bằng chứng](#13-nguồn-và-ranh-giới-bằng-chứng)

## 1. Mục tiêu và phạm vi

### 1.1. Định vị sản phẩm

Surge Control là console hỗ trợ Pricing/Ops hiểu và xử lý đề xuất hiệu chỉnh trên bidding hiện có. Đơn vị công việc là một đề xuất cho một hex, tại một cutoff, từ một model và policy xác định. Miền dữ liệu đang tham chiếu có 61 hex H3 resolution 7, nhịp 5 phút; UI lấy node set và nhịp từ metadata, không hard-code để che sai contract.

Bidding hiện có được chủ dự án mô tả là đang hoạt động tốt và có lợi nhuận; tác động tới cân bằng marketplace chưa được xác minh. UI MUST diễn đạt module mới là **hiệu chỉnh trên bidding**, không quảng bá việc thay thế bidding hoặc bảo đảm tăng doanh thu. [Confidence: High — Technical Report §1; thông tin kinh doanh là bối cảnh do chủ dự án cung cấp.]

Thông điệp trải nghiệm: **Chọn một vùng → thấy mạng liên quan → hiểu đề xuất → quyết định ngay trong cùng góc nhìn.**

### 1.2. Ranh giới trách nhiệm

| Thành phần | Trách nhiệm |
|---|---|
| Model/controller và adapter backend | Tính forecast, reference, Pressure/Revision, requested/final delta, giá, reason, thời hạn và eligibility |
| Frontend | Trình bày, kiểm tính đầy đủ/tương thích của payload, giữ ngữ cảnh đang xem, thu thao tác và hiển thị kết quả được xác nhận |
| Decision/execution backend | Xác thực người dùng/quyền, kiểm lại bidding/version/thời hạn, chống lặp, ghi audit và theo dõi việc thực thi |

Frontend MUST NOT tự tính policy production, tự inverse tensor để đoán D/S, tự chọn threshold hoặc chuyển số liệu thiếu thành 0. Tính toán phía trình duyệt chỉ được dùng trong adapter DEMO tách biệt, có nhãn rõ. Endpoint sản phẩm ở mục 6 là hợp đồng đề xuất, chưa phải API đã có.

### 1.3. Phạm vi vòng đầu

Một workspace vận hành tiếng Việt, desktop-first: bản đồ, panel quyết định, hàng đợi, nhật ký và replay. Giữ khả năng đọc Demand/Supply và truy vết; thêm kiểm soát dữ liệu lỗi, hết hiệu lực và trạng thái thực thi. Không mở rộng thành app rider/driver, màn hình huấn luyện model hoặc công cụ sửa policy.

## 2. Người dùng và tác vụ chính

Một persona chính: **Pricing/Ops**. Quyền xem, xác nhận, override và hủy lệnh được backend cấp riêng; một persona không có nghĩa mọi tài khoản đều có quyền thực thi.

| ID | Công việc cần hoàn thành | Trải nghiệm bắt buộc |
|---|---|---|
| T1 | Biết vùng nào cần chú ý | Bản đồ + hàng đợi, trạng thái dữ liệu luôn thấy |
| T2 | Hiểu tại sao có đề xuất | Bidding → đề xuất, một câu lý do, Local/Graph/reference |
| T3 | Xác nhận hoặc giữ bidding | Hành động rõ giá, đúng snapshot, phản hồi theo server |
| T4 | Xử lý nhiều đề xuất hợp lệ | Chọn tập rõ ràng, rà soát trước gửi, kết quả từng đề xuất |
| T5 | Kiểm tra quyết định đã xử lý | Nhật ký có decision ID, người thực hiện, trạng thái và version |
| T6 | Xem diễn biến và kiểm tra forecast | Replay đồng bộ, phân biệt dự báo với quan sát sau cutoff |

Mục tiêu usability đề xuất: tìm vùng cần xem xét trong 10 giây, giải thích một đề xuất trong 30 giây. Đây là mục tiêu thử nghiệm với người dùng, không phải KPI đã đạt. [Confidence: Medium — mục tiêu PO/BA cần usability test.]

## 3. Bố cục màn hình

### 3.1. Workspace chính

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Surge Control | TP.HCM | DEMO / SHADOW / PRODUCTION | dữ liệu t | dự báo t+5│
├─────────────────────────────────────────────┬──────────────────────────────┤
│ [Cung cầu D/S] [Hiệu chỉnh] [Lớp khác]       │ Vùng đang chọn · trạng thái  │
│                                             │ Bidding → Đề xuất sau giới hạn│
│ BẢN ĐỒ + HEX + LUỒNG OD LIÊN QUAN           │ Một câu giải thích           │
│ Chú giải gọn; control lớp; zoom/fit          │ Local / Graph / Reference    │
│                                             │ Pressure / Revision / Delta  │
├─────────────────────────────────────────────┤                              │
│ HÀNG ĐỢI / NHẬT KÝ                          │ [Lịch sử] [Chi tiết] [Dữ liệu]│
│ Bộ lọc + tìm vùng + duyệt tập đã chọn        │ Nội dung một tab đang mở     │
│ Vùng | Trạng thái | Bidding → Đề xuất | Lý do│                              │
│                                             │ [Giữ bidding] [Xác nhận …]   │
├─────────────────────────────────────────────┴──────────────────────────────┤
│ REPLAY | lùi / phát / tiến | ngày giờ | timeline | tốc độ | xem sau 5 phút│
└────────────────────────────────────────────────────────────────────────────┘
```

Ưu tiên thị giác: bản đồ → giá → lý do → hành động. Không thêm dãy KPI cards lớn chiếm vùng bản đồ. Bốn chỉ số ngắn có thể nằm trên thanh tóm tắt khi đủ chiều rộng.

### 3.2. Kích thước và responsive

| Viewport | Quy tắc layout |
|---|---|
| Từ 1440px, cao từ 900px | Cột trái khoảng 62–65%; phải khoảng 35–38%, thường 420–560px. Header 56–64px; replay 80–96px; hàng đợi 220–280px |
| 1280–1439px, gồm 1366×768 | Panel phải 380–420px; queue 180–220px; biểu đồ phụ nằm trong tab. Không thu nhỏ chữ để ép hai biểu đồ cùng mở |
| 1100–1279px hoặc chiều cao nhỏ | Cho phép cuộn có kiểm soát, queue thu gọn; đảm bảo giá/lý do/nút không bị cắt |
| Dưới 1100px | Một cột: header → bản đồ → panel → queue/log → replay; chiều cao bản đồ khoảng 360–480px |
| Màn hình rất hẹp hoặc zoom lớn | Nội dung văn bản reflow; hàng đợi chuyển sang thẻ hoặc cuộn trong vùng bảng; bản đồ có pan/zoom và danh sách thay thế |

Khoảng cách ngoài 12–16px, khoảng cách giữa vùng 8–12px. Grid/flex child MUST có giới hạn overflow thích hợp; desktop ưu tiên không cuộn toàn trang nhưng không được cắt nội dung khi zoom/font lớn. Panel và queue có thể cuộn độc lập. Thanh hành động sticky bên trong panel, có padding để không che nội dung/focus.

### 3.3. Điều hướng trong hình tham chiếu

Vận hành là workspace chính. Lịch sử mở nhật ký trong workspace, giữ vùng và thời điểm. Tổng quan chỉ triển khai khi có dữ liệu tổng hợp thật; Cài đặt vòng đầu chỉ có thể là phần xem ngữ cảnh/phiên bản, không chỉnh policy. Chưa có chức năng thì ẩn mục, không để nút trang trí không hoạt động. Ảnh khu vực ở góc panel là tùy chọn sau; không tải ảnh bất kỳ hoặc gắn địa danh chưa có mapping.

## 4. Thành phần chi tiết

### 4.1. Header và ngữ cảnh dữ liệu

MUST hiển thị brand, miền đang xem, ngày đầy đủ, cutoff, forecast timestamp/horizon, nguồn dữ liệu và chế độ thực thi. Dùng giờ Asia/Ho_Chi_Minh; payload timestamp MUST có timezone/offset, không dùng riêng HH:MM làm định danh.

Ba trục độc lập, không gom vào một badge mơ hồ:

| Trục | Giá trị đề xuất | Quy tắc hiển thị |
|---|---|---|
| `data_kind` | SYNTHETIC / HISTORICAL / LIVE | Nguồn synthetic luôn ghi dữ liệu mô phỏng, dù liên tục cập nhật |
| `view_mode` | REPLAY / LATEST | Đang xem quá khứ khác với snapshot mới nhất |
| `execution_mode` | DEMO / SHADOW / PRODUCTION | DEMO chỉ ghi mô phỏng; SHADOW không gửi thay đổi giá; PRODUCTION còn cần quyền và server eligibility |

Badge `DEMO · forecast giả lập` MUST luôn thấy khi forecast là heuristic. Model đã train trên synthetic vẫn là nguồn synthetic, không được tự biến thành Live production. Dòng `Dữ liệu lúc … / Dự báo cho …` lấy từ payload; ngày trong ảnh mockup không phải default runtime.

Các chỉ số tùy chọn: **Vùng cần xem xét**, **Đề xuất hợp lệ đang chờ**, **Quyết định đã ghi nhận**, **Đã có hiệu lực**. Mỗi count có phạm vi snapshot/khoảng thời gian rõ. Chỉ hiển thị Đã có hiệu lực khi có execution receipt tương ứng. Không đếm số lần click.

D/S toàn mạng chỉ hiển thị khi backend khai báo công thức aggregate và coverage. Không lấy trung bình tỷ lệ từng hex thay tổng Demand/tổng Supply, không trộn raw/smoothed ratio, không coi reference mặc nhiên bằng 1. Nếu chưa đủ định nghĩa thì ẩn KPI đó.

### 4.2. Bản đồ mạng hex

**MAP-01 — Nền và địa lý.** Bản đồ navy tối, đường/sông mờ hơn hex. Polygon và vị trí lấy từ geography đã version, không dựng địa giới từ tên giả như Q9-14 trong ảnh. Hiện tên vùng nếu mapping có nguồn; nếu chưa có thì dùng zone + mã hex rút gọn. Mã đầy đủ có thể copy. Basemap đường phố là phần bổ sung so với v0.1; provider, license/attribution, kết nối và chi phí là dependency cần chốt. Prototype offline tiếp tục dùng SVG tọa độ đúng trên nền trung tính; mất tile không được mất hex/queue. Không render nhãn basemap mâu thuẫn vị trí overlay.

**MAP-02 — Các lớp dữ liệu.** Toolbar chính chỉ có Cung cầu (D/S) và Hiệu chỉnh; Demand, Supply và các lớp kỹ thuật nằm trong Lớp khác.

| Lớp | Giá trị | Chú giải và điều kiện |
|---|---|---|
| Cung cầu (D/S) | Observation hoặc forecast đã khai báo | Mặc định Quan sát tại t. Chuyển Forecast t+5 phải đổi nhãn thời gian; không trộn hai loại trên cùng lớp |
| Hiệu chỉnh | `delta_applied` của controller | Xanh dương âm, trung tính 0, cam dương; nhãn điểm hệ số surge; chưa phải kết quả thực thi |
| Demand | Request mới trong cửa sổ đã khai báo | Sequential scale, có đơn vị/cửa sổ |
| Supply | Effective supply, không thay bằng idle | Sequential scale; tooltip nêu đây là proxy theo contract |

Thang D/S/reference, màu và vùng cảnh báo dùng metadata versioned. Không hard-code 1.5, D/18 hoặc S/18 của prototype thành chuẩn production. Trong replay/so sánh cùng profile, giữ thang ổn định để màu không đổi nghĩa theo mỗi frame. Nếu đổi thang, phải thông báo. Null/invalid dùng hatch hoặc nền khác kèm nhãn Thiếu dữ liệu, không màu của giá trị 0/cân bằng.

**MAP-03 — Tô màu và trạng thái độc lập.** Fill luôn phản ánh lớp dữ liệu. Viền tím sáng đánh dấu vùng đang chọn. Chữ/icon riêng cho REVIEW, Đã ghi nhận, Đã có hiệu lực. Duyệt một vùng không được đổi fill sang xanh lá như thể cung cầu đã được cải thiện. Glow chỉ dùng vừa phải cho selection.

**MAP-04 — Quan hệ mạng.** Luồng OD bật/tắt độc lập; adjacency tắt mặc định, mở trong lớp kỹ thuật. Khi chọn hex, nhấn các cạnh liên quan và hạ độ tương phản cạnh không liên quan. Mặc định hiển thị tối đa khoảng 12 cạnh liên quan theo metric đang chọn; có Xem thêm. Nếu ẩn/lược cạnh thì hiện số đang xem/tổng số; không ngụ ý đây là toàn bộ mạng. Số 12 là giới hạn trình bày đề xuất, không phải giới hạn model.

OD MUST có hướng src → dst, loại metric, đơn vị, cửa sổ và aggregation. Dữ liệu prototype là yêu cầu OD trung bình theo giờ: gọi **Luồng yêu cầu OD · trung bình theo giờ**, không gọi số tài xế đang đến. Không dùng toàn bộ một giờ chưa kết thúc làm bằng chứng as-of cho quyết định ở giữa giờ; dữ liệu đó chỉ được hiện ở chế độ phân tích hồi cứu có nhãn hoặc phải thay bằng trailing window đúng cutoff. Adjacency không phải luồng di chuyển. Attention chỉ hiện trong view kỹ thuật có cảnh báo không phải tác động nhân quả. [Confidence: High — frontend v0.1 §4.2, §6.1; ML analysis contract §5.]

**MAP-05 — Tương tác.** Click/Enter một hex hoặc một hàng queue đồng bộ panel, chart, selection; đổi layer/zoom không mất vùng chọn. Khi đã chọn, auto-fit nhẹ lần đầu nếu vùng nằm ngoài viewport; không liên tục kéo bản đồ ngược thao tác pan của người dùng. Controls: zoom ±, fit miền, về vùng đang chọn. Tooltip xuất hiện cả khi focus, gồm vùng/hex, metric và loại thời gian, D, effective supply, bidding, đề xuất và tình trạng dữ liệu.

Chú giải gọn, thu mở được và luôn truy cập bằng bàn phím. Không hiển thị mọi nhãn/cạnh cùng lúc. Animation lựa chọn 150–250ms; mũi tên OD tĩnh là mặc định, animation chỉ tùy chọn và tắt với reduced motion.

### 4.2A. Approved Visual Direction — Network Intelligence Map (12/10/2026)

**Design decision.** Chủ dự án đã chọn mockup Graph Surge phong cách **Midnight Intelligence / Geospatial Command Center**: nền navy đậm, mạng hex H3 trên dark basemap, các cạnh cong OD nhiều màu làm nổi bật network, panel đề xuất và Surge History nằm bên phải, Recommendation Queue cùng Network Connections ở dưới, Replay Timeline chạy toàn chiều ngang đáy. Đây là quyết định về **hướng thiết kế**, không biến các con số, tên địa danh, năm 2024, 128 hex, giá hoặc câu lý do giả định trên mockup thành dữ liệu sản phẩm. Khi có mâu thuẫn với contract API, safety hoặc tính trung thực dữ liệu, contract và safety có ưu tiên cao hơn hình minh họa.

**MAP-N01 — Layer stack (đề xuất implementation).** Dùng MapLibre GL làm dark basemap kết hợp deck.gl: `H3HexagonLayer` cho polygon theo H3 index, `ArcLayer` cho directed OD src→dst, `LineLayer` cho adjacency, và overlay/selection tương thích picking. Có thể giữ polygon layer hiện hành thay cho H3HexagonLayer nếu kiểm tra parity hình học/ID/selection tốt hơn; thư viện cụ thể là lựa chọn kỹ thuật, **không được tuyên bố đã tích hợp**. Không hard-code hex theo bố cục ảnh mockup; dùng geometry/node mapping từ dataset.

**MAP-N02 — Layer controls và mode.** Layer controls nằm trong popup mở từ nút góc trên-trái bản đồ (nút hiển thị view mode đang chọn; đóng bằng click ra ngoài hoặc Esc). Hex H3 luôn hiển thị. Nhóm `Network` gồm `OD Flows (Top)` (bật nếu có directed OD hợp lệ) và `Selected Network` (bật). Nhóm thu gọn `Technical` gồm `Show more edges` và `Adjacency` (tắt). `Demand Heatmap` và flow animation đã bỏ vì trùng với view mode / chỉ mang tính trang trí. Nhóm View Mode gồm `Recommendation` (mặc định theo hướng mockup), `Surge Delta`, `Demand / Supply`, `Base Surge`. Đây là **thay đổi có chủ ý** so với MAP-02 v0.3 trước đó (D/S mặc định). Bật/tắt edges độc lập với màu hex. Khi nguồn edge không có hoặc dữ liệu OD chỉ là aggregate hồi cứu, disable/annotate layer tương ứng thay vì tự giả lập tuyến.

**MAP-N03 — Hybrid edge visibility.** Ở trạng thái mặc định có thể hiện **một tập nhỏ OD edges nổi bật nhất có ý nghĩa và được khai báo metric/window**, đồng thời ưu tiên hiển thị các kết nối của selected hex. Không hiển thị toàn bộ E cạnh ở cùng cường độ. Chọn hex làm đậm các incoming/outgoing edge liên quan, làm mờ edge không liên quan, giữ màu fill biểu thị action. Giới hạn ban đầu: top 8–12 edge liên quan mỗi hex và giới hạn top edges toàn map theo viewport; hiển thị `X/Y edges` và cho phép `Show more`. Ranking dựa trên OD volume được khai báo, không xếp hạng theo attention/causal importance.

**MAP-N04 — Edge visual semantics.** `ArcLayer` biểu diễn hướng src→dst với màu network riêng (cyan/blue/violet), độ dày hoặc opacity theo volume có legend; ưu tiên nét cong có hướng và halo nhẹ tại điểm được chọn. Đường adjacency dùng nét mảnh, ít tương phản, không có animation dòng chảy. Edge không lấy màu action INCREASE/DECREASE để tránh ám chỉ edge là recommendation. Nếu data chỉ là OD requests trung bình giờ, label rõ `OD request flow · hourly average`, **không gọi driver relocation**. Mọi popup phải có source, destination, metric, units, window, cutoff và validity; không được lộ số lượng cá nhân/định danh tài xế.

**MAP-N05 — Network interactions.** Hover/focus hex hiển thị ID, action, base→proposed, time/source; click hex đồng bộ map, right-side proposal detail, chart, queue và network connections. Hover/focus edge hiển thị src/dst, direction, volume, window và loại quan hệ; click edge chọn relation để xem Incoming/Outgoing list nhưng không tự đổi proposal hoặc gửi decision. Chọn hex không làm pan liên tục chống lại người dùng. Zoom/fit/recenter và legend phải accessible. Selected hex có outline sáng trắng hoặc violet, halo mỏng; không dùng glow để ám chỉ confidence.

**MAP-N06 — Network Connections panel.** Khi một hex được chọn, panel bổ sung hai tab `Incoming` / `Outgoing`, hiển thị connected hex, loại OD metric, volume, khoảng cách/chỉ số travel-time chỉ khi có dữ liệu đúng contract, trend chỉ khi có chuỗi lịch sử. Row click có thể điều hướng đến hex đối tác và đồng bộ map/panel. Không tạo giá trị volume/distance/trend giả để lấp UI. Bảng này nằm trong tab Network của panel chi tiết, không thay thế Recommendation Queue hay chiếm mất primary action.

**MAP-N07 — Animation / replay.** Chuyển trạng thái selection, edge highlighting và giá ở panel khoảng 150–250ms ease-out; animation hạt/đường OD (chu kỳ đề xuất 2–4s) chỉ **opt-in**, chỉ khi edge hợp lệ và số lượng đủ ít. H3 polygon không nhấp nháy liên tục; không tạo chuyển động giả làm nguồn cung/driver thực. Replay cập nhật network edges **đúng snapshot và event-time semantics**; thay frame không được nội suy hoặc dùng dữ liệu tương lai không gắn nhãn. `prefers-reduced-motion` chuyển về edges tĩnh và tắt particle animation. Không ưu tiên animation hơn khả năng đọc số và FPS.

**MAP-N08 — Render budgets & graceful degradation.** Với nhiều cạnh/viewport hẹp, cull và lọc theo selection/volume trước khi render; ưu tiên performance của pan/zoom, hit-testing, queue và batch actions. Giảm/tắt animation và edges không thiết yếu khi low FPS/reduced-motion. Khi mất WebGL/basemap, hỗ trợ nền fallback + danh sách hex/queue, không giấu proposal. Không nạp hàng triệu OD edges của toàn dataset vào browser. Map fail không được ảnh hưởng backend decision correctness.

**MAP-N09 — Meaning & color contract.** Hex fill khi `Recommendation`: INCREASE coral/orange, DECREASE blue/cyan, HOLD slate, REVIEW violet; legend bắt buộc và selection dùng outline khác màu fill. `Surge Delta` dùng diverging scale với zero trung tính; `D/S`, `Demand`, `Supply`, `Base Surge` dùng scale/metric label riêng. `Recorded` dùng emerald ở badges/log, không tô lại hex như đã cải thiện thị trường. Hãy giữ versioned scales khi replay.

**MAP-N10 — Acceptance additions (chưa kiểm thử).** FE-MAP-41: correct H3 geometry + synchronized selected hex; FE-MAP-42: OD src→dst, units/window và edge tooltip; FE-MAP-43: toggle top OD/adjacency/selected network độc lập; FE-MAP-44: Incoming/Outgoing panel phản ánh đúng graph records; FE-MAP-45: replay edge source/cutoff consistency; FE-MAP-46: missing/invalid OD disables/hides edges có thông báo; FE-MAP-47: reduced-motion/fallback basemap/WebGL; FE-MAP-48: visual review phù hợp mockup, contrast/accessibility và performance thực đo. Tất cả ở trạng thái **NOT TESTED**.

### 4.3. Panel quyết định

**Tầng 1 — Kết luận.** Tên vùng/hex; chip đề xuất Tăng / Giảm / Giữ / Cần xem xét; một badge eligibility tách biệt; giá lớn **Bidding hiện tại → Đề xuất sau giới hạn**; delta có dấu và đơn vị **điểm hệ số surge**. Nhãn Đủ điều kiện duyệt chỉ dựa trên server validation trong đúng execution mode; DEMO thêm chữ demo, không gọi Đã an toàn về kinh doanh.

`+0.20 điểm hệ số` không đồng nghĩa tăng 20% giá chuyến đi. `s_bid` không tự đồng nghĩa giá đang thực sự có hiệu lực. Nếu có `effective_surge` và receipt, hiển thị riêng giá thực thi và thời điểm hiệu lực.

**Tầng 2 — Vì sao.** Một câu giải thích ngắn từ dữ liệu và reason đã kiểm chứng. Không cần LLM trong luồng chính. Ví dụ: “Dự báo Graph còn cao hơn mốc tham chiếu; chênh lệch so với Local làm nhẹ mức tăng đề xuất.” Không khẳng định chắc chắn tài xế sẽ đến hoặc doanh thu tăng.

Ngay dưới là hai khối gọn: so sánh Local / Graph / Mốc tham chiếu trên cùng thang và cùng t+5; phân rã Pressure / Revision / mức hiệu chỉnh sau giới hạn. Pressure được tính từ Graph so với reference, không gắn nhãn là đóng góp Local. Chênh lệch hai forecast không phải causal network effect.

**Tầng 3 — Bằng chứng theo nhu cầu.** Tab mặc định Biểu đồ lịch sử; tab Chi tiết đề xuất; tab Dữ liệu hỗ trợ; liên kết Nhật ký quyết định đã lọc vùng. Chỉ một nội dung chi tiết mở để không đẩy nút ra ngoài viewport. Chi tiết gồm P/R, dead zones/gains, direction gate, requested cap, global price cap, các giá trị trước/sau và reason từ backend. Dữ liệu hỗ trợ gồm freshness, coverage, cohort/support counts, nguồn fallback và phiên bản. Không vẽ gauge “AI confidence 98%” từ volume hay support.

| Hành động | Điều kiện và kết quả |
|---|---|
| Xác nhận đề xuất ×X | Chỉ khi proposal hợp lệ, không hết hạn, có quyền và production được phép. Hiện giá chính xác sẽ gửi; khóa double click |
| Xác nhận demo ×X | Chỉ trong DEMO; lưu quyết định mô phỏng, không gọi endpoint thực thi |
| Giữ bidding | Ghi quyết định không chấp thuận correction cho đề xuất này; không gửi lệnh ghi đè giá toàn hệ thống |
| Điều chỉnh thủ công | Secondary action trong menu; chỉ hiện khi capability được cấp; mở drawer với lý do, giới hạn và review |
| Hủy lệnh đang chờ / Tạo điều chỉnh mới | Chỉ khi backend hỗ trợ và cho phép ở trạng thái hiện tại; không xóa lịch sử |

HOLD do model là kết luận, không cần nút xác nhận giá lặp. Có thể đánh dấu Đã xem nếu backend hỗ trợ. REVIEW do lỗi forecast/schema/horizon không được duyệt kể cả bằng menu override thông thường. Quy trình can thiệp khẩn cấp, nếu có, là scope riêng.

**Override.** Không còn nút ±0.1 luôn mở. Step, precision, min/max, mức sai lệch được phép và thời hạn lấy từ policy/capability. Thiếu chúng thì khóa nhập/gửi, hiện lý do. Validate lại ở server. Frontend không round giá để tự tạo một action khác; tách display formatting với canonical value sẽ gửi. Lý do override bắt buộc.

### 4.4. Biểu đồ và kiểm tra dự báo

Từ v0.3, tab Lịch sử có bốn subtab theo thứ tự **Surge Base / D/S / Demand / Supply**, mở **Surge Base** mặc định theo yêu cầu mới của chủ dự án. Chỉ một biểu đồ mở trong panel, không thêm chart thứ ba ép nhỏ layout. Bộ chọn subtab và 60 phút / Cả ngày dùng chung, không remount khi đổi loại chart để giữ focus bàn phím. Cửa sổ chart độc lập với W4/W12 của model, không quảng bá 60 phút chart là input history thực tế.

#### 4.4.1. Surge Base — bidding gốc theo thời gian

**SURGE-01 — Ý nghĩa.** Vẽ chuỗi hệ số bidding trước correction theo hex đang chọn. Đơn vị là hệ số ×, không phải phần trăm, D/S hay tiền cước. Chuỗi này MUST NOT lấy từ `s_final`, `delta_applied`, quyết định override hoặc receipt. Xác nhận/giữ/hủy một đề xuất không sửa lịch sử bidding. Đây là yêu cầu bổ sung frontend, không thay công thức policy. [Confidence: High — yêu cầu chủ dự án và mapping trực tiếp trong adapter; chưa xác nhận production integration.]

**SURGE-02 — Nguồn DEMO.** App React đọc `DATASET.raw.surge[k][hex.index]`, tức trường `surge` đã có trong `ui/data.json`. Trong kịch bản có override bidding, lịch sử dùng cùng `scenario.override(..., k).bid` như snapshot adapter ở từng cutoff. Điểm hiện tại lấy `item.market.bidding.value`, kể cả khi null; không fallback về raw để che fixture/lỗi. Kiểm hex mapping và cutoff trước khi dùng lịch sử. Nguồn JSON cũ đã được builder làm tròn một chữ số thập phân; chart không tuyên bố khôi phục precision của Parquet gốc và không sửa/re-export dataset trong lần bổ sung này.

**SURGE-03 — Cách vẽ.** Đường bậc thang kiểu step-after: giữ mức của điểm trước đến timestamp kế tiếp rồi đổi mức. Không spline, nội suy chéo hoặc trung bình trượt, vì các cách đó có thể tạo mức bidding không được ghi nhận. Giữ nguyên giá trị số khi tính/toạ độ; format hai chữ số theo UI demo chỉ phục vụ hiển thị. Trục Y tự bao phủ dữ liệu có giá trị, không ép vào [1,3] hay coi biên đồ thị là giới hạn policy. Vạch cutoff tím và chấm tại base hiện tại cùng timestamp với header/replay.

**SURGE-04 — As-of và replay.** Nét liền sáng cho bidding đến cutoff. Chỉ trong REPLAY, quan sát đã có sau cutoff được vẽ nét chấm mờ, với nhãn **Bidding sau cutoff · chỉ replay**. Không vẽ quá `head`/cuối dữ liệu, không gọi phần đó là forecast. LATEST không hiện lịch sử sau cutoff dù file chứa phần tương lai. Không tạo dự báo Surge Base tại t+5 và không nối giá đề xuất vào chuỗi bidding. `current_surge_t` của simulator là giá snapshot dùng cho bước tiếp theo; hình bậc thang không chứng minh giá đã thực thi trên hệ thống thật.

**SURGE-05 — Thông tin cạnh chart.** Hiện base tại cutoff, chênh lệch so với đúng bước 5 phút trước, và min/max trong cửa sổ quan sát đến cutoff. Không dùng phần replay sau cutoff tính các tóm tắt này. Mặc định 60 phút là tối đa 13 endpoint, từ t−60 đến t, không phải cửa sổ input của model. Trong REPLAY, cửa sổ này có thể thêm tối đa 30 phút quan sát sau cutoff đã có tới head. Cả ngày hiển thị lịch sử của ngày được nạp; chỉ REPLAY mới thêm đoạn sau cutoff đã có tới head.

**SURGE-06 — Điều khiển.** Chọn hex, kéo replay, lùi/tiến và Play cập nhật chart từ cùng store, không có timer riêng. Hover hiển thị full ngày/giờ Asia/Ho_Chi_Minh và base tại điểm tương ứng. Click một điểm hoặc dùng ←/→, Home/End khi focus chart sẽ pause replay và chuyển shared cutoff qua `seek`, giữ hex đang chọn. Chart có semantics slider, accessible label/value; toolbar không mất focus khi đổi subtab. Không chọn im lặng một timestamp khác qua khoảng thời gian bị thiếu. Khi chưa chọn hex, panel giữ empty state hiện có.

**SURGE-07 — Thiếu dữ liệu.** Null, nonfinite hoặc base không dương được hiển thị Thiếu cùng reason; không thay bằng 0, 1 hoặc giá hợp lệ trước đó. Missing sample và khoảng timestamp không liên tục tạo gap; các điểm hợp lệ đứng riêng vẫn có chấm. Thiếu base ở cutoff hoặc bước trước, hoặc khoảng cách không đúng 5 phút, thì delta 5 phút là Thiếu. Nếu toàn bộ cửa sổ thiếu thì không có đường giá/min/max giả. Pointwise plot không được dùng cap production chưa chốt để loại/clamp một giá trị số hợp lệ.

**SURGE-08 — Phạm vi chạy.** Phần bổ sung nằm ở app React `ui/app`, không phải `ui/dashboard.html` legacy. Giữ badge DEMO/SYNTHETIC và chú thích nguồn. Không thêm thư viện biểu đồ, timer hay endpoint thực thi. Lịch sử bidding production cần contract ở mục6.7; current implementation là adapter DEMO, không phải feed Live.

#### 4.4.2. D/S, Demand/Supply và kiểm tra dự báo

Ba subtab còn lại giữ trách nhiệm hiện có. Khung mặc định là 60 phút trước cutoff và vùng t+5; chọn Cả ngày khi cần. Các quy tắc forecast dưới đây không tạo một đường dự báo Surge Base.

| Dữ liệu | Biểu diễn |
|---|---|
| Quan sát đến cutoff | Nét liền, tương phản rõ, ghi Observation |
| Forecast phát hành tại cutoff cho t+5 | Điểm/đoạn tách biệt, nét đứt hoặc ký hiệu riêng, ghi model/cutoff/horizon |
| Quan sát sau cutoff đã có trong replay | Nét chấm mờ, nhãn Quan sát sau thời điểm đang xem — chỉ có trong replay |

Vạch tím biểu diễn đúng cutoff; forecast point nằm đúng forecast timestamp. Chỉ có một dự báo H5 thì không vẽ như có cả đường dự báo đa horizon. Live chưa có nhãn sau t thì để khoảng trống, không nội suy tương lai.

Không làm mượt mặc định khi so lỗi forecast với observation. Có thể bật trung bình trượt trailing 30 phút cho quan sát, nhưng ghi rõ và không dùng đường đã làm mượt đó làm ground truth thay target. Không tính tỷ lệ từ trung bình D/S rồi đối chiếu một target định nghĩa khác. Profile raw ratio có q=0: không tự log-scale làm mất điểm; dùng linear hoặc transform hiển thị có nhãn rõ. Missing/invalid là khoảng trống, không backfill bằng 0.

**Xem lại sau 5 phút** giữ forecast ban đầu và cutoff, chỉ mở quan sát hợp lệ tại forecast timestamp. Nếu label chưa đến, chưa mature hoặc khác contract thì hiển thị Chưa thể đối chiếu + reason. Không chạy lại model mới rồi gắn kết quả đó vào quyết định cũ. Forecast tốt hơn không tự chứng minh correction gây cải thiện marketplace.

Click chart đổi thời điểm xem qua cùng state với timeline. Timestamp không có dữ liệu là gap, không chọn một frame khác mà không thông báo.

### 4.5. Hàng đợi duyệt

Queue nằm trong tab `Recommendations` của panel chi tiết ở view `Map` (panel kéo ngang để mở rộng); nav chỉ còn `Map` và `History` (Nhật ký quyết định, chiếm toàn chiều cao, panel chi tiết bên phải). Toolbar queue gồm search vùng/mã hex, filter, số kết quả và hành động batch. Không có nút Duyệt tất cả không giới hạn phạm vi.

Filters: Chờ xử lý, Đủ điều kiện duyệt, Cần xem xét, Đã xử lý. Chờ xử lý = proposal hiện hành chưa có operator decision/terminal disposition; HOLD mặc định không nằm trong queue hành động. Đã xử lý gồm các trạng thái con và không đồng nghĩa tất cả đã có hiệu lực. Count lấy từ cùng snapshot/query; kết quả rỗng có lời giải thích và Xóa bộ lọc.

Cột chính: checkbox, trạng thái, vùng/hex, bidding → đề xuất, delta, lý do cần chú ý, cập nhật. Desktop nhỏ có thể gộp delta vào giá; không ẩn reason/data warning. Bấm dòng để chọn, bấm checkbox chỉ chọn batch và không gửi. Chi tiết mỗi dòng là thông tin ngắn, không dump raw JSON.

Ưu tiên REVIEW nghiêm trọng theo severity backend, rồi proposal có priority backend; tie-break ổn định theo hex ID. Nếu chỉ có severity và delta, dùng thứ tự trình bày công bố trong UI, không gọi đó là xếp hạng lợi nhuận. Không làm REVIEW mất hút ở cuối như v0.1. Không re-sort dưới con trỏ khi người dùng đang đọc/chọn.

Có snapshot mới: hiện “Có đề xuất mới · <thời điểm>”. Giữ nội dung đang xem nhưng đánh dấu stale/superseded theo server, khóa action cũ khi không còn hợp lệ. Refresh snapshot cập nhật nguyên khối; batch selection phải được xóa hoặc yêu cầu rà soát lại, không tự chuyển selection sang proposal ID mới.

**Batch flow:** chọn các proposal eligible → “Xem và duyệt N đề xuất hợp lệ” → màn rà soát đúng tập ID/giá/thời hạn → gửi một batch có idempotency key → hiển thị kết quả từng item. REVIEW, stale, invalid, thiếu quyền không được chọn. Backend kiểm lại từng item; partial success phải hiện đúng số thành công/thất bại/lỗi chưa rõ, không gắn xanh cả batch. Không tự chọn thêm proposal mới vào batch đã rà soát.

Với 61 hex, cho phép xem hết bằng cuộn trong queue; không cắt im lặng ở 40. Nếu paging/virtualization, tổng count và selection scope vẫn chính xác.

### 4.6. Nhật ký và audit

Timeline nhật ký append-only; mỗi event có decision/proposal ID, vùng/hex, actor do server xác thực, action, lý do, giá yêu cầu, server status, cutoff, thời điểm nhận/thực thi, model/policy/metric versions. Hiển thị cùng timezone với màn chính. Override có nhãn riêng.

Phân biệt Đã xác nhận, Đã ghi nhận, Đang thực thi, Đã có hiệu lực, Lỗi, Đã hủy và Đã chọn giữ bidding. Việc duyệt không đổi market observation. Snapshot tiếp theo vẫn có thể phát sinh proposal mới cho cùng hex.

Nút Hoàn tác tổng quát bị thay: lệnh đang chờ chỉ hủy khi server chấp nhận; lệnh đã thực thi cần quyết định bù/điều chỉnh mới dựa trên bidding hiện tại. Không xóa event gốc hoặc âm thầm khôi phục giá cũ.

### 4.7. Replay và phím tắt

Replay toàn chiều ngang dưới cùng, gồm ngày giờ, lùi/phát/tiến, timeline, tốc độ và Xem lại sau 5 phút. Track và nhãn con trỏ dùng chung timestamp; không để nhãn 14:25 nhưng vị trí là 15:00 như sai lệch có thể có trong ảnh minh họa.

Một bước là 5 phút theo dataset hiện tại; tốc độ 1×/4×/12× phải giải thích là tốc độ phát: 1× tương ứng một snapshot mỗi giây, không phải thời gian thật. Dừng cuối dữ liệu, không tự lặp. Khi bắt đầu review/override/demo confirmation, pause replay để giá không đổi dưới tay người dùng. Kéo thời gian/chọn chart đổi mode sang REPLAY; trở lại LATEST cần thao tác rõ.

Decision markers chỉ lấy từ audit/demo session; không tạo mốc giả. Trong PRODUCTION, xem REPLAY là read-only đối với giá, dù còn kết nối live. Muốn xử lý phải về snapshot mới nhất và xác thực lại.

Space phát/dừng chỉ khi focus thuộc replay hoặc chế độ phím tắt hợp lệ; không chặn Space trên button/input. Mũi tên trái/phải trong timeline đổi một bước; ở slider/input/map giữ semantics riêng. Escape đóng overlay và trả focus về control mở nó. Không có phím đơn toàn cục để duyệt giá trực tiếp.

## 5. Trạng thái và hành động

### 5.1. Tách ba lớp trạng thái

| Lớp | Trạng thái đề xuất | Ý nghĩa |
|---|---|---|
| Recommendation | INCREASE / DECREASE / HOLD / REVIEW | Kết luận model/controller, không đổi khi user từ chối |
| Eligibility | ELIGIBLE / BLOCKED / EXPIRED / SUPERSEDED / UNKNOWN | Có được thao tác trong ngữ cảnh hiện tại không |
| Operator/execution | PENDING / SUBMITTING / RECORDED / EXECUTING / EFFECTIVE / KEPT_BIDDING / FAILED / CANCELLED / UNKNOWN | Trạng thái quyết định và lệnh thực thi, không dùng thay recommendation |

Eligibility/status sản phẩm là phần backend adapter cần bổ sung, không tuyên bố report hiện đã có toàn bộ các enum này. `UNKNOWN` sau timeout nghĩa là chưa xác định kết quả, không đồng nghĩa lệnh đã thất bại.

Luồng xác nhận: PENDING → SUBMITTING → RECORDED → EXECUTING → EFFECTIVE, hoặc nhánh lỗi do server trả. Một hệ thống không có EXECUTING có thể đi từ RECORDED sang EFFECTIVE nhưng vẫn phải có receipt. Chỉ nhận HTTP 2xx hoặc lưu audit không đủ để hiện Đã có hiệu lực. Giữ bidding: PENDING → SUBMITTING → KEPT_BIDDING sau server acknowledgement; recommendation gốc vẫn giữ.

### 5.2. State frontend tối thiểu

| Nhóm | Dữ liệu cần giữ |
|---|---|
| Context | data_kind, view_mode, execution_mode, timezone, region, snapshot_id, cutoff, forecast_ts |
| Selection | selected_hex_id, selected_proposal_id, selected_snapshot_id |
| Presentation | map layer + observation/forecast mode, edge metric/filter, chart window/tab, queue filters, replay position/speed |
| Working set | batch proposal IDs + versions, draft override + reason + source proposal |
| Request lifecycle | pending idempotency keys, server receipts, unknown-result requests, connectivity |

Không dùng `applied[hex]`/`rejected[hex]` làm source of truth production. Key quyết định ít nhất phải gắn proposal ID và snapshot/version; thay thời gian không xóa audit hoặc làm quyết định cũ tự áp cho proposal mới. Frontend có một shared state/query identity cho các view, không cache panel khác cutoff với map.

### 5.3. An toàn khi thao tác

MUST revalidate ở server tại thời điểm gửi: quyền, proposal version, thời hạn, dữ liệu hợp lệ, bidding version, policy/metric compatibility và readiness. Nếu bidding thay đổi, reject/supersede và yêu cầu rà soát proposal mới; không âm thầm cộng delta cũ vào bidding mới rồi thực thi.

Double-click/retry cùng ý định dùng cùng idempotency key. Timeout chuyển UNKNOWN, query kết quả theo key trước khi tạo request mới. Version conflict hiện “Đề xuất đã thay đổi, cần xem lại”; không tự resubmit. Mất kết nối khóa action có thể đổi giá, giữ snapshot cuối với nhãn stale. Server vẫn là authority; UI disabled không thay phân quyền/validation.

Điều chỉnh đã ghi nhận nhưng chưa có hiệu lực không được tăng count EFFECTIVE hoặc thay số effective_surge. Acknowledgement muộn của snapshot cũ cập nhật đúng audit/decision, không overwrite panel đang xem snapshot khác.

### 5.4. Màn hình lần đầu

DEMO có thể mở một kịch bản được đặt tên và ghi rõ là minh họa; không trình bày frame được chọn hồi cứu như Live. LATEST mở snapshot hợp lệ mới nhất. Tự chọn REVIEW priority cao hoặc proposal đầu trong queue; không auto-confirm. Queue rỗng thì chọn vùng người dùng đang xem trước đó hoặc hiện lời hướng dẫn; không tạo proposal để lấp khoảng trống.

## 6. Data contract

### 6.1. Prototype hiện có — giữ để tương thích

Dữ liệu nhúng hiện mô tả một ngày replay, thường 288 bước, 61 hex; đây không phải toàn bộ dataset 30 ngày.

| Field | Ý nghĩa |
|---|---|
| `day`, `ts` | Ngày và nhãn HH:MM theo bước; adapter mới cần full timestamp có timezone |
| `hexes` | id, zone, ring, lat, lng, poly; phải biết thứ tự tọa độ trước khi đổi library |
| `D`, `S`, `I` | Demand, effective supply, idle supply theo thời gian và node |
| `surge` | Surge nguồn; mapping sang bidding/effective cần semantics rõ |
| `npress`, `eta` | Neighbor pressure, ETA; chưa đủ để suy confidence |
| `adj` | Quan hệ kề |
| `od[24]` | Danh sách OD aggregate theo giờ, không phải stream tài xế |

Nguồn tham chiếu là features/hex_features và features/graph_edges trong data/hcm_data_2. Adapter legacy phải xử lý 00:00 đóng cửa sổ cuối theo ngày kế tiếp khi cần; không dùng chỉ HH:MM làm key, không tự coi toàn bộ payload có timezone UTC.

### 6.2. Blocker: định nghĩa D/S chưa đồng bộ

[Confidence: High — đối chiếu trực tiếp Technical Report §14 với ML data/serving contracts tại thời điểm sửa spec.]

| Nội dung | Technical Report / frontend v0.1 | ML pipeline docs/contract |
|---|---|---|
| Target | log((D+1)/(S_eff+1)) | log1p(D/S_eff) |
| Inverse forecast | exp | expm1 |
| Đại lượng UI | Smoothed ratio | Raw ratio |
| D = S_eff = 0 | Smoothed ratio = 1, support thấp | Ratio không xác định, mask/invalid |
| History/model routing | W4, `gru_local37`/`gru_gatv2_40` | W12, context29/graph input tương ứng |

Phiên bản frontend 0.2 **không giải quyết xung đột bằng cách chọn ngầm một nhánh** và không sửa model/ML docs. UI chỉ cho kết nối production khi có một integration profile được chốt, model bundle/policy/reference cùng thang và adapter đã kiểm parity. Metadata thiếu hoặc không tương thích thì hiển thị contract mismatch, không tính lại để hợp thức hóa.

Trường `metric_definition` bắt buộc: ID/version, display name, equation/units, denominator semantics, zero-supply policy, output space, reference/version, horizon. Observation, Local, Graph và reference trên cùng chart MUST cùng definition. UI có thể hỗ trợ nhiều profile qua adapter tường minh nhưng không trộn chúng trong một snapshot/comparison.

Các tên smoothed_ratio_demo và raw_ratio_demo trong test là nhãn fixture nội bộ, không phải model contract đã đăng ký. Scenario demo mặc định có thể giữ smoothed ratio để khớp prototype, luôn có nhãn và không được quảng bá là integration model mới.

### 6.3. Read model dành cho UI — đề xuất bổ sung

Một response snapshot nhất quán là source of truth cho map, queue và panel. Có thể do backend-for-frontend dựng từ forecast/controller/decision services; đây không phải thay core tensor signature.

| Nhóm | Fields tối thiểu |
|---|---|
| Envelope | schema_version, snapshot_id/version, region_id, node_mapping_version, cutoff_ts, forecast_ts, generated_at, timezone, data_kind, view_mode, execution_mode |
| Model/evidence | numeric model_version hoặc demo_model_id có namespace riêng, bundle/dataset fingerprint nếu có, target/feature/routing versions, window, forecast_horizon_min |
| Metric | metric_definition, map_scale/reference_version, observation_kind, coverage, units/windows |
| Market | hex_id, display_name/zone, demand, idle_supply, effective_supply, observed_ratio + validity, bidding value/version, effective_surge + receipt nếu có |
| Forecast | local, graph, validity, support/freshness, reason codes; named values đã inverse đúng profile |
| Proposal | proposal_id/version, status, s_bid, s_final, delta_requested, delta_applied, pressure, revision, a_P, a_R, a, policy/reference versions |
| Eligibility | action_eligible, blocked_reasons, expires_at, validated_at, readiness, capabilities, limits/precision/step |
| Decision | decision_id, action, status, server timestamps, actor label, reason, execution receipt |

`null` MUST có validity/reason; unsupported không trả số 0. Decimal giá nên có canonical representation và precision trong contract, tránh sai lệch serialize/round. Metadata không sẵn có trong DEMO ghi rõ demo/unavailable, không chế numeric model version hoặc bundle hash.

### 6.4. Mapping legacy và controller

| UI | Report field / adapter requirement |
|---|---|
| Bidding hiện tại | s_bid; biến thể surge_bid chỉ map qua profile explicit |
| Đề xuất sau giới hạn | s_final; biến thể surge_final map explicit |
| Hiệu chỉnh chính | delta_applied = s_final - s_bid, **không phải execution receipt** |
| Requested correction | delta_requested, hiện trong Chi tiết |
| Local / Graph / reference | q_L / q_G / q_star trong report; ds_local / ds_graph / ds_ref chỉ map khi profile kiểm semantic compatibility |
| Pressure/Revision trace | pressure, revision, a_P, a_R, a và trace các gate/cap do adapter cung cấp |
| Dữ liệu hỗ trợ | demand, idle_supply, effective_supply, support; không đổi match rate thành booking rate |

Controller algebraic cap ±0.4 là yêu cầu của report, không phải global price range 1.0–3.0 và không phải business guarantee. Không dùng frontend clipping để che payload sai. Base ngoài policy hoặc invalid làm proposal bị chặn; thiếu bidding hợp lệ thì không ghi “đã giữ bidding an toàn”. Phân biệt requested cap với global price cap bằng trace/stage; không suy cả hai từ một reason code.

### 6.5. Decision API và lifecycle — hợp đồng đề xuất

Các thao tác cần có: đọc snapshot, đọc lịch sử/forecast tại cutoff, đọc OD đúng cửa sổ, gửi quyết định đơn/batch, tra cứu kết quả theo idempotency key, đọc audit và yêu cầu hủy khi được phép. Route/transport và schema cuối phải được chốt với backend; spec này không khẳng định endpoint đã tồn tại.

Ví dụ **payload thiết kế**, không phải request đã gửi:

```json
{
  "schema_version": "surge-decision.v1",
  "idempotency_key": "<unique-client-intent-id>",
  "proposal_id": "<server-proposal-id>",
  "expected_proposal_version": "<version>",
  "snapshot_id": "<snapshot-id>",
  "hex_id": "<hex-id>",
  "cutoff_ts": "2026-01-27T14:25:00+07:00",
  "expected_bidding_version": "<bidding-version>",
  "policy_version": "<policy-version>",
  "metric_definition_id": "<agreed-profile>",
  "action": "ACCEPT_PROPOSAL",
  "requested_surge": "1.38",
  "reason": null
}
```

Các action khác: KEEP_BIDDING, OVERRIDE_PROPOSAL; endpoint hủy tham chiếu decision ID. KEEP_BIDDING không bắt buộc requested_surge và không thực thi một lệnh giá. OVERRIDE phải có canonical price và reason. Server lấy actor từ danh tính đã xác thực, không tin `user` hoặc `decided_at` do client tự khai. Server cũng lấy execution mode từ môi trường/capability, không cho client đổi DEMO thành PRODUCTION.

Response tối thiểu: decision_id, proposal_id/version, receipt status, accepted_at, error/blocked reasons và execution receipt khi có. Batch trả từng item, không chỉ success=true. Đọc snapshot và ghi decision phải có rule expiry/version concurrency; FE không tự suy TTL = 5 phút.

### 6.6. Reason code và lời giải thích

| Mã/nhóm | Copy hiển thị và hành vi |
|---|---|
| PRESSURE_DEADZONE | Áp lực nằm trong vùng không điều chỉnh của policy; giữ proposal HOLD |
| DIRECTION_BLOCKED | Hướng hiệu chỉnh bị giới hạn theo policy; mở trace |
| GLOBAL_CAP_CLIPPED | Đã bị giới hạn; lấy cap stage từ trace để phân biệt correction cap và price cap |
| OUT_OF_VALIDATED_RANGE | Dự báo ngoài miền đã kiểm; action theo server eligibility, mặc định chặn nếu chưa xác định |
| LOCAL_RATIO_TOO_SMALL | Local quá nhỏ để tính revision hợp lệ; REVIEW |
| REFERENCE_SCALE_MISMATCH | Mốc tham chiếu khác thang; chặn action |
| INVALID_TARGET_TRANSFORM / FEATURE_ROUTING_MISMATCH / INVALID_HORIZON / NONFINITE_FORECAST | Lỗi train–serve; REVIEW, khóa xác nhận và batch |
| LOW_SUPPORT | Hiện số quan sát và lý do; rule D+S < 4 của prototype chỉ có hiệu lực trong DEMO |
| Reason chưa biết | Hiện mã gốc và Không đủ thông tin để duyệt; không tự map sang success/HOLD |

Lỗi vận hành như hết hạn, mất kết nối, thiếu quyền và xung đột version thuộc lifecycle sản phẩm, không được giả làm reason từ model. Copy phải nêu được việc gì xảy ra, có gửi/ghi nhận lệnh chưa và thao tác tiếp theo nào được phép.

### 6.7. Lịch sử Surge Base — contract tích hợp đề xuất

Đây là phần bổ sung read-only, chưa phải endpoint đã tồn tại. Adapter production cần một series riêng **BASE_BIDDING**, không tái sử dụng series proposal/final/effective nếu chưa xác minh cùng nghĩa.

| Nhóm | Trường cần có và ý nghĩa |
|---|---|
| Identity | region_id, hex_id, node_mapping_version, series_kind=BASE_BIDDING, schema_version |
| Time scope | from_ts, to_ts, cutoff_ts, latest_available_ts, timezone, sample_interval_min |
| Value semantics | source field/definition, multiplier unit, source precision, snapshot/effective-time semantics |
| Point | timestamp có offset, base_value hoặc null, validity/reason, bidding_version khi có |
| Provenance | data_kind, available_at/source timestamp khi có, source version; không tạo execution receipt |

UI kiểm cùng hex/snapshot context, thứ tự timestamp và availability. Trong LATEST chỉ quan sát đã biết ở cutoff được hiển thị; trong REPLAY phần sau cutoff phải có nhãn riêng và giới hạn latest_available_ts. Production không được lấy history sau cutoff làm bằng chứng đã biết lúc ra quyết định. Không tự biến snapshot timestamp thành thời điểm thực thi giá; nếu có effective_at do hệ thống giá cung cấp thì giữ đó là field riêng.

Đối với adapter DEMO hiện tại, `raw.surge` + `dataset.stamps` là nguồn, `market.bidding` là authority cho điểm cutoff; các bid override của scenario chỉ có giá trị fixture. Không có bidding version từng điểm trong nguồn cũ thì ghi unavailable, không chế provenance. Read-only base chart không tự giải quyết xung đột D/S mục6.2 và không mở khóa action khi model/policy contract đang lỗi.

## 7. Trạng thái prototype so với hệ thống thật

### 7.1. Không nhầm prototype với năng lực đã triển khai

| Thành phần | Prototype v0.1 được mô tả | Đích v0.2 |
|---|---|---|
| Forecast/controller | Heuristic chạy trong browser, thông số demo | Adapter demo cách ly; production đọc backend đã kiểm contract |
| Quyết định | Memory theo hex, mất khi reload | Identity theo proposal/version; server audit và execution receipt |
| Replay | Một ngày nhúng HTML | Cùng shared time state, as-of rõ, không apply giá từ replay production |
| Map | SVG không basemap ngoài | Giữ offline fallback; thêm basemap khi có provider hợp lệ |
| UI | Hai chart luôn mở, timeline ở header | Map-first, panel phân tầng, detail tabs, timeline đáy |
| Kiểm thử | Một số checks cũ được v0.1 ghi đã chạy | Tất cả tiêu chí v0.2 cần kiểm lại; không kế thừa trạng thái PASS |

Dữ liệu synthetic hoặc forecast metric đạt chưa đủ để mở production. Thiếu business evidence thì ghi Chưa đánh giá, không dùng badge readiness kỹ thuật làm chứng nhận bảo toàn lợi nhuận. [Confidence: High — Technical Report §13.7; ML serving contract §3 và §7.]

### 7.2. Scenario fixtures để dựng UI và demo

MUST có fixtures riêng cho INCREASE, DECREASE, HOLD, REVIEW, low support, missing graph, cap clipping, stale/superseded, empty queue, request timeout/unknown, partial batch, mất basemap và mất kết nối. Mỗi fixture có mode/source label, coherent timestamp và trace; không lấy toàn bộ con số trong ảnh làm expected values.

Fixture số tham chiếu từ Technical Report §11.1: q_L=2.00, q_G=1.60, q_star=1.20; Pressure=0.333333…, Revision=-0.20; a_P=+0.14, a_R=-0.06; requested=+0.08; bidding=1.30 → final=1.38 nếu price cap cho phép. Đây là minh họa smoothed-ratio policy, chưa phải kết quả model thật. Không ghép Graph > Local với revision âm khi cùng profile/gain dương; dấu trong ảnh minh họa không có thẩm quyền hơn công thức.

Các fixtures khác phải tính expected values từ policy demo được version, không làm frontend thay model thật để cho hình đẹp. Sinh GMV/booking uplift giả hoặc attention-as-causal bị loại khỏi scope.

## 8. Thiết kế hình ảnh

[Confidence: Medium — design system từ hướng hình ảnh đã duyệt; chưa có usability/contrast test trên implementation.]

### 8.1. Tokens và ngôn ngữ hình ảnh

Nền navy tối, panel có viền mảnh, độ sâu vừa đủ; hạn chế gradient và glow. Không dùng hiệu ứng glass làm chữ mờ. Không hỗ trợ light mode trong vòng đầu.

| Token | Giá trị khởi đầu | Cách dùng |
|---|---|---|
| background | #0B1220 | Nền ứng dụng |
| surface / surface-raised | #111B2B / #172337 | Panel, overlay |
| border | #2A3A52 | Đường phân tách |
| text / text-muted | #F3F6FC / #A9B8D0 | Chữ chính/phụ; phải kiểm contrast khi dùng |
| increase | #FF8A3D | Coral-orange cho INCREASE và giá đề xuất tăng; nút primary orange trong mockup |
| decrease | #38BDF8 | Cyan/blue cho DECREASE |
| review | #A78BFA | Violet cho REVIEW; warning validation riêng dùng #F5B942 |
| recorded / effective | #34D399 | Icon/chip lifecycle có chữ cụ thể; không thay fill thị trường |
| focus-accent | #8B7CFF | Selected hex, active tab, timeline |
| neutral | #64748B | HOLD, bối cảnh phụ; không mặc định dùng cho chữ nhỏ |
| od-flow | #5EEAD4 | Cạnh OD khi được bật; độ dày theo metric |

Màu token là khởi đầu, không tự chứng minh đạt WCAG. Trên nền cam sáng dùng chữ tối nếu cần để đạt tương phản, không bắt buộc chữ trắng chỉ vì ảnh có chữ trắng. Màu luôn đi cùng dấu +/−, nhãn hoặc icon. Không dùng emoji làm icon hệ thống; một họ vector icon thống nhất, 16–20px.

### 8.2. Typography và density

System font, hỗ trợ tiếng Việt, không bắt buộc tải font ngoài. Body 14px, nhãn phụ tối thiểu khoảng 12px, heading vùng 18–22px, giá chính 32–40px. Dùng tabular-nums; tăng/giảm thể hiện bằng dấu. Hiển thị multiplier với ký hiệu ×; full precision/legal value xem được trước submit.

Spacing theo nhịp 4/8px; padding card 12–16px; radius 10–14px. Primary action cao 44px; control thường ưu tiên 40px; row queue khoảng 44–48px tùy density. Một primary action trong panel; nút Giữ bidding có kiểu secondary rõ. Border, khoảng trống và kích thước tạo hierarchy trước khi thêm màu.

### 8.3. Micro-interactions

Hover/focus/pressed/disabled/loading có state nhìn thấy và không làm layout nhảy. Chuyển selection/overlay 150–250ms; không animate giá thay đổi như một kết quả kinh doanh tích cực. Disabled action có lý do truy cập được bằng text, không tooltip-only trên button disabled. Toast hỗ trợ, không thay trạng thái bền trong panel/log.

## 9. Phi chức năng

### 9.1. Accessibility

Mục tiêu WCAG 2.2 AA cho phần triển khai, không tuyên bố conformant trước audit. Chữ thường phải đạt contrast tối thiểu 4.5:1; control và focus có contrast phù hợp. Vùng bấm tối thiểu 24×24 CSS px hoặc đáp ứng ngoại lệ hợp lệ của SC 2.5.8; sản phẩm ưu tiên 40–44px cho action. Focus không bị che hoàn toàn bởi nội dung tự tạo theo SC 2.4.11; thiết kế SHOULD giữ toàn bộ control đang focus nhìn thấy. [Confidence: High — W3C [R4], [R5], [R6]; kích thước 40–44px là lựa chọn sản phẩm.]

Mọi tác vụ chính dùng được bằng bàn phím. Hex có accessible name/state; danh sách queue là đường thay thế tương đương với thao tác bản đồ, kể cả tìm HOLD bằng filter/list vùng. Dialog có focus trap và trả focus đúng nơi. Tab/slider/button có semantics native thích hợp, không ARIA role trang trí. Screen reader nhận thông báo trạng thái action có kiểm soát, không đọc lại toàn bộ 61 hex mỗi frame. Tắt animation không thiết yếu theo prefers-reduced-motion. Kiểm zoom 200%, reflow 320 CSS px cho nội dung thông thường; map/bảng hai chiều có điều khiển và thông tin thay thế.

### 9.2. Hiệu năng và cập nhật nhất quán

Mục tiêu nghiệm thu đề xuất trên Chrome desktop và dataset demo 61 hex/288 frame: selection → các view đồng bộ P95 dưới 200ms với dữ liệu đã có; frame replay cập nhật P95 dưới 250ms. Đo trên hardware/test profile được ghi rõ; chưa phải số đã đo. Không buộc preload toàn bộ raw 30 ngày hay 7,6 triệu edge vào browser.

Cập nhật theo thành phần, giữ DOM/focus; chart/history cache theo region/hex/profile/window/cutoff và model identity khi có forecast. Cancel/ignore response out-of-order. Snapshot mới xuất hiện atomically ở map/queue/panel. Prefetch lịch sử được phép nhưng dữ liệu sau cutoff không đi vào vùng bằng chứng as-of không gắn nhãn.

### 9.3. Trạng thái lỗi/empty/loading

| Tình huống | UI bắt buộc |
|---|---|
| Loading snapshot đầu | Skeleton giữ layout; chưa có metric/eligibility giả |
| Refresh chậm | Giữ snapshot cuối có timestamp + trạng thái; không reset giá về 0 |
| Thiếu forecast/contract sai | Hiện observation hợp lệ nếu có; chặn proposal và nêu lý do |
| Support bằng 0 nhưng rate có fallback | Ghi Không có quan sát / giá trị fallback, không báo độ tin cậy cao |
| Không có proposal phù hợp | Empty state + bỏ filter; vẫn xem được bản đồ |
| Hết phiên hoặc thiếu quyền | Giữ read-only khi được phép; chặn gửi và yêu cầu đăng nhập lại theo hệ thống |
| Timeout khi submit | UNKNOWN + tra cứu receipt; không báo Đã có hiệu lực/Chưa gửi khi chưa biết |
| Basemap lỗi | Nền fallback + hex/queue còn dùng được; không làm mất quyết định đang xem |

### 9.4. Security và observability

Không nhúng secret/model registry credential vào HTML; không gửi dữ liệu người dùng/tài xế thô sang tile/analytics provider. Escape reason/copy do server trả, không render raw HTML. Chỉ mở evidence links từ nguồn/host được cho phép. Logging client không chứa token hay thông tin cá nhân không cần thiết.

Đề xuất telemetry: view_snapshot, select_hex, open_explanation, review_batch, submit_intent, receive_receipt, contract_block, stale_block, render_latency. Gắn correlation IDs, không xem client click là số lệnh executed. Audit nghiệp vụ do server giữ. Kết nối MLflow chỉ là link tới evidence được phép, không biến UI này thành trang train/deploy.

## 10. Tiêu chí chấp nhận

**FE-01…FE-32 là bộ nghiệm thu v0.2, không được tự chuyển sang PASS do lần bổ sung này. FE-33…FE-40 bổ sung cho Surge Base v0.3, hiện Chưa kiểm thử.** Đã viết 16 test trong `ui/app/src/__tests__/surgeHistory.test.ts`, gồm adapter, hình học bậc thang và server-render smoke; lệnh test đang yêu cầu phê duyệt CodeLocal. Chưa có kết quả build, test tương tác trình duyệt hoặc số đo performance cho phần bổ sung. Kiểm tra tĩnh/read-back không thay các bước đó.

| ID | Tình huống kiểm thử | Kết quả bắt buộc |
|---|---|---|
| FE-01 | Mở ở 1536×1024 và 1366×768 | View Map: bản đồ + panel phải; view Recommendations: queue + panel phải; timeline đáy; giá/lý do/action không bị cắt |
| FE-02 | Width <1100, zoom 200%, reflow | Đọc/thao tác được; không bị sticky UI che focus; map có list thay thế |
| FE-03 | Chọn hex từ map và queue | Tất cả view cùng hex/proposal/snapshot; đổi lớp không mất selection |
| FE-04 | Synthetic/latest và historical/replay | Badge nguồn/mode đúng; không xuất hiện Live production giả |
| FE-05 | LATEST có snapshot mới khi đang review | View cũ giữ rõ stale; action bị khóa nếu superseded; không đổi giá dưới con trỏ |
| FE-06 | Quan sát/Dự báo/Replay future cùng chart | Kiểu nét/nhãn/thời gian khác nhau; future không giả thành forecast |
| FE-07 | Click chart/slider qua midnight | Full timestamp đúng ngày/timezone; con trỏ khớp nhãn và cutoff |
| FE-08 | Chỉ model H5 | Chỉ hiện forecast H5; không tạo H10/H15 hoặc forecast curve giả |
| FE-09 | Xem lại sau 5 phút | So đúng forecast gốc với label đúng profile; chưa mature thì pending |
| FE-10 | Mất data, invalid ratio hoặc unsupported metric | Gap/hatch/null reason; không biến thành 0/HOLD/cân bằng |
| FE-11 | Profile raw D=0,S=0 so với smoothed | Raw invalid, smoothed=1 có low support; không trộn profile |
| FE-12 | Observation/forecast/reference khác contract | Contract mismatch và chặn action; không tự inverse để sửa |
| FE-13 | Fixture report §11.1 | 1.30→1.38, +0.08; a_P +0.14, a_R -0.06; đúng dấu và copy |
| FE-14 | Requested +0.40, bid1.30, cap1.50 | Đề xuất cuối1.50, main delta+0.20; requested+0.40 trong trace; cap là fixture không phải global mặc định |
| FE-15 | REVIEW/unknown reason/invalid bidding | Không có đường xác nhận hoặc batch lách guard; reason dễ đọc |
| FE-16 | Model HOLD và user giữ bidding trên INCREASE | Hai tình huống có nhãn/audit khác nhau; recommendation gốc không đổi |
| FE-17 | Xác nhận được server ghi nhận, chưa thực thi | Hiện RECORDED, không EFFECTIVE; fill cung cầu không đổi |
| FE-18 | Receipt EFFECTIVE tới muộn | Cập nhật đúng decision; không ghi đè snapshot hiện tại khác ID |
| FE-19 | Double click và timeout rồi retry | Cùng intent/key; UNKNOWN được tra cứu; không tạo lệnh trùng |
| FE-20 | Bidding/proposal version đổi trước submit | Reject/conflict, yêu cầu review mới; không rebase delta ngầm |
| FE-21 | Batch chứa REVIEW/stale/thiếu quyền | Không chọn được item bị chặn; confirm chỉ đúng tập đã review |
| FE-22 | Batch partial success | Kết quả/count theo từng item, không báo cả batch có hiệu lực |
| FE-23 | Override thiếu capability/step/limits/reason | Không gửi; khi đủ điều kiện giá canonical và reason được server validate |
| FE-24 | Hủy sau khi giá đã thực thi | Không xóa log; cần quyết định mới hoặc nêu không hỗ trợ |
| FE-25 | OD hourly/trailing/attention | Nhãn metric và cutoff đúng; hồi cứu được đánh dấu; không gọi causal/tài xế sẽ đến |
| FE-26 | Mất tile và mạng dữ liệu | Map fallback/last snapshot vẫn đọc được; action production khóa phù hợp |
| FE-27 | Queue >40 và filter/search | Xem đủ/count đúng; không mất silently các dòng; sort ổn định |
| FE-28 | Keyboard, screen reader, reduced motion | Hoàn thành tác vụ chính không cần hover/mouse; focus và status đúng |
| FE-29 | Đo contrast/vùng bấm | Đạt ngưỡng mục9; token màu không tự coi là PASS |
| FE-30 | Đo selection/replay latency | Có fixture/hardware/P95 thực đo, đối chiếu mục9; không copy target thành kết quả |
| FE-31 | Permission bị thu hồi giữa review và submit | Backend từ chối, UI cập nhật capability; không chỉ dựa vào nút disabled |
| FE-32 | Check read-model, receipt, audit | Mọi số/decision truy được tới field, snapshot và version; không ghi GMV uplift giả |
| FE-33 | Mở Lịch sử của một hex | Surge Base mở mặc định; đủ bốn subtab và bộ chọn 60 phút/Cả ngày; không nhân đôi toolbar |
| FE-34 | Đối chiếu base với nguồn và thử duyệt/override | Base theo snapshot/source/scenario; đề xuất/decision không đổi chuỗi gốc, không cộng correction |
| FE-35 | Play, pause, seek, đổi hex | Điểm hiện tại/cutoff/header cùng state; không timer riêng; chart không giữ giá của hex trước |
| FE-36 | Giá đổi theo bước và các đoạn hằng | Bậc thang ngang rồi dọc đúng timestamp; không smoothing, không NaN, hiển thị được một điểm riêng |
| FE-37 | LATEST so với REPLAY và head/last frame | LATEST không lộ tương lai; replay sau cutoff nét riêng, không vượt head; stats chỉ đến cutoff |
| FE-38 | Null/nonfinite/base không dương hoặc timestamp gap | Khoảng trống và reason; không fallback/zero-fill; delta5m null khi không đủ hai điểm liên tục |
| FE-39 | 60 phút/Cả ngày, đầu dữ liệu và midnight | Cửa sổ đúng, timestamp có ngày/offset; không tạo giá trước điểm đầu hoặc sau điểm cuối |
| FE-40 | Click, hover và bàn phím trên base chart | Hiện giá/ngày giờ chính xác; click/←/→ pause và seek đúng; chuyển tab giữ focus; dữ liệu demo có nhãn, không gọi giá đã thực thi |

Test evidence SHOULD gồm screenshot ở hai kích thước chuẩn, fixture/profile versions, functional tests, keyboard/contrast review và performance measurements. Screenshot đẹp một mình không đủ nghiệm thu lifecycle/data semantics.

## 11. Ngoài phạm vi và câu hỏi mở

### 11.1. Ngoài phạm vi

Không xây rider/driver app, forecast trainer, model promotion, policy editor, tối ưu GMV/RL/MPC, causal attribution, nhiều thành phố, mobile-native hoặc hệ thống alert đẩy trong vòng này. Không tự động duyệt hàng loạt bằng AI. Login provider/RBAC backend không triển khai trong UI spec; tích hợp identity/capabilities và xử lý thiếu quyền là điều kiện production. Collaboration UI nhiều operator chưa có, nhưng conflict/idempotency phía server vẫn bắt buộc trước write thật.

### 11.2. Quyết định đã chốt cho frontend

Bố cục map-first; panel phân tầng; queue/log dưới map; replay đáy; dark navy và màu ngữ nghĩa; không dùng mock numbers làm policy; default tích hợp là demo/shadow tới khi backend cấp quyền/readiness phù hợp. REVIEW lỗi hợp đồng bị chặn. Quyết định gắn proposal/version, không gắn hex suốt phiên. Không có undo xóa lịch sử.

### 11.3. Dependencies phải chốt trước live write

| ID | Quyết định/phụ thuộc | Chủ trì đề xuất | Hành vi khi chưa chốt |
|---|---|---|---|
| B1 | Model/metric integration profile, raw hay smoothed, W/feature/horizon | ML + backend | DEMO fixtures tách biệt; block integration không tương thích |
| B2 | Reference/gains/global bounds, precision/step, policy trace | Pricing owner + backend | Không override hoặc xác nhận production |
| B3 | Proposal TTL, bidding version, receipts, idempotency, cancel semantics | Backend + Pricing/Ops | Chỉ demo/shadow, không mô phỏng execution success |
| B4 | Identity/capabilities và production readiness/business evidence | Product owner + security/operations | Read-only theo capability, không suy quyền từ role label |
| B5 | Basemap provider, license/attribution, deployment/network | Frontend + product owner | SVG offline/fallback, không tải tile không được phép |
| B6 | History/OD as-of API, snapshot transport push/pull, freshness limits | Data/backend | Dùng replay gắn nhãn; không hứa có live feed |

Đây là dependencies được ghi để đội triển khai giải quyết, không phải yêu cầu người dùng chốt lại toàn bộ bố cục đã duyệt. Push hay polling không đổi semantics snapshot; live acceptance vẫn cần server timestamps và stale policy.

## 12. Thứ tự triển khai và thay đổi phiên bản

### 12.1. Phân kỳ

| Ưu tiên | Bàn giao | Gate |
|---|---|---|
| P0-A | Shell/layout/tokens, shared selection/time state, fixtures, map/queue/panel/replay | Visual theo hướng duyệt; DEMO rõ; FE-01–14 phù hợp scope |
| P0-B | Reason/support views, mode isolation, invalid/stale/empty/timeout UI, batch review/override gating | State tests và contract adapter tests; chưa gửi giá thật |
| P1-A | Read-only backend/shadow, history/OD đúng cutoff, audit/evidence links, basemap được cấp phép | Resolve B1/B5/B6 và data/access checks |
| P1-B | Production decision/execution integration | Resolve B1–B4, receipt/idempotency/concurrency/expiry gates và business approval |
| P2 | Tổng quan, báo cáo cuối ngày, ảnh vùng hoặc mở rộng khác có dữ liệu | Spec riêng, không làm trì hoãn luồng quyết định chính |

Không chọn frontend framework/map library mới trong tài liệu này. Có thể refactor prototype hoặc xây app khi kiến trúc triển khai được chốt; trách nhiệm tách adapter/state/view và các acceptance criteria giữ nguyên.

### 12.2. Thay đổi từ v0.1

| Trước | Sau ở v0.2 |
|---|---|
| Timeline trong header, hai chart luôn mở | Timeline đáy, panel có tabs, map được ưu tiên diện tích |
| Giá hiện tại / Đã áp dụng chỉ dựa click | Bidding / đề xuất sau giới hạn / giá có hiệu lực tách biệt |
| applied/rejected theo hex trong session | Proposal/version identity, decision lifecycle và receipts |
| ±0.1, giá1.0–3.0 hard-code | Policy-provided precision/step/limits; demo rules không thành production |
| Duyệt tất cả, REVIEW có thể lẫn action đơn | Batch có review theo tập ID; hard-block lỗi/REVIEW, server revalidate |
| Undo gỡ quyết định | Hủy có điều kiện hoặc quyết định bù; audit append-only |
| D/S smoothed giả định đồng nhất | Metric integration profile explicit; conflict report/ML là blocker |
| OD chạy liên tục và toàn giờ ít chú thích | Luồng có metric/hướng/cutoff, focus-related edges, reduced motion |
| Không basemap ngoài, không phân mode đầy đủ | Basemap tùy dependency + offline fallback; data/view/execution modes độc lập |
| Checks prototype ghi đã đạt | Bộ FE-01…FE-32 mới, tất cả chưa kiểm thử v0.2 |

Không xóa trách nhiệm cũ: Demand/Supply charts, reason codes, audit, keyboard, offline demo và chronological replay vẫn được giữ dưới bố cục mới.

### 12.3. Bổ sung v0.3 — Surge Base

| File | Thay đổi |
|---|---|
| [surgeHistory.ts](../../ui/app/src/adapters/demo/surgeHistory.ts) | Adapter lịch sử bidding read-only, scenario/cutoff parity, as-of summary, gap và step-after geometry |
| [SurgeBaseChart.tsx](../../ui/app/src/components/panel/SurgeBaseChart.tsx) | Chart SVG, giá hiện tại/delta5m, replay future riêng, hover/click/bàn phím |
| [HistoryChart.tsx](../../ui/app/src/components/panel/HistoryChart.tsx) | Toolbar chung bốn subtab; giữ D/S, Demand, Supply; không mất toolbar focus khi đổi loại |
| [store.ts](../../ui/app/src/state/store.ts) | Thêm chartSub=surge và chọn mặc định; tái dùng shared selection/time state |
| [surgeHistory.test.ts](../../ui/app/src/__tests__/surgeHistory.test.ts) | 16 test cho source/snapshot/scenario, null/gap, head/replay, midnight, step paths và server-render smoke |
| frontend_spec.md | Mục4.4.1, contract6.7 và FE-33…FE-40; giữ các yêu cầu v0.2 không liên quan |

Không chỉnh `ui/data.json`, `ui/build_data.py`, prototype HTML cũ, model, controller hoặc policy; không thêm package dependency. Vì vậy đường mở đúng phần bổ sung là app React, **Lịch sử → Surge Base**, không phải file HTML legacy.

Các lệnh để đội dev chạy tại `ui/app` sau khi có quyền execution:

```text
npm run test
npm run typecheck
npm run build
npm run dev
```

Đã yêu cầu `npm run test` và khởi động `npm run dev -- --host 127.0.0.1` qua CodeLocal; cả hai dừng ở `approval_required`, chưa chạy. Không đổi quyền hoặc tự xác nhận. Mã và tests đã được lưu, chưa có bằng chứng test/build/browser PASS. Lần kiểm tra diagnostics không thấy lỗi mới so với baseline nhưng không thay TypeScript build/Vitest, nhất là các file còn untracked. Dùng mục10 để cập nhật evidence sau khi chạy thật; không coi spec/checks cũ là kết quả của v0.3.

## 13. Nguồn và ranh giới bằng chứng

| Mã | Nguồn | Phạm vi sử dụng |
|---|---|---|
| R1 | [Technical Report](../model/technical_report.md), §1, §10–14 | Vai trò bidding, controller, fixture số, output fields, giới hạn evidence; hiện có smoothed-ratio contract |
| R2 | [ML data contract](../ml_pipeline/02_data_contract.md) và [serving contract](../ml_pipeline/06_artifacts_and_serving.md) | Nhánh raw-ratio/W12/context29, validity và serving; ghi nhận xung đột thay vì tuyên bố đã đồng bộ |
| R3 | [ML analysis contract](../ml_pipeline/11_post_training_analysis.md), §5 | Giới hạn attention/explanation, không diễn giải causal |
| R4 | [W3C WCAG 2.2 — Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) | Contrast chữ thường; truy cập 09/10/2026 |
| R5 | [W3C WCAG 2.2 — Target Size Minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum) | 24×24 CSS px và các ngoại lệ; truy cập 09/10/2026 |
| R6 | [W3C WCAG 2.2 — Focus Not Obscured Minimum](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum) | Focus không bị che hoàn toàn; truy cập 09/10/2026 |
| R7 | Frontend spec v0.1 và mockup được duyệt trong hội thoại 09/10/2026 | Nền tảng chức năng cũ và hướng hình ảnh; không phải bằng chứng model/API đã sẵn sàng |

Nội dung mới về read model, capability, lifecycle, layout và acceptance là đặc tả thiết kế để triển khai, không phải mô tả mọi thành phần đã tồn tại trong repo. [Confidence: Medium — engineering/product design; cần integration và usability verification.]
