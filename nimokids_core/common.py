"""Tiện ích dùng chung: ffmpeg/ffprobe, thư mục dữ liệu, định dạng thời gian.
Không chứa giao diện: dùng chung cho bản máy tính (Tkinter) và bản web trên server."""
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path



NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

class Stopped(Exception):
    pass

def need(tool):
    if not shutil.which(tool):
        raise RuntimeError(
            f"Không tìm thấy '{tool}'. Cài ffmpeg (Windows: winget install Gyan.FFmpeg) rồi mở lại ứng dụng.")

def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        return None
    try:
        j = json.loads(r.stdout)
        dur = float(j["format"]["duration"])
        has_a = any(s.get("codec_type") == "audio" for s in j.get("streams", []))
        has_v = any(s.get("codec_type") == "video" for s in j.get("streams", []))
        return (dur, has_a) if has_v and dur > 0 else None
    except Exception:
        return None

def default_font():
    cands = {
        "Windows": ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"],
        "Darwin": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"],
    }.get(platform.system(), ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"])
    for c in cands:
        if Path(c).exists():
            return c
    return None

def app_data_dir():
    """Thư mục dữ liệu riêng của tool (Chrome riêng, lưu đăng nhập) - không nằm trong thư mục video."""
    # Server (Docker) đặt NIMOKIDS_DATA_DIR để chọn thư mục dữ liệu riêng (volume)
    if os.environ.get("NIMOKIDS_DATA_DIR"):
        d = Path(os.environ["NIMOKIDS_DATA_DIR"])
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        d = Path(base) / "NimoKidsTool"
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_png(src, dst):
    """Lưu ảnh thành PNG, giữ nguyên kích thước và nội dung gốc."""
    from PIL import Image
    with Image.open(src) as im:
        im.load()
        im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(dst, "PNG")
    return dst

def safe(s, n=60):
    s = re.sub(r'[\\/:*?"<>|\r\n#]+', " ", s or "").strip()
    return s[:n].strip() or "video"

def fmt_duration(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s_ = divmod(r, 60)
    if h:
        return f"{h} giờ {m} phút {s_} giây"
    if m:
        return f"{m} phút {s_} giây"
    return f"{s_} giây"

def fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"
