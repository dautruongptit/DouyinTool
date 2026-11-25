# Douyin Tool — bản web của Nimo Kids Tool (server Ubuntu, không CUDA)
# Build context = thư mục gốc repo (để COPY được cả nimokids_core/ và web/).
#   docker compose build   (xem docker-compose.yml)
#
# Ghi chú: không dùng multi-stage như quy chuẩn Spring Boot, vì runtime vẫn cần
# đủ thư viện hệ thống của Chromium + ffmpeg + Xvfb; tách stage không giảm được image.
# Vẫn giữ nguyên tắc quan trọng nhất của quy chuẩn: chạy bằng user không phải root.

# Python 3.12: rapidocr-onnxruntime chưa có bản cho 3.13
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

# Gói hệ thống:
#   ffmpeg        : ghép video + đọc âm thanh cho Whisper
#   fonts-dejavu  : font cho watermark chữ (drawtext)
#   xvfb, x11vnc  : màn hình ảo + VNC để xem Chromium khi cần đăng nhập/giải captcha
#   x11-utils     : xdpyinfo (chờ Xvfb sẵn sàng)
#   git, curl     : tải noVNC, healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fonts-dejavu-core xvfb x11vnc x11-utils git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Thư viện Python
COPY web/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Chromium cho Playwright + thư viện hệ thống đi kèm
RUN playwright install --with-deps chromium

# noVNC (trang xem màn hình Chromium ngay trên web)
RUN git clone --depth 1 https://github.com/novnc/noVNC /opt/novnc

# Mã nguồn: lõi nghiệp vụ dùng chung + bản web (import trực tiếp, KHÔNG chép code)
COPY nimokids_core/ /app/nimokids_core/
COPY web/src/ /app/web/
COPY web/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# User không phải root; tạo sẵn /data và cấp quyền các thư mục cần ghi
RUN addgroup --gid 1001 appgroup \
    && adduser --disabled-password --gecos "" --uid 1001 --gid 1001 appuser \
    && mkdir -p /data /ms-playwright \
    && chown -R appuser:appgroup /app /data /ms-playwright /opt/novnc
USER appuser

EXPOSE 8600
ENTRYPOINT ["/app/entrypoint.sh"]
