"""Phụ đề SRT bằng faster-whisper (GPU NVIDIA nếu có), ngắt câu theo mốc thời gian từng từ.
Không chứa giao diện: dùng chung cho bản máy tính (Tkinter) và bản web trên server."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .common import NO_WINDOW, Stopped, app_data_dir, fmt_duration, need

WHISPER_MODELS = ["small", "medium", "large-v3", "base", "tiny"]

MODEL_SIZE_NOTE = {"tiny": "75MB", "base": "150MB", "small": "500MB", "medium": "1.5GB", "large-v3": "3GB"}

SPOKEN_LANGS = {"Tự nhận dạng": None, "Tiếng Trung": "zh", "Tiếng Anh": "en", "Tiếng Việt": "vi",
                "Tiếng Nhật": "ja", "Tiếng Hàn": "ko"}

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".wav")

def python_console_exe():
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        exe = exe.with_name("python.exe")
    return str(exe)

def has_nvidia():
    return bool(shutil.which("nvidia-smi"))

def add_cuda_dll_dirs():
    """Windows: thêm thư mục DLL của gói nvidia-cublas-cu12 / nvidia-cudnn-cu12 để faster-whisper chạy GPU."""
    import site
    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    found = []
    for r in roots:
        for sub in ("cublas", "cudnn", "cuda_runtime"):
            d = Path(r) / "nvidia" / sub / "bin"
            if d.is_dir():
                found.append(str(d))
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(str(d))
                    except OSError:
                        pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")
    return found

def pip_install(pkgs, log):
    p = subprocess.Popen([python_console_exe(), "-m", "pip", "install", "--user"] + pkgs,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    for line in p.stdout:
        line = line.strip()
        if line.startswith(("Collecting", "Successfully", "ERROR")):
            log("   " + line)
    return p.wait() == 0

def ensure_cuda_libs(log):
    try:
        import importlib.util
        if importlib.util.find_spec("nvidia.cublas") and importlib.util.find_spec("nvidia.cudnn"):
            return True
    except Exception:
        pass
    log("Có card NVIDIA: đang cài thư viện GPU (cuBLAS + cuDNN, ~1GB, chỉ lần đầu)...")
    return pip_install(["nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"], log)

def ensure_faster_whisper(log):
    try:
        import faster_whisper  # noqa: F401
        return
    except ImportError:
        pass
    log("Đang cài faster-whisper (chỉ lần đầu, 1-3 phút)...")
    if not pip_install(["faster-whisper"], log):
        raise RuntimeError("Cài faster-whisper thất bại. Mở PowerShell chạy: python -m pip install faster-whisper")
    import importlib
    import site
    us = site.getusersitepackages()
    if us not in sys.path:
        sys.path.append(us)
    importlib.invalidate_caches()
    import faster_whisper  # noqa: F401

HF_REPO = "Systran/faster-whisper-{}"

MODEL_FILES = ["config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "model.bin"]

def download_model(size, log, prog, stop):
    """Tải model Whisper về %LOCALAPPDATA%\\NimoKidsTool\\models\\<size> (không dùng bộ tải của huggingface_hub
    vì nó hay treo với file lớn). Có % tiến độ, tải tiếp được nếu bị ngắt."""
    import requests
    d = app_data_dir() / "models" / size
    d.mkdir(parents=True, exist_ok=True)
    base = f"https://huggingface.co/{HF_REPO.format(size)}/resolve/main/"
    if all((d / f).exists() for f in MODEL_FILES) and not (d / "model.bin.part").exists():
        return d
    sess = requests.Session()
    sizes = {}
    for f in MODEL_FILES:  # hỏi trước dung lượng từng file
        try:
            r = sess.head(base + f, allow_redirects=True, timeout=20)
            sizes[f] = int(r.headers.get("content-length") or 0)
        except Exception:
            sizes[f] = 0
    total = sum(sizes.values()) or 1
    done_before = sum(sizes[f] for f in MODEL_FILES if (d / f).exists())
    log(f"Đang tải model '{size}' ({total / 1e9:.1f} GB) vào {d} ...")
    got = done_before
    last_log = time.time()
    t0, got0 = time.time(), got
    for f in MODEL_FILES:
        final, part = d / f, d / (f + ".part")
        if final.exists() and (not sizes[f] or final.stat().st_size == sizes[f]):
            continue
        for attempt in range(1, 6):
            if stop.is_set():
                raise Stopped()
            have = part.stat().st_size if part.exists() else 0
            hdr = {"Range": f"bytes={have}-"} if have else {}
            try:
                with sess.get(base + f, headers=hdr, stream=True, timeout=(15, 60), allow_redirects=True) as r:
                    if r.status_code == 416:  # đã đủ
                        break
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    if r.status_code == 200 and have:
                        got -= have
                        have = 0  # máy chủ không cho tải tiếp -> tải lại từ đầu
                    with open(part, "ab" if have else "wb") as fh:
                        for chunk in r.iter_content(1024 * 1024):
                            if stop.is_set():
                                raise Stopped()
                            fh.write(chunk)
                            got += len(chunk)
                            prog(int(1000 * got / total), 1000)
                            if time.time() - last_log > 5:
                                spd = (got - got0) / max(1, time.time() - t0)
                                eta = (total - got) / spd if spd > 0 else 0
                                log(f"   tải model: {got / 1e6:,.0f}/{total / 1e6:,.0f} MB "
                                    f"({100 * got / total:.0f}%) - {spd / 1e6:.1f} MB/s - còn khoảng {fmt_duration(eta)}")
                                last_log = time.time()
                break
            except Stopped:
                raise
            except Exception as e:
                log(f"   lỗi mạng ({e}), thử lại lần {attempt}...")
                time.sleep(3 * attempt)
        else:
            raise RuntimeError(f"Không tải được {f}. Kiểm tra mạng rồi bấm lại.")
        if part.exists():
            part.replace(final)
    log("Tải model xong.")
    return d

def load_audio_16k(path):
    """Đọc âm thanh bằng ffmpeg -> mảng float32 16kHz mono (Whisper cần đúng định dạng này).
    Không dùng bộ đọc 'av' của faster-whisper vì bản av mới không tương thích (lỗi metadata_errors)."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "s16le", "-"], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg không đọc được âm thanh: " + r.stderr.decode("utf-8", "replace")[-300:])
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0

CJK_RANGES = ((0x3040, 0x30ff), (0x3400, 0x9fff), (0xac00, 0xd7af), (0xf900, 0xfaff))

END_PUNCT = tuple(".?!。？！…")

HALLUCINATIONS = ("请不吝点赞", "订阅 转发", "打赏支持", "明镜与点点", "字幕由", "字幕志愿者", "Amara.org",
                  "Thank you for watching", "Thanks for watching", "Subtitles by", "ご視聴ありがとう")

def is_cjk(text):
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in CJK_RANGES)

def build_cues(words, max_dur=5.0, gap=0.6):
    """Ghép từng từ (có mốc thời gian) thành câu phụ đề ngắn, dễ đọc - giống TurboScribe.
    Ngắt câu khi: im lặng > gap giây, câu dài quá max_dur giây / quá nhiều chữ, hoặc gặp dấu kết câu."""
    cues, cur = [], []

    def flush():
        if cur:
            text = "".join(w[2] for w in cur).strip()
            if text and not any(h.lower() in text.lower() for h in HALLUCINATIONS):
                cues.append((cur[0][0], cur[-1][1], text))
            cur.clear()

    for w in words:
        start, end, text = w
        if cur:
            joined = "".join(x[2] for x in cur)
            max_chars = 18 if is_cjk(joined) else 42
            if (start - cur[-1][1] > gap or end - cur[0][0] > max_dur
                    or len((joined + text).strip()) > max_chars):
                flush()
        cur.append((start, end, text))
        if text.strip().endswith(END_PUNCT):
            flush()
    flush()
    return cues

def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def write_srt(segments, path):
    lines = []
    for i, (a, b, text) in enumerate(segments, 1):
        lines += [str(i), f"{srt_time(a)} --> {srt_time(b)}", text.strip(), ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")

def collect_media(src):
    p = Path(src).expanduser()
    if p.is_dir():
        return sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT)
    return [p] if p.exists() else []

def run_transcribe(cfg, log, prog, stop):
    """cfg: src, model, lang, task('transcribe'|'translate'), device('auto'|'cpu'), skip, txt"""
    files = collect_media(cfg["src"])
    if not files:
        raise RuntimeError("Không tìm thấy video/âm thanh nào.")
    need("ffmpeg")
    ensure_faster_whisper(log)
    from faster_whisper import WhisperModel

    model_dir = download_model(cfg["model"], log, prog, stop)

    def load(device):
        ct = "float16" if device == "cuda" else "int8"
        log(f"Đang nạp model '{cfg['model']}' trên {'GPU' if device == 'cuda' else 'CPU'}...")
        t = time.time()
        m = WhisperModel(str(model_dir), device=device, compute_type=ct)
        log(f"   nạp model xong ({fmt_duration(time.time() - t)})")
        return m

    device = "cpu"
    if cfg["device"] == "auto" and has_nvidia():
        if ensure_cuda_libs(log):
            import importlib
            import site
            us = site.getusersitepackages()
            if us not in sys.path:
                sys.path.append(us)
            importlib.invalidate_caches()
            add_cuda_dll_dirs()
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    device = "cuda"
            except Exception:
                pass
        if device == "cpu":
            log("Không bật được GPU, chạy bằng CPU (chậm hơn).")
    try:
        model = load(device)
    except Exception as e:
        if device != "cuda":
            raise
        log(f"GPU lỗi khi nạp model ({str(e)[:120]}), chuyển sang CPU...")
        device = "cpu"
        model = load("cpu")

    done = 0
    results = []
    for idx, f in enumerate(files, 1):
        if stop.is_set():
            raise Stopped()
        out_dir = f.parent / "subtitles"
        out_dir.mkdir(exist_ok=True)
        srt = out_dir / (f.stem + (".en" if cfg["task"] == "translate" else "") + ".srt")
        if cfg["skip"] and srt.exists():
            log(f"[{idx}/{len(files)}] bỏ qua (đã có phụ đề): {f.name}")
            continue
        log(f"[{idx}/{len(files)}] Đang nghe: {f.name}")
        t_file = time.time()
        # Đã thử trên video thật của kênh: tắt VAD + mốc thời gian từng từ cho câu đầy đủ, đúng thời gian nhất;
        # VAD làm mất câu ngắn, còn ép ngôn ngữ sai / gợi ý (prompt) dễ làm Whisper "bịa" câu khi có nhạc.
        kw = dict(language=cfg["lang"], task=cfg["task"], vad_filter=False, beam_size=5,
                  word_timestamps=True, condition_on_previous_text=False)
        for attempt in (1, 2):
            try:
                audio = load_audio_16k(f)
                if audio.size < 1600:  # dưới 0,1 giây âm thanh
                    log("   video không có tiếng, bỏ qua.")
                    items = []
                    break
                segs, info = model.transcribe(audio, **kw)
                total = max(1.0, audio.size / 16000)
                if attempt == 1 and not cfg["lang"]:
                    log(f"   ngôn ngữ nhận ra: {info.language} ({info.language_probability:.0%})")
                words = []
                for sg in segs:
                    if stop.is_set():
                        raise Stopped()
                    if sg.words:
                        words += [(w.start, w.end, w.word) for w in sg.words]
                    else:
                        words.append((sg.start, sg.end, sg.text))
                    prog(int(1000 * min(1.0, sg.end / total)), 1000)
                items = build_cues(words)  # ngắt thành câu phụ đề ngắn + bỏ câu "bịa"
                break
            except Stopped:
                raise
            except Exception as e:
                if device == "cuda" and attempt == 1:
                    log(f"   GPU lỗi ({str(e)[:120]}), chuyển sang CPU...")
                    device = "cpu"
                    model = load("cpu")
                    continue
                raise
        write_srt(items, srt)
        if cfg.get("txt"):
            srt.with_suffix(".txt").write_text("\n".join(t.strip() for _, _, t in items), encoding="utf-8")
        log(f"   -> {srt.name} ({len(items)} câu, mất {fmt_duration(time.time() - t_file)})")
        results.append(srt)
        done += 1
        prog(1000, 1000)
    return f"Xong {done} file phụ đề. Lưu trong thư mục 'subtitles' cạnh video."
