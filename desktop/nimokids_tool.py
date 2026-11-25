#!/usr/bin/env python3
"""
Nimo Kids Tool - bản máy tính (giao diện Tkinter).
Toàn bộ nghiệp vụ nằm trong gói nimokids_core (dùng chung với bản web trên server);
file này chỉ chứa giao diện. Số phiên bản: nimokids_core.__version__ (xem docs/CHANGELOG.md).

Chạy: bấm icon "Nimo Kids Tool" ngoài Desktop, hoặc  py -3.13 nimokids_tool.py
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import queue
from datetime import datetime
from pathlib import Path

# Chạy bằng pythonw (icon Desktop) thì không có cửa sổ lệnh: sys.stdout/stderr là None,
# thư viện nào in tiến độ (tải model Whisper...) sẽ lỗi -> chuyển vào "hố đen".
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Lõi dùng chung nằm ở thư mục gốc repo (cha của desktop/): thêm vào đường dẫn import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nimokids_core import (__version__)
from nimokids_core.common import (Stopped, app_data_dir, fmt_duration, fmt_time)
from nimokids_core.compile import (detect_cn_region, ensure_rapidocr, list_clips, make_logo_png, pick_clips, preview_frame,
                                   run_compile)
from nimokids_core.titles import detect_texts
from nimokids_core.douyin import (collect_list, download_items, is_downloaded, parse_channel_link)
from nimokids_core.subtitles import (SPOKEN_LANGS, VIDEO_EXT, WHISPER_MODELS, has_nvidia, run_transcribe)

DEFAULT_URL = "https://www.douyin.com/user/MS4wLjABAAAAqpNISE46Jp14stf1jE4MoIXaWtQ9Gq-NPmPB5fG7M_Fk7T_aocX0ZDml2SIdaZ09"

DEFAULT_OUT = "E:/MY PRO/Video AI/Download douyin/88951274316"

def settings_file():
    return app_data_dir() / "settings.json"

def load_settings():
    try:
        return json.loads(settings_file().read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_settings(d):
    try:
        settings_file().write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    settings = load_settings()
    root = tk.Tk()
    root.title(f"Nimo Kids Tool v{__version__}")
    style = ttk.Style(root)  # giữ theme mặc định của Windows (giao diện như v2.4)
    BAR_COLOR = "#2f9e44"

    def image_left(layout):
        """Đổi bố cục tiêu đề cột Treeview: ô hình (ô tích) đứng TRƯỚC chữ."""
        out = []
        for name, opts in layout:
            opts = dict(opts)
            if name.endswith("image"):
                opts["side"] = "left"
            if "children" in opts:
                opts["children"] = image_left(opts["children"])
            out.append((name, opts))
        return out

    try:
        style.layout("Treeview.Heading", image_left(style.layout("Treeview.Heading")))
    except tk.TclError:
        pass
    root.geometry("900x1000")
    root.minsize(760, 680)

    q = queue.Queue()
    stop = threading.Event()
    user_go = threading.Event()
    state = {"busy": False}

    # ---- hàng đợi thông điệp từ thread nền về giao diện
    def log(msg):
        q.put(("log", (time.strftime("%H:%M:%S"), msg)))

    def prog(v, mx):
        q.put(("prog", (v, mx)))

    def log_level(msg):
        m = msg.lower()
        if m.startswith("lỗi") or "thất bại" in m:
            return "err"
        if msg.startswith("---") or msg.startswith("==="):
            return "head"
        if any(k in m for k in ("xong", "hoàn tất", "thành công", "đã tải", "đã lưu", "tuyệt")):
            return "ok"
        if any(k in m for k in ("chưa", "thiếu", "bỏ qua", "cảnh báo", "chờ", "đăng nhập", "captcha")):
            return "warn"
        if any(k in m for k in ("đang", "bắt đầu", "mở", "nạp", "tải")):
            return "info"
        return "norm"

    def pump():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    ts, msg = val
                    txt.configure(state="normal")
                    txt.insert("end", f"[{ts}] ", "time")
                    txt.insert("end", msg + "\n", log_level(msg))
                    txt.see("end")
                    txt.configure(state="disabled")
                elif kind == "prog":
                    v, mx = val
                    set_bar(v, mx)
                elif kind == "done":
                    set_busy(False)
                    go_btn.configure(state="disabled")
                    if val:
                        messagebox.showinfo("Nimo Kids Tool", val)
                elif kind == "fail":
                    set_busy(False)
                    go_btn.configure(state="disabled")
                    log("LỖI: " + val)
                    messagebox.showerror("Có lỗi", val)
                elif kind == "waiting":
                    go_btn.configure(state="normal")
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        root.after(100, pump)

    all_buttons = []

    def set_busy(b):
        state["busy"] = b
        for btn in all_buttons:
            btn.configure(state="disabled" if b else "normal")
        stop_btn.configure(state="normal" if b else "disabled")
        try:
            dl_btn.configure(state="disabled" if b or not listed["res"] or not checked else "normal")
        except NameError:
            pass
        if not b:
            end_bar()  # xong việc: giữ nguyên % cuối, tắt vạch chạy và đồng hồ

    def start_worker(fn, done_msg=None, show_timing=True):
        if state["busy"]:
            return
        stop.clear()
        user_go.clear()
        set_busy(True)
        begin_bar()

        t_start = time.time()
        if show_timing:
            log(f"--- Bắt đầu lúc {datetime.now():%H:%M:%S %d/%m/%Y} ---")

        def timing():
            return (f"Bắt đầu: {datetime.fromtimestamp(t_start):%H:%M:%S}  |  "
                    f"Kết thúc: {datetime.now():%H:%M:%S}  |  "
                    f"Thời gian thực hiện: {fmt_duration(time.time() - t_start)}")

        def target():
            try:
                res = fn()
                msg = done_msg(res) if callable(done_msg) else done_msg
                if show_timing:
                    tm = timing()
                    log("--- " + tm + " ---")
                    q.put(("done", (msg + "\n\n" + tm.replace("  |  ", "\n")) if msg else None))
                else:
                    q.put(("done", msg))
            except Stopped:
                log("Đã dừng." + (" " + timing() if show_timing else ""))
                q.put(("done", None))
            except Exception as e:
                if show_timing:
                    log("--- " + timing() + " ---")
                q.put(("fail", str(e)))

        threading.Thread(target=target, daemon=True).start()

    def row(parent, r, label, widget_factory, span=1):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        w = widget_factory(parent)
        w.grid(row=r, column=1, columnspan=span, sticky="ew", pady=3)
        return w

    def open_path(var_or_path):
        p = var_or_path.get() if hasattr(var_or_path, "get") else var_or_path
        p = Path(str(p).strip() or ".").expanduser()
        try:
            if p.is_file():
                if platform.system() == "Windows":
                    subprocess.Popen(["explorer", "/select,", str(p.resolve())])
                    return
                p = p.parent
            elif not p.exists():
                if p.suffix:  # là đường dẫn file chưa tạo -> mở thư mục chứa nó
                    p = p.parent
                p.mkdir(parents=True, exist_ok=True)
            if platform.system() == "Windows":
                os.startfile(str(p.resolve()))
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            messagebox.showerror("Không mở được", str(e))

    def browse_dir(var):
        d = filedialog.askdirectory(initialdir=var.get() or ".")
        if d:
            var.set(d)

    def browse_file(var, types, save=False):
        f = (filedialog.asksaveasfilename if save else filedialog.askopenfilename)(
            filetypes=types, **({"defaultextension": types[0][1].replace("*", "")} if save else {}))
        if f:
            var.set(f)

    nb = ttk.Notebook(root)
    nb.pack(fill="x", padx=10, pady=(10, 4))

    # ======================= TAB 1: TẢI DOUYIN =======================
    t1 = ttk.Frame(nb, padding=12)
    nb.add(t1, text="1. Tải kênh Douyin")
    t1.columnconfigure(1, weight=1)
    v_url = tk.StringVar(value=settings.get("url", DEFAULT_URL))
    v_out = tk.StringVar(value=settings.get("out", DEFAULT_OUT))
    v_limit = tk.IntVar(value=0)
    v_channel = tk.StringVar(value="chrome")
    v_sleep = tk.DoubleVar(value=2.0)
    v_thumbs = tk.BooleanVar(value=True)
    v_hidden = tk.BooleanVar(value=True)
    listed = {"res": None, "url": None}

    row(t1, 0, "Link kênh Douyin:", lambda p: ttk.Entry(p, textvariable=v_url))
    f = ttk.Frame(t1)
    ttk.Entry(f, textvariable=v_out).pack(side="left", fill="x", expand=True)
    ttk.Button(f, text="Chọn...", command=lambda: browse_dir(v_out)).pack(side="left", padx=(6, 0))
    ttk.Button(f, text="Mở", width=5, command=lambda: open_path(v_out)).pack(side="left", padx=(4, 0))
    ttk.Label(t1, text="Lưu vào thư mục:").grid(row=1, column=0, sticky="w", pady=3)
    f.grid(row=1, column=1, sticky="ew", pady=3)
    f2 = ttk.Frame(t1)
    ttk.Label(f2, text="Số video tối đa (0 = tất cả):").pack(side="left")
    ttk.Spinbox(f2, from_=0, to=9999, width=6, textvariable=v_limit).pack(side="left", padx=6)
    ttk.Label(f2, text="Trình duyệt:").pack(side="left", padx=(12, 0))
    ttk.Combobox(f2, values=["chrome", "msedge"], width=8, textvariable=v_channel,
                 state="readonly").pack(side="left", padx=6)
    ttk.Label(f2, text="Nghỉ giữa video (s):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(f2, from_=0, to=30, increment=0.5, width=5, textvariable=v_sleep).pack(side="left", padx=6)
    f2.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
    ttk.Checkbutton(t1, text="Tải kèm thumbnail PNG (ảnh minh hoạ như trên trang kênh, lưu trong thư mục 'thumbnails')",
                    variable=v_thumbs).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
    ttk.Checkbutton(t1, text="Chạy ẩn Chrome (chỉ hiện ra khi Douyin bắt đăng nhập / captcha)",
                    variable=v_hidden).grid(row=4, column=0, columnspan=2, sticky="w", pady=2)

    def make_cfg(url, short):
        out = v_out.get().strip()
        return dict(url=url, short=short, out=out, profile=str(app_data_dir() / "browser_profile"),
                    channel=v_channel.get(), limit=int(v_limit.get()), sleep=float(v_sleep.get()),
                    thumbs=v_thumbs.get(), hidden=v_hidden.get())

    checked = set()  # iid (= aweme_id) đang được tích

    def box_img(on, partial=False):
        """Vẽ ô tích 16x16 bằng hình (không phụ thuộc font). partial = chọn một phần (dấu gạch)."""
        im = tk.PhotoImage(width=16, height=16)
        im.put("#ffffff", to=(2, 2, 14, 14))
        for i in range(2, 14):
            for x, y in ((i, 2), (i, 13), (2, i), (13, i)):
                im.put("#2b6cb0" if (on or partial) else "#888888", (x, y))
        if partial:
            im.put("#2b6cb0", to=(3, 3, 13, 13))
            im.put("#ffffff", to=(5, 7, 11, 9))
        elif on:
            im.put("#2b6cb0", to=(3, 3, 13, 13))
            for x, y in ((5, 8), (6, 9), (7, 10), (8, 9), (9, 8), (10, 7), (11, 6),
                         (5, 7), (6, 8), (7, 9), (8, 8), (9, 7), (10, 6), (11, 5)):
                im.put("#ffffff", (x, y))
        return im

    IMG_ON, IMG_OFF, IMG_PART = box_img(True), box_img(False), box_img(False, partial=True)

    def update_header():
        n = len(tree.get_children())
        k = len(checked)
        img = IMG_OFF if k == 0 or n == 0 else (IMG_ON if k == n else IMG_PART)
        tree.heading("#0", image=img)

    def header_click():
        n = len(tree.get_children())
        if n:
            check_all(len(checked) < n)  # chưa tích hết -> tích hết; đã tích hết -> bỏ hết

    def refresh_status():
        res = listed["res"]
        if not res:
            return
        update_header()
        n = len(res["items"])
        total = f"/{res['total']}" if res.get("total") else ""
        status.configure(text=f"Đã lấy {n}{total} video  •  Đang chọn {len(checked)} video để tải.",
                         foreground="#0a7a2f")
        if not state["busy"]:
            dl_btn.configure(state="normal" if checked else "disabled")

    def set_checked(iids, value):
        for iid in iids:
            if value:
                checked.add(iid)
            else:
                checked.discard(iid)
            tree.item(iid, image=IMG_ON if value else IMG_OFF)
        refresh_status()

    def fill_list(res):
        tree.delete(*tree.get_children())
        checked.clear()
        out = v_out.get().strip()
        for i, a in enumerate(res["items"], 1):
            d = datetime.fromtimestamp(a.get("create_time", 0)).strftime("%d/%m/%Y")
            done = is_downloaded(out, a)
            iid = a["aweme_id"]
            tree.insert("", "end", iid=iid, image=IMG_OFF,
                        values=(i, d, "Đã tải" if done else "", (a.get("desc") or "").replace("\n", " ")[:120]))
            if not done:
                checked.add(iid)  # mặc định: tích sẵn các video chưa tải
                tree.item(iid, image=IMG_ON)
        refresh_status()

    def on_tree_click(ev):
        if tree.identify_region(ev.x, ev.y) in ("cell", "tree") and tree.identify_column(ev.x) == "#0":
            iid = tree.identify_row(ev.y)
            if iid:
                set_checked([iid], iid not in checked)
                return "break"

    def toggle_selected(_=None):
        sel = tree.selection()
        if sel:
            set_checked(sel, not all(i in checked for i in sel))
        return "break"

    def check_all(value):
        set_checked(tree.get_children(), value)

    def check_not_downloaded():
        out = v_out.get().strip()
        items = {a["aweme_id"]: a for a in (listed["res"] or {}).get("items", [])}
        for iid in tree.get_children():
            done = is_downloaded(out, items[iid])
            tree.set(iid, "state", "Đã tải" if done else "")
            set_checked([iid], not done)

    def do_list():
        url, short = parse_channel_link(v_url.get())
        if url:
            v_url.set(url)
            log(f"Đã nhận dạng link kênh: {url}")
        elif not short:
            if re.search(r"douyin\.com/video/\d+", v_url.get()):
                messagebox.showwarning("Link video", "Đây là link của MỘT video. Bấm vào tên tác giả để vào trang kênh, "
                                       "rồi copy link trang kênh (có dạng douyin.com/user/MS4wLjAB...).")
            else:
                messagebox.showwarning("Không nhận ra link", "Dán link trang kênh Douyin (douyin.com/user/MS4wLjAB...) "
                                       "hoặc link chia sẻ v.douyin.com/...")
            return
        cfg = make_cfg(url, short)
        listed["res"], listed["url"] = None, None
        dl_btn.configure(state="disabled")
        tree.delete(*tree.get_children())
        status.configure(text="Đang lấy danh sách video...", foreground="#666")

        def wait_user(ready=None):
            q.put(("waiting", None))
            while not user_go.is_set():
                if stop.is_set() or (ready and ready()):
                    break
                time.sleep(0.3)
            q.put(("call", lambda: go_btn.configure(state="disabled")))

        def work():
            res = collect_list(cfg, log, prog, wait_user, stop)
            if not res["items"]:
                raise RuntimeError("Không lấy được video nào. Thử bỏ tick 'Chạy ẩn Chrome' rồi lấy lại.")
            listed["res"], listed["url"] = res, cfg["url"]
            q.put(("call", lambda: fill_list(res)))
            return None

        start_worker(work, show_timing=False)

    def do_download():
        res = listed["res"]
        if not res:
            messagebox.showwarning("Chưa có danh sách", "Bấm '1. Lấy danh sách video' trước.")
            return
        url, _ = parse_channel_link(v_url.get())
        if url and url != listed["url"]:
            messagebox.showwarning("Link đã đổi", "Link kênh đã thay đổi, hãy lấy danh sách lại.")
            return
        sel = [a for a in res["items"] if a["aweme_id"] in checked]
        if not sel:
            messagebox.showwarning("Chưa chọn video", "Tích chọn ít nhất 1 video trong danh sách.")
            return
        cfg = make_cfg(listed["url"], None)
        v_cmp_folder.set(cfg["out"])
        res_sel = dict(res, items=sel)

        def work():
            r = download_items(cfg, res_sel, log, prog, stop)
            q.put(("call", check_marks))
            return r

        def check_marks():  # cập nhật cột "Đã tải" sau khi tải xong, giữ nguyên các ô tích
            items = {a["aweme_id"]: a for a in res["items"]}
            for iid in tree.get_children():
                if is_downloaded(cfg["out"], items[iid]):
                    tree.set(iid, "state", "Đã tải")
                    set_checked([iid], False)

        start_worker(work, lambda r: r)

    bf = ttk.Frame(t1)
    bf.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
    b = ttk.Button(bf, text="1. Lấy danh sách video", command=do_list)
    b.pack(side="left")
    all_buttons.append(b)
    ttk.Button(bf, text="Chỉ chọn video chưa tải", command=check_not_downloaded).pack(side="left", padx=8)
    go_btn = ttk.Button(bf, text="Đã đăng nhập xong - Tiếp tục", state="disabled",
                        command=lambda: (user_go.set(), go_btn.configure(state="disabled")))
    go_btn.pack(side="left", padx=8)
    status = ttk.Label(t1, text="Chưa có danh sách. Dán link kênh rồi bấm '1. Lấy danh sách video'.",
                       foreground="#666")
    status.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 2))
    tf = ttk.Frame(t1)
    tf.grid(row=7, column=0, columnspan=2, sticky="ew")
    tf.columnconfigure(0, weight=1)
    tree = ttk.Treeview(tf, columns=("n", "date", "state", "title"), show="tree headings", height=10)
    tree.heading("#0", text=" Chọn", image=IMG_OFF, anchor="w", command=header_click)
    tree.heading("n", text="#")
    tree.heading("date", text="Ngày đăng")
    tree.heading("state", text="Trạng thái")
    tree.heading("title", text="Tiêu đề")
    tree.column("#0", width=72, anchor="w", stretch=False)
    tree.column("n", width=40, anchor="e", stretch=False)
    tree.column("date", width=90, stretch=False)
    tree.column("state", width=75, anchor="center", stretch=False)
    tree.column("title", width=560)
    tsb = ttk.Scrollbar(tf, command=tree.yview)
    tree.configure(yscrollcommand=tsb.set)
    tree.grid(row=0, column=0, sticky="ew")
    tsb.grid(row=0, column=1, sticky="ns")
    tree.bind("<Button-1>", on_tree_click)
    tree.bind("<space>", toggle_selected)
    cf = ttk.Frame(t1)
    cf.grid(row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
    dl_btn = ttk.Button(cf, text="2. Tải video đã chọn", state="disabled", command=do_download)
    dl_btn.pack(side="left")
    ttk.Button(cf, text="Đảo chọn dòng đang bôi đen (Space)", command=toggle_selected).pack(side="left", padx=6)
    ttk.Label(t1, foreground="#666", text="Bấm ô vuông ở tiêu đề cột 'Chọn' để chọn/bỏ chọn tất cả; bấm ô ở từng dòng để "
              "tích riêng. Giữ Shift/Ctrl bôi đen nhiều dòng rồi bấm Space. Mặc định tích sẵn video chưa tải.").grid(
        row=9, column=0, columnspan=2, sticky="w")

    # ======================= TAB 2: GHÉP VIDEO =======================
    t2 = ttk.Frame(nb, padding=12)
    nb.add(t2, text="2. Ghép video + watermark")
    t2.columnconfigure(1, weight=1)
    v_cmp_folder = tk.StringVar(value=settings.get("cmp_folder", DEFAULT_OUT))
    v_cmp_out = tk.StringVar(value=settings.get("cmp_out", str(Path(DEFAULT_OUT).parent / "tong_10p.mp4")))
    v_target = tk.DoubleVar(value=10.0)
    v_order = tk.StringVar(value="oldest")
    v_size = tk.StringVar(value="1920x1080")
    v_fps = tk.IntVar(value=30)
    v_exact = tk.BooleanVar(value=False)
    v_mode = tk.StringVar(value="text")
    v_text = tk.StringVar(value="nimokids")
    v_logo = tk.StringVar(value="")
    v_fsize = tk.IntVar(value=44)
    v_logoh = tk.IntVar(value=110)
    v_op = tk.DoubleVar(value=0.35)
    v_speed = tk.DoubleVar(value=0.15)
    v_crf = tk.IntVar(value=21)
    v_wm_on = tk.BooleanVar(value=True)
    v_cover = tk.BooleanVar(value=False)
    v_cover_style = tk.StringVar(value="Làm mờ")
    v_cover_top = tk.DoubleVar(value=88.0)
    v_cover_h = tk.DoubleVar(value=9.0)
    v_cover_w = tk.DoubleVar(value=100.0)
    v_vsub = tk.BooleanVar(value=False)
    v_vsub_dir = tk.StringVar(value=settings.get("cmp_vsub", str(Path(DEFAULT_OUT) / "subtitles")))
    v_vsub_size = tk.DoubleVar(value=5.0)
    v_title = tk.BooleanVar(value=False)
    v_title_dir = tk.StringVar(value=settings.get("cmp_titles", str(Path(DEFAULT_OUT) / "titles")))
    v_title_lang = tk.StringVar(value="vi")

    def path_row(parent, r, label, var, chooser):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3)
        fr = ttk.Frame(parent)
        ttk.Entry(fr, textvariable=var).pack(side="left", fill="x", expand=True)
        if isinstance(chooser, (list, tuple)):
            for name, cmd in chooser:
                ttk.Button(fr, text=name, command=cmd).pack(side="left", padx=(6, 0))
        else:
            ttk.Button(fr, text="Chọn...", command=chooser).pack(side="left", padx=(6, 0))
        ttk.Button(fr, text="Mở", width=5, command=lambda: open_path(var)).pack(side="left", padx=(4, 0))
        fr.grid(row=r, column=1, sticky="ew", pady=3)

    path_row(t2, 0, "Thư mục video nguồn:", v_cmp_folder, lambda: browse_dir(v_cmp_folder))
    path_row(t2, 1, "File video xuất ra:", v_cmp_out,
             lambda: browse_file(v_cmp_out, [("MP4", "*.mp4")], save=True))
    g = ttk.Frame(t2)
    ttk.Label(g, text="Thời lượng (phút):").pack(side="left")
    ttk.Spinbox(g, from_=1, to=120, increment=1, width=5, textvariable=v_target).pack(side="left", padx=6)
    ttk.Label(g, text="Thứ tự:").pack(side="left", padx=(12, 0))
    ttk.Combobox(g, values=["oldest", "newest", "random"], width=8, textvariable=v_order,
                 state="readonly").pack(side="left", padx=6)
    ttk.Label(g, text="Khung hình:").pack(side="left", padx=(12, 0))
    ttk.Combobox(g, values=["1920x1080", "1280x720", "1080x1920"], width=10, textvariable=v_size).pack(side="left", padx=6)
    ttk.Label(g, text="FPS:").pack(side="left", padx=(12, 0))
    ttk.Spinbox(g, from_=15, to=60, width=4, textvariable=v_fps).pack(side="left", padx=6)
    g.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
    ttk.Checkbutton(t2, text="Cắt đúng bằng thời lượng (có thể cắt ngang video cuối)",
                    variable=v_exact).grid(row=3, column=0, columnspan=2, sticky="w")

    wm_head = ttk.Checkbutton(t2, text="Chèn watermark di chuyển", variable=v_wm_on)
    lf = ttk.LabelFrame(t2, labelwidget=wm_head, padding=8)
    lf.grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
    lf.columnconfigure(2, weight=1)
    ttk.Radiobutton(lf, text="Chữ", variable=v_mode, value="text").grid(row=0, column=0, sticky="w")
    ttk.Entry(lf, textvariable=v_text, width=20).grid(row=0, column=1, sticky="w", padx=6)
    fs = ttk.Frame(lf)
    ttk.Label(fs, text="Cỡ chữ:").pack(side="left")
    ttk.Spinbox(fs, from_=12, to=200, width=5, textvariable=v_fsize).pack(side="left", padx=6)
    fs.grid(row=0, column=2, sticky="w")
    ttk.Radiobutton(lf, text="Logo PNG", variable=v_mode, value="logo").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(lf, textvariable=v_logo).grid(row=1, column=1, columnspan=2, sticky="ew", padx=6)
    lb = ttk.Frame(lf)
    ttk.Button(lb, text="Chọn...", command=lambda: browse_file(v_logo, [("PNG", "*.png")])).pack(side="left")

    def gen_logo():
        try:
            im, _ = make_logo_png(None, 800)
            dst = filedialog.asksaveasfilename(defaultextension=".png", initialfile="nimokids_logo.png",
                                               filetypes=[("PNG", "*.png")])
            if dst:
                im.save(dst)
                v_logo.set(dst)
                v_mode.set("logo")
                log(f"Đã tạo logo: {dst}")
        except ImportError:
            messagebox.showwarning("Thiếu Pillow", "Chạy: python -m pip install pillow")

    ttk.Button(lb, text="Tạo logo Nimo Kids", command=gen_logo).pack(side="left", padx=6)
    lb.grid(row=1, column=3, sticky="e")
    fs2 = ttk.Frame(lf)
    ttk.Label(fs2, text="Chiều cao logo (px):").pack(side="left")
    ttk.Spinbox(fs2, from_=30, to=500, width=5, textvariable=v_logoh).pack(side="left", padx=6)
    ttk.Label(fs2, text="Độ đậm (0-1):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(fs2, from_=0.1, to=1.0, increment=0.05, width=5, textvariable=v_op).pack(side="left", padx=6)
    ttk.Label(fs2, text="Tốc độ (nhỏ = chậm):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(fs2, from_=0.03, to=1.0, increment=0.01, width=5, textvariable=v_speed).pack(side="left", padx=6)
    fs2.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

    cf2 = ttk.LabelFrame(t2, text="Chữ trong video", padding=8)
    cf2.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    cf2.columnconfigure(1, weight=1)
    c1 = ttk.Frame(cf2)
    ttk.Checkbutton(c1, text="Che phụ đề cũ (chữ Trung)", variable=v_cover).pack(side="left")
    ttk.Label(c1, text="Kiểu:").pack(side="left", padx=(12, 0))
    ttk.Combobox(c1, values=["Làm mờ", "Hộp đen"], width=9, textvariable=v_cover_style,
                 state="readonly").pack(side="left", padx=6)
    ttk.Label(c1, text="Từ mép trên (%):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(c1, from_=0, to=99, increment=1, width=5, textvariable=v_cover_top).pack(side="left", padx=6)
    ttk.Label(c1, text="Cao (%):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(c1, from_=2, to=40, increment=1, width=5, textvariable=v_cover_h).pack(side="left", padx=6)
    ttk.Label(c1, text="Rộng (%):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(c1, from_=10, to=100, increment=1, width=5, textvariable=v_cover_w).pack(side="left", padx=6)
    c1.grid(row=0, column=0, columnspan=3, sticky="w")
    c1b = ttk.Frame(cf2)
    b_det = ttk.Button(c1b, text="Tự dò vị trí chữ Trung", command=lambda: do_detect())
    b_det.pack(side="left")
    b_pv = ttk.Button(c1b, text="Xem thử 1 khung hình", command=lambda: do_preview())
    b_pv.pack(side="left", padx=8)
    all_buttons.extend([b_det, b_pv])
    ttk.Label(c1b, foreground="#666", text="Khung che tự rộng hơn cả chữ Trung lẫn dòng phụ đề Việt dài nhất.").pack(
        side="left", padx=4)
    c1b.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
    c2 = ttk.Frame(cf2)
    ttk.Checkbutton(c2, text="Chèn phụ đề tiếng Việt (file SRT)", variable=v_vsub).pack(side="left")
    ttk.Label(c2, text="Cỡ chữ (% chiều cao):").pack(side="left", padx=(12, 0))
    ttk.Spinbox(c2, from_=2, to=15, increment=0.5, width=5, textvariable=v_vsub_size).pack(side="left", padx=6)
    c2.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
    ttk.Label(cf2, text="Thư mục SRT tiếng Việt:").grid(row=3, column=0, sticky="w", pady=(6, 0))
    cf3 = ttk.Frame(cf2)
    ttk.Entry(cf3, textvariable=v_vsub_dir).pack(side="left", fill="x", expand=True)
    ttk.Button(cf3, text="Chọn...", command=lambda: browse_dir(v_vsub_dir)).pack(side="left", padx=(6, 0))
    ttk.Button(cf3, text="Mở", width=5, command=lambda: open_path(v_vsub_dir)).pack(side="left", padx=(4, 0))
    cf3.grid(row=3, column=1, sticky="ew", pady=(6, 0))
    ttk.Label(cf2, foreground="#666", wraplength=780, justify="left",
              text="Tên file SRT khớp tên video: 'tên_video.vi.srt' (ưu tiên) hoặc 'tên_video.srt'. Tool tự gộp phụ đề các video "
                   "theo đúng thứ tự ghép. File SRT tiếng Trung sẽ bị bỏ qua. Che chữ cũ ở vị trí nào thì phụ đề Việt nằm đúng "
                   "dải đó.").grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

    tf2 = ttk.LabelFrame(t2, text="Thẻ chữ / chữ tiêu đề trong video (dịch chữ Trung)", padding=8)
    tf2.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    tf2.columnconfigure(1, weight=1)
    d1 = ttk.Frame(tf2)
    ttk.Checkbutton(d1, text="Che chữ Trung bằng màu nền và viết bản dịch", variable=v_title).pack(side="left")
    ttk.Label(d1, text="Đuôi ngôn ngữ file dịch:").pack(side="left", padx=(12, 0))
    ttk.Entry(d1, textvariable=v_title_lang, width=5).pack(side="left", padx=6)
    b_tdet = ttk.Button(d1, text="Dò chữ, xuất danh sách để dịch", command=lambda: do_detect_titles())
    b_tdet.pack(side="left", padx=(12, 0))
    all_buttons.append(b_tdet)
    d1.grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(tf2, text="Thư mục danh sách chữ:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    d2 = ttk.Frame(tf2)
    ttk.Entry(d2, textvariable=v_title_dir).pack(side="left", fill="x", expand=True)
    ttk.Button(d2, text="Chọn...", command=lambda: browse_dir(v_title_dir)).pack(side="left", padx=(6, 0))
    ttk.Button(d2, text="Mở", width=5, command=lambda: open_path(v_title_dir)).pack(side="left", padx=(4, 0))
    d2.grid(row=1, column=1, sticky="ew", pady=(6, 0))
    ttk.Label(tf2, foreground="#666", wraplength=780, justify="left",
              text="Cách dùng: (1) bấm 'Dò chữ' -> tool tạo file 'tên_video.titles.srt' (chữ Trung, có đánh số). (2) Dịch file đó, lưu "
                   "thành 'tên_video.titles.vi.srt' trong cùng thư mục (mốc thời gian lệch vài giây cũng được, tool chỉ lấy chữ). "
                   "(3) Tích ô trên rồi Render. Chữ ở dải dưới cùng (phụ đề) không nằm trong danh sách, vì đã có tính năng riêng.").grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

    h = ttk.Frame(t2)
    ttk.Label(h, text="Chất lượng CRF (nhỏ = nét hơn, nặng hơn):").pack(side="left")
    ttk.Spinbox(h, from_=16, to=30, width=4, textvariable=v_crf).pack(side="left", padx=6)
    h.grid(row=7, column=0, columnspan=2, sticky="w")

    def cmp_cfg():
        mode = v_mode.get() if v_wm_on.get() else "none"
        return dict(
            folder=v_cmp_folder.get().strip(), out=v_cmp_out.get().strip(),
            target=float(v_target.get()) * 60, tol=0.15, order=v_order.get(),
            size=v_size.get().strip(), fps=int(v_fps.get()), exact=v_exact.get(), crf=int(v_crf.get()),
            wm=dict(mode=mode, text=v_text.get() or "nimokids", font=None, fontsize=int(v_fsize.get()),
                    logo=v_logo.get().strip(), logo_h=int(v_logoh.get()),
                    opacity=round(float(v_op.get()), 2), speed=float(v_speed.get()), margin=30),
            cover=dict(top=float(v_cover_top.get()), height=float(v_cover_h.get()), width=float(v_cover_w.get()),
                       style="box" if v_cover_style.get() == "Hộp đen" else "blur") if v_cover.get() else None,
            vsub=dict(folder=v_vsub_dir.get().strip(), size=float(v_vsub_size.get())) if v_vsub.get() else None,
            titles=dict(folder=v_title_dir.get().strip(), lang=(v_title_lang.get().strip() or "vi")) if v_title.get() else None)

    def do_detect():
        folder = Path(v_cmp_folder.get().strip())
        vids = sorted(folder.glob("*.mp4")) if folder.is_dir() else []
        if not vids:
            messagebox.showwarning("Thiếu video", "Chọn thư mục video nguồn có file .mp4 trước.")
            return

        def work():
            if not ensure_rapidocr(log):
                raise RuntimeError("Cài thư viện nhận dạng chữ thất bại. Mở PowerShell chạy: "
                                   "py -3.13 -m pip install rapidocr-onnxruntime")
            log(f"Đang dò chữ Trung ở nửa dưới video (lấy mẫu trong {min(3, len(vids))} video)...")
            r = detect_cn_region(vids, log, stop)
            if not r:
                raise RuntimeError("Không thấy dòng phụ đề chữ Trung nào. Có thể video không có phụ đề cứng, "
                                   "hoặc chữ quá mờ: hãy đặt vị trí bằng tay rồi bấm 'Xem thử 1 khung hình'.")

            def apply():
                v_cover_top.set(r["top"])
                v_cover_h.set(r["height"])
                v_cover_w.set(r["width"])
                v_cover.set(True)
            q.put(("call", apply))
            log(f"Đã dò xong: chữ Trung ở {r['top']}% → {r['top'] + r['height']:.1f}% chiều cao, rộng {r['width']}% khung "
                f"(thấy ở {r['seen']}/{r['frames']} khung hình). Đã điền vào các ô; bấm 'Xem thử' để kiểm tra.")
            return None

        start_worker(work, show_timing=False)

    def do_detect_titles():
        cfg = cmp_cfg()
        if not Path(cfg["folder"]).is_dir():
            messagebox.showwarning("Thiếu thư mục", "Chọn thư mục video nguồn trước.")
            return
        tdir = Path(v_title_dir.get().strip())
        ignore = (float(v_cover_top.get()) / 100) if v_cover.get() else 0.84

        def work():
            if not ensure_rapidocr(log):
                raise RuntimeError("Cài thư viện nhận dạng chữ thất bại. Mở PowerShell chạy: "
                                   "py -3.13 -m pip install rapidocr-onnxruntime")
            files, _ = list_clips(cfg["folder"], cfg["order"], cfg.get("seed"))
            chosen, _ = pick_clips(files, cfg["target"], cfg["tol"])
            log(f"Đang dò chữ Trung trong {len(chosen)} video sẽ ghép (bỏ qua chữ thấp hơn {ignore * 100:.0f}% chiều cao, "
                "mỗi video vài chục giây)...")
            scanned, total = detect_texts(chosen, tdir, log, prog, stop, ignore_below=ignore)
            log(f"Dò xong: {total} chữ. Danh sách nằm ở {tdir}")
            return (f"Đã dò xong {total} chữ trong {len(chosen)} video.\n\nBước tiếp theo: dịch các file 'tên_video.titles.srt' "
                    f"trong thư mục:\n{tdir}\nlưu thành 'tên_video.titles.{v_title_lang.get().strip() or 'vi'}.srt', "
                    "rồi tích ô 'Che chữ Trung bằng màu nền và viết bản dịch' và Render.")

        start_worker(work, lambda r: r)

    def show_preview(path):
        win = tk.Toplevel(root)
        win.title("Xem thử 1 khung hình")
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            im.thumbnail((960, 600))
            ph = ImageTk.PhotoImage(im)
            lbl = ttk.Label(win, image=ph)
            lbl.image = ph
            lbl.pack(padx=8, pady=8)
        except Exception:
            ttk.Label(win, text=f"Ảnh xem thử đã lưu ở:\n{path}").pack(padx=20, pady=20)

    def do_preview():
        if not v_cover.get() and not v_vsub.get() and not v_title.get():
            messagebox.showwarning("Chưa bật", "Tích 'Che phụ đề cũ', 'Chèn phụ đề tiếng Việt' hoặc 'Che chữ Trung ở thẻ chữ' để xem thử.")
            return
        dest = Path(tempfile.gettempdir()) / "nimokids_preview.png"

        def work():
            p = preview_frame(cmp_cfg(), log, dest)
            q.put(("call", lambda: show_preview(p)))
            log("Đã dựng khung hình xem thử.")
            return None

        start_worker(work, show_timing=False)

    bt = ttk.Frame(t2)
    bt.grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))
    b1 = ttk.Button(bt, text="Xem danh sách sẽ ghép",
                    command=lambda: start_worker(lambda: run_compile(cmp_cfg(), log, prog, stop, dry=True)))
    b2 = ttk.Button(bt, text="Render video tổng",
                    command=lambda: start_worker(lambda: run_compile(cmp_cfg(), log, prog, stop),
                                                 lambda r: f"Đã tạo xong:\n{r}"))
    b1.pack(side="left")
    b2.pack(side="left", padx=8)
    all_buttons += [b1, b2]

    # ======================= TAB 3: PHỤ ĐỀ SRT =======================
    t4 = ttk.Frame(nb, padding=12)
    nb.add(t4, text="3. Phụ đề SRT")
    t4.columnconfigure(1, weight=1)
    v_sub_src = tk.StringVar(value=settings.get("sub_src", DEFAULT_OUT))
    v_model = tk.StringVar(value="large-v3" if has_nvidia() else "medium")
    v_lang = tk.StringVar(value="Tự nhận dạng")
    v_task = tk.StringVar(value="Giữ nguyên lời nói")
    v_dev = tk.StringVar(value="Tự động (GPU nếu có)")
    v_skip = tk.BooleanVar(value=True)
    v_txt = tk.BooleanVar(value=False)

    path_row(t4, 0, "Video hoặc thư mục:", v_sub_src, [
        ("Chọn file...", lambda: browse_file(v_sub_src, [("Video/Âm thanh", " ".join("*" + e for e in VIDEO_EXT)),
                                                          ("Tất cả", "*.*")])),
        ("Chọn thư mục...", lambda: browse_dir(v_sub_src))])
    o1 = ttk.Frame(t4)
    ttk.Label(o1, text="Lời nói trong video:").pack(side="left")
    ttk.Combobox(o1, values=list(SPOKEN_LANGS), width=13, textvariable=v_lang, state="readonly").pack(side="left", padx=6)
    ttk.Label(o1, text="Phụ đề:").pack(side="left", padx=(12, 0))
    ttk.Combobox(o1, values=["Giữ nguyên lời nói", "Dịch sang tiếng Anh"], width=20, textvariable=v_task,
                 state="readonly").pack(side="left", padx=6)
    o1.grid(row=1, column=0, columnspan=2, sticky="w", pady=3)
    o2 = ttk.Frame(t4)
    ttk.Label(o2, text="Model:").pack(side="left")
    ttk.Combobox(o2, values=WHISPER_MODELS, width=9, textvariable=v_model, state="readonly").pack(side="left", padx=6)
    ttk.Label(o2, text="Chạy bằng:").pack(side="left", padx=(12, 0))
    ttk.Combobox(o2, values=["Tự động (GPU nếu có)", "Chỉ CPU"], width=20, textvariable=v_dev,
                 state="readonly").pack(side="left", padx=6)
    o2.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
    ttk.Checkbutton(t4, text="Bỏ qua video đã có phụ đề", variable=v_skip).grid(row=3, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(t4, text="Xuất thêm file .txt (chỉ chữ, không mốc thời gian)", variable=v_txt).grid(
        row=4, column=0, columnspan=2, sticky="w")

    def do_sub():
        src = v_sub_src.get().strip()
        if not src or not Path(src).exists():
            messagebox.showwarning("Thiếu file", "Chọn một video hoặc thư mục video.")
            return
        cfg = dict(src=src, model=v_model.get(), lang=SPOKEN_LANGS[v_lang.get()],
                   task="translate" if v_task.get().startswith("Dịch") else "transcribe",
                   device="cpu" if v_dev.get() == "Chỉ CPU" else "auto", skip=v_skip.get(), txt=v_txt.get())
        start_worker(lambda: run_transcribe(cfg, log, prog, stop), lambda r: r)

    sb4 = ttk.Frame(t4)
    sb4.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
    b5 = ttk.Button(sb4, text="Tạo phụ đề SRT", command=do_sub)
    b5.pack(side="left")
    ttk.Button(sb4, text="Mở thư mục phụ đề", command=lambda: open_path(
        (Path(v_sub_src.get()) if Path(v_sub_src.get()).is_dir() else Path(v_sub_src.get()).parent) / "subtitles"
    )).pack(side="left", padx=8)
    all_buttons.append(b5)
    ttk.Label(t4, foreground="#666", wraplength=780, justify="left",
              text="Dùng Whisper chạy ngay trên máy bạn, không cần mạng (trừ lần đầu tải model). File .srt lưu trong "
                   "thư mục 'subtitles' cạnh video. Model: small = nhanh, medium = cân bằng (khuyên dùng), "
                   "large-v3 = chính xác nhất. Có card NVIDIA (RTX) thì tool tự chạy GPU và chọn sẵn large-v3: video 1 phút "
                   "chỉ mất vài giây. Lần đầu tool tự cài thư viện GPU (~1GB) và tải model (~3GB).").grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # ======================= DƯỚI: tiến độ + nhật ký =======================
    bottom = ttk.Frame(root)
    bottom.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    top = ttk.Frame(bottom)
    top.pack(fill="x")
    bar = tk.Canvas(top, height=24, highlightthickness=1, highlightbackground="#b5b5b5", bg="#ececec")
    bar.pack(side="left", fill="x", expand=True)
    prog_state = {"v": 0, "mx": 1, "show": False, "busy": False, "t0": 0.0, "phase": 0}

    def draw_bar(_=None):
        bar.delete("all")
        w, h = bar.winfo_width(), bar.winfo_height()
        ps = prog_state
        frac = min(1.0, max(0.0, ps["v"] / max(1, ps["mx"])))
        elapsed = fmt_time(time.time() - ps["t0"]) if ps["busy"] else ""
        if ps["show"]:
            if frac > 0:
                bar.create_rectangle(0, 0, int(w * frac), h, fill=BAR_COLOR, width=0)
            text = f"{frac * 100:.0f}%" + (f"   •   {elapsed}" if ps["busy"] else "")
        elif ps["busy"]:
            # chưa biết % -> vạch chạy qua lại cho biết tool đang làm việc
            seg = max(40, w // 5)
            pos = (ps["phase"] % (2 * (w - seg))) if w > seg else 0
            x = pos if pos <= w - seg else 2 * (w - seg) - pos
            bar.create_rectangle(x, 0, x + seg, h, fill="#8fd19e", width=0)
            text = f"Đang chạy...   {elapsed}"
        else:
            text = ""
        if text:
            bar.create_text(w // 2, h // 2, text=text, font=("Segoe UI", 10, "bold"),
                            fill="#ffffff" if ps["show"] and frac >= 0.55 else "#1b1b1b")

    def set_bar(v, mx):
        prog_state.update(v=v, mx=mx, show=v > 0)
        draw_bar()

    def tick_bar():
        if prog_state["busy"]:
            prog_state["phase"] += 8
            draw_bar()
            root.after(50, tick_bar)

    def begin_bar():
        prog_state.update(v=0, mx=1, show=False, busy=True, t0=time.time(), phase=0)
        tick_bar()

    def end_bar():
        prog_state["busy"] = False
        draw_bar()

    bar.bind("<Configure>", draw_bar)
    stop_btn = ttk.Button(top, text="Dừng", state="disabled", width=10,
                          command=lambda: (stop.set(), user_go.set()))
    stop_btn.pack(side="left", padx=(8, 0))
    txt = tk.Text(bottom, height=12, state="disabled", wrap="word", font=("Consolas", 9))
    txt.tag_configure("time", foreground="#868e96")
    txt.tag_configure("err", foreground="#e03131")
    txt.tag_configure("ok", foreground="#2b8a3e")
    txt.tag_configure("warn", foreground="#e67700")
    txt.tag_configure("info", foreground="#1971c2")
    txt.tag_configure("head", foreground="#7048e8")
    txt.tag_configure("norm", foreground="#212529")
    sb = ttk.Scrollbar(bottom, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y", pady=(6, 0))
    txt.pack(fill="both", expand=True, pady=(6, 0))

    log(f"Nimo Kids Tool v{__version__} - Python {platform.python_version()}")
    log("Sẵn sàng. " + ("ffmpeg OK." if shutil.which("ffmpeg") else
                         "CHƯA thấy ffmpeg (tab 2, 3 cần): winget install Gyan.FFmpeg"))
    pump()
    def on_close():
        save_settings(dict(url=v_url.get(), out=v_out.get(), cmp_folder=v_cmp_folder.get(),
                           cmp_out=v_cmp_out.get(), sub_src=v_sub_src.get(),
                           cmp_vsub=v_vsub_dir.get(), cmp_titles=v_title_dir.get()))
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    try:
        run_gui()
    except Exception:
        # chạy bằng icon (không có cửa sổ lệnh) thì ghi lỗi ra file để còn biết lỗi gì
        import traceback
        err = traceback.format_exc()
        log_file = Path(__file__).with_name("nimokids_error.log")
        log_file.write_text(err, encoding="utf-8")
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("Nimo Kids Tool", f"Tool bị lỗi khi mở:\n\n{err[-600:]}\n\nChi tiết: {log_file}")
        except Exception:
            pass
