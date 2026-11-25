# Kiến trúc Nimo Kids Tool: 2 bản, 1 lõi nghiệp vụ

```
DouyinTool/
├─ nimokids_core/          LÕI NGHIỆP VỤ DÙNG CHUNG (không có giao diện)
│  ├─ __init__.py          __version__: số phiên bản duy nhất của cả 2 bản
│  ├─ common.py            tiện ích: ffmpeg/ffprobe, thư mục dữ liệu, định dạng thời gian
│  ├─ douyin.py            nhận dạng link, lấy danh sách (Chrome thật), tải video + thumbnail
│  ├─ compile.py           ghép video + watermark, che chữ, phụ đề Việt
│  ├─ titles.py            dò + dịch chữ tiêu đề trong video (OCR)
│  └─ subtitles.py         Whisper → SRT (GPU nếu có), tải model, ngắt câu
├─ desktop/                BẢN MÁY TÍNH (Windows, GPU RTX)
│  ├─ nimokids_tool.py     giao diện Tkinter
│  ├─ Mo Nimo Kids Tool.bat  cài lần đầu + tạo icon Desktop
│  └─ nimokids.ico, nimokids_logo.png, DOC_TRUOC.txt
├─ web/                    BẢN SERVER (Docker trên Ubuntu): Dockerfile, entrypoint.sh, src/
├─ docs/                   ARCHITECTURE.md (file này), CHANGELOG.md (lịch sử chung 2 bản)
├─ docker-compose.yml, .env.example   triển khai bản web (build context = thư mục gốc)
└─ CLAUDE.md, README.md    hướng dẫn cho Claude Code / người dùng
```

## Quy tắc
1. **Nghiệp vụ chỉ viết trong `nimokids_core`.**
   - Hai giao diện (Tkinter và web) chỉ thu thập lựa chọn của người dùng, gọi hàm trong lõi và hiển thị kết quả.
   - Không được chép code nghiệp vụ sang giao diện.
2. **Một số phiên bản cho cả hai bản:** `nimokids_core.__version__`.
   - Lõi thay đổi: tăng phiên bản và cập nhật cả hai giao diện nếu cần (ví dụ thêm ô lựa chọn mới).
   - Chỉ sửa giao diện của một bản: vẫn tăng PATCH hoặc MINOR, và ghi rõ trong CHANGELOG là bản nào (Máy tính / Web).
3. **Hợp đồng gọi hàm.** Mọi tác vụ dài đều nhận:
   - `cfg`: dict cấu hình.
   - `log(msg)`: ghi một dòng nhật ký.
   - `prog(value, max)`: báo tiến độ.
   - `stop`: `threading.Event`; khi được bật, hàm dừng bằng cách ném `Stopped`.

   Bản máy tính nối các callback này vào khung nhật ký và thanh tiến độ. Bản web nối vào job và gửi tiến độ về trình duyệt qua SSE hoặc WebSocket.
4. **Thư mục dữ liệu** (Chrome profile, model Whisper, cài đặt) lấy từ `common.app_data_dir()`:
   - Windows: `%LOCALAPPDATA%\NimoKidsTool`.
   - Server: đặt biến môi trường `NIMOKIDS_DATA_DIR` trỏ vào volume Docker.
5. **Phát hành:**
   - Tăng `__version__`.
   - Thêm mục vào `CHANGELOG.md`, ghi rõ ảnh hưởng tới [Lõi] / [Máy tính] / [Web].
   - Đóng gói `NimoKidsTool_vX.Y.Z.zip` cho bản máy tính, build image Docker cùng tag `X.Y.Z` cho bản web.
6. **Phần chạy được ở đâu:**

| Nghiệp vụ | Máy tính (RTX 3060) | Server (ZBook, không CUDA) |
|---|---|---|
| Tải Douyin | Có | Có (Chrome trong Docker + Xvfb; đăng nhập qua noVNC hoặc cookie) |
| Ghép video | Có | Có (CPU, chậm hơn) |
| Phụ đề Whisper | Có, nhanh (GPU) | Có nhưng chậm (CPU int8, nên dùng model small/medium) |
