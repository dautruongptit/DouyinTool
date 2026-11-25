"""Bản web Douyin Tool (FastAPI).

Phục vụ giao diện + REST API + job nền + proxy noVNC trong cùng một tiến trình.
Nghiệp vụ gọi thẳng vào nimokids_core (không chép code).
"""
import asyncio
import re
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from nimokids_core import __version__, douyin
from nimokids_core import compile as ncompile
from nimokids_core import subtitles

from . import config, store
from .jobs import manager

app = FastAPI(title="Douyin Tool (web)", version=__version__)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
if config.NOVNC_DIR.is_dir():
    app.mount("/novnc", StaticFiles(directory=str(config.NOVNC_DIR), html=True), name="novnc")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


# ----------------------------------------------------------------------------
# Mô hình request
# ----------------------------------------------------------------------------
class ListReq(BaseModel):
    url: str
    folder: str = ""
    limit: int = 0
    thumbs: bool = True


class DownloadReq(BaseModel):
    ids: list


class Wm(BaseModel):
    mode: str = "text"            # text | logo | none
    text: str = "nimokids"
    fontsize: int = 44
    logo: str = ""               # tên file PNG trong /data/media
    logo_h: int = 110
    opacity: float = 0.35
    speed: float = 0.15


class ComposeReq(BaseModel):
    folder: str
    out: str = ""
    target_min: float = 10.0
    order: str = "oldest"        # oldest | newest | random
    size: str = "1920x1080"
    fps: int = 30
    exact: bool = False
    crf: int = 21
    wm: Wm = Wm()
    dry: bool = False


class SubReq(BaseModel):
    src_folder: str = ""
    src_file: str = ""
    model: str = config.DEFAULT_WHISPER_MODEL
    lang: str = "Tự nhận dạng"
    task: str = "Giữ nguyên lời nói"
    skip: bool = True
    txt: bool = False


# ----------------------------------------------------------------------------
# Tiện ích
# ----------------------------------------------------------------------------
def _folder_from_url(url: str) -> str:
    m = douyin.SEC_UID_RE.search(url or "")
    tail = m.group(0)[-10:] if m else "kenh"
    return "kenh_" + re.sub(r"[^0-9A-Za-z_\-]", "", tail)


def _busy_guard():
    if manager.busy():
        raise HTTPException(409, "Đang có việc chạy. Chờ xong hoặc bấm Dừng trước.")


# ----------------------------------------------------------------------------
# Trang + sức khỏe
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    s = store.load_settings()
    return templates.TemplateResponse(request, "index.html", {
        "version": __version__,
        "settings": s,
        "folders": store.list_media_folders(),
        "whisper_models": subtitles.WHISPER_MODELS,
        "spoken_langs": list(subtitles.SPOKEN_LANGS.keys()),
        "default_model": config.DEFAULT_WHISPER_MODEL,
    })


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/folders")
def folders():
    return {"folders": store.list_media_folders()}


# ----------------------------------------------------------------------------
# Tab 1: tải Douyin
# ----------------------------------------------------------------------------
@app.post("/api/douyin/list")
def douyin_list(req: ListReq):
    _busy_guard()
    url, short = douyin.parse_channel_link(req.url)
    if not url and not short:
        if re.search(r"douyin\.com/video/\d+", req.url):
            raise HTTPException(400, "Đây là link của MỘT video. Mở video, bấm tên tác giả để vào trang kênh "
                                     "rồi copy link trang kênh (douyin.com/user/MS4wLjAB...).")
        raise HTTPException(400, "Không nhận ra link kênh. Dán link douyin.com/user/MS4wLjAB... hoặc v.douyin.com/...")

    folder = (req.folder or "").strip() or _folder_from_url(url or "")
    out = store.safe_media_path(folder)
    cfg = dict(url=url, short=short, out=str(out), profile=str(config.BROWSER_PROFILE),
               channel=config.BROWSER_CHANNEL, limit=int(req.limit), sleep=2.0,
               thumbs=req.thumbs, hidden=config.BROWSER_HIDDEN)

    def fn(job):
        res = douyin.collect_list(cfg, job.log, job.prog, job.wait_user, job.stop)
        if not res["items"]:
            raise RuntimeError("Không lấy được video nào. Mở 'Màn hình Chrome' kiểm tra đăng nhập rồi thử lại.")
        manager.last_result = res
        manager.last_list_items = res["items"]
        manager.last_channel_url = cfg.get("url")
        manager.last_out = str(out)
        store.update_settings(last_url=req.url, last_folder=folder)
        return f"Lấy danh sách xong: {len(res['items'])} video."

    if not manager.start("Lấy danh sách Douyin", fn):
        _busy_guard()
    return {"ok": True}


@app.post("/api/douyin/login")
def douyin_login():
    """Mở Chrome trên màn ảo để người dùng đăng nhập Douyin một lần (xem qua noVNC)."""
    _busy_guard()
    cfg = dict(profile=str(config.BROWSER_PROFILE), channel=config.BROWSER_CHANNEL)

    def fn(job):
        return douyin.open_for_login(cfg, job.log, job.prog, job.wait_user, job.stop)

    if not manager.start("Đăng nhập Douyin", fn):
        _busy_guard()
    return {"ok": True}


@app.get("/api/douyin/videos")
def douyin_videos():
    out = manager.last_out
    items = []
    for i, a in enumerate(manager.last_list_items, 1):
        items.append({
            "id": a["aweme_id"],
            "n": i,
            "date": datetime.fromtimestamp(a.get("create_time", 0)).strftime("%d/%m/%Y"),
            "desc": (a.get("desc") or "").replace("\n", " ")[:120],
            "downloaded": douyin.is_downloaded(out, a) if out else False,
        })
    return {
        "items": items,
        "total": (manager.last_result or {}).get("total"),
        "folder": Path(out).name if out else "",
        "channel_url": manager.last_channel_url,
    }


@app.post("/api/douyin/download")
def douyin_download(req: DownloadReq):
    _busy_guard()
    if not manager.last_result:
        raise HTTPException(409, "Chưa có danh sách. Bấm 'Lấy danh sách video' trước.")
    ids = set(req.ids)
    sel = [a for a in manager.last_list_items if a["aweme_id"] in ids]
    if not sel:
        raise HTTPException(400, "Chưa chọn video nào.")
    cfg = dict(out=manager.last_out, thumbs=True, sleep=2.0)
    res_sel = dict(manager.last_result, items=sel)

    def fn(job):
        return douyin.download_items(cfg, res_sel, job.log, job.prog, job.stop)

    if not manager.start(f"Tải {len(sel)} video", fn):
        _busy_guard()
    return {"ok": True, "count": len(sel)}


# ----------------------------------------------------------------------------
# Tab 2: ghép video + watermark
# ----------------------------------------------------------------------------
@app.post("/api/compose")
def compose(req: ComposeReq):
    _busy_guard()
    folder = store.safe_media_path(req.folder)
    if not folder.is_dir():
        raise HTTPException(400, "Thư mục video nguồn không tồn tại.")
    out_name = Path(req.out).name or f"tong_{int(req.target_min)}p.mp4"
    out = folder / out_name

    logo_path = ""
    if req.wm.mode == "logo" and req.wm.logo:
        logo_path = str(store.safe_media_path(req.wm.logo))

    cfg = dict(
        folder=str(folder), out=str(out), target=float(req.target_min) * 60, tol=0.15,
        order=req.order, size=req.size.strip(), fps=int(req.fps), exact=req.exact, crf=int(req.crf),
        wm=dict(mode=req.wm.mode, text=req.wm.text or "nimokids", font=None, fontsize=int(req.wm.fontsize),
                logo=logo_path, logo_h=int(req.wm.logo_h), opacity=round(float(req.wm.opacity), 2),
                speed=float(req.wm.speed), margin=30),
    )
    dry = req.dry

    def fn(job):
        r = ncompile.run_compile(cfg, job.log, job.prog, job.stop, dry=dry)
        if dry:
            return "Đã liệt kê danh sách sẽ ghép (xem nhật ký)."
        rel = Path(r).relative_to(config.MEDIA_DIR)
        return {"message": f"Đã tạo xong: {r}", "download": str(rel)}

    name = "Xem danh sách sẽ ghép" if dry else "Render video tổng"
    if not manager.start(name, fn):
        _busy_guard()
    return {"ok": True}


@app.post("/api/logo")
def make_logo():
    im, _ = ncompile.make_logo_png(None, 800)
    dst = config.MEDIA_DIR / "nimokids_logo.png"
    im.save(dst)
    return {"ok": True, "rel": "nimokids_logo.png"}


# ----------------------------------------------------------------------------
# Tab 3: phụ đề SRT
# ----------------------------------------------------------------------------
@app.post("/api/subtitle")
def subtitle(req: SubReq):
    _busy_guard()
    if req.src_file:
        src = store.safe_media_path(req.src_file)
        if not src.is_file():
            raise HTTPException(400, "File video không tồn tại.")
    else:
        src = store.safe_media_path(req.src_folder)
        if not src.is_dir():
            raise HTTPException(400, "Thư mục video không tồn tại.")
    cfg = dict(
        src=str(src), model=req.model, lang=subtitles.SPOKEN_LANGS.get(req.lang),
        task="translate" if req.task.startswith("Dịch") else "transcribe",
        device="cpu", skip=req.skip, txt=req.txt,
    )

    def fn(job):
        return subtitles.run_transcribe(cfg, job.log, job.prog, job.stop)

    if not manager.start("Tạo phụ đề SRT", fn):
        _busy_guard()
    return {"ok": True}


# ----------------------------------------------------------------------------
# Job: trạng thái + điều khiển
# ----------------------------------------------------------------------------
@app.get("/api/job")
def job_status(since: int = 0):
    j = manager.current
    if not j:
        return {"status": "idle", "busy": False, "progress": 0, "logs": [], "log_cursor": 0}
    return j.snapshot(since)


@app.post("/api/job/stop")
def job_stop():
    j = manager.current
    if j and j.status in ("running", "needs_login"):
        j.stop.set()
        j.do_continue()
        return {"ok": True}
    return {"ok": False, "reason": "Không có việc đang chạy."}


@app.post("/api/job/continue")
def job_continue():
    j = manager.current
    if j and j.status == "needs_login":
        j.do_continue()
        return {"ok": True}
    return {"ok": False}


@app.get("/api/download")
def download(rel: str):
    p = store.safe_media_path(rel)
    if not p.is_file():
        raise HTTPException(404, "Không tìm thấy file.")
    return FileResponse(str(p), filename=p.name)


# ----------------------------------------------------------------------------
# noVNC: bắc cầu WebSocket sang x11vnc (xem màn hình Chromium để đăng nhập/captcha)
# ----------------------------------------------------------------------------
@app.websocket("/websockify")
async def websockify(ws: WebSocket):
    await ws.accept()
    try:
        reader, writer = await asyncio.open_connection(config.VNC_HOST, config.VNC_PORT)
    except Exception:
        await ws.close(code=1011)
        return

    async def browser_to_vnc():
        try:
            while True:
                data = await ws.receive_bytes()
                writer.write(data)
                await writer.drain()
        except Exception:
            pass

    async def vnc_to_browser():
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await ws.send_bytes(data)
        except Exception:
            pass

    try:
        await asyncio.gather(browser_to_vnc(), vnc_to_browser())
    finally:
        try:
            writer.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass


# Thông báo lỗi dạng JSON gọn cho giao diện
@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
