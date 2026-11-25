# Nimo Kids Tool – Lịch sử phiên bản

Phiên bản hiện tại nằm ở `nimokids_core/__init__.py` (`__version__`), dùng chung cho bản máy tính và bản web. Số này cũng hiện trên tiêu đề cửa sổ và ở dòng đầu nhật ký.

## Quy tắc đánh số (Semantic Versioning: MAJOR.MINOR.PATCH)

| Phần | Tăng khi | Ví dụ |
|---|---|---|
| **MAJOR** | Bỏ hoặc đổi tính năng làm cách dùng cũ không còn đúng (bỏ tab, đổi cấu trúc thư mục, đổi tên file đầu ra) | 1.7.1 → 2.0.0 |
| **MINOR** | Thêm tính năng mới, cách dùng cũ vẫn đúng | 2.0.0 → 2.1.0 |
| **PATCH** | Chỉ sửa lỗi, không thêm tính năng | 1.7.0 → 1.7.1 |

- Tăng phần nào thì đưa các phần bên phải nó về 0 (1.4.1 → 1.5.0).
- Mỗi lần phát hành thì làm đủ 3 việc:
  1. Sửa `__version__` trong `nimokids_core/__init__.py`.
  2. Thêm mục mới lên đầu file này.
  3. Đặt tên file nén theo dạng `NimoKidsTool_vX.Y.Z.zip`.
- Ghi vào các nhóm: **Thêm**, **Thay đổi**, **Sửa lỗi**, **Bỏ**.

---

## [2.9.0] – 25/11/2026

### Thêm
- **[Lõi]** Thẻ chữ / chữ tiêu đề: dịch chữ Trung nằm trong video (không phải phụ đề cuối khung). Quy trình 3 bước:
  1. \"Dò chữ\": quét ~1 khung hình/giây bằng OCR, gộp thành từng chữ có vị trí và thời gian, xuất `titles/tên_video.titles.srt` (chữ Trung, đánh số) và `.titles.json` (vị trí, màu nền, màu chữ).
  2. Người dùng dịch file SRT, lưu thành `tên_video.titles.<ngôn ngữ>.srt` (ví dụ `.titles.vi.srt`). Mốc thời gian trong file dịch có thể lệch vài giây: tool chỉ lấy chữ, ghép theo thứ tự (cùng số dòng) hoặc theo mốc gần nhất (trong 6 giây) khi số dòng khác nhau.
  3. Khi ghép video: che chữ cũ bằng màu nền lấy mẫu quanh chữ và viết bản dịch đúng chỗ, đúng thời gian; màu chữ lấy theo chữ gốc, cỡ chữ tự co cho vừa, tự xuống dòng.
- **[Lõi]** Tự bỏ qua chữ cố định suốt video (watermark kênh), chữ không có ký tự Hán, chữ chớp 1 khung, và chữ ở dải phụ đề dưới cùng.
- **[Máy tính]** Tab 2: khung \"Thẻ chữ / chữ tiêu đề trong video\" với nút \"Dò chữ, xuất danh sách để dịch\", ô đuôi ngôn ngữ, thư mục danh sách chữ. \"Xem thử 1 khung hình\" hiện cả chữ tiêu đề đã thay.

## [2.8.0] – 24/11/2026

### Thêm
- **[Lõi]** Tự dò vị trí dòng phụ đề chữ Trung cứng trong video bằng OCR (RapidOCR, chạy CPU): lấy mẫu ~12 khung hình mỗi video, chỉ xét nửa dưới, chỉ nhận ô chữ có ký tự Hán xuất hiện ở nhiều khung (dòng tiếng Anh hay chữ trong cảnh không bị che nhầm).
- **[Lõi]** Xem thử 1 khung hình với đúng khung che, phụ đề Việt và watermark đang chọn (chọn câu Việt dài nhất để kiểm tra khung đủ rộng).
- **[Máy tính]** Tab 2: nút "Tự dò vị trí chữ Trung" và "Xem thử 1 khung hình"; thêm ô "Rộng (%)" cho khung che. Thư viện nhận dạng chữ tự cài ở lần dò đầu tiên.

### Thay đổi
- **[Lõi]** Khung che giờ rộng vừa chữ Trung (không còn che hết chiều ngang khung) và luôn rộng, cao hơn cả dòng phụ đề Việt dài nhất. Phụ đề Việt tự ngắt dòng, đặt giữa khung che.
- **[Lõi]** Phụ đề Việt dựng bằng file ASS với kích thước tính bằng pixel của video, thay cho bộ lọc `subtitles` của SRT.

## [2.7.0] – 24/11/2026

### Thêm
- **[Lõi]** Che phụ đề cũ (chữ Trung) ở dải dưới video: kiểu "Làm mờ" hoặc "Hộp đen", chỉnh được vị trí (% từ mép trên) và độ cao.
- **[Lõi]** Chèn phụ đề tiếng Việt vào video từ file SRT: khớp theo tên video (`tên.vi.srt`, rồi `tên.srt`), tự gộp mốc thời gian theo thứ tự ghép, tự bỏ file SRT tiếng Trung, chữ nằm đúng dải đã che.
- **[Máy tính]** Tab 2: ô tích "Chèn watermark di chuyển" để bật/tắt watermark; khung "Chữ trong video" cho hai tính năng trên.

## [2.6.0] – 24/11/2026

### Thêm
- [Máy tính] Nhật ký có màu và giờ ở đầu mỗi dòng `[HH:MM:SS]`: đỏ = lỗi, xanh lá = xong/thành công, cam = cảnh báo/chờ, xanh dương = đang làm, tím = dòng tổng kết thời gian.

### Thay đổi
- [Lõi] Thông báo sau khi lấy danh sách nói rõ hơn khi số video chênh với số kênh báo (video ẩn/riêng tư/đã gỡ hoặc đã tải từ trước). Danh sách vẫn luôn được lấy đầy đủ, kể cả video đã tải rồi (hiện trạng thái "đã tải").

## [2.5.1] – 24/11/2026
### Thay đổi
- **[Máy tính]** Trở lại giao diện kiểu v2.4 (dùng theme mặc định của Windows, không còn kiểu phẳng). Vì vậy tab đang chọn không còn tô màu xanh — đổi màu tab cần theme "clam" làm cả giao diện trông phẳng. Vẫn giữ ô tích "chọn tất cả" đứng trước chữ "Chọn" ở tiêu đề cột.
- **[Máy tính]** Đổi chỗ hai nút: "Chỉ chọn video chưa tải" lên hàng trên (cạnh "1. Lấy danh sách video"); "2. Tải video đã chọn" xuống hàng dưới danh sách (cạnh "Đảo chọn dòng").
- **[Máy tính]** Dòng thời gian (Bắt đầu / Kết thúc / Thời gian thực hiện) chỉ hiện khi tải video, ghép video và tạo phụ đề xong; không hiện khi "Lấy danh sách video".

## [2.5.0] – 24/11/2026
### Thêm
- **[Máy tính]** Thanh tiến độ:
  - Chưa có %: hiện vạch chạy qua lại kèm dòng "Đang chạy…" và đồng hồ.
  - Có %: hiện dạng `37% • 1:25` (phần trăm và thời gian đã chạy).
  - Làm xong: giữ lại % cuối.
- **[Máy tính]** Tab đang chọn có nền xanh, chữ trắng đậm để phân biệt với các tab khác. Giao diện chuyển sang theme "clam", vì theme mặc định của Windows không cho đổi màu tab.
### Thay đổi
- **[Máy tính]** Ô tích "chọn tất cả" đứng trước chữ "Chọn" ở tiêu đề cột.
- **[Máy tính]** Hàng nút "1. Lấy danh sách / 2. Tải video đã chọn" về lại phía trên danh sách (bản 2.4.0 đã đặt nhầm xuống dưới).

## [2.4.0] – 24/11/2026
### Thay đổi
- **[Máy tính]** % tiến độ hiện ngay giữa thanh tiến độ, không hiện trên nút Dừng nữa. Làm xong vẫn giữ % cuối để xem lại.
- **[Máy tính]** Tab 1 xếp lại theo thứ tự: danh sách video → nút chọn → hàng nút "1. Lấy danh sách / 2. Tải video đã chọn".
### Thêm
- **[Máy tính]** Ô tích ở tiêu đề cột **Chọn**: bấm để chọn hoặc bỏ chọn tất cả. Ô này có 3 trạng thái: tích hết, bỏ hết, chọn một phần.
### Bỏ
- **[Máy tính]** Nút "Chọn tất cả" và "Bỏ chọn tất cả" (đã thay bằng ô tích ở tiêu đề cột).

## [2.3.0] – 24/11/2026
### Thay đổi
- **[Lõi]** Tách toàn bộ nghiệp vụ ra gói `nimokids_core/` (gồm `douyin.py`, `compile.py`, `subtitles.py`, `common.py`). Gói này dùng chung cho bản máy tính và bản web trên server sau này, xem `ARCHITECTURE.md`.
- **[Lõi]** Số phiên bản duy nhất cho cả hai bản giờ nằm ở `nimokids_core/__init__.py`. Thư mục dữ liệu chọn được qua biến môi trường `NIMOKIDS_DATA_DIR` (dùng cho Docker).
- **[Máy tính]** `nimokids_tool.py` chỉ còn phần giao diện. Cách dùng, icon Desktop và các tính năng giữ nguyên.

## [2.2.0] – 24/11/2026
### Sửa lỗi
- Lỗi `open() got an unexpected keyword argument 'metadata_errors'` khi tạo phụ đề. Nguyên nhân: faster-whisper 1.2.1 không tương thích với thư viện `av` 19. Tool giờ đọc âm thanh bằng ffmpeg, không dùng `av` nữa.
### Thay đổi
- Phụ đề ngắt câu theo mốc thời gian từng từ, giống TurboScribe: câu ngắn, có dấu câu, đúng thời gian.
- Tắt lọc khoảng lặng (VAD), vì khi thử trên video thật của kênh, VAD làm mất các câu ngắn ("Whoops.", "Stop the cart.").
- Ngôn ngữ mặc định đổi thành **Tự nhận dạng**. Bỏ câu gợi ý tiếng Trung, vì ép sai ngôn ngữ làm Whisper bịa ra câu `请不吝点赞 订阅 转发…`.
- Tự loại các câu Whisper hay bịa ra khi gặp đoạn nhạc ("请不吝点赞", "字幕由", "Thanks for watching"…).

## [2.1.0] – 24/11/2026
### Thêm
- Tool tự tải model Whisper, không dùng bộ tải của huggingface_hub (bộ này hay treo với file lớn). Nhật ký hiện %, tốc độ và thời gian còn lại; nếu mất mạng, tool tải tiếp từ chỗ dừng. Model lưu tại `%LOCALAPPDATA%\NimoKidsTool\models`.
- Nút **Dừng** hiện % tiến độ, ví dụ `Dừng (37%)`.
- Giá trị mặc định cho link kênh và thư mục lưu. Tool nhớ các đường dẫn đã dùng lần trước (`settings.json`).

## [2.0.0] – 24/11/2026
### Bỏ
- Tab **Ảnh bìa PNG**. Thumbnail đã được tải kèm khi tải video ở tab 1.
### Thêm
- Danh sách video có ô tích chọn, chỉ tải những video được tích. Có nút "Chọn tất cả", "Bỏ chọn tất cả", "Chỉ chọn video chưa tải", và có thể bôi đen nhiều dòng rồi bấm Space.
- Cột **Trạng thái** hiện "Đã tải" cho video đã có trong thư mục.
### Thay đổi
- Còn 3 tab: 1. Tải kênh Douyin, 2. Ghép video + watermark, 3. Phụ đề SRT.

## [1.7.1] – 24/11/2026
### Sửa lỗi
- Cài faster-whisper thất bại do chạy bằng Python 3.15 (thư viện `av` chưa hỗ trợ). File `.bat` giờ ưu tiên Python 3.13 → 3.10.
- Tool có thể bị lỗi khi mở bằng icon (pythonw không có cửa sổ lệnh) lúc thư viện ghi tiến độ.

## [1.7.0] – 24/11/2026
### Thêm
- Mỗi lần chạy đều ghi thời gian bắt đầu, kết thúc và tổng thời gian thực hiện. Phụ đề có thêm thời gian xử lý của từng video.
- Phụ đề chạy bằng GPU NVIDIA: tool tự cài cuBLAS và cuDNN, tự chọn model large-v3 khi có GPU, gặp lỗi GPU thì tự chuyển sang CPU.

## [1.6.0] – 24/11/2026
### Thêm
- Tab **Phụ đề SRT**: tạo phụ đề bằng Whisper chạy trên máy. Hỗ trợ tiếng Trung giản thể, dịch sang tiếng Anh, xuất thêm `.txt`.
- Nút **Mở** cạnh mọi nút "Chọn...", để mở thư mục hoặc file trong Explorer.

## [1.5.0] – 24/11/2026
### Thay đổi
- Tải theo 2 bước: **Lấy danh sách video** xong mới bấm được **Bắt đầu tải**.
### Sửa lỗi
- Chạy ẩn Chrome chỉ lấy được 18/88 video (Chrome "ngủ" khi cửa sổ bị ẩn; cuộn không trúng khung danh sách).
- Nhật ký lặp nhiều dòng "Đã thấy N video". Giờ chỉ ghi khi số video tăng, dạng `36/88`.

## [1.4.1] – 24/11/2026
### Sửa lỗi
- Thumbnail tải nhầm khung hình cắt từ video. Giờ lấy đúng ảnh minh hoạ tác giả đặt, giữ nguyên kích thước.
- Thư mục `browser_profile` chuyển ra `%LOCALAPPDATA%\NimoKidsTool`, không còn nằm trong thư mục video.

## [1.4.0] – 24/11/2026
### Thêm
- Chạy ẩn Chrome: tool tự nhận danh sách video, chỉ hiện cửa sổ khi Douyin bắt đăng nhập hoặc captcha.

## [1.3.0] – 24/11/2026
### Thêm
- Mở bằng 1 click: `Mo Nimo Kids Tool.bat` tự cài thư viện và tạo icon ngoài Desktop. Lỗi khi mở được ghi vào `nimokids_error.log`.

## [1.2.0] – 24/11/2026
### Thêm
- Tự nhận dạng link kênh: tách mã kênh từ link dài có tham số, link rút gọn `v.douyin.com` hoặc đoạn chữ chia sẻ.

## [1.1.0] – 24/11/2026
### Thêm
- Tải kèm thumbnail PNG vào thư mục `thumbnails/`, không còn file `.cover.jpg`.
### Thay đổi
- Watermark chậm hơn khoảng 3 lần (tốc độ 0.15) và mờ hơn (độ đậm 0.35).

## [1.0.0] – 24/11/2026
### Thêm
- Phiên bản giao diện đầu tiên, gồm 3 tab: tải kênh Douyin, ghép video có watermark di chuyển (chữ hoặc logo PNG), tạo ảnh bìa PNG.
