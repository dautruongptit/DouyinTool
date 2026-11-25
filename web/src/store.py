"""Lưu cài đặt và trạng thái nhẹ của bản web vào file JSON trong /data/app.
(Chưa cần SQLite: 1 người dùng, dữ liệu nhỏ. Có thể nâng cấp sau nếu cần lịch sử job.)"""
import json
from pathlib import Path

from . import config


def load_settings() -> dict:
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        config.SETTINGS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def update_settings(**kw) -> None:
    s = load_settings()
    s.update({k: v for k, v in kw.items() if v is not None})
    save_settings(s)


def list_media_folders() -> list:
    """Các thư mục con trong /data/media (mỗi kênh một thư mục)."""
    try:
        return sorted(p.name for p in config.MEDIA_DIR.iterdir() if p.is_dir())
    except Exception:
        return []


def safe_media_path(rel: str) -> Path:
    """Ghép đường dẫn tương đối vào MEDIA_DIR, chặn thoát ra ngoài (path traversal)."""
    base = config.MEDIA_DIR.resolve()
    p = (base / (rel or "")).resolve()
    if base != p and base not in p.parents:
        raise ValueError("Đường dẫn không hợp lệ.")
    return p
