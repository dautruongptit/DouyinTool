"""Cấu hình bản web: đường dẫn, thư mục dữ liệu, giá trị mặc định.
Thư mục dữ liệu lấy từ nimokids_core (đọc biến môi trường NIMOKIDS_DATA_DIR trên server)."""
import os
from pathlib import Path

from nimokids_core import common

# Thư mục mã nguồn bản web (chứa webui/templates, webui/static)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "webui" / "templates"
STATIC_DIR = BASE_DIR / "webui" / "static"

# Trang noVNC (được git clone vào image trong Dockerfile)
NOVNC_DIR = Path(os.environ.get("NOVNC_DIR", "/opt/novnc"))

# Thư mục dữ liệu (volume Docker /data). Mọi thứ nằm trong đây:
DATA_DIR = common.app_data_dir()                 # = /data trên server
MEDIA_DIR = DATA_DIR / "media"                   # video nguồn, thumbnail, video tổng
BROWSER_PROFILE = DATA_DIR / "browser_profile"   # Chrome/Chromium profile (đăng nhập Douyin)
APP_DIR = DATA_DIR / "app"                        # cài đặt, log của bản web
for _d in (MEDIA_DIR, APP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = APP_DIR / "settings.json"

# Cổng VNC nội bộ mà x11vnc đang nghe (entrypoint.sh mở sẵn)
VNC_HOST = "127.0.0.1"
VNC_PORT = int(os.environ.get("VNC_PORT", "5900"))

# Model Whisper mặc định cho tab Phụ đề (server không CUDA)
DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")

# Trên server luôn chạy Chromium bản Playwright (không có "chrome" kênh hệ thống),
# cửa sổ hiện trên màn ảo Xvfb (không đặt ra ngoài màn hình) để noVNC xem được.
# Mặc định dùng Google Chrome thật (cài trong image) vì Chromium bundled bị Douyin trả danh sách rỗng.
# Đặt BROWSER_CHANNEL=chromium để dùng Chromium bundled.
BROWSER_CHANNEL = None if os.environ.get("BROWSER_CHANNEL", "chrome") == "chromium" else os.environ.get("BROWSER_CHANNEL", "chrome")
BROWSER_HIDDEN = False   # False = cửa sổ nằm trên màn ảo, noVNC thấy được
