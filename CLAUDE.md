# CLAUDE.md — Hướng dẫn cho Claude Code (đọc trước khi làm bất cứ việc gì)

> File này Claude Code tự đọc đầu mỗi phiên. Giữ cho ngắn gọn và đúng thực tế.

## Dự án này là gì
**Douyin Tool** (*Nimo Kids Tool*) — **một repo duy nhất cho cả bản máy tính và bản web**. Pipeline: lấy video hoạt hình từ kênh Douyin
(chỉ kênh đã được tác giả đồng ý) → ghép thành video dài có watermark "nimokids" → tạo phụ đề SRT →
đăng lên kênh YouTube **Nimo Kids** (nội dung trẻ em).

Repo này gồm **2 giao diện dùng chung 1 lõi**:
- **Bản máy tính** (Tkinter, Windows, GPU RTX): thư mục `desktop/` (`nimokids_tool.py` + `Mo Nimo Kids Tool.bat`).
- **Bản web** (Docker, Ubuntu, CPU): thư mục `web/`.
Thư mục `NimoKidsTool` cũ (repo gốc) đã bỏ; **từ nay chỉ phát triển ở đây**.

## Người dùng
- Truong, lập trình viên backend Java (Spring Boot). **Luôn trả lời bằng tiếng Việt.**
- Thích công cụ bấm-1-click, giao diện/nhật ký/thông báo lỗi bằng tiếng Việt, dễ hiểu với người không gõ lệnh.

## Quy tắc QUAN TRỌNG NHẤT: lõi dùng chung
- **Mọi nghiệp vụ nằm trong gói `nimokids_core/`** (`douyin.py`, `compile.py`, `subtitles.py`, `titles.py`, `common.py`).
  Hai giao diện (Tkinter và web) chỉ **import** và gọi, **KHÔNG chép / viết lại nghiệp vụ** trong `desktop/` hay `web/`.
- `nimokids_core/` ở đây là **nguồn sự thật duy nhất** (không còn bản copy nào khác): sửa thẳng ở đây,
  cả bản máy tính lẫn bản web tự nhận theo. Dockerfile COPY thư mục này vào image.
- **Một số phiên bản cho cả hai bản:** `nimokids_core/__init__.py` → `__version__` (hiện 2.9.1).
  Bản web đọc version này động (hiện trên tiêu đề trang + API /health).
- Hợp đồng gọi hàm (mọi tác vụ dài): `fn(cfg, log, prog, stop[, wait_user])`
  - `cfg`: dict cấu hình · `log(msg)`: ghi nhật ký · `prog(value, max)`: tiến độ · `stop`: threading.Event (bật → ném `Stopped`).
  - `douyin.collect_list(cfg, log, prog, wait_user, stop)` → dict(items, cookies, ua, total)
  - `douyin.download_items(cfg, res, log, prog, stop)` · `compile.run_compile(cfg, log, prog, stop, dry=)` · `subtitles.run_transcribe(cfg, log, prog, stop)`

## Định danh hạ tầng (theo quy chuẩn Docker riêng của Truong)
| Mục | Giá trị |
|---|---|
| Tên dự án (PP) | **douyin-tool**, mã **86** |
| Cổng web | **8600** (bind `127.0.0.1`, Cloudflare Tunnel trỏ vào) |
| Redis DB | 6 (để dành, chưa dùng) |
| Container / image | `douyin-tool-web` / `douyin-tool-web:latest` |
| Network | `douyin-tool-net` |
> ⚠️ KHÔNG dùng mã 85 / tên "nimokids" — đó là dự án **NimoKids-web** khác.

## Kiến trúc (một container)
FastAPI (uvicorn :8600) phục vụ **UI + REST API + job nền + proxy noVNC** trong cùng container.
Cùng container còn chạy: **Xvfb :99 → Chromium (Playwright) → x11vnc :5900**; FastAPI bắc cầu
WebSocket `/websockify` sang x11vnc để xem màn Chromium trên web khi Douyin bắt đăng nhập/captcha.
Một volume `${DATA_PATH}:/data` chứa `media/` `models/` `browser_profile/` `app/`.
Server ZBook **không có CUDA** → Whisper chạy CPU (chậm); mỗi lúc chỉ chạy **1 job nặng**.

## Bản đồ file
```
nimokids_core/          # LÕI DÙNG CHUNG — nghiệp vụ Douyin/ghép/phụ đề/dò chữ (nguồn duy nhất)
desktop/                # BẢN MÁY TÍNH: nimokids_tool.py (Tkinter), Mo Nimo Kids Tool.bat, ico/logo, DOC_TRUOC.txt
docs/                   # ARCHITECTURE.md + CHANGELOG.md (mục [Lõi]/[Máy tính]/[Web])
web/                    # BẢN WEB
  Dockerfile            # python:3.12-slim + ffmpeg + Chromium + Xvfb/x11vnc + noVNC, chạy non-root
  entrypoint.sh         # bật Xvfb + x11vnc rồi chạy uvicorn (GIỮ xuống dòng LF)
  requirements.txt
  src/
    main.py             # FastAPI: routes + proxy noVNC /websockify
    config.py           # đường dẫn, đọc NIMOKIDS_DATA_DIR, model Whisper mặc định
    jobs.py             # JobManager: 1 job nặng/lúc, log + % + Dừng + wait_user(needs_login)
    store.py            # settings.json + liệt kê thư mục media (JSON, chưa cần SQLite)
    webui/templates/index.html, webui/static/{app.js,styles.css}
docker-compose.yml  .env.example  .dockerignore  .gitignore  .gitattributes
```

## Chạy / deploy
```bash
cp .env.example .env            # sửa DATA_PATH, WHISPER_MODEL
mkdir -p /srv/douyin-tool/data
docker compose build            # lần đầu lâu (tải Chromium, image ~2.5GB)
docker compose up -d
docker compose logs -f web
```
Cloudflare Tunnel: ingress → `http://douyin-tool-web:8600` (nếu cloudflared cùng network) hoặc `http://127.0.0.1:8600`.

## Bài học kỹ thuật (đừng lặp lỗi cũ)
- Lấy danh sách Douyin bằng cách **bắt phản hồi `aweme/post`** trong Chrome thật, không gọi API trực tiếp (Douyin đổi chữ ký liên tục).
- Trên server: Playwright dùng **Chromium bundled** (`channel=None`), cửa sổ **hiện trên Xvfb** (`hidden=False`) để noVNC xem được. Chrome không được "ngủ" khi bị che.
- Thumbnail lấy `cover_original_scale`/`cover`, **không** lấy `origin_cover` (khung hình cắt từ video).
- Whisper: **tắt VAD**, đọc âm thanh bằng **ffmpeg** (không dùng `av`), không ép sai ngôn ngữ / không `initial_prompt`, lọc câu "bịa".
- Font Windows có dấu `:` làm hỏng `drawtext` → chép font sang thư mục tạm tên đơn giản (đã xử lý trong core).

## Quy tắc khi sửa
- Sửa nghiệp vụ → sửa trực tiếp ở `nimokids_core/` (một nơi). Tăng `__version__` theo SemVer, ghi `docs/CHANGELOG.md` (mục `[Web]` / `[Lõi]` / `[Máy tính]`).
- Giao diện/nhật ký/lỗi bằng tiếng Việt. Chạy thử trước khi gửi, nói rõ phần nào đã thử/chưa thử.

## Việc còn mở
- Bản máy tính (`desktop/nimokids_tool.py`) đã có giao diện cho che vùng, phụ đề Việt, tự dò chữ Trung, thẻ chữ (v2.8–2.9); **bản web chưa có**:
- Chưa phơi UI cho tính năng **che vùng (cover)** + **chèn phụ đề tiếng Việt (vsub)** mà `compile.run_compile` đã hỗ trợ (cfg["cover"], cfg["vsub"]).
- Chưa đo tốc độ ffmpeg/Whisper CPU trên ZBook thật; chưa test noVNC + đăng nhập Douyin end-to-end.
