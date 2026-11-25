"""Ghép nhiều video thành 1 video tổng + watermark (chữ / logo PNG) di chuyển.
Không chứa giao diện: dùng chung cho bản máy tính (Tkinter) và bản web trên server."""
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import NO_WINDOW, Stopped, default_font, need, probe

def build_title_ops(*a, **k):
    from .titles import build_title_ops as _b
    return _b(*a, **k)

def list_clips(folder, order, seed=None):
    paths = sorted(Path(folder).expanduser().glob("*.mp4"), key=lambda p: p.name)
    if order == "newest":
        paths.reverse()
    elif order == "random":
        random.Random(seed).shuffle(paths)
    files = []
    skipped = []
    for p in paths:
        info = probe(p)
        if info:
            files.append((p, info[0], info[1]))
        else:
            skipped.append(p.name)
    return files, skipped

def pick_clips(files, target, tol):
    chosen, total = [], 0.0
    for f, dur, a in files:
        if total >= target:
            break
        if chosen and total + dur > target * (1 + tol):
            continue
        chosen.append((f, dur, a))
        total += dur
    return chosen, total

CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")

def font_family(font_path):
    """Tên họ font để libass chọn đúng file font đã chép vào thư mục tạm."""
    return "Arial" if font_path and Path(font_path).name.lower().startswith("arial") else "DejaVu Sans"

def find_srt(folder, stem):
    """Tìm file phụ đề tiếng Việt của video: ưu tiên tên.vi.srt, rồi tên.vie.srt, rồi tên.srt."""
    d = Path(folder).expanduser()
    for suf in (".vi.srt", ".vie.srt", ".srt"):
        p = d / (stem + suf)
        if p.is_file():
            return p
    return None

def read_srt(path):
    """Đọc SRT -> list (bắt đầu_s, kết_thúc_s, chữ)."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1258", errors="replace")
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(lines):
            m = SRT_TIME.search(l)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                body = "\n".join(lines[i + 1:]).strip()
                if body:
                    cues.append((a, b, body))
                break
    return cues

def fmt_srt(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

def merge_srts(chosen, folder, log=None):
    """Gộp phụ đề của từng video đã chọn thành 1 danh sách cue (bắt đầu, kết thúc, chữ), cộng dồn mốc thời gian
    theo thứ tự ghép. Trả về (list cue, số video có phụ đề)."""
    out, offset, found = [], 0.0, 0
    for f, dur, _ in chosen:
        p = find_srt(folder, f.stem)
        if p is None:
            if log:
                log(f"  Không thấy phụ đề tiếng Việt cho: {f.name}")
        else:
            cues = read_srt(p)
            cjk = sum(1 for _, _, t in cues if len(CJK_RE.findall(t)) > len(t) * 0.3)
            if cues and cjk > len(cues) * 0.5:
                if log:
                    log(f"  Bỏ qua {p.name}: là phụ đề tiếng Trung, không phải tiếng Việt")
            else:
                found += 1
                for a, b, t in cues:
                    if a < dur:
                        out.append((a + offset, min(b, dur) + offset, t))
        offset += dur
    return out, found

def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"

def text_measurer(font_path, fs):
    """Hàm đo chiều rộng chữ (px) bằng chính font sẽ dùng để vẽ phụ đề; không có Pillow thì ước lượng."""
    try:
        from PIL import ImageFont
        if font_path and Path(font_path).exists():
            f = ImageFont.truetype(str(font_path), fs)
            return lambda t: f.getlength(t) * 1.04
    except Exception:
        pass
    return lambda t: len(t) * fs * 0.6

def wrap_text(text, measure, max_w):
    """Ngắt dòng theo chiều rộng tối đa; giữ các dòng đã xuống dòng sẵn."""
    lines = []
    for para in text.replace("\r", "").split("\n"):
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if cur and measure(trial) > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    return [l for l in lines if l] or [""]

def plan_layout(w, h, cover, vsub, cues, font_path):
    """Tính khung che (band) và chỗ đặt phụ đề Việt.
    Khung che luôn phủ hết vùng chữ Trung đã dò/đặt VÀ dài, cao hơn cả dòng phụ đề Việt dài nhất."""
    fs = max(10, int(h * vsub["size"] / 100)) if vsub else 0
    measure = text_measurer(font_path, fs) if vsub else None
    wrapped, vw, vl = [], 0, 1
    if vsub:
        max_w = w * 0.92
        for a, b, t in cues:
            lines = wrap_text(t, measure, max_w)
            wrapped.append((a, b, lines))
            vw = max(vw, max(measure(l) for l in lines))
            vl = max(vl, len(lines))
    band = None
    cy = h * 0.92
    if cover:
        cw = min(w, w * cover.get("width", 100) / 100)
        y0, ch = h * cover["top"] / 100, h * cover["height"] / 100
        bw, bh = cw, ch
        if vsub:
            bw = max(bw, vw + fs * 1.2)
            bh = max(bh, vl * fs * 1.25 + fs * 0.5)
        bw, bh = min(w, bw), min(h, bh)
        cy = y0 + ch / 2
        bx = (w - bw) / 2
        by = min(max(0, cy - bh / 2), h - bh)
        band = tuple(int(round(v / 2)) * 2 for v in (bx, by, bw, bh))
        cy = band[1] + band[3] / 2
    return dict(fs=fs, band=band, cx=w / 2, cy=cy, wrapped=wrapped, vw=vw, lines=vl)

def make_ass(w, h, lay, family):
    fs = lay["fs"]
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,"
            "Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,"
            "MarginV,Encoding\nStyle: Vi,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,%d,1,5,0,0,0,1"
            "\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
            % (w, h, family, fs, max(2, fs // 14)))
    rows = []
    for a, b, lines in lay["wrapped"]:
        txt = "\\N".join(l.replace("{", "(").replace("}", ")") for l in lines)
        rows.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Vi,,0,0,0,,{{\\an5\\pos({lay['cx']:.0f},{lay['cy']:.0f})}}{txt}")
    return head + "\n".join(rows) + "\n"

def build_filter(chosen, w, h, fps, wm, cover=None, lay=None, audio=True, tops=None):
    """wm: dict(mode='text'|'logo'|'none', text, font, fontsize, opacity, speed, margin, logo_h)"""
    parts = []
    n = len(chosen)
    for i, (_, dur, has_a) in enumerate(chosen):
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},format=yuv420p[v{i}]")
        if not audio:
            continue
        if has_a:
            parts.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")
        else:
            parts.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={dur:.3f},asetpts=PTS-STARTPTS[a{i}]")
    if audio:
        labels = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{labels}concat=n={n}:v=1:a=1[vc][a]")
    else:
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc]")

    cur = "vc"
    if tops:
        from .titles import title_filters
        parts.append(title_filters(tops, cur, "vtit"))
        cur = "vtit"
    band = lay["band"] if lay else None
    if cover and band:
        bx, by, bw, bh = band
        if cover["style"] == "box":
            parts.append(f"[{cur}]drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=black@0.92:t=fill[vcov]")
        else:
            parts.append(f"[{cur}]split[cv1][cv2];[cv2]crop={bw}:{bh}:{bx}:{by},"
                         f"boxblur=luma_radius={max(1, min(bh // 2 - 1, 30))}:luma_power=3:"
                         f"chroma_radius={max(1, min(bh // 4 - 1, 15))}:chroma_power=3,"
                         f"eq=brightness=-0.15[cvb];[cv1][cvb]overlay={bx}:{by}[vcov]")
        cur = "vcov"
    if lay and lay["wrapped"]:
        parts.append(f"[{cur}]ass=sub_vi.ass:fontsdir=fonts[vsub]")
        cur = "vsub"

    m, sp, op = wm.get("margin", 30), wm.get("speed", 0.15), wm.get("opacity", 0.35)
    mode = wm.get("mode", "text")
    if mode == "text":
        clean = re.sub(r"[':\\%]", "", wm["text"])
        font_opt = f"fontfile='{wm['font']}':" if wm.get("font") else ""
        x = f"{m}+(w-text_w-{2 * m})*(0.5+0.5*sin(t*{sp}))"
        y = f"{m}+(h-text_h-{2 * m})*(0.5+0.5*sin(t*{sp * 0.69:.4f}+1.3))"
        parts.append(
            f"[{cur}]drawtext={font_opt}text='{clean}':fontsize={wm['fontsize']}:"
            f"fontcolor=white@{op}:borderw=2:bordercolor=black@{op * 0.6:.2f}:"
            f"shadowcolor=black@0.4:shadowx=2:shadowy=2:x='{x}':y='{y}'[vout]")
    elif mode == "logo":
        # logo là input thứ n (sau các clip)
        parts.append(f"[{n}:v]scale=-1:{wm['logo_h']},format=rgba,colorchannelmixer=aa={op}[lg]")
        x = f"{m}+(W-w-{2 * m})*(0.5+0.5*sin(t*{sp}))"
        y = f"{m}+(H-h-{2 * m})*(0.5+0.5*sin(t*{sp * 0.69:.4f}+1.3))"
        parts.append(f"[{cur}][lg]overlay=x='{x}':y='{y}':shortest=1:format=auto[vout]")
    else:
        parts.append(f"[{cur}]null[vout]")
    return ";".join(parts)

def run_compile(cfg, log, prog, stop, dry=False):
    need("ffmpeg")
    need("ffprobe")
    m = re.fullmatch(r"(\d+)x(\d+)", cfg["size"])
    if not m:
        raise RuntimeError("Kích thước phải có dạng 1920x1080")
    w, h = int(m.group(1)), int(m.group(2))

    log("Đang đọc thông tin các video...")
    files, skipped = list_clips(cfg["folder"], cfg["order"], cfg.get("seed"))
    for s in skipped:
        log(f"Bỏ qua file lỗi/không đọc được: {s}")
    if not files:
        raise RuntimeError("Không có video .mp4 nào dùng được trong thư mục này.")
    chosen, total = pick_clips(files, cfg["target"], cfg["tol"])
    log(f"Sẽ ghép {len(chosen)} video, tổng {total / 60:.1f} phút (mục tiêu {cfg['target'] / 60:.1f} phút):")
    for i, (f, d, a) in enumerate(chosen, 1):
        log(f"  {i:>3}. {d:6.1f}s {'' if a else '[không có tiếng] '}{f.name}")
    if total < cfg["target"] * 0.7:
        log(f"Lưu ý: tổng chỉ {total / 60:.1f} phút, ít hơn mục tiêu. Cần thêm video hoặc giảm thời lượng mục tiêu.")
    if len(chosen) > 80:
        raise RuntimeError("Quá nhiều video trong một lần ghép (>80). Giảm thời lượng mục tiêu.")
    cover = cfg.get("cover")
    vs = cfg.get("vsub")
    cues = []
    if vs:
        log("Đang tìm phụ đề tiếng Việt...")
        cues, found = merge_srts(chosen, vs["folder"], log)
        if not cues:
            raise RuntimeError("Không tìm thấy file phụ đề tiếng Việt nào khớp với các video "
                               "(đặt tên 'tên_video.vi.srt' trong thư mục phụ đề).")
        log(f"Có phụ đề tiếng Việt cho {found}/{len(chosen)} video.")
    if dry:
        return None

    wm = dict(cfg["wm"])
    tmp = Path(tempfile.mkdtemp(prefix="nimokids_"))
    try:
        if wm["mode"] == "text":
            font = wm.get("font") or default_font()
            if font and Path(font).exists():
                lf = tmp / ("wmfont" + Path(font).suffix)  # tên đơn giản, tránh lỗi "C:" trong drawtext
                shutil.copyfile(font, lf)
                wm["font"] = lf.name
            else:
                wm["font"] = None
                log("Không tìm thấy font, ffmpeg sẽ dùng font mặc định (có thể lỗi).")
        elif wm["mode"] == "logo":
            if not wm.get("logo") or not Path(wm["logo"]).exists():
                raise RuntimeError("Chưa chọn file logo PNG.")

        sf = default_font()
        lay = plan_layout(w, h, cover, vs, cues, sf)
        if vs:
            (tmp / "sub_vi.ass").write_text(make_ass(w, h, lay, font_family(sf)), encoding="utf-8")
            if sf and Path(sf).exists():
                (tmp / "fonts").mkdir(exist_ok=True)
                shutil.copyfile(sf, tmp / "fonts" / ("subfont" + Path(sf).suffix))
        if cover and lay["band"]:
            bx, by, bw, bh = lay["band"]
            log(f"Khung che chữ cũ: rộng {bw}px ({bw * 100 // w}% khung hình), cao {bh}px"
                + (f"; dòng phụ đề Việt dài nhất {int(lay['vw'])}px, tối đa {lay['lines']} dòng" if vs else ""))
        tops = []
        tt = cfg.get("titles")
        if tt:
            tops = build_title_ops(chosen, w, h, tt["folder"], tt["lang"], sf, tmp, log)
            log(f"Chữ tiêu đề: sẽ che và viết lại {len(tops)} chữ.")
            if tops and sf and Path(sf).exists():
                shutil.copyfile(sf, tmp / "titlefont.ttf")
        fc = build_filter(chosen, w, h, cfg["fps"], wm, cover, lay, tops=tops)
        total_dur = cfg["target"] if cfg["exact"] else total
        out = Path(cfg["out"]).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-nostats", "-progress", "pipe:1"]
        for f, _, _ in chosen:
            cmd += ["-i", str(f.resolve())]
        if wm["mode"] == "logo":
            cmd += ["-loop", "1", "-t", f"{total + 5:.1f}", "-i", str(Path(wm["logo"]).resolve())]
        cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg["crf"]), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest"]
        if cfg["exact"]:
            cmd += ["-t", str(cfg["target"])]
        cmd += [str(out)]

        log("Đang render... (có thể mất vài phút, đừng đóng cửa sổ)")
        prog(0, 1000)
        proc = subprocess.Popen(cmd, cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        errors = []
        for line in proc.stdout:
            line = line.strip()
            if stop.is_set():
                proc.terminate()
                proc.wait()
                if out.exists():
                    out.unlink()
                raise Stopped()
            if line.startswith("out_time_ms="):
                try:
                    done = int(line.split("=")[1]) / 1e6
                    prog(min(1000, int(1000 * done / max(1, total_dur))), 1000)
                except ValueError:
                    pass
            elif "=" not in line and line:
                errors.append(line)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError("ffmpeg lỗi:\n" + "\n".join(errors[-8:]))
        prog(1000, 1000)
        log(f"XONG: {out}")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def ensure_rapidocr(log):
    """Cài thư viện nhận dạng chữ (chỉ lần đầu, ~50-100MB)."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        pass
    from .subtitles import pip_install
    log("Đang cài thư viện nhận dạng chữ (chỉ lần đầu, vài phút)...")
    return pip_install(["rapidocr-onnxruntime"], log)

def grab_frame(video, t, dest, crop_bottom=None, max_w=None):
    """Lấy 1 khung hình ở giây t ra file ảnh (có thể chỉ lấy phần dưới / thu nhỏ)."""
    vf = []
    if crop_bottom:
        vf.append(f"crop=iw:ih*{crop_bottom}:0:ih*{1 - crop_bottom}")
    if max_w:
        vf.append(f"scale='min({max_w},iw)':-2")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    r = subprocess.run(cmd + [str(dest)], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0 and Path(dest).exists()

def detect_cn_region(videos, log, stop, n_frames=12, max_videos=3, bottom=0.5):
    """Tự dò vị trí dòng phụ đề chữ Trung cứng trong video bằng OCR (RapidOCR, chạy CPU).
    Lấy ~n_frames khung hình mỗi video, chỉ xét nửa dưới, giữ ô chữ có ký tự Hán xuất hiện ở nhiều khung.
    Trả về dict(top, height, width) tính bằng % khung hình (đã chừa lề), hoặc None nếu không thấy."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise RuntimeError("Thiếu thư viện nhận dạng chữ. Chạy: py -3.13 -m pip install rapidocr-onnxruntime")
    need("ffmpeg")
    engine = RapidOCR()
    videos = list(videos)
    if len(videos) > max_videos:
        idx = sorted({round(i * (len(videos) - 1) / (max_videos - 1)) for i in range(max_videos)})
        videos = [videos[i] for i in idx]
    tmp = Path(tempfile.mkdtemp(prefix="nimokids_ocr_"))
    boxes, frames = [], 0
    try:
        from PIL import Image
        for vp in videos:
            info = probe(vp)
            if not info:
                continue
            dur = info[0]
            for k in range(n_frames):
                if stop.is_set():
                    raise Stopped()
                t = dur * (0.08 + 0.84 * k / max(1, n_frames - 1))
                img = tmp / "f.png"
                if img.exists():
                    img.unlink()
                if not grab_frame(vp, t, img, crop_bottom=bottom, max_w=1280):
                    continue
                W, H = Image.open(img).size
                frames += 1
                res, _ = engine(str(img))
                for pts, text, score in (res or []):
                    if not CJK_RE.search(text) or float(score) < 0.5:
                        continue
                    xs = [pt[0] for pt in pts]
                    ys = [pt[1] for pt in pts]
                    boxes.append((frames, min(xs) / W, max(xs) / W,
                                  (1 - bottom) + min(ys) / H * bottom, (1 - bottom) + max(ys) / H * bottom))
            log(f"  Đã quét {vp.name} ({frames} khung hình, thấy {len(boxes)} ô chữ Trung)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not boxes or not frames:
        return None
    # gom các ô chữ theo độ cao (cùng một dòng phụ đề), chọn dòng xuất hiện ở nhiều khung nhất
    boxes.sort(key=lambda b: (b[3] + b[4]) / 2)
    clusters = []
    for b in boxes:
        cyb = (b[3] + b[4]) / 2
        if clusters and abs(cyb - clusters[-1]["cy"]) < 0.04:
            clusters[-1]["items"].append(b)
            clusters[-1]["cy"] = sum((i[3] + i[4]) / 2 for i in clusters[-1]["items"]) / len(clusters[-1]["items"])
        else:
            clusters.append(dict(cy=cyb, items=[b]))
    best = max(clusters, key=lambda c: len({i[0] for i in c["items"]}))
    seen = len({i[0] for i in best["items"]})
    if seen < max(2, 0.3 * frames):
        return None
    it = best["items"]
    x0, x1 = min(i[1] for i in it), max(i[2] for i in it)
    y0, y1 = min(i[3] for i in it), max(i[4] for i in it)
    half = max(abs(x1 - 0.5), abs(0.5 - x0))
    pad_y = 0.012
    top = max(0.0, y0 - pad_y)
    height = min(1 - top, (y1 - y0) + 2 * pad_y)
    width = min(1.0, 2 * half + 0.03)
    return dict(top=round(top * 100, 1), height=round(height * 100, 1), width=round(width * 100, 1),
                seen=seen, frames=frames)

def preview_frame(cfg, log, dest):
    """Dựng thử 1 khung hình (video đầu tiên) với đúng khung che, phụ đề Việt và watermark đang chọn."""
    need("ffmpeg")
    need("ffprobe")
    m = re.fullmatch(r"(\d+)x(\d+)", cfg["size"])
    if not m:
        raise RuntimeError("Kích thước phải có dạng 1920x1080")
    w, h = int(m.group(1)), int(m.group(2))
    files, _ = list_clips(cfg["folder"], cfg["order"], cfg.get("seed"))
    if not files:
        raise RuntimeError("Không có video .mp4 nào dùng được trong thư mục này.")
    chosen = files[:1]
    cover, vs = cfg.get("cover"), cfg.get("vsub")
    tt = cfg.get("titles")
    cues, t = [], chosen[0][1] * 0.4
    t_title = None
    if tt:  # xem thử ở video đầu tiên đã dò chữ, đúng lúc chữ đầu tiên đang hiện
        import json
        for f in files:
            jf = Path(tt["folder"]) / f"{f[0].stem}.titles.json"
            if jf.exists():
                its = json.loads(jf.read_text(encoding="utf-8")).get("items", [])
                if its:
                    chosen, t_title = [f], (its[0]["start"] + its[0]["end"]) / 2
                    t = t_title
                    break
        if t_title is None:
            log("Chưa có video nào được dò chữ: bấm 'Dò chữ' trước.")
    if vs:
        cues, _ = merge_srts(chosen, vs["folder"], log)
        if cues and t_title is None:
            longest = max(cues, key=lambda c: len(c[2]))  # chọn câu dài nhất để kiểm tra khung đủ rộng
            t = (longest[0] + longest[1]) / 2
        else:
            log("Video đầu tiên chưa có phụ đề tiếng Việt khớp tên, xem thử chỉ có khung che.")
    wm = dict(cfg["wm"])
    tmp = Path(tempfile.mkdtemp(prefix="nimokids_pv_"))
    try:
        if wm["mode"] == "text":
            font = wm.get("font") or default_font()
            if font and Path(font).exists():
                lf = tmp / ("wmfont" + Path(font).suffix)
                shutil.copyfile(font, lf)
                wm["font"] = lf.name
            else:
                wm["font"] = None
        elif wm["mode"] == "logo" and not (wm.get("logo") and Path(wm["logo"]).exists()):
            wm["mode"] = "none"
        sf = default_font()
        lay = plan_layout(w, h, cover, vs if cues else None, cues, sf)
        if cues:
            (tmp / "sub_vi.ass").write_text(make_ass(w, h, lay, font_family(sf)), encoding="utf-8")
            if sf and Path(sf).exists():
                (tmp / "fonts").mkdir(exist_ok=True)
                shutil.copyfile(sf, tmp / "fonts" / ("subfont" + Path(sf).suffix))
        tops = []
        if tt and t_title is not None:
            tops = build_title_ops(chosen, w, h, tt["folder"], tt["lang"], sf, tmp, log, t_shift=t)
            if tops and sf and Path(sf).exists():
                shutil.copyfile(sf, tmp / "titlefont.ttf")
        fc = build_filter(chosen, w, h, cfg["fps"], wm, cover, lay, audio=False, tops=tops)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, t - 0.0):.2f}", "-i", str(chosen[0][0].resolve())]
        if wm["mode"] == "logo":
            cmd += ["-loop", "1", "-t", "30", "-i", str(Path(wm["logo"]).resolve())]
        # -ss đặt trước -i làm mốc thời gian về 0, nên dịch mốc phụ đề lùi đúng t giây rồi mới dựng khung
        if cues:
            shifted = [(a - t, b - t, ln) for a, b, ln in lay["wrapped"]]
            lay2 = dict(lay, wrapped=shifted)
            (tmp / "sub_vi.ass").write_text(make_ass(w, h, lay2, font_family(sf)), encoding="utf-8")
        cmd += ["-filter_complex", fc, "-map", "[vout]", "-frames:v", "1", str(Path(dest).resolve())]
        r = subprocess.run(cmd, cwd=str(tmp), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
        if r.returncode != 0 or not Path(dest).exists():
            raise RuntimeError("ffmpeg lỗi:\n" + "\n".join(r.stderr.strip().splitlines()[-6:]))
        return Path(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def make_logo_png(path, size=800):
    """Vẽ logo Nimo Kids (mặt cười + 2 tai) thành PNG nền trong suốt bằng Pillow."""
    from PIL import Image, ImageDraw
    S = 4
    N = size * S
    k = N / 120.0
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def circ(cx, cy, r, fill):
        d.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=fill)

    coral, yellow, navy = (255, 107, 90, 255), (255, 201, 60, 255), (30, 42, 82, 255)
    circ(26, 26, 17, coral)
    circ(94, 26, 17, coral)
    circ(60, 64, 50, yellow)
    circ(43, 58, 6, navy)
    circ(77, 58, 6, navy)
    circ(34, 76, 7, (255, 107, 90, 140))
    circ(86, 76, 7, (255, 107, 90, 140))
    pts = []
    for i in range(41):
        u = i / 40
        x = (1 - u) ** 2 * 44 + 2 * (1 - u) * u * 60 + u ** 2 * 76
        y = (1 - u) ** 2 * 78 + 2 * (1 - u) * u * 94 + u ** 2 * 78
        pts.append((x, y))
    for x, y in pts:
        circ(x, y, 3, navy)
    return im.resize((size, size), Image.LANCZOS), path
