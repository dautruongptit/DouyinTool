"""Douyin: nhận dạng link kênh, lấy danh sách video bằng Chrome thật, tải video + thumbnail.
Không chứa giao diện: dùng chung cho bản máy tính (Tkinter) và bản web trên server."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from .common import Stopped, safe, save_png

REFERER = "https://www.douyin.com/"

def norm_url(u):
    if u.startswith("//"):
        u = "https:" + u
    return u.replace("http://", "https://", 1)

def pick_video_url(aweme):
    v = aweme.get("video") or {}
    best = None
    for br in v.get("bit_rate") or []:
        urls = (br.get("play_addr") or {}).get("url_list") or []
        if urls and (best is None or br.get("bit_rate", 0) > best[0]):
            best = (br.get("bit_rate", 0), urls[0])
    if best:
        return norm_url(best[1])
    urls = (v.get("play_addr") or {}).get("url_list") or []
    return norm_url(urls[0]) if urls else None

def thumb_urls(aweme):
    """Link ảnh thumbnail (ảnh minh hoạ tác giả đặt, như hiện trên trang kênh), theo thứ tự ưu tiên.
    cover_original_scale = ảnh thumbnail bản gốc, đủ khung; cover = bản hiện trên lưới kênh.
    origin_cover/dynamic_cover là khung hình cắt từ video -> chỉ dùng khi không có ảnh nào khác."""
    v = aweme.get("video") or {}
    out = []
    for key in ("cover_original_scale", "cover", "origin_cover"):
        urls = [norm_url(u) for u in ((v.get(key) or {}).get("url_list") or [])]
        urls.sort(key=lambda u: 0 if "jpeg" in u or ".jpg" in u else 1)  # ưu tiên JPEG (dễ đổi sang PNG)
        out += [u for u in urls if u not in out]
    return out

SEC_UID_RE = re.compile(r"MS4wLjAB[0-9A-Za-z_\-]+")

def parse_channel_link(text):
    """Nhận link/đoạn chữ chia sẻ bất kỳ, trả về (link_kênh_sạch hoặc None, link_rút_gọn hoặc None).
    Ví dụ: https://www.douyin.com/user/MS4w...?from_tab_name=main&vid=771...  -> https://www.douyin.com/user/MS4w..."""
    text = (text or "").strip()
    m = SEC_UID_RE.search(text)
    if m:
        return f"https://www.douyin.com/user/{m.group(0)}", None
    m = re.search(r"https?://v\.douyin\.com/[0-9A-Za-z_\-]+/?", text)
    if m:
        return None, m.group(0)
    return None, None

def resolve_short(short_url):
    """Mở link v.douyin.com để lấy link thật, rồi tách sec_uid."""
    import requests
    r = requests.get(short_url, allow_redirects=True, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"})
    hops = [h.headers.get("Location", "") for h in r.history] + [r.url]
    for u in hops:
        m = SEC_UID_RE.search(u or "")
        if m:
            return f"https://www.douyin.com/user/{m.group(0)}"
    if any("/video/" in (u or "") for u in hops):
        raise RuntimeError("Đây là link của MỘT video, không phải link kênh. Mở video đó, bấm vào tên tác giả "
                           "để vào trang kênh rồi copy link trang kênh.")
    raise RuntimeError("Không tìm thấy mã kênh (sec_uid) trong link rút gọn này.")

def video_name(a):
    date = datetime.fromtimestamp(a.get("create_time", 0)).strftime("%Y%m%d")
    return f"{date}_{a['aweme_id']}_{safe(a.get('desc'))}"

def is_downloaded(out, a):
    p = Path(out).expanduser()
    return any(f.stat().st_size > 0 for f in p.glob(f"*_{a['aweme_id']}_*.mp4")) if p.is_dir() else False

def download_file(session, url, dest, stop, retries=3):
    part = dest.with_suffix(dest.suffix + ".part")
    last_err = None
    for attempt in range(1, retries + 1):
        if stop.is_set():
            raise Stopped()
        try:
            with session.get(url, stream=True, timeout=(15, 60)) as r:
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(2 * attempt)
                    continue
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if stop.is_set():
                            raise Stopped()
                        if chunk:
                            f.write(chunk)
            part.replace(dest)
            return True, None
        except Stopped:
            if part.exists():
                part.unlink()
            raise
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * attempt)
    if part.exists():
        part.unlink()
    return False, last_err

SCROLL_JS = """() => {
  // Cuộn mọi khung có thanh cuộn xuống đáy (Douyin để danh sách video trong một khung cuộn riêng)
  let n = 0;
  for (const el of [document.scrollingElement, ...document.querySelectorAll('*')]) {
    if (!el) continue;
    const st = getComputedStyle(el);
    if (el === document.scrollingElement || /(auto|scroll)/.test(st.overflowY)) {
      if (el.scrollHeight > el.clientHeight + 50) { el.scrollTop = el.scrollHeight; n++; }
    }
  }
  window.scrollTo(0, document.body.scrollHeight);
  return n;
}"""

# Khung "Log in to Douyin" (đăng nhập bằng QR/SĐT) hay bật lên che trang. Tìm nút X và bấm.
CLOSE_LOGIN_JS = """() => {
  const vis = el => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sels = ['.dy-account-close', '[class*="dy-account-close"]', '[data-e2e="login-close"]',
                '#login-panel-new [class*="close"]', '[id^="login-pa"] [class*="close"]',
                '[class*="login-panel"] [class*="close"]'];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (vis(el)) { el.click(); return s; }
  }
  return vis(document.querySelector('#login-panel-new, [id^="login-pa"]')) ? 'esc' : '';
}"""

def close_login_popup(page, log=None, state=None):
    """Nếu đang có khung đăng nhập Douyin (đang hiện) thì đóng (bấm X). Trả về True nếu thấy khung."""
    try:
        r = page.evaluate(CLOSE_LOGIN_JS)
        if r == "esc":
            page.keyboard.press("Escape")
        if r:
            if state is None:
                state = {}
            n = state["n"] = state.get("n", 0) + 1
            if log and (n == 1 or n % 20 == 0):
                log(f"Thấy khung đăng nhập Douyin, đã bấm X để đóng (lần {n}, cách đóng: {r}).")
            return True
    except Exception:
        pass
    return False

def collect_list(cfg, log, prog, wait_user, stop):
    """Bước 1: dùng Chrome lấy danh sách video + cookie. Trả về dict(items, cookies, ua, total)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Thiếu thư viện. Chạy: python -m pip install playwright requests")

    if cfg.get("short"):
        log(f"Đang mở link rút gọn {cfg['short']} ...")
        cfg["url"] = resolve_short(cfg["short"])
        log(f"Link kênh: {cfg['url']}")
    out = Path(cfg["out"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    limit = cfg["limit"]
    collected = {}
    info = {"total": None, "has_more": True, "posts": []}
    popup = {"n": 0}

    hidden = cfg.get("hidden", True)
    log("Đang mở Chrome ở chế độ ẩn..." if hidden else "Đang mở Chrome...")
    with sync_playwright() as p:
        # Chế độ ẩn: vẫn là Chrome thật (Douyin không chặn), chỉ đặt cửa sổ ra ngoài màn hình.
        extra = ["--window-position=-32000,-32000"] if hidden else []
        # không cho Chrome "ngủ" khi cửa sổ bị che/ẩn, nếu không trang sẽ không tải thêm video khi cuộn
        extra += ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                  "--disable-background-timer-throttling"]
        ctx = p.chromium.launch_persistent_context(
            cfg["profile"], channel=cfg["channel"], headless=False,
            viewport={"width": 1280, "height": 900}, args=extra)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def show_window():
            try:
                cdp = ctx.new_cdp_session(page)
                wid = cdp.send("Browser.getWindowForTarget")["windowId"]
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                cdp.send("Browser.setWindowBounds",
                         {"windowId": wid, "bounds": {"left": 80, "top": 40, "width": 1280, "height": 900}})
                page.bring_to_front()
            except Exception as e:
                log(f"(Không đưa được cửa sổ Chrome ra giữa: {e})")

        def on_response(resp):
            u = resp.url
            if "aweme/post" in u:
                try:
                    data = resp.json()
                except Exception:
                    info["posts"].append(f"HTTP {resp.status}, không đọc được JSON (có thể bị chặn/captcha)")
                    return
                lst = data.get("aweme_list") or []
                info["posts"].append(f"HTTP {resp.status}, {len(lst)} video, status_code={data.get('status_code')}, "
                                     f"msg={str(data.get('status_msg') or '')[:60]}")
                for a in lst:
                    if a.get("aweme_id"):
                        collected[a["aweme_id"]] = a
                info["has_more"] = bool(data.get("has_more", 1))
            elif "user/profile/other" in u:
                try:
                    cnt = (resp.json().get("user") or {}).get("aweme_count")
                    if cnt:
                        info["total"] = int(cnt)
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(cfg["url"], wait_until="domcontentloaded")
        # Tự chờ danh sách video xuất hiện (tối đa 25 giây)
        t0 = time.time()
        closed_at, reloads = None, 0
        while not collected and time.time() - t0 < 25:
            if stop.is_set():
                ctx.close()
                raise Stopped()
            page.wait_for_timeout(500)
            if close_login_popup(page, log, popup):
                closed_at = closed_at or time.time()
            if closed_at and not collected and time.time() - closed_at > 3 and reloads < 2:
                # đã đóng khung đăng nhập mà vẫn chưa có danh sách -> tải lại trang để lấy lại
                log("Đã đóng khung đăng nhập nhưng chưa có danh sách, tải lại trang để lấy lại...")
                page.reload(wait_until="domcontentloaded")
                reloads, closed_at, t0 = reloads + 1, None, time.time()
            if time.time() - t0 > 8 and not collected:
                page.mouse.wheel(0, 1500)  # đôi khi phải cuộn nhẹ Douyin mới gọi danh sách
        if collected:
            log(f"Đã tự nhận danh sách video ({len(collected)} video đầu tiên), bắt đầu cuộn...")
        else:
            try:
                has_cap = page.evaluate("!!document.querySelector('#captcha_container, .captcha_verify_container, [class*=captcha]')")
                log(f"[Chẩn đoán] Trang: {page.url[:90]} | Tiêu đề: {page.title()[:50]} | "
                    f"Khung đăng nhập thấy {popup['n']} lần | Captcha: {'có' if has_cap else 'không'}")
                log("[Chẩn đoán] Phản hồi aweme/post: " + (" ; ".join(info["posts"][:5]) or "KHÔNG có phản hồi nào"))
            except Exception as e:
                log(f"[Chẩn đoán] lỗi: {e}")
            if hidden:
                show_window()
            log("Douyin cần đăng nhập hoặc xác minh captcha. Cửa sổ Chrome đã hiện ra: xử lý xong, "
                "tool sẽ TỰ chạy tiếp khi thấy danh sách video (hoặc bấm nút 'Đã thấy danh sách...').")
            def ready():
                page.wait_for_timeout(200)  # cho Playwright nhận phản hồi mạng
                return bool(collected)
            wait_user(ready)
        if stop.is_set():
            ctx.close()
            raise Stopped()

        def tot():
            return f"/{info['total']}" if info["total"] else ""

        page.mouse.move(640, 500)  # đặt chuột giữa danh sách để cuộn đúng khung
        idle, last, shown_win = 0, len(collected), False
        while True:
            if stop.is_set():
                ctx.close()
                raise Stopped()
            n = len(collected)
            if limit and n >= limit:
                break
            if not info["has_more"] or (info["total"] and n >= info["total"]):
                break  # Douyin báo đã hết video
            close_login_popup(page, log, popup)  # khung đăng nhập có thể bật lại giữa chừng và chặn cuộn
            try:
                page.evaluate(SCROLL_JS)
            except Exception:
                pass
            page.mouse.wheel(0, 4000)
            page.keyboard.press("End")
            page.wait_for_timeout(1500)  # chờ bằng Playwright để nó kịp nhận dữ liệu mạng
            n = len(collected)
            if n != last:
                log(f"Đã lấy {n}{tot()} video...")
                if info["total"]:
                    prog(n, info["total"])
                idle, last = 0, n
            else:
                idle += 1
                if idle == 6 and hidden and not shown_win:
                    # ẩn mà không cuộn được -> hiện cửa sổ ra thử tiếp
                    log("Chưa lấy thêm được video ở chế độ ẩn, đưa cửa sổ Chrome ra để thử tiếp...")
                    show_window()
                    page.mouse.move(640, 500)
                    shown_win, idle = True, 0
                elif idle >= 8:
                    break
        ua = page.evaluate("navigator.userAgent")
        cookies = ctx.cookies()
        ctx.close()

    items = sorted(collected.values(), key=lambda a: a.get("create_time", 0), reverse=True)
    if limit:
        items = items[:limit]
    (out / "links.txt").write_text(
        "\n".join(f"https://www.douyin.com/video/{a['aweme_id']}" for a in items), encoding="utf-8")
    msg = f"Lấy danh sách xong: {len(items)}{tot()} video. Chrome đã đóng."
    if info["total"] and len(items) < info["total"] and not limit:
        msg += (f" (Kênh báo {info['total']}, chênh {info['total'] - len(items)} video: có thể là video ẩn/riêng tư/đã gỡ, "
                "hoặc đã tải về từ trước. Bấm 'Lấy danh sách' lại nếu muốn thử tiếp.)")
    log(msg)
    return dict(items=items, cookies=cookies, ua=ua, total=info["total"])

def download_items(cfg, res, log, prog, stop):
    """Bước 2: tải video + thumbnail từ danh sách đã lấy."""
    try:
        import requests
    except ImportError:
        raise RuntimeError("Thiếu thư viện. Chạy: python -m pip install requests")
    out = Path(cfg["out"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    items, cookies, ua = res["items"], res["cookies"], res["ua"]
    log(f"Bắt đầu tải {len(items)} video vào {out}")

    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Referer": REFERER})
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))

    thumb_dir = out / "thumbnails"
    if cfg.get("thumbs", True):
        thumb_dir.mkdir(exist_ok=True)
    ok = fail = skipped = 0
    failed_ids = []
    prog(0, max(1, len(items)))
    for i, a in enumerate(items, 1):
        if stop.is_set():
            raise Stopped()
        vid = a["aweme_id"]
        name = video_name(a)
        mp4 = out / f"{name}.mp4"
        if cfg.get("thumbs", True):
            thumb = thumb_dir / f"{name}.png"
            old = out / f"{name}.cover.jpg"  # file của bản cũ (khung hình video): xoá
            if not thumb.exists():
                tmp_jpg = thumb_dir / f"{name}.tmp.jpg"
                done_thumb = False
                for cu in thumb_urls(a):
                    try:
                        if download_file(s, cu, tmp_jpg, stop, retries=2)[0]:
                            save_png(tmp_jpg, thumb)
                            done_thumb = True
                            break
                    except Stopped:
                        raise
                    except Exception:
                        continue  # ảnh định dạng lạ -> thử link kế tiếp
                    finally:
                        if tmp_jpg.exists():
                            tmp_jpg.unlink()
                if not done_thumb:
                    log(f"   không tải được thumbnail cho {vid}")
            if old.exists():
                old.unlink()
        if mp4.exists() and mp4.stat().st_size > 0:
            log(f"[{i}/{len(items)}] bỏ qua (đã có): {mp4.name}")
            skipped += 1
        else:
            url = pick_video_url(a)
            if not url:
                log(f"[{i}/{len(items)}] không có link video: {vid}")
                fail += 1
                failed_ids.append(vid)
            else:
                good, err = download_file(s, url, mp4, stop)
                if good:
                    (out / f"{name}.json").write_text(
                        json.dumps({"id": vid, "desc": a.get("desc"), "create_time": a.get("create_time")},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
                    log(f"[{i}/{len(items)}] đã tải: {mp4.name}")
                    ok += 1
                else:
                    log(f"[{i}/{len(items)}] LỖI ({err}): {vid}")
                    fail += 1
                    failed_ids.append(vid)
                time.sleep(cfg["sleep"])
        prog(i, len(items))

    summary = f"Tải xong. Tải mới: {ok} | Đã có từ trước: {skipped} | Lỗi: {fail}"
    log("XONG. " + summary)
    if failed_ids:
        (out / "failed_ids.txt").write_text("\n".join(failed_ids), encoding="utf-8")
        log("Có video lỗi (failed_ids.txt). Bấm tải lại để thử tiếp, file đã tải sẽ được bỏ qua.")
    return summary
