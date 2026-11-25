"""
nimokids_core - lõi nghiệp vụ dùng chung của Nimo Kids Tool.

Dùng chung cho:
  - bản máy tính:  nimokids_tool.py (giao diện Tkinter, chạy GPU NVIDIA)
  - bản web:       chạy trên server Ubuntu (Docker), import cùng gói này

QUY TẮC: mọi thay đổi nghiệp vụ chỉ sửa ở đây, cả hai bản tự nhận theo.
__version__ là số phiên bản DUY NHẤT của cả hai bản (Semantic Versioning, xem docs/CHANGELOG.md).
Các hàm nhận callback log(msg), prog(value, max) và stop (threading.Event) nên không phụ thuộc giao diện.
"""
__version__ = "2.10.0"

from .common import Stopped  # noqa: F401
