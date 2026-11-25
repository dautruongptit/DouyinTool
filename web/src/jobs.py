"""Quản lý job nền cho bản web.

Server ZBook yếu, nên CHỈ cho 1 job nặng chạy tại một thời điểm (tải / ghép / phụ đề).
Mỗi job nhận hợp đồng callback của nimokids_core: log(msg), prog(value, max), stop (Event).
Giao diện hỏi trạng thái qua /api/job (polling) và điều khiển qua /api/job/stop, /api/job/continue.
"""
import threading
import time
import traceback
from datetime import datetime

from nimokids_core import Stopped


class Job:
    def __init__(self, name: str):
        self.name = name
        self.status = "running"          # running | needs_login | done | error | stopped
        self.logs = []                   # list[str]
        self.prog_val = 0
        self.prog_max = 1
        self.result = None
        self.error = None
        self.started = time.time()
        self.ended = None
        self.stop = threading.Event()
        self._cont = threading.Event()   # người dùng bấm "Tiếp tục" sau khi đăng nhập

    # --- callback truyền cho nimokids_core ---
    def log(self, msg):
        self.logs.append(f"{datetime.now():%H:%M:%S}  {msg}")
        if len(self.logs) > 20000:       # chặn phình bộ nhớ
            del self.logs[:5000]

    def prog(self, value, mx):
        self.prog_val, self.prog_max = value, max(1, mx)

    def wait_user(self, ready=None):
        """collect_list gọi khi Douyin bắt đăng nhập/captcha.
        Chờ đến khi: người dùng bấm Tiếp tục, hoặc danh sách video đã xuất hiện (ready()), hoặc bấm Dừng."""
        self.status = "needs_login"
        self.log("Douyin cần đăng nhập hoặc giải captcha. Mở 'Màn hình Chrome' để xử lý, "
                 "rồi bấm 'Tôi đã đăng nhập xong — Tiếp tục'.")
        while not self._cont.is_set():
            if self.stop.is_set():
                break
            if ready:
                try:
                    if ready():
                        break
                except Exception:
                    pass
            time.sleep(0.3)
        self._cont.clear()
        if not self.stop.is_set():
            self.status = "running"

    def do_continue(self):
        self._cont.set()

    @property
    def progress_pct(self) -> float:
        return round(100 * self.prog_val / max(1, self.prog_max), 1)

    def snapshot(self, since: int = 0) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "busy": self.status in ("running", "needs_login"),
            "progress": self.progress_pct,
            "logs": self.logs[since:],
            "log_cursor": len(self.logs),
            "result": self.result,
            "error": self.error,
            "elapsed": int((self.ended or time.time()) - self.started),
        }


class JobManager:
    def __init__(self):
        self.current = None               # Job | None
        self._lock = threading.Lock()
        # Dữ liệu dùng lại giữa các bước (giữ trong bộ nhớ):
        self.last_list_items = []         # danh sách video đã lấy (để hiển thị + chọn)
        self.last_result = None           # kết quả collect_list đầy đủ (kèm cookies, ua) để tải
        self.last_channel_url = None
        self.last_out = None              # thư mục media của lần lấy danh sách gần nhất

    def busy(self) -> bool:
        return self.current is not None and self.current.status in ("running", "needs_login")

    def start(self, name: str, fn):
        """fn(job) -> result. Trả Job nếu bắt đầu được, None nếu đang bận."""
        with self._lock:
            if self.busy():
                return None
            job = Job(name)
            self.current = job

        def runner():
            job.log(f"--- Bắt đầu: {datetime.now():%H:%M:%S %d/%m/%Y} ---")
            try:
                job.result = fn(job)
                job.status = "done"
            except Stopped:
                job.status = "stopped"
                job.log("Đã dừng theo yêu cầu.")
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                job.log("LỖI: " + str(e))
                job.log(traceback.format_exc())
            finally:
                job.ended = time.time()
                from nimokids_core.common import fmt_duration
                job.log(f"--- Kết thúc: {datetime.now():%H:%M:%S}  |  Tổng thời gian: "
                        f"{fmt_duration(job.ended - job.started)} ---")

        threading.Thread(target=runner, daemon=True).start()
        return job


manager = JobManager()
