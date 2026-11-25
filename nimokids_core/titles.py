"""Thẻ chữ / chữ tiêu đề trong video: dò chữ Trung bằng OCR, xuất file SRT để dịch, nhập bản dịch,
rồi che chữ cũ bằng màu nền và viết bản dịch lên đúng chỗ, đúng lúc.
Không chứa giao diện: dùng chung cho bản máy tính (Tkinter) và bản web trên server.

Quy trình:
  1. detect_texts(): quét video ~1 khung/giây, ghi  titles/<tên>.titles.json (vị trí, thời gian, màu)
     và  titles/<tên>.titles.srt (chữ Trung, đánh số) để đem đi dịch.
  2. Người dùng dịch, lưu thành  titles/<tên>.titles.<đuôi ngôn ngữ>.srt  (ví dụ .titles.vi.srt).
     Mốc thời gian trong file dịch có thể lệch vài giây: tool chỉ lấy CHỮ, còn thời gian và vị trí
     lấy từ lần dò (ghép theo thứ tự; nếu lệch số lượng thì ghép theo mốc thời gian gần nhất).
  3. build_title_ops(): tạo các lệnh che + viết chữ để compile.py đưa vào bộ lọc ffmpeg.
"""
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .common import NO_WINDOW, Stopped, need

CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def titles_dir(folder):
    return Path(folder).expanduser() / "titles"


def probe_size(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0:s=x", str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    m = re.match(r"(\d+)x(\d+)", r.stdout.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def fmt_srt(t):
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def read_numbered_srt(path):
    """Đọc SRT -> list (số thứ tự hoặc None, bắt đầu, kết thúc, chữ), giữ nguyên thứ tự trong file."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1258", errors="replace")
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = TIME_RE.search(ln)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                idx = int(lines[i - 1]) if i > 0 and lines[i - 1].strip().isdigit() else None
                body = "\n".join(lines[i + 1:]).strip()
                if body:
                    out.append((idx, a, b, body))
                break
    return out


# --------------------------------------------------------------------------------------- dò chữ
def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _extract_frames(video, dest, fps, max_w=960):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"fps={fps},scale='min({max_w},iw)':-2",
           str(Path(dest) / "f%05d.png")]
    return subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).returncode == 0


def _sample_colors(img, box):
    """Màu nền quanh ô chữ (để tô che) và màu chữ (điểm ảnh khác nền nhất trong ô)."""
    import numpy as np
    H, W = img.shape[:2]
    x0, y0, x1, y1 = (int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H))
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    bh = max(2, y1 - y0)
    m1, m2 = max(4, int(bh * 0.35)), max(8, int(bh * 0.8))
    ex = lambda m: (max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m))  # noqa: E731
    ox0, oy0, ox1, oy1 = ex(m2)
    ix0, iy0, ix1, iy1 = ex(m1)
    mask = np.ones((H, W), bool)
    mask[:] = False
    mask[oy0:oy1, ox0:ox1] = True
    mask[iy0:iy1, ix0:ix1] = False
    ring = img[mask]
    fill = np.median(ring, axis=0) if len(ring) else np.array([0, 0, 0])
    inside = img[y0:y1, x0:x1].reshape(-1, 3).astype(float)
    if len(inside) == 0:
        return [int(v) for v in fill], [255, 255, 255]
    lum = lambda a: a @ np.array([0.299, 0.587, 0.114])  # noqa: E731
    diff = np.abs(lum(inside) - float(lum(fill.astype(float))))
    k = max(1, len(inside) // 10)
    top = inside[np.argsort(diff)[-k:]]
    return [int(v) for v in fill], [int(v) for v in np.median(top, axis=0)]


def detect_texts(clips, out_dir, log, prog, stop, ignore_below=0.84, fps=1.0, redo=False):
    """Dò chữ Trung (không phải phụ đề cuối khung) trong các clip, ghi .titles.json và .titles.srt.
    clips: list (đường dẫn, thời lượng, có_tiếng). ignore_below: bỏ qua chữ có tâm thấp hơn mức này (tỉ lệ chiều cao).
    Trả về (số video đã quét, tổng số chữ tìm thấy)."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        from PIL import Image
    except ImportError:
        raise RuntimeError("Thiếu thư viện nhận dạng chữ. Chạy: py -3.13 -m pip install rapidocr-onnxruntime")
    need("ffmpeg")
    need("ffprobe")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR()
    scanned = total = 0
    prog(0, max(1, len(clips)))
    for ci, (path, dur, _) in enumerate(clips):
        if stop.is_set():
            raise Stopped()
        jf = out_dir / f"{path.stem}.titles.json"
        if jf.exists() and not redo:
            try:
                n = len(json.loads(jf.read_text(encoding="utf-8")).get("items", []))
            except Exception:
                n = 0
            log(f"[{ci + 1}/{len(clips)}] đã dò từ trước ({n} chữ), bỏ qua: {path.name}")
            total += n
            prog(ci + 1, len(clips))
            continue
        size = probe_size(path)
        if not size:
            log(f"[{ci + 1}/{len(clips)}] không đọc được kích thước: {path.name}")
            continue
        tmp = Path(tempfile.mkdtemp(prefix="nimokids_tt_"))
        try:
            if not _extract_frames(path, tmp, fps):
                log(f"[{ci + 1}/{len(clips)}] không tách được khung hình: {path.name}")
                continue
            frames = sorted(tmp.glob("f*.png"))
            open_items, items = [], []
            for fi, fp in enumerate(frames):
                if stop.is_set():
                    raise Stopped()
                t = fi / fps
                W, H = Image.open(fp).size
                res, _ = engine(str(fp))
                for pts, text, score in (res or []):
                    if float(score) < 0.5 or len(CJK_RE.findall(text)) < 2:
                        continue
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    box = (min(xs) / W, min(ys) / H, max(xs) / W, max(ys) / H)
                    if (box[1] + box[3]) / 2 > ignore_below:
                        continue
                    best, best_iou = None, 0.0
                    for it in open_items:
                        if t - it["last"] > max(2.0, 2.5 / fps):
                            continue
                        iou = _iou(box, it["box"])
                        if (text in it["texts"] and iou > 0.05) or iou >= 0.3:
                            if iou >= best_iou:
                                best, best_iou = it, iou
                    if best is None:
                        best = dict(texts=[], box=list(box), first=t, last=t, obs=[], conf=[])
                        open_items.append(best)
                        items.append(best)
                    best["texts"].append(text)
                    best["box"] = [min(best["box"][0], box[0]), min(best["box"][1], box[1]),
                                   max(best["box"][2], box[2]), max(best["box"][3], box[3])]
                    best["last"] = t
                    best["obs"].append(fi)
            out_items = []
            for it in items:
                if len(it["obs"]) < 2:
                    continue  # chữ chớp 1 khung: thường là nhiễu
                if dur > 12 and (it["last"] - it["first"]) >= 0.8 * dur:
                    log(f"   bỏ qua chữ cố định suốt video (watermark kênh): {Counter(it['texts']).most_common(1)[0][0]}")
                    continue
                cnt = Counter(it["texts"])
                text = max(cnt.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
                mid = frames[it["obs"][len(it["obs"]) // 2]]
                fill, color = _sample_colors(np.asarray(Image.open(mid).convert("RGB")), it["box"])
                pad = 0.6 / fps
                out_items.append(dict(start=round(max(0.0, it["first"] - pad), 2),
                                      end=round(min(dur, it["last"] + pad + 1.0 / fps * 0.5), 2),
                                      box=[round(v, 4) for v in it["box"]], text=text, fill=fill, color=color))
            out_items.sort(key=lambda d: (d["start"], d["box"][1]))
            for i, d in enumerate(out_items, 1):
                d["id"] = i
            jf.write_text(json.dumps(dict(version=1, src_w=size[0], src_h=size[1], duration=dur, items=out_items),
                                     ensure_ascii=False, indent=1), encoding="utf-8")
            srt = "\n".join(f"{d['id']}\n{fmt_srt(d['start'])} --> {fmt_srt(d['end'])}\n{d['text']}\n"
                            for d in out_items)
            (out_dir / f"{path.stem}.titles.srt").write_text(srt, encoding="utf-8")
            log(f"[{ci + 1}/{len(clips)}] {path.name}: {len(out_items)} chữ")
            scanned += 1
            total += len(out_items)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        prog(ci + 1, len(clips))
    return scanned, total


# ------------------------------------------------------------------------------- nhập bản dịch
def match_items(items, cues, log=None):
    """Ghép chữ dịch với từng chữ đã dò. Trả về {id: chữ dịch}.
    Cùng số lượng -> ghép theo thứ tự (không phụ thuộc mốc thời gian, chịu được lệch vài giây).
    Khác số lượng -> ghép theo mốc bắt đầu gần nhất (trong 6 giây)."""
    good = [c for c in cues if len(CJK_RE.findall(c[3])) <= len(c[3]) * 0.3]
    if len(good) < len(cues) and log:
        log(f"   {len(cues) - len(good)} dòng trong file dịch vẫn là chữ Trung, bỏ qua")
    out = {}
    if len(good) == len(items):
        for it, c in zip(items, good):
            out[it["id"]] = c[3]
        return out
    used = set()
    for it in items:
        best, bd = None, 6.0
        for k, c in enumerate(good):
            if k in used:
                continue
            d = abs(c[1] - it["start"])
            if d <= bd:
                best, bd = k, d
        if best is not None:
            used.add(best)
            out[it["id"]] = good[best][3]
    if log:
        log(f"   Số dòng dịch ({len(good)}) khác số chữ đã dò ({len(items)}): ghép theo mốc thời gian gần nhất, "
            f"khớp {len(out)}/{len(items)}")
    return out


def build_title_ops(chosen, w, h, tdir, lang, font_path, tmp, log, t_shift=0.0):
    """Tạo danh sách lệnh (che bằng màu nền + viết bản dịch) theo thời gian của video tổng.
    chosen: list (đường dẫn, thời lượng, có_tiếng) theo thứ tự ghép. t_shift: trừ bớt mốc (dùng cho xem thử)."""
    from .compile import font_family, text_measurer, wrap_text  # noqa: F401
    ops, offset, n_ops = [], 0.0, 0
    for path, dur, _ in chosen:
        jf = Path(tdir) / f"{path.stem}.titles.json"
        sf = Path(tdir) / f"{path.stem}.titles.{lang}.srt"
        if not jf.exists():
            log(f"  Chưa dò chữ cho: {path.name}")
        elif not sf.exists():
            log(f"  Chưa có file dịch {sf.name}")
        else:
            data = json.loads(jf.read_text(encoding="utf-8"))
            items = data["items"]
            matched = match_items(items, read_numbered_srt(sf), log)
            sw, sh = data["src_w"], data["src_h"]
            s = min(w / sw, h / sh)
            ox, oy = (w - sw * s) / 2, (h - sh * s) / 2
            for it in items:
                text = matched.get(it["id"])
                if not text:
                    continue
                x0, y0, x1, y1 = it["box"]
                px0, py0, px1, py1 = ox + x0 * sw * s, oy + y0 * sh * s, ox + x1 * sw * s, oy + y1 * sh * s
                bw, bh = px1 - px0, py1 - py0
                pad = max(6.0, 0.25 * bh)
                fx, fy = max(0, px0 - pad), max(0, py0 - pad)
                fw, fh = min(w - fx, bw + 2 * pad), min(h - fy, bh + 2 * pad)
                # cỡ chữ: bắt đầu theo chiều cao ô chữ gốc, thu nhỏ cho vừa chiều rộng (tối đa 2 dòng)
                max_w = min(w * 0.9, max(bw * 1.8, w * 0.45))
                fs0 = int(min(max(14, bh * 0.8), h * 0.2))
                fs, lines = fs0, None
                for f in range(fs0, 13, -2):  # ưu tiên 1 dòng nếu chỉ phải thu nhỏ tối đa 30%, không thì cho 2 dòng
                    ls = wrap_text(text, text_measurer(font_path, f), max_w)
                    if len(ls) == 1 and f >= fs0 * 0.7:
                        fs, lines = f, ls
                        break
                    if len(ls) <= 2 and lines is None and f <= fs0 * 0.7:
                        fs, lines = f, ls
                if lines is None:
                    fs = 14
                    lines = wrap_text(text, text_measurer(font_path, fs), max_w)
                cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
                lh = fs * 1.2
                ys = [cy + (i - (len(lines) - 1) / 2) * lh for i in range(len(lines))]
                line_files = []
                for ln, y in zip(lines, ys):
                    n_ops += 1
                    tf = tmp / f"tt_{n_ops}.txt"
                    tf.write_text(ln, encoding="utf-8")
                    line_files.append((tf.name, y))
                ops.append(dict(
                    rect=tuple(int(round(v / 2)) * 2 for v in (fx, fy, fw, fh)),
                    fill="0x%02x%02x%02x" % tuple(it["fill"]), color="0x%02x%02x%02x" % tuple(it["color"]),
                    start=max(0.0, it["start"] + offset - t_shift), end=it["end"] + offset - t_shift,
                    fs=fs, cx=cx, lines=line_files))
        offset += dur
    return ops


def title_filters(ops, cur, label):
    """Chuỗi bộ lọc ffmpeg: [cur] -> [label] (tô che + viết chữ dịch, bật đúng khoảng thời gian)."""
    if not ops:
        return None
    chain = []
    for op in ops:
        en = f"enable='between(t,{op['start']:.2f},{op['end']:.2f})'"
        x, y, w, h = op["rect"]
        chain.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={op['fill']}:t=fill:{en}")
        bw = max(2, op["fs"] // 16)
        for name, ly in op["lines"]:
            chain.append(f"drawtext=fontfile=titlefont.ttf:textfile={name}:fontsize={op['fs']}:fontcolor={op['color']}:"
                         f"borderw={bw}:bordercolor=black@0.55:x={op['cx']:.0f}-text_w/2:y={ly:.0f}-text_h/2:{en}")
    return f"[{cur}]" + ",".join(chain) + f"[{label}]"
