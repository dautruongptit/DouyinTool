#!/usr/bin/env bash
# Khởi động màn hình ảo + VNC rồi chạy web app.
set -e

: "${APP_PORT:=8600}"
: "${VNC_PORT:=5900}"
export DISPLAY="${DISPLAY:-:99}"

echo "[entrypoint] Khởi động Xvfb trên $DISPLAY ..."
Xvfb "$DISPLAY" -screen 0 1280x900x24 -nolisten tcp &
# Chờ Xvfb sẵn sàng (tối đa ~9 giây)
for _ in $(seq 1 30); do
  if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then break; fi
  sleep 0.3
done

echo "[entrypoint] Khởi động x11vnc trên cổng $VNC_PORT (chỉ localhost) ..."
# -localhost: chỉ nghe 127.0.0.1; FastAPI bắc cầu WebSocket /websockify vào đây.
# -nopw: không mật khẩu VNC — an toàn vì chỉ nghe localhost và cả web nằm sau Cloudflare Access.
x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -localhost -forever -shared \
       -nopw -quiet -noxdamage -bg >/dev/null 2>&1

echo "[entrypoint] Chạy web app trên cổng $APP_PORT ..."
exec uvicorn web.main:app --host 0.0.0.0 --port "$APP_PORT"
