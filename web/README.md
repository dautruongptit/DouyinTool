# Douyin Tool — bản web (server Ubuntu)

Bản web của Nimo Kids Tool, chạy trong Docker trên server ZBook. Dùng chung lõi nghiệp vụ
`nimokids_core` với bản desktop (không chép code), cùng số phiên bản.

## Kiến trúc
- **Một container** (`douyin-tool-web`): FastAPI phục vụ giao diện + REST API + job nền + proxy noVNC.
- Trong container còn chạy **Xvfb** (màn hình ảo) → **Chromium** (Playwright) → **x11vnc**; FastAPI bắc cầu
  WebSocket `/websockify` sang x11vnc để xem màn Chrome ngay trên web khi Douyin bắt đăng nhập/captcha.
- Chỉ mở **một cổng 8600** (chỉ nghe `127.0.0.1`) → Cloudflare Tunnel trỏ vào.
- Một volume `${DATA_PATH}:/data` chứa: `media/`, `models/`, `browser_profile/`, `app/`.

## Quy chuẩn hạ tầng
| Mục | Giá trị |
|---|---|
| Mã dự án (PP) | 86 |
| Cổng web | 8600 (Cloudflare Tunnel) |
| Redis DB | 6 (chưa dùng) |
| Container / image | `douyin-tool-web` / `douyin-tool-web:latest` |
| Network | `douyin-tool-net` |

## Cài đặt trên server
```bash
# Trong thư mục gốc repo DouyinTool (có nimokids_core/, desktop/ và web/)
cp .env.example .env            # sửa DATA_PATH, WHISPER_MODEL nếu cần
mkdir -p /srv/douyin-tool/data  # hoặc DATA_PATH bạn chọn
docker compose build            # lần đầu lâu: tải Chromium + thư viện (~2.5GB image)
docker compose up -d
docker compose logs -f web
```

## Cloudflare Tunnel
Trỏ ingress của tunnel vào web app (có Zero Trust Access bảo vệ):
- Nếu `cloudflared` chạy container cùng server: thêm nó vào network `douyin-tool-net`, service = `http://douyin-tool-web:8600`.
- Nếu `cloudflared` chạy trên host: service = `http://127.0.0.1:8600`.

## Cách dùng (trên trình duyệt)
1. **Tải kênh Douyin:** dán link kênh → *Lấy danh sách video*. Nếu Douyin bắt đăng nhập/captcha,
   bấm *Mở màn hình Chrome* (noVNC), xử lý xong bấm *Tiếp tục*. Tích chọn video → *Tải video đã chọn*.
   Profile đăng nhập lưu ở `browser_profile/`, lần sau không phải làm lại.
2. **Ghép video + watermark:** chọn thư mục nguồn, đặt thời lượng/khung hình/watermark → *Render video tổng*.
3. **Phụ đề SRT:** chọn thư mục/file, chọn model (medium khuyên dùng trên CPU) → *Tạo phụ đề SRT*.

## Lưu ý
- Server không có CUDA → Whisper chạy CPU, chậm. Dùng `small`/`medium`.
- Mỗi lúc chỉ chạy **một** việc nặng (tải / ghép / phụ đề) để không nghẽn ZBook.
- x11vnc dùng `-nopw` nhưng chỉ nghe localhost và cả web nằm sau Cloudflare Access.
