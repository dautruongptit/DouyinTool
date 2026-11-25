# Hướng dẫn sử dụng Douyin Tool (Nimo Kids Tool)

Công cụ có **hai bản dùng chung một lõi**: bản máy tính (Windows) và bản web (chạy Docker trên server).
Quy trình chung: **Tải video Douyin → Ghép thành video dài có watermark → Tạo phụ đề SRT → Đăng YouTube.**

> Chỉ tải video từ kênh **đã được tác giả đồng ý**.

## 1. Cấu trúc thư mục

| Thư mục / file | Dùng để |
|---|---|
| `nimokids_core/` | Lõi nghiệp vụ dùng chung, không có giao diện |
| `desktop/` | Bản máy tính (Tkinter, Windows) |
| `web/` | Bản web (FastAPI + Docker) |
| `docs/` | `ARCHITECTURE.md` (kiến trúc), `CHANGELOG.md` (lịch sử phiên bản), file này |
| `docker-compose.yml`, `.env.example` | Triển khai bản web |

## 2. Bản máy tính (Windows)

### Cài và mở lần đầu
1. Để nguyên thư mục `DouyinTool` ở chỗ cố định (ví dụ `E:\MY PRO\applications\Tools\DouyinTool`). Không chạy khi còn nằm trong file zip.
2. Bấm đúp `desktop\Mo Nimo Kids Tool.bat`. Lần đầu nó sẽ:
   - tìm Python 3.10–3.13 (chưa có thì mở trang tải Python; nhớ tick *Add python.exe to PATH*),
   - cài thư viện cần thiết (1–2 phút),
   - tạo icon **Nimo Kids Tool** ngoài Desktop, rồi mở tool.
3. Từ lần sau, bấm đúp icon ngoài Desktop. Nếu di chuyển thư mục, bấm lại file `.bat` để tạo lại icon.
4. Cần **ffmpeg** cho tab Ghép video và ảnh bìa: `winget install Gyan.FFmpeg`.
5. Windows hiện "Windows protected your PC": bấm *More info* → *Run anyway*.
6. Tool báo lỗi khi mở: xem file `desktop\nimokids_error.log`.

### Ba tab
1. **Tải kênh Douyin:** dán link kênh → *1. Lấy danh sách video* → tích chọn video (có nút *Chỉ chọn video chưa tải*, *Đảo chọn dòng*) → *2. Tải video đã chọn*. Nếu Douyin bắt đăng nhập hoặc captcha, xử lý trong cửa sổ Chrome hiện ra rồi bấm tiếp tục.
2. **Ghép video + watermark:** chọn thư mục video nguồn, đặt thời lượng, watermark chữ hoặc logo PNG (có nút *Tạo logo Nimo Kids*). Khung **Chữ trong video** gồm:
   - *Che phụ đề cũ* (làm mờ hoặc hộp đen), *Tự dò vị trí chữ Trung*, *Xem thử 1 khung hình*;
   - *Chèn phụ đề tiếng Việt* từ file SRT;
   - *Thẻ chữ / chữ tiêu đề*: **Dò chữ** → dịch file `.titles.srt` thành `tên_video.titles.vi.srt` → ghép video, tool tự thay chữ.
3. **Phụ đề SRT:** chọn thư mục hoặc file video, chọn model Whisper (có GPU NVIDIA thì chạy nhanh) → tạo phụ đề.

Nhật ký có màu: đỏ = lỗi, xanh lá = xong, cam = cảnh báo, xanh dương = đang làm. Nút **Dừng** dừng việc đang chạy.

## 3. Bản web (Docker trên server)

### Cài đặt
```bash
cp .env.example .env           # sửa DATA_PATH, WHISPER_MODEL, giới hạn CPU/RAM
mkdir -p /srv/douyin-tool/data # đúng với DATA_PATH
docker compose build           # lần đầu lâu (tải Chromium, image khoảng 2.5GB)
docker compose up -d
docker compose logs -f web
```
Kiểm tra: mở `http://127.0.0.1:8600/health`. Truy cập từ ngoài qua Cloudflare Tunnel: service = `http://douyin-tool-web:8600` (cloudflared cùng network `douyin-tool-net`) hoặc `http://127.0.0.1:8600` (cloudflared trên host).

### Cập nhật phiên bản
```bash
git pull   # hoặc chép mã mới lên server
docker compose build && docker compose up -d
```
Dữ liệu nằm ở `DATA_PATH` nên không mất khi build lại.

### Cách dùng trên trình duyệt
Bản web hiện có 3 tab: Tải kênh Douyin, Ghép video + watermark, Phụ đề SRT. Khi Douyin bắt đăng nhập, bấm *Mở màn hình Chrome* (noVNC), xử lý xong bấm *Tiếp tục*; đăng nhập được lưu ở `browser_profile/`.

Lưu ý:
- Server không có CUDA nên Whisper chạy CPU, chậm. Dùng model `small` hoặc `medium`.
- Mỗi lúc chỉ chạy **một** việc nặng.
- Các tính năng mới của lõi 2.8–2.9 (che vùng, phụ đề Việt, dò chữ, thẻ chữ) **chưa có giao diện trên web**; hiện chỉ dùng được ở bản máy tính.

## 4. Quy tắc phát triển

1. **Nghiệp vụ chỉ viết trong `nimokids_core/`.** `desktop/` và `web/` chỉ lo giao diện: thu thập lựa chọn, gọi hàm lõi, hiển thị kết quả. Không chép logic sang giao diện, và lõi không được import Tkinter hay FastAPI.
2. **Hợp đồng gọi hàm:** `fn(cfg, log, prog, stop[, wait_user])`. `cfg` là dict cấu hình, `log(msg)` ghi nhật ký, `prog(value, max)` báo tiến độ, `stop` là `threading.Event` (bật thì ném `Stopped`).
3. **Phiên bản** (SemVer) chỉ có một số: `nimokids_core/__init__.py` → `__version__`.
   - MAJOR: đổi cách dùng cũ · MINOR: thêm tính năng · PATCH: sửa lỗi.
4. **Phát hành:** tăng `__version__` → thêm mục lên đầu `docs/CHANGELOG.md` (nhóm Thêm / Thay đổi / Sửa lỗi / Bỏ, ghi rõ [Lõi] / [Máy tính] / [Web]) → đóng zip `NimoKidsTool_vX.Y.Z.zip` cho bản máy tính và build image Docker cùng tag cho bản web.
5. Giao diện, nhật ký, thông báo lỗi bằng **tiếng Việt**.

## 5. Dữ liệu và nơi lưu
- Máy tính: `%LOCALAPPDATA%\NimoKidsTool` (profile Chrome, model Whisper, cài đặt).
- Server: `NIMOKIDS_DATA_DIR` → volume `${DATA_PATH}:/data` gồm `media/`, `models/`, `browser_profile/`, `app/`.
- Không commit `.env`, thư mục dữ liệu, file zip và `nimokids_error.log` (đã có trong `.gitignore`).

## 6. Xử lý sự cố nhanh
| Triệu chứng | Cách xử lý |
|---|---|
| Không mở được bản máy tính | Xem `desktop\nimokids_error.log`; bấm lại file `.bat` |
| Ghép video báo thiếu ffmpeg | `winget install Gyan.FFmpeg`, mở lại tool |
| Danh sách video ít hơn số kênh báo | Có thể do video ẩn, riêng tư hoặc đã gỡ |
| Douyin bắt đăng nhập/captcha (web) | Dùng *Mở màn hình Chrome* rồi *Tiếp tục* |
| Whisper quá chậm trên server | Đổi sang model `small`, hoặc phụ đề ở máy có GPU |
| Chữ tiêu đề dịch bị lệch | Giữ nguyên số dòng trong file `.titles.vi.srt` để ghép theo thứ tự |
