# -*- coding: utf-8 -*-
"""
YouTube Downloader (by tfrog)
Paste a link (or open your own video), optionally pick a time range,
get an MP4 (H.264 + AAC), an MP3 or a GIF - and the thumbnail as JPG.

Requires: Python 3.10+, yt-dlp[default], PySide6, FFmpeg, Deno  ->  installed by the setup.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

APP = "YouTube Downloader"
APP_VERSION = "2.9.11"
UPDATE_REPO = "TFrogVFX/youtube-downloader"   # "Update app" loads the newest version from this GitHub repo
UPDATE_BASE = f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/"
APP_ID = "tfrog.YouTubeDownloader"  # Windows AppUserModelID (own taskbar entry)
APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "tfrog_ytclip"
CFG_FILE = APP_DIR / "config.json"
WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
YT_URL = re.compile(r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)
ANY_URL = re.compile(r"https?://\S+", re.I)
YDL_EXTRA: dict = {}   # options for every yt-dlp call (browser login / cookies), set by the app
ANSI = re.compile(r"\x1b\[[0-9;]*m")
UPDATE_INTERVAL = 20 * 3600  # auto-update yt-dlp at most once a day

QUALITIES = {
    "Best available": None,
    "2160p (4K)": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}
MP3_QUALITIES = {"320 kbps": 320, "256 kbps": 256, "192 kbps": 192, "128 kbps": 128}
ENCODERS = ["CPU", "NVIDIA GPU (NVENC)"]
CODECS = {  # label -> (codec, ProRes profile)
    "H.264 (MP4)": ("h264", None),
    "H.265 / HEVC (MP4)": ("hevc", None),
    "ProRes 422 (MOV)": ("prores", 2),
    "ProRes 422 HQ (MOV)": ("prores", 3),
}
AUDIO_FORMATS = {"MP3": "mp3", "WAV": "wav", "M4A (AAC)": "m4a"}
DEFAULT_CODEC = "H.264 (MP4)"
DEFAULT_AUDIO = "MP3"
SIZES = {  # name -> CRF  (None = original, "mb" = target size)
    "Original": None,
    "High": 20,
    "Medium": 23,
    "Small": 26,
    "Target MB": "mb",
}
SIZE_HINTS = {
    "Original": "YouTube file without re-encoding when possible",
    "High": "CRF 20 · barely visible difference",
    "Medium": "CRF 23 · good balance",
    "Small": "CRF 26 · much smaller, fine detail suffers",
    "Target MB": "file ends up about this size",
}
GIF_WIDTHS = {"320 px": 320, "480 px": 480, "640 px": 640, "800 px": 800}
GIF_FPS = {"10 fps": 10, "12 fps": 12, "15 fps": 15, "20 fps": 20, "25 fps": 25}
GIF_COLORS = {"Best (256 colors)": 256, "Smaller (128 colors)": 128, "Smallest (64 colors)": 64}
GIF_MAX = 30          # seconds
GIF_RECOMMENDED = 10  # seconds
ORIGINAL_CRF = 18  # used when "Original" still has to encode (clips, VP9/AV1 sources)
PIECE_CRF = 14     # intermediate clips that get encoded once more (joining, crop, subtitles …)
DEFAULT_QUALITY = "Best available"
DEFAULT_MP3 = "320 kbps"
DEFAULT_ENCODER = ENCODERS[0]
DEFAULT_SIZE = "Original"
VIDEO_TAIL = ["-pix_fmt", "yuv420p"]
PP_NAMES = {
    "Merger": "Merging video + audio",
    "ExtractAudio": "Converting audio",
    "Metadata": "Writing tags",
    "EmbedThumbnail": "Embedding cover art",
    "ThumbnailsConvertor": "Preparing cover art",
    "MoveFiles": "Finishing",
}
EXT = {"mp4": ".mp4", "mp3": ".mp3", "gif": ".gif"}  # mode keys (kept for old settings files)
PRORES_HINTS = {2: "Editing codec · 10-bit 4:2:2 · roughly 1 GB per minute at 1080p",
                3: "Editing codec · 10-bit 4:2:2 · roughly 1.5 GB per minute at 1080p"}
AUDIO_HINTS = {"mp3": "With title, artist and cover art.",
               "wav": "Uncompressed 16-bit PCM for editing · ~10 MB per minute · no cover art",
               "m4a": "AAC with title and cover art · YouTube audio is kept without re-encoding"}

# ---- hover help (Settings → "Show help when hovering")
ITEM_HELP = {
    # quality
    "Best available": "The highest resolution this video has.",
    "2160p (4K)": "Up to 3840 × 2160. Big files.",
    "1440p": "Up to 2560 × 1440.",
    "1080p": "Up to 1920 × 1080 (Full HD).",
    "720p": "Up to 1280 × 720. Small and quick.",
    "480p": "Up to 854 × 480. Smallest.",
    # codec
    "H.264 (MP4)": "Plays everywhere: phones, browsers, editing apps, WhatsApp, Discord …",
    "H.265 / HEVC (MP4)": "Same look at roughly half the size. Needs a newer device or player "
                          "and takes longer to encode.",
    "ProRes 422 (MOV)": "Editing codec for Premiere, After Effects, Resolve … "
                        "Scrubs smoothly, but the files are very large.",
    "ProRes 422 HQ (MOV)": "Higher-quality ProRes for grading and compositing. Even larger files.",
    # size
    "Original": "Keeps the YouTube file as it is when possible – best quality, no waiting for an encode.",
    "High": "Re-encodes with almost no visible difference. Noticeably smaller.",
    "Medium": "Good balance of quality and size.",
    "Small": "Much smaller files. Fine detail and dark areas suffer.",
    "Target MB": "Type a size in MB – the bitrate is chosen so the file ends up about that big "
                 "(e.g. for upload limits).",
    # encoder
    "CPU": "Encodes on the processor. Works on every PC and gives the best quality per MB.",
    "NVIDIA GPU (NVENC)": "Encodes on an NVIDIA graphics card – much faster. "
                          "Falls back to the CPU automatically if the card or driver can't do it.",
    # audio format
    "MP3": "Plays everywhere. Small, with title, artist and cover art.",
    "WAV": "Uncompressed audio for editing and DAWs. Large, no cover art.",
    "M4A (AAC)": "Better quality per MB than MP3. YouTube's own AAC audio is copied without re-encoding.",
    # bitrate
    "320 kbps": "Highest quality · about 2.4 MB per minute.",
    "256 kbps": "Very good · about 1.9 MB per minute.",
    "192 kbps": "Good · about 1.4 MB per minute.",
    "128 kbps": "OK for speech and podcasts · about 1 MB per minute.",
    # gif
    "320 px": "Tiny – stickers and reactions.",
    "480 px": "Good default for chats and forums.",
    "640 px": "Sharper, but noticeably bigger files.",
    "800 px": "Large – only for very short clips.",
    "10 fps": "Choppy but very small.",
    "12 fps": "Slightly smoother, still small.",
    "15 fps": "Good default – smooth enough, reasonable size.",
    "20 fps": "Smooth motion, bigger files.",
    "25 fps": "Smoothest, biggest files.",
    "Best (256 colors)": "Best-looking gradients and skin tones.",
    "Smaller (128 colors)": "Smaller file, slight banding in gradients.",
    "Smallest (64 colors)": "Smallest file, visible banding.",
    # theme
    "Dark": "Neutral dark grey.",
    "Midnight": "Dark blue.",
    "Light": "Bright theme for daylight.",
}
# ---- frame (crop)
# AI upscaling for pictures (Save frame / Save thumbnail) – label -> (engine, model, file key or None, help)
AI_UPSCALES = {"Off": None, "2×": 2, "4×": 4}
SPEEDS = {"0.25×": 0.25, "0.5×": 0.5, "0.75×": 0.75, "Normal (1×)": 1.0, "1.25×": 1.25, "1.5×": 1.5, "2×": 2.0,
          "3×": 3.0, "4×": 4.0}
DEFAULT_SPEED = "Normal (1×)"
AI_MODELS = {
    "UltraSharp – photos, films": ("esrgan", "ultrasharp-4x", "ultrasharp",
                                   "4x-UltraSharp (Kim2091): very sharp, lots of detail – the favourite for real "
                                   "footage, games and photos."),
    "Siax – natural detail (large)": ("esrgan", "4x_NMKD-Siax_200k", "siax",
                                      "4x NMKD Siax (Nmkd), the big 64 MB model: natural, calm detail, good on faces "
                                      "and skin."),
    "Nomos8kSC – YouTube / compressed": ("esrgan", "4xNomos8kSC", "nomos",
                                         "4xNomos8kSC (Phhofm): trained on blurry, compressed pictures – cleans "
                                         "YouTube blocks and noise while it upscales."),
    "Real-ESRGAN – classic": ("esrgan", "realesrgan-x4plus", None,
                              "Real-ESRGAN x4plus (xinntao): the all-rounder, a bit softer."),
    "Real-CUGAN Pro – anime best": ("cugan", "pro", None,
                                    "Real-CUGAN Pro (Bilibili): the cleanest anime lines and flat colors. "
                                    "2× uses the Pro model, 4× the SE model."),
    "HFA2k – anime detailed": ("esrgan", "4xHFA2k", "hfa2k",
                               "4xHFA2k (Phhofm): High Fidelity Anime – keeps fine lines, texture and grain."),
    "Real-ESRGAN anime – fast": ("esrgan", "realesrgan-x4plus-anime", None,
                                 "Real-ESRGAN x4plus anime: quick and clean."),
}
DEFAULT_AI_MODEL = "UltraSharp – photos, films"
AI_PX_PRESETS = [(1920, "Full HD"), (2560, "QHD"), (3840, "4K"), (5120, "5K"), (7680, "8K")]
FREE = "free"            # "Custom": a box of any shape
ASPECTS = {"Off": None, "16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:3": (4, 3), "Custom": FREE}
# volume curve: how the volume goes from a point to the next one
EASES = {"Linear": "linear", "Easy ease": "ease", "Ease in": "in", "Ease out": "out", "Hold": "hold"}
FONTS_DIR = APP_DIR / "fonts"
SUB_STYLE = {"font": "Arial", "font_file": "", "size": 100, "color": "#ffffff", "outline": "#000000",
             "bold": True, "pos": None}
COOKIE_FILE = APP_DIR / "youtube_login.txt"   # YouTube login (cookies), taken from the sign-in in your browser
SIGNIN_DIR = APP_DIR / "signin"                 # old own browser profile (up to 2.9.1) – removed once
LOGIN_URL = ("https://accounts.google.com/ServiceLogin?service=youtube&uilel=3&passive=true"
             "&continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin%3Dtrue%26app%3Ddesktop"
             "%26next%3Dhttps%253A%252F%252Fwww.youtube.com%252F")
HISTORY_MAX = 500
# where the history (links + small pictures) and the small preview copies are kept – changeable in Settings
DEFAULT_PATHS = {"history": APP_DIR / "history", "preview": APP_DIR / "preview"}
PATHS = dict(DEFAULT_PATHS)
SUB_TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

LOCAL_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".ts", ".m2ts", ".mts", ".flv", ".wmv", ".mpg",
              ".mpeg", ".3gp", ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}

# ---- appearance (user can change theme + accent color in the app)
THEMES = {
    "Dark": dict(bg="#0d0e10", panel="#15161a", panel2="#1d1f24", field="#111216", border="#272a31",
                 border_hi="#3a3e47", text="#ececee", muted="#8b8f99", dark=True),
    "Midnight": dict(bg="#0a0f1c", panel="#101829", panel2="#172036", field="#0c1323", border="#22304a",
                     border_hi="#33456a", text="#e6ebf5", muted="#8792aa", dark=True),
    "Light": dict(bg="#eef0f3", panel="#ffffff", panel2="#f2f3f6", field="#f7f8fa", border="#dcdfe5",
                  border_hi="#c3c8d1", text="#16181d", muted="#6b7280", dark=False),
}
ACCENTS = [("Lime", "#c4f240"), ("Mint", "#3ddc97"), ("Cyan", "#22d3ee"), ("Blue", "#4d8bff"),
           ("Violet", "#a78bfa"), ("Pink", "#ff5fa2"), ("Red", "#ff4d4d"), ("Orange", "#ff9f43"),
           ("Yellow", "#ffd43b")]
DEFAULT_THEME = "Dark"
DEFAULT_ACCENT = "#ff4d4d"
WARN_COLOR = "#f0b429"
ERR_COLOR = "#ff6b6b"


# ----------------------------------------------------------------------------- helpers

def refresh_path() -> None:
    """Reload PATH from the registry so fresh winget installs are found without logging off."""
    if not WIN:
        return
    import winreg
    dirs: list[str] = []
    for hive, key in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                dirs += os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(";")
        except OSError:
            pass
    dirs += [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        os.path.expandvars(r"%ProgramFiles%\WinGet\Links"),
        os.path.expanduser(r"~\.deno\bin"),
    ]
    seen, merged = set(), []
    for d in os.environ.get("PATH", "").split(os.pathsep) + dirs:
        if d and d.lower() not in seen:
            seen.add(d.lower())
            merged.append(d)
    os.environ["PATH"] = os.pathsep.join(merged)


def find_tool(name: str) -> str | None:
    hit = shutil.which(name)
    if hit:
        return hit
    if WIN:  # fallback: search winget package folders
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        for pattern in (f"*/*/bin/{name}.exe", f"*/{name}.exe"):
            for p in base.glob(pattern):
                os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")
                return str(p)
    return None


def parse_time(text: str) -> float | None:
    """'10' = minute 10 · '10:30' · '1:02:30' · '90s' · '1.5h'  ->  seconds"""
    s = text.strip().lower().replace(",", ".")
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        if len(parts) > 3:
            raise ValueError(text)
        sec = 0.0
        for p in parts:
            sec = sec * 60 + float(p or 0)
        if sec < 0:
            raise ValueError(text)
        return sec
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|hr|m|min|s|sec)?", s)
    if not m:
        raise ValueError(text)
    mult = {"h": 3600, "hr": 3600, "s": 1, "sec": 1}.get(m.group(2), 60)
    return float(m.group(1)) * mult


def fmt_t(sec: float) -> str:
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def fmt_ts(sec: float) -> str:
    """Display format for time fields: 1:05, 1:05.5, 1:02:03"""
    sec = max(0.0, float(sec))
    whole = int(sec)
    frac = sec - whole
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    out = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if frac >= 0.05:
        out += f".{int(round(frac * 10)) % 10}"
    return out


def fmt_tf(sec: float) -> str:
    """Time fields: as exact as needed (frame-accurate cuts) - 1:05, 1:05.5, 1:05.52"""
    cs = int(round(max(0.0, float(sec)) * 100))
    s_, c_ = divmod(cs, 100)
    h, rest = divmod(s_, 3600)
    m, s_ = divmod(rest, 60)
    out = f"{h}:{m:02d}:{s_:02d}" if h else f"{m}:{s_:02d}"
    return out + (f".{c_:02d}".rstrip("0") if c_ else "")


def fmt_tc(sec: float) -> str:
    """Timecode of the preview with 1/100 s: 1:31.24, 1:02:03.50"""
    cs = int(round(max(0.0, float(sec)) * 100))
    s, c = divmod(cs, 100)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return (f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}") + f".{c:02d}"


def safe_name(name: str) -> str:
    """File name without characters Windows does not allow."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return name[:150]


def unique_name(outdir, name: str, ext: str) -> str:
    """name -> name (2) -> name (3) ... if a file with that name already exists."""
    base = safe_name(name) or "download"
    cand, i = base, 2
    while (Path(outdir) / f"{cand}{ext}").exists():
        cand = f"{base} ({i})"
        i += 1
    return cand


def load_cfg() -> dict:
    try:
        return json.loads(CFG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cfg(cfg: dict) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CFG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def probe(ffprobe: str | None, path: Path):
    """-> (video_codec, audio_codec, duration_sec)"""
    if not ffprobe:
        return None, None, 0.0
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name:stream_disposition=attached_pic:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    streams = data.get("streams", [])
    v = next((s.get("codec_name") for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), None)
    try:
        dur = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return v, a, dur


def video_ext(codec: str) -> str:
    return ".mov" if codec == "prores" else ".mp4"


def video_args(encoder: str, crf: int | None = None, kbps: int | None = None,
               codec: str = "h264", profile: int | None = None) -> list[str]:
    if codec == "prores":  # editing codec: 10-bit 4:2:2, size is fixed by the profile
        return ["-c:v", "prores_ks", "-profile:v", str(profile or 2), "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]
    nv = encoder.startswith("NVIDIA")
    rate = (["-b:v", f"{kbps}k", "-maxrate", f"{kbps * 3 // 2}k", "-bufsize", f"{kbps * 2}k"] if kbps else None)
    if codec == "hevc":  # CRF scale of x265 is ~4 higher than x264 for the same look
        if nv:
            v = ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr"] + (rate or ["-cq", str(crf + 3), "-b:v", "0"])
        else:
            v = ["-c:v", "libx265", "-preset", "medium", "-x265-params", "log-level=error"] + \
                (rate or ["-crf", str(crf + 4)])
        return v + ["-tag:v", "hvc1"] + VIDEO_TAIL  # hvc1 tag: plays in QuickTime / Apple devices
    if nv:
        v = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr"] + (rate or ["-cq", str(crf + 1), "-b:v", "0"])
    else:
        v = ["-c:v", "libx264", "-preset", "medium"] + (rate or ["-crf", str(crf)])
    return v + VIDEO_TAIL


def encode_args(encoder: str, size: str, target_mb: float | None, duration: float | None,
                codec: str = "h264", profile: int | None = None):
    """-> (video_args, audio_args) for the selected size and codec"""
    if codec == "prores":
        return video_args(encoder, codec="prores", profile=profile), ["-c:a", "pcm_s16le"]
    mode = SIZES.get(size)
    abr = 128 if mode in ("mb", 26) else 192
    aargs = ["-c:a", "aac", "-b:a", f"{abr}k"]
    if mode == "mb":
        if not duration:
            raise RuntimeError("Video length unknown – 'Target MB' can't be used here.")
        total_kbit = target_mb * 1048576 * 8 / 1000
        kbps = int(total_kbit / duration * 0.96) - abr  # 4 % headroom for container/variance
        if kbps < 200:
            need = (200 + abr) * duration / 0.96 / (1048576 * 8 / 1000)
            raise RuntimeError(f"{target_mb:g} MB is too small for {fmt_t(duration)} – "
                               f"you need at least ~{need:.0f} MB (or a shorter clip).")
        return video_args(encoder, kbps=kbps, codec=codec), aargs
    crf = PIECE_CRF if size == "_piece" else (mode if isinstance(mode, int) else ORIGINAL_CRF)
    return video_args(encoder, crf=crf, codec=codec), aargs


FF_REPORT = APP_DIR / "ffmpeg_report_ffmpeg.log"  # written by ffmpeg itself (FFREPORT)


def enable_ffmpeg_report() -> None:
    """Every ffmpeg run (also the ones started by yt-dlp) writes its warnings/errors to a file.
    Without this, ffmpeg's error text is lost under pythonw and only an exit code remains."""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    base = str(APP_DIR).replace("%", "%%").replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    os.environ["FFREPORT"] = f"file={base}/ffmpeg_report_%p.log:level=24"


def ffmpeg_report_tail(since: float, n: int = 6) -> str:
    """Last error lines of the most recent ffmpeg run (only if it ran after `since`)."""
    try:
        if FF_REPORT.stat().st_mtime < since - 1:
            return ""
        lines = FF_REPORT.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for i, line in enumerate(lines):
        if line.startswith("Command line:"):
            lines = lines[i + 2:]
            break
    lines = [x.strip() for x in lines if x.strip() and not x.startswith("Report written")]
    return "\n".join(lines[-n:])


def clean_error(ex) -> str:
    msg = ANSI.sub("", str(ex)).strip() or ex.__class__.__name__
    return re.sub(r"^ERROR:\s*", "", msg)


_NVENC: dict = {}


def check_encoder(encoder: str, ffmpeg, emit, codec: str = "h264") -> str:
    """NVENC needs an NVIDIA GPU with a recent driver - fall back to the CPU instead of failing."""
    if codec == "prores" or not encoder.startswith("NVIDIA") or not ffmpeg:
        return encoder
    nv = "hevc_nvenc" if codec == "hevc" else "h264_nvenc"
    key = (ffmpeg, nv)
    if key not in _NVENC:
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                "-i", "color=c=black:s=256x256:d=0.2", "-c:v", nv, "-f", "null", "-"],
                               capture_output=True, timeout=60, creationflags=NO_WINDOW)
            _NVENC[key] = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _NVENC[key] = False
    if _NVENC[key]:
        return encoder
    emit("log", f"NVENC ({nv}) is not available on this PC (no NVIDIA GPU or driver too old) – using the CPU.")
    return DEFAULT_ENCODER


def run_encode(cmd, dur, emit, label, cwd=None) -> None:
    """Run ffmpeg (with -progress pipe:1), report progress, raise with ffmpeg's own error text."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    err: list[str] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    last = 0.0
    for line in proc.stdout:
        if dur and line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                pct = min(100.0, int(line.split("=", 1)[1]) / 1e6 / dur * 100)
            except ValueError:
                continue
            if pct - last >= 0.5:
                last = pct
                emit("progress", pct)
                emit("status", f"{label} … {pct:.0f} %")
    rc = proc.wait()
    reader.join(5)
    if rc != 0:
        lines = [x for x in "".join(err).splitlines() if x.strip() and not x.startswith("Report written")]
        raise RuntimeError("FFmpeg error:\n" + ("\n".join(lines[-8:]) or f"exit code {rc}"))


def cut_local(src: Path, dst: Path, start: float, end, extra_args, ffmpeg, emit, label) -> Path:
    """Frame-accurate cut of a local file (input seeking + the given codec args)."""
    length = (end - start) if end is not None else None
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += [*extra_args, "-progress", "pipe:1", "-nostats", str(tmp)]
    emit("progress", 0 if length else None)
    try:
        run_encode(cmd, length, emit, label)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def _clip_bounds(start, end, dur):
    s = start or 0.0
    if dur and s >= dur:
        raise ValueError(f"Start time {fmt_t(s)} is past the end of the video ({fmt_t(dur)}).")
    e = end
    if dur:
        e = dur if e is None else min(e, dur)
    return s, e


def _remove_leftovers(dst: Path) -> None:
    """Delete what the failed direct attempt left next to the result (thumbnail, .part files)."""
    import glob
    for f in Path(dst.parent).glob(glob.escape(dst.stem) + ".*"):
        if f.name != dst.name and f.is_file():
            try:
                f.unlink()
            except OSError:
                pass


def _note_fallback(ex, since, emit) -> None:
    emit("log", f"Direct clip download failed: {clean_error(ex)}")
    tail = ffmpeg_report_tail(since)
    if tail:
        emit("log", "ffmpeg said:\n" + tail)
    emit("log", "Falling back: downloading the whole video and cutting it locally …")


def finalize(src: Path, encoder, size, target_mb, ffmpeg, ffprobe, emit, encoded: bool,
             codec: str = "h264", profile: int | None = None) -> Path:
    """Make sure the result has the requested codec (H.264/H.265 MP4 or ProRes MOV) and size."""
    v, a, dur = probe(ffprobe, src)
    if ffprobe and v is None and a is None:
        src.unlink(missing_ok=True)
        raise RuntimeError("The file is empty – is the start time past the end of the video?")
    ext = video_ext(codec)
    a_ok = ("pcm_s16le", "pcm_s24le") if codec == "prores" else ("aac",)
    force = codec != "prores" and SIZES.get(size) is not None and not encoded  # a size was picked
    usable = src.suffix.lower() == ext and v in (codec, None) and a in (*a_ok, None)
    if usable and not force:
        return src

    need_v = force or (v is not None and v != codec)
    need_a = force or (a is not None and a not in a_ok)
    enc_v, enc_a = (encode_args(encoder, size, target_mb, dur, codec, profile) if (need_v or need_a)
                    else ([], []))
    vargs = enc_v if need_v else ["-c:v", "copy"]
    aargs = enc_a if need_a else ["-c:a", "copy"]

    dst = src.with_suffix(ext)
    tmp = src.with_name(src.stem + ".encoding" + ext)
    what = "ProRes" if codec == "prores" else ("H.265" if codec == "hevc" else "H.264")
    label_ = (f"Encoding {what}" + ("" if codec == "prores" or size == "_piece" else f" ({size})")) if need_v \
        else f"Remuxing to {ext[1:].upper()}"
    emit("status", f"{label_} …")
    emit("progress", 0 if dur else None)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-map", "0:v:0?", "-map", "0:a:0?", *vargs, *aargs, "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", str(tmp)]
    try:
        run_encode(cmd, dur, emit, label_)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if usable and tmp.stat().st_size >= src.stat().st_size:
        # the YouTube file was already smaller -> re-encoding would only lose quality
        tmp.unlink(missing_ok=True)
        emit("log", f"'{size}' would be larger than the YouTube original – kept the original.")
        return src
    os.replace(tmp, dst)
    if src != dst:
        src.unlink(missing_ok=True)
    return dst


def collect_files(info) -> list[str]:
    if not info:
        return []
    if info.get("entries") is not None:
        out: list[str] = []
        for e in info["entries"]:
            out += collect_files(e)
        return out
    return [d["filepath"] for d in info.get("requested_downloads") or [] if d.get("filepath")]


LOGIN_NOTE: list[str] = []   # set when YouTube says the saved login doesn't work any more (shown once)


def _watch_login(msg) -> None:
    if YDL_EXTRA.get("login") and re.search(r"cookies are no longer valid|account cookies", str(msg), re.I):
        LOGIN_NOTE[:] = ["YouTube says your login has expired – sign in again: Settings → YouTube login."]


class _Log:
    def __init__(self, emit):
        self.emit = emit

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self.emit("log", ANSI.sub("", msg))

    def info(self, msg):
        self.emit("log", ANSI.sub("", msg))

    def warning(self, msg):
        _watch_login(msg)
        self.emit("log", "WARNING: " + ANSI.sub("", msg))

    def error(self, msg):
        self.emit("log", ANSI.sub("", msg))


def make_ranges(start, end, on_section=None):
    def ranges(info, _ydl):
        s = start or 0.0
        e = end
        dur = info.get("duration")
        known = True
        if dur:
            if s >= dur:
                raise ValueError(f"Start time {fmt_t(s)} is past the end of the video ({fmt_t(dur)}).")
            e = dur if e is None else min(e, dur)
        elif e is None:
            e = s + 12 * 3600  # length unknown: ffmpeg stops at end of file
            known = False
        if on_section:
            on_section(e - s if known else None)
        yield {"start_time": s, "end_time": e}
    return ranges


def format_sort(height, prefer_h264: bool = True) -> list[str]:
    # best resolution <= limit (else the next larger one); at equal resolution prefer H.264/AAC
    # -> the YouTube file can often be used 1:1 without re-encoding
    res = [f"res:{height}" if height else "res", "fps"]
    return res + ["vcodec:h264", "acodec:aac"] if prefer_h264 else res


def _base_opts(outdir, suffix, section, emit, name=None) -> dict:
    stem = safe_name(name).replace("%", "%%") if name else f"%(title).120B{suffix}"
    tmpl = str(Path(outdir)).replace("%", "%%") + os.sep + stem + ".%(ext)s"

    def hook(d):
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            pct = done / total * 100 if total else None
            what = "clip" if section else (
                "audio" if (d.get("info_dict") or {}).get("vcodec") == "none" else "video")
            parts = [f"Downloading {what}"]
            if pct is not None:
                parts.append(f"{pct:.0f} %")
            elif done:
                parts.append(f"{done / 1048576:.1f} MB")
            if d.get("speed"):
                parts.append(f"{d['speed'] / 1048576:.1f} MB/s")
            if d.get("eta"):
                parts.append(f"{int(d['eta']) // 60}:{int(d['eta']) % 60:02d} left")
            emit("progress", pct)
            emit("status", " · ".join(parts))
        elif st == "finished":
            emit("progress", 100)

    def pp_hook(d):
        if d.get("status") == "started":
            name = d.get("postprocessor", "")
            emit("status", f"{PP_NAMES.get(name, 'Post-processing: ' + name)} …")
            emit("progress", None)

    return {
        "outtmpl": tmpl,
        "noplaylist": True,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "logger": _Log(emit),
        "noprogress": True,
        "concurrent_fragment_downloads": 4,
        **YDL_EXTRA,
    }


_NO_FORMATS = re.compile(r"Requested format is not available|Only images are available|No video formats found", re.I)
# yt-dlp asks YouTube with a few "clients" (web, TV, …). Signed in (esp. with Premium) its default ones can come back
# empty (YouTube wants a "PO token" from them) – these others often still work with the login.
LOGIN_CLIENTS = ["tv", "tv_simply", "tv_downgraded", "mweb", "web_safari", "web_embedded"]
LOGIN_DEBUG = APP_DIR / "login_debug.txt"


class _Keep:
    """Logger that passes everything on and keeps a copy (for login_debug.txt)."""

    def __init__(self, inner, lines):
        self.inner, self.lines = inner, lines

    def _k(self, kind, msg):
        self.lines.append(f"{kind}: {ANSI.sub('', str(msg))}"[:600])

    def debug(self, msg):
        self._k("debug", msg)
        if self.inner is not None and not str(msg).startswith("[debug] "):
            self.inner.debug(msg)

    def info(self, msg):
        self._k("info", msg)
        if self.inner is not None:
            self.inner.info(msg)

    def warning(self, msg):
        self._k("WARNING", msg)
        if self.inner is not None:
            self.inner.warning(msg)

    def error(self, msg):
        self._k("ERROR", msg)
        if self.inner is not None:
            self.inner.error(msg)


def _login_debug(url, tries):
    """What happened with the login (no cookies, no account data) -> login_debug.txt, for finding the cause."""
    try:
        import yt_dlp
        head = [f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}", f"app: {APP_VERSION}",
                f"yt-dlp: {yt_dlp.version.__version__}", f"deno: {shutil.which('deno') or '-'}",
                f"url: {url}", ""]
        body = []
        for name, lines, res in tries:
            body += [f"===== {name}: {res}"] + [x for x in lines if not re.search(r"cookie|SAPISID|Authorization", x, re.I)
                                               or x.startswith(("WARNING", "ERROR"))] + [""]
        LOGIN_DEBUG.write_text("\n".join(head + body)[-200_000:], encoding="utf-8")
    except Exception:  # noqa: BLE001 - only diagnostics
        pass


def _with_js_variant(o):
    """yt-dlp ≤ 2026.11.22: YouTube's new players (05a4ffc0, b485e332, b17b74e6) break its JS challenge solving with
    the "main" player variant -> only pictures, no video (yt-dlp issue #18123). The fix there: the "tv" variant.
    Newer yt-dlp versions use it by themselves, so this is only added for the older ones."""
    try:
        import yt_dlp
        ver = tuple(int(x) for x in yt_dlp.version.__version__.split(".")[:3])
    except Exception:  # noqa: BLE001
        return o
    if ver > (2026, 11, 22):
        return o
    ea = {k: dict(v) for k, v in (o.get("extractor_args") or {}).items()}
    yt = ea.setdefault("youtube", {})
    if "player_js_variant" not in yt:
        yt["player_js_variant"] = ["tv"]
    return {**o, "extractor_args": ea}


def ydl_extract(opts, url, download=True, use_login=True):
    """One yt-dlp run (the YouTube login, if any, is handed in by add_login – from memory). If YouTube offers no
    video with the login, other YouTube clients are tried with the login; only then the run is done without it."""
    from yt_dlp import YoutubeDL  # imported late so the auto-update can run first
    clean = _with_js_variant({k: v for k, v in opts.items() if k != "login"})
    if not (use_login and logged_in()):
        with YoutubeDL(clean) as ydl:
            return ydl.extract_info(url, download=download)
    log = opts.get("logger")
    tries = []
    preferred = load_cfg().get("login_clients")
    plans = [("default clients", None)]
    if preferred:
        plans.insert(0, ("last working clients", preferred))
    plans.append(("other clients", [c for c in LOGIN_CLIENTS if c not in (preferred or [])] or LOGIN_CLIENTS))
    last = None
    for i, (name, clients) in enumerate(plans):
        lines: list[str] = []
        o = dict(clean, logger=_Keep(log, lines), verbose=True)
        if clients:
            ea = {k: dict(v) for k, v in (clean.get("extractor_args") or {}).items()}
            ea.setdefault("youtube", {})["player_client"] = list(clients)
            o["extractor_args"] = ea
        try:
            with YoutubeDL(o) as ydl:
                add_login(ydl)
                res = ydl.extract_info(url, download=download)
            tries.append((name, lines, "OK"))
            if clients and clients != preferred:
                try:
                    save_cfg({**load_cfg(), "login_clients": list(clients)})
                except Exception:  # noqa: BLE001
                    pass
            if i or tries[0][2] != "OK":
                _login_debug(url, tries)
            return res
        except Exception as ex:  # noqa: BLE001
            tries.append((name, lines, f"failed – {ANSI.sub('', str(ex))[:300]}"))
            if not _NO_FORMATS.search(str(ex)):
                _login_debug(url, tries)
                raise
            last = ex
            if clients == preferred and preferred:
                try:
                    save_cfg({k: v for k, v in load_cfg().items() if k != "login_clients"})
                except Exception:  # noqa: BLE001
                    pass
            if log is not None and hasattr(log, "warning") and i < len(plans) - 1:
                log.warning("With your YouTube login YouTube offered no video – trying other YouTube clients …")
    _login_debug(url, tries)
    if log is not None and hasattr(log, "warning"):
        log.warning("With your YouTube login YouTube offered no video – trying without the login …")
    LOGIN_NOTE[:] = ["With your YouTube login, YouTube offered no video for this link, so it was loaded without "
                     "the login. Details for fixing it: login_debug.txt in the app folder."]
    del last
    return ydl_extract(opts, url, download, use_login=False)


def _suffix(start, end) -> str:
    if start is None and end is None:
        return ""
    return f"_{fmt_t(start or 0)}-{fmt_t(end) if end is not None else 'end'}"


def download(url, start, end, height, encoder, size, target_mb, outdir, *,
             ffmpeg, ffprobe, emit, extra_opts=None, name=None, codec="h264", profile=None):
    """Video -> H.264/H.265 MP4 or ProRes MOV"""

    section = start is not None or end is not None
    t_start = time.time()
    enable_ffmpeg_report()
    encoder = check_encoder(encoder, ffmpeg, emit, codec)
    opts = _base_opts(outdir, _suffix(start, end), section, emit, name=name)
    opts.update({
        "format": "bv*+ba/b",
        "format_sort": format_sort(height, codec == "h264"),
        "merge_output_format": "mp4/mkv" if codec == "h264" else "mkv",
    })
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if section:
        out_args: list[str] = []  # filled in once the clip length is known

        container = "mov" if codec == "prores" else "mp4"

        def on_section(dur):
            vargs, aargs = encode_args(encoder, size, target_mb, dur, codec, profile)
            # -f overrides yt-dlp's container choice (e.g. if the source is webm)
            out_args[:] = vargs + aargs + ["-movflags", "+faststart", "-f", container]

        opts.update({
            "download_ranges": make_ranges(start, end, on_section),
            "force_keyframes_at_cuts": True,  # frame-accurate cut (re-encodes)
            "merge_output_format": container,
            "external_downloader_args": {"ffmpeg_o": out_args},
        })
    if extra_opts:
        opts.update(extra_opts)

    try:
        if section:
            emit("status", "Downloading clip and encoding frame-accurately …")
            emit("progress", None)
        info = ydl_extract(opts, url, download=True)
    except ValueError:
        raise
    except Exception as ex:
        if not section:
            tail = ffmpeg_report_tail(t_start)
            raise RuntimeError(clean_error(ex) + (f"\nffmpeg said:\n{tail}" if tail else "")) from ex
        _note_fallback(ex, t_start, emit)
        return [_full_then_cut_video(url, start, end, height, encoder, size, target_mb, outdir,
                                     ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit, name=name,
                                     codec=codec, profile=profile)]

    files = collect_files(info)
    if not files:
        raise RuntimeError("No file was downloaded.")
    return [finalize(Path(f), encoder, size, target_mb, ffmpeg, ffprobe, emit, encoded=section,
                     codec=codec, profile=profile) for f in files]


def _full_then_cut_video(url, start, end, height, encoder, size, target_mb, outdir, *, ffmpeg, ffprobe, emit,
                         name=None, codec="h264", profile=None):
    """Fallback for clips: normal (robust) download of the whole video, then cut locally."""

    tmpdir = Path(outdir) / ".ytclip_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        opts = _base_opts(tmpdir, "", False, emit)
        opts.update({"format": "bv*+ba/b", "format_sort": format_sort(height, codec == "h264"),
                     "merge_output_format": "mkv"})
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        info = ydl_extract(opts, url, download=True)
        files = collect_files(info)
        if not files:
            raise RuntimeError("No file was downloaded.")
        src = Path(files[0])
        _v, _a, dur = probe(ffprobe, src)
        s, e = _clip_bounds(start, end, dur or (info or {}).get("duration"))
        vargs, aargs = encode_args(encoder, size, target_mb, (e - s) if e is not None else None, codec, profile)
        ext = video_ext(codec)
        dst = Path(outdir) / (f"{safe_name(name)}{ext}" if name else f"{src.stem}{_suffix(start, end)}{ext}")
        cut_local(src, dst, s, e, ["-map", "0:v:0?", "-map", "0:a:0?", *vargs, *aargs,
                                   "-movflags", "+faststart"],
                  ffmpeg, emit, "Cutting + encoding" + ("" if size == "_piece" else f" ({size})"))
        _remove_leftovers(dst)
        return dst
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def download_mp3(url, start, end, kbps, outdir, *, ffmpeg, ffprobe, emit, extra_opts=None, name=None,
                 afmt="mp3"):
    """Audio -> MP3 / M4A (tags + cover art) or WAV (lossless PCM, for editing)"""

    section = start is not None or end is not None
    t_start = time.time()
    enable_ffmpeg_report()
    opts = _base_opts(outdir, _suffix(start, end), section, emit, name=name)
    cover = afmt in ("mp3", "m4a")
    pps = [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}] if cover else []
    pps.append({"key": "FFmpegExtractAudio", "preferredcodec": afmt,
                "preferredquality": None if afmt == "wav" else str(kbps)})
    if cover:
        pps += [{"key": "FFmpegMetadata", "add_metadata": True}, {"key": "EmbedThumbnail"}]
    opts.update({
        # M4A: take YouTube's AAC stream -> copied without re-encoding
        "format": "ba[ext=m4a]/ba/b" if afmt == "m4a" else "ba/b",
        "writethumbnail": cover,
        "postprocessors": pps,
    })
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if section:
        opts["download_ranges"] = make_ranges(start, end)
        # copying the stream would only cut at WebM cluster borders (seconds off) -> decode to a
        # lossless intermediate (ALAC) so ffmpeg seeks sample-accurately; the final format comes after
        opts["external_downloader_args"] = {"ffmpeg_o": ["-vn", "-c:a", "alac", "-f", "mp4"]}
    if extra_opts:
        opts.update(extra_opts)

    try:
        if section:
            emit("status", "Downloading clip …")
            emit("progress", None)
        info = ydl_extract(opts, url, download=True)
    except ValueError:
        raise
    except Exception as ex:
        if not section:
            tail = ffmpeg_report_tail(t_start)
            raise RuntimeError(clean_error(ex) + (f"\nffmpeg said:\n{tail}" if tail else "")) from ex
        _note_fallback(ex, t_start, emit)
        return [_full_then_cut_mp3(url, start, end, kbps, outdir, ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit,
                                   name=name, afmt=afmt)]

    files = [Path(f) for f in collect_files(info)]
    if not files:
        raise RuntimeError("No file was downloaded.")
    for f in files:
        _v, a, _d = probe(ffprobe, f)
        if ffprobe and a is None:
            f.unlink(missing_ok=True)
            raise RuntimeError("The file is empty – is the start time past the end of the video?")
    return files


def _full_then_cut_mp3(url, start, end, kbps, outdir, *, ffmpeg, ffprobe, emit, name=None, afmt="mp3"):
    """Fallback for audio clips: whole track (with tags + cover), then cut locally without re-encoding."""
    tmpdir = Path(outdir) / ".ytclip_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        src = download_mp3(url, None, None, kbps, tmpdir, ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit, afmt=afmt)[0]
        _v, _a, dur = probe(ffprobe, src)
        s, e = _clip_bounds(start, end, dur)
        ext = "." + afmt
        dst = Path(outdir) / (f"{safe_name(name)}{ext}" if name else f"{src.stem}{_suffix(start, end)}{ext}")
        maps = {"mp3": ["-map", "0:a:0", "-map", "0:v?", "-c", "copy", "-id3v2_version", "3", "-write_id3v1", "1"],
                "m4a": ["-map", "0:a:0", "-map", "0:v?", "-c", "copy", "-disposition:v", "attached_pic",
                        "-movflags", "+faststart"],
                "wav": ["-map", "0:a:0", "-c", "copy"]}[afmt]
        cut_local(src, dst, s, e, maps, ffmpeg, emit, f"Cutting {afmt.upper()}")
        _remove_leftovers(dst)
        return dst
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def make_gif(url, start, end, width, fps, colors, outdir, *, ffmpeg, ffprobe, emit, name=None, extra_opts=None):
    """Short clip -> animated GIF (two-pass palette for clean colors, loops forever)."""
    tmpdir = Path(outdir) / ".ytclip_tmp_gif"
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        height = 1080 if width > 640 else 720
        clip = download(url, start, end, height, DEFAULT_ENCODER, "Original", None, tmpdir,
                        ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit, extra_opts=extra_opts)[0]
        _v, _a, dur = probe(ffprobe, clip)
        if dur and dur > GIF_MAX + 0.5:
            raise RuntimeError(f"GIFs can be at most {GIF_MAX} s long – set a shorter time range.")
        dst = Path(outdir) / ((safe_name(name) if name else clip.stem) + ".gif")
        return [gif_encode(clip, dst, None, None, dur, width, fps, colors, ffmpeg, emit)]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def gif_encode(src, dst, start, length, dur, width, fps, colors, ffmpeg, emit) -> Path:
    """Two-pass palette GIF (clean colors, small file), loops forever."""
    tmp = dst.with_name(dst.stem + ".part.gif")
    vf = (f"fps={fps},scale=w='min({width},iw)':h=-1:flags=lanczos,split[a][b];"
          f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
          f"[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-i", str(src), "-an", "-vf", vf, "-loop", "0", "-progress", "pipe:1", "-nostats", str(tmp)]
    emit("progress", 0)
    try:
        run_encode(cmd, length or dur, emit, "Creating GIF")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


# ----------------------------------------------------------------------------- local files

def local_path(text):
    """Path of an existing local file (also accepts "quoted" paths and file:// URLs), else None."""
    t = (text or "").strip().strip('"').strip("'")
    if not t or ANY_URL.match(t):
        return None
    if t.lower().startswith("file:"):
        from urllib.parse import unquote, urlparse
        t = unquote(urlparse(t).path)
        if re.match(r"^/[A-Za-z]:", t):
            t = t[1:]
    try:
        p = Path(t)
        return p if p.is_file() else None
    except (OSError, ValueError):
        return None


def local_info(path, ffprobe) -> dict:
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name,width,height,avg_frame_rate:stream_tags=language,title"
         ":stream_disposition=attached_pic:format=duration", "-show_chapters", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    streams = data.get("streams", [])
    v = next((x for x in streams if x.get("codec_type") == "video"
              and not (x.get("disposition") or {}).get("attached_pic")), None)
    a = next((x for x in streams if x.get("codec_type") == "audio"), None)
    if not v and not a:
        raise RuntimeError("This file has no video or audio that FFmpeg can read.")
    fps = None
    if v and v.get("avg_frame_rate") not in (None, "0/0"):
        try:
            n, d = v["avg_frame_rate"].split("/")
            fps = float(n) / float(d) if float(d) else None
        except (ValueError, ZeroDivisionError):
            fps = None
    try:
        dur = float(data.get("format", {}).get("duration") or 0) or None
    except ValueError:
        dur = None
    chapters = []
    for ch in data.get("chapters") or []:
        try:
            chapters.append((float(ch["start_time"]), float(ch["end_time"]), (ch.get("tags") or {}).get("title") or ""))
        except (KeyError, ValueError):
            pass
    subs, k = [], 0
    for x in streams:
        if x.get("codec_type") != "subtitle":
            continue
        tags = x.get("tags") or {}
        if x.get("codec_name") in SUB_TEXT_CODECS:
            name = " · ".join(t for t in (tags.get("language"), tags.get("title")) if t) or f"Track {k + 1}"
            subs.append({"label": f"{name} (in the file)", "kind": "embedded", "key": k})
        k += 1
    subs += sidecar_subs(path)
    return {"duration": dur, "vcodec": v.get("codec_name") if v else None,
            "acodec": a.get("codec_name") if a else None,
            "width": v.get("width") if v else None, "height": v.get("height") if v else None, "fps": fps,
            "chapters": chapters, "subs": subs}


def grab_frame(path, t, ffmpeg, width=None) -> bytes | None:
    """One frame as JPEG bytes."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path),
           "-frames:v", "1"]
    if width:
        cmd += ["-vf", f"scale='min({width},iw)':-2"]
    cmd += ["-q:v", "2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8" else None


def _local_dst(src, outdir, name, start, end, ext) -> Path:
    dst = Path(outdir) / ((safe_name(name) if name else f"{Path(src).stem}{_suffix(start, end)}") + ext)
    if dst.resolve() == Path(src).resolve():  # never overwrite the source
        dst = dst.with_name(unique_name(dst.parent, dst.stem, ext) + ext)
    return dst


def local_mp4(src, start, end, height, encoder, size, target_mb, outdir, *, ffmpeg, ffprobe, emit, name=None,
              codec="h264", profile=None):
    """Cut / convert a local file to H.264/H.265 MP4 or ProRes MOV (frame-accurate)."""
    src = Path(src)
    info = local_info(src, ffprobe)
    if not info["vcodec"]:
        raise RuntimeError("This file has no video – choose Audio instead.")
    dur = info["duration"]
    s, e = _clip_bounds(start, end, dur)
    whole = not s and (e is None or (dur and e >= dur - 0.01))
    encoder = check_encoder(encoder, ffmpeg, emit, codec)
    dst = _local_dst(src, outdir, name, start, end, video_ext(codec))
    too_big = bool(height and info["height"] and info["height"] > height)
    if (whole and codec in ("h264", "hevc") and SIZES.get(size) is None and info["vcodec"] == codec
            and info["acodec"] in ("aac", None) and not too_big):
        args, label_ = ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart"], "Remuxing"
    else:
        length = ((e if e is not None else dur) or 0) - s or None
        vargs, aargs = encode_args(encoder, size, target_mb, length, codec, profile)
        vf = ["-vf", f"scale=-2:{height}"] if too_big else []
        args = ["-map", "0:v:0", "-map", "0:a:0?", *vf, *vargs, *aargs, "-movflags", "+faststart"]
        what = "ProRes" if codec == "prores" else ("H.265" if codec == "hevc" else "H.264")
        label_ = f"Encoding {what}" + ("" if codec == "prores" or size == "_piece" else f" ({size})")
    emit("status", f"{label_} …")
    return [cut_local(src, dst, s, None if whole else e, args, ffmpeg, emit, label_)]


def local_mp3(src, start, end, kbps, outdir, *, ffmpeg, ffprobe, emit, name=None, afmt="mp3"):
    """Audio of a local file -> MP3 / M4A (title tag + a video frame as cover) or WAV."""
    src = Path(src)
    info = local_info(src, ffprobe)
    if not info["acodec"]:
        raise RuntimeError("This file has no audio track.")
    dur = info["duration"]
    s, e = _clip_bounds(start, end, dur)
    length = (e - s) if e is not None else None
    ext = "." + afmt
    dst = _local_dst(src, outdir, name, start, end, ext)
    tmp = dst.with_name(dst.stem + ".part" + ext)
    cover = None
    if info["vcodec"] and afmt != "wav":
        span = length or ((dur or 2) - s)
        data = grab_frame(src, s + min(1.0, span / 2), ffmpeg, width=800)
        if data:
            cover = dst.with_name(dst.stem + ".cover.jpg")
            cover.write_bytes(data)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if s:
        cmd += ["-ss", f"{s:.3f}"]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-i", str(src)]
    if cover:
        cmd += ["-i", str(cover)]
    cmd += ["-map", "0:a:0"]
    if cover:
        cmd += ["-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
        if afmt == "mp3":
            cmd += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    if afmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-id3v2_version", "3", "-write_id3v1", "1"]
    elif afmt == "m4a":
        cmd += (["-c:a", "copy"] if info["acodec"] == "aac" else ["-c:a", "aac", "-b:a", f"{kbps}k"])
        cmd += ["-movflags", "+faststart"]
    else:  # wav: 24-bit if the source is lossless, else 16-bit
        lossless = info["acodec"] and (info["acodec"].startswith("pcm_") or info["acodec"] in ("flac", "alac", "truehd"))
        cmd += ["-c:a", "pcm_s24le" if lossless else "pcm_s16le"]
    cmd += ["-metadata", f"title={dst.stem}", "-progress", "pipe:1", "-nostats", str(tmp)]
    emit("progress", 0)
    try:
        run_encode(cmd, length or ((dur or 0) - s) or None, emit, f"Converting to {afmt.upper()}")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
        if cover:
            cover.unlink(missing_ok=True)
    return [dst]


def local_gif(src, start, end, width, fps, colors, outdir, *, ffmpeg, ffprobe, emit, name=None):
    src = Path(src)
    info = local_info(src, ffprobe)
    if not info["vcodec"]:
        raise RuntimeError("This file has no video – a GIF needs a picture.")
    dur = info["duration"]
    s, e = _clip_bounds(start, end, dur)
    end_t = e if e is not None else dur
    if end_t is None:
        raise RuntimeError(f"Set a time range for the GIF (max {GIF_MAX} s).")
    length = end_t - s
    if length > GIF_MAX + 0.01:
        raise RuntimeError(f"GIFs can be at most {GIF_MAX} s long – set a shorter time range.")
    dst = _local_dst(src, outdir, name, start, end, ".gif")
    return [gif_encode(src, dst, s, length, length, width, fps, colors, ffmpeg, emit)]


# ----------------------------------------------------------------------------- thumbnails

def save_jpg(data: bytes, dst: Path, ffmpeg) -> Path:
    """Write image bytes as JPG (converts WebP/PNG with ffmpeg)."""
    if data[:3] == b"\xff\xd8\xff":
        dst.write_bytes(data)
        return dst
    tmp = dst.with_name(dst.stem + ".src.img")
    tmp.write_bytes(data)
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), "-q:v", "2",
                            str(dst)], capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("Could not convert the thumbnail to JPG.")
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def save_thumbnail(source, dst: Path, *, ffmpeg, info=None, at=0.0) -> Path:
    """Best available YouTube thumbnail -> JPG, or for local files a full-size frame at `at` seconds."""
    lp = local_path(source)
    if lp:
        data = grab_frame(lp, at, ffmpeg)
        if not data:
            raise RuntimeError("Could not read a frame from the file.")
        dst.write_bytes(data)
        return dst
    info = info or fetch_info(source)
    for u in info.get("thumbs") or ([info["thumb"]] if info.get("thumb") else []):
        try:
            data = fetch_bytes(u)
        except Exception:  # noqa: BLE001 - try the next (smaller) one
            continue
        if data:
            return save_jpg(data, dst, ffmpeg)
    raise RuntimeError("No thumbnail found for this video.")


class _Silent:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): _watch_login(msg)
    def error(self, msg): pass


def fetch_info(url: str) -> dict:
    """Title, channel, duration and thumbnail URL for the preview card."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
            "extract_flat": "in_playlist", "logger": _Silent(), **YDL_EXTRA}
    info = ydl_extract(opts, url, download=False)
    entries = info.get("entries")
    vids = [f for f in info.get("formats") or [] if f.get("vcodec") not in (None, "none") and f.get("height")]
    best = max(vids, key=lambda f: (f.get("height") or 0, f.get("width") or 0), default=None)
    return {
        "id": info.get("id") or "",
        "site": info.get("extractor_key") or info.get("extractor") or "",
        "width": (best or {}).get("width") or info.get("width"),
        "height": (best or {}).get("height") or info.get("height"),
        "chapters": [(float(c.get("start_time") or 0), float(c.get("end_time") or 0), c.get("title") or "")
                     for c in info.get("chapters") or [] if c.get("end_time")],
        "subs": list_subs(info),
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": float(info["duration"]) if info.get("duration") else None,
        "thumb": pick_thumb(info),
        "thumbs": [t["url"] for t in reversed(info.get("thumbnails") or []) if t.get("url")],
        "playlist": len(list(entries)) if entries is not None else 0,
        "fps": info.get("fps") or max((f.get("fps") or 0 for f in info.get("formats") or []), default=0) or None,
        "stream": pick_streams(info) if entries is None else None,
        "streams": stream_choices(info) if entries is None else {},
    }


def pick_thumb(info: dict) -> str | None:
    """Prefer a JPG thumbnail (Qt can always decode those), biggest up to 1280 px wide."""
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    jpgs = [t for t in thumbs if t["url"].split("?")[0].lower().endswith(".jpg")
            and (t.get("width") or 0) <= 1280]
    if jpgs:
        jpgs.sort(key=lambda t: ((t.get("width") or 0), t.get("preference") or 0))
        return jpgs[-1]["url"]
    url = info.get("thumbnail") or (thumbs[-1]["url"] if thumbs else None)
    if url and "i.ytimg.com" in url:
        url = url.replace("/vi_webp/", "/vi/").replace(".webp", ".jpg")
    return url


def fetch_bytes(url: str, timeout: float = 15.0, headers=None) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def update_ytdlp(emit, force=False) -> bool:
    """yt-dlp to the newest version (force: put its files in again even if it is up to date – repair)."""
    py = Path(sys.executable)
    if py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists():
        py = py.with_name("python.exe")
    emit("log", "Reinstalling yt-dlp …" if force else "Checking for yt-dlp update …")
    if force:
        subprocess.run([str(py), "-m", "pip", "install", "-U", "-q", "--disable-pip-version-check", "--force-reinstall",
                        "--no-deps", "yt-dlp"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW)
    base = [str(py), "-m", "pip", "install", "-U", "-q", "--disable-pip-version-check", "yt-dlp[default]"]
    r = None
    for extra in ([], ["--user"]):
        r = subprocess.run(base + extra, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW)
        if r.returncode == 0:
            break
    else:
        emit("log", "yt-dlp update failed:\n" + ((r.stderr or r.stdout) if r else "").strip()[-600:])
        return False
    v = subprocess.run([str(py), "-m", "yt_dlp", "--version"], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    emit("log", f"yt-dlp {v.stdout.strip()} is up to date.")
    return True




# ----------------------------------------------------------------------------- video preview for the player

PREVIEW_HEIGHT = 360
PREVIEW_AUTO_MAX = 20 * 60       # load the preview by itself for videos up to 20 minutes
PREVIEW_MB_PER_MIN = 4.0         # rough size of the 360p preview (for the "≈ N MB" hint)


def preview_height(duration) -> int:
    """Long videos get a smaller preview copy, so it loads in reasonable time."""
    d = float(duration or 0)
    return 360 if d <= 30 * 60 else 240 if d <= 90 * 60 else 144


def preview_mb(duration) -> int:
    per_min = {360: PREVIEW_MB_PER_MIN, 240: 2.4, 144: 1.3}[preview_height(duration)]
    return max(1, round(float(duration or 0) / 60 * per_min))


def preview_video(url, outdir, *, ffmpeg, emit, duration=None) -> Path:
    """Small (≤360p, long videos less) copy of a YouTube video for the built-in player. H.264/AAC is preferred
    (plays everywhere); yt-dlp does the downloading, so it works wherever downloads work."""
    h = preview_height(duration)
    opts = _base_opts(outdir, "", False, emit, name="preview")
    opts.update({
        "format": f"bv*[height<={h}]+ba/b[height<={h}]/wv*+wa/w",
        "format_sort": [f"res:{h}", "vcodec:h264", "acodec:aac", "+size"],
        "merge_output_format": "mp4/mkv",
        "overwrites": True,
    })
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    info = ydl_extract(opts, url, download=True)
    files = collect_files(info)
    if not files:
        raise RuntimeError("The preview could not be downloaded.")
    return Path(files[0])


PREVIEW_RX = re.compile(r".* \[([\w-]+)\] preview \d+p\.(mp4|mkv|webm)$", re.I)


def preview_dir() -> Path:
    return Path(PATHS["preview"])


def preview_name(info) -> str:
    """'<title> [<id>] preview 360p' – readable, and the app finds it again by the id."""
    title = safe_name(info.get("title") or "video")[:80].strip() or "video"
    vid = re.sub(r"[^\w-]+", "", str(info.get("id") or "")) or "x"
    return f"{title} [{vid}] preview {preview_height(info.get('duration'))}p"


def preview_files(root=None) -> list:
    root = Path(root or preview_dir())
    try:
        return [f for f in root.iterdir() if f.is_file() and PREVIEW_RX.match(f.name)]
    except OSError:
        return []


def find_preview(info, root=None):
    vid = re.sub(r"[^\w-]+", "", str(info.get("id") or ""))
    if not vid:
        return None
    for f in preview_files(root):
        if PREVIEW_RX.match(f.name).group(1) == vid and f.stat().st_size > 0:
            return f
    return None


def preview_cleanup(keep: bool, root=None) -> int:
    """Leftovers of unfinished downloads always go; the copies themselves only if they are not to be kept.
    Only files the app made are touched (the folder can be one of the user's own). -> files removed."""
    root = Path(root or preview_dir())
    n = 0
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir() and (d.name.startswith(".dl_") or (root == DEFAULT_PATHS["preview"] and
                                                              re.fullmatch(r"p\d+", d.name))):
                shutil.rmtree(d, ignore_errors=True)
    if not keep:
        for f in preview_files(root):
            try:
                f.unlink()
                n += 1
            except OSError:      # still open in the player
                pass
    return n


def preview_stats(root=None) -> dict:
    fs = preview_files(root)
    return {"files": len(fs), "bytes": sum(f.stat().st_size for f in fs)}


def fmt_bytes(n) -> str:
    n = float(n or 0)
    return f"{n / 1073741824:.1f} GB" if n >= 1073741824 else f"{n / 1048576:.0f} MB" if n >= 1048576 \
        else f"{n / 1024:.0f} KB"


# ----------------------------------------------------------------------------- several clips

def _sub_emit(emit, k, n, label):
    """Progress of step k of n -> overall progress; status gets a 'Clip 2/3 · ' prefix."""
    def sub(kind, val=None):
        if kind == "progress":
            emit("progress", None if val is None else (k + min(100.0, float(val)) / 100.0) / n * 100.0)
        elif kind == "status":
            emit("status", f"{label} · {val}")
        else:
            emit(kind, val)
    return sub


def _single_export(kind, src, s, e, outdir, local, p, name, ffmpeg, ffprobe, emit):
    kw = dict(ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit, name=name)
    if kind == "mp4":
        fn = local_mp4 if local else download
        return fn(src, s, e, p["height"], p["encoder"], p["size"], p["target_mb"], outdir,
                  codec=p["codec"], profile=p["profile"], **kw)
    if kind == "mp3":
        fn = local_mp3 if local else download_mp3
        return fn(src, s, e, p["kbps"], outdir, afmt=p["afmt"], **kw)
    fn = local_gif if local else make_gif
    return fn(src, s, e, p["width"], p["fps"], p["colors"], outdir, **kw)


def _kind_ext(kind, p):
    if kind == "mp4":
        return video_ext(p["codec"])
    if kind == "mp3":
        return "." + p["afmt"]
    return ".gif"


def _piece(kind, src, s, e, tmp, k, local, p, ffmpeg, ffprobe, emit) -> Path:
    """One clip in a good intermediate quality (it gets encoded once more when joining)."""
    kw = dict(ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit, name=f"piece_{k:02d}")
    if kind == "mp3":
        fn = local_mp3 if local else download_mp3
        return fn(src, s, e, 320, tmp, afmt="wav", **kw)[0]
    height = p.get("height") if kind == "mp4" else (1080 if p.get("width", 480) > 640 else 720)
    enc = p.get("encoder", DEFAULT_ENCODER) if kind == "mp4" else DEFAULT_ENCODER
    fn = local_mp4 if local else download
    return fn(src, s, e, height, enc, "_piece", None, tmp, codec="h264", **kw)[0]


def media_info(path, ffprobe) -> dict:
    """Size, frame rate and sample rate of a piece."""
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,duration"
         ":stream_disposition=attached_pic:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    streams = data.get("streams", [])
    v = next((x for x in streams if x.get("codec_type") == "video"
              and not (x.get("disposition") or {}).get("attached_pic")), None)
    a = next((x for x in streams if x.get("codec_type") == "audio"), None)
    rate = (v or {}).get("r_frame_rate") or "30/1"
    if rate in ("0/0", "0/1"):
        rate = "30/1"
    try:
        dur = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    def _d(x):
        try:
            return float((x or {}).get("duration") or 0) or dur
        except ValueError:
            return dur
    return {"duration": dur, "vdur": _d(v), "adur": _d(a), "video": bool(v), "audio": bool(a),
            "width": (v or {}).get("width"),
            "height": (v or {}).get("height"), "rate": rate,
            "sr": int((a or {}).get("sample_rate") or 48000), "acodec": (a or {}).get("codec_name")}


def _audio_chain(i, dur, sr, exact=False, extra=""):
    """Same format for every piece + 10 ms fades at the cuts (no clicks). exact: audio gets exactly
    `dur` long (the video length) - otherwise AAC padding would push the next clip by a frame.
    extra: more filters (e.g. the volume curve), time 0 = start of the piece."""
    fo = max(0.0, dur - 0.012)
    fit = f"apad=whole_dur={dur:.6f},atrim=duration={dur:.6f}," if exact else ""
    ex = f"{extra}," if extra else ""
    return (f"[{i}:a:0]aresample={sr},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
            f"{fit}{ex}afade=t=in:d=0.01,afade=t=out:st={fo:.3f}:d=0.01[a{i}]")


def atempo(speed) -> str:
    """Audio speed filter (keeps the pitch); atempo takes 0.5 … 100 per step."""
    sp, parts = float(speed), []
    while sp < 0.5:
        parts.append("atempo=0.5")
        sp /= 0.5
    parts.append(f"atempo={sp:.6g}")
    return ",".join(parts)


def join_video(pieces, dst, *, vargs, aargs, ffmpeg, ffprobe, emit, audio=True, label="Joining clips",
               crops=None, size=None, afx=None, post_vf="", sub_track=None, sub_lang=None, cwd=None,
               infos=None, speed=1.0) -> Path:
    """Puts the pieces one after another (frame-accurate, one encode). All pieces get the size and
    frame rate of the first one.
    crops: per piece None or (w, h, x, y) in pixels · size: (w, h) of the result · afx: per piece extra audio
    filters · post_vf: filter on the joined picture (burned-in subtitles) · sub_track: .srt as subtitle track.
    File names in post_vf / sub_track are relative to `cwd`."""
    infos = infos or [media_info(p, ffprobe) for p in pieces]
    first = infos[0]
    if not first["video"]:
        raise RuntimeError("The clips have no video.")
    w, h, rate = first["width"], first["height"], first["rate"]
    if size:
        w, h = size
    has_a = audio and all(i["audio"] for i in infos)
    total = sum(i["vdur"] for i in infos)
    parts, labels = [], ""
    for i, inf in enumerate(infos):
        fps = "" if inf["rate"] == rate else f"fps={rate},"   # fps adds a frame at the end -> only if needed
        cr = (crops or [None] * len(infos))[i]
        crop = f"crop={cr[0]}:{cr[1]}:{cr[2]}:{cr[3]}," if cr else ""
        parts.append(f"[{i}:v:0]{crop}scale={w}:{h}:flags=lanczos:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,{fps}setpts=PTS-STARTPTS[v{i}]")
        if has_a:
            parts.append(_audio_chain(i, inf["vdur"], first["sr"], exact=True, extra=(afx or [""] * len(infos))[i]))
        labels += f"[v{i}]" + (f"[a{i}]" if has_a else "")
    fast = abs(float(speed or 1.0) - 1.0) > 1e-6
    vout = "[vc]" if (post_vf or fast) else "[v]"
    aout = "[ac]" if fast else "[a]"
    graph = ";".join(parts) + f";{labels}concat=n={len(pieces)}:v=1:a={1 if has_a else 0}{vout}" + (aout if has_a else "")
    if post_vf or fast:     # burned-in subtitles first (source timing), then the speed
        chain = ",".join(x for x in (post_vf, f"setpts=PTS/{float(speed):.6g},fps={rate}" if fast else "") if x)
        graph += f";[vc]{chain}[v]"
    if fast and has_a:
        graph += f";[ac]{atempo(speed)}[a]"
    if fast:
        total /= float(speed)
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for p in pieces:
        cmd += ["-i", str(p)]
    if sub_track:
        cmd += ["-i", str(sub_track)]
    cmd += ["-filter_complex", graph, "-map", "[v]"]
    if has_a:
        cmd += ["-map", "[a]"]
    if sub_track:
        cmd += ["-map", f"{len(pieces)}:s", "-c:s", "mov_text"]
        if sub_lang:
            cmd += ["-metadata:s:s:0", f"language={_iso639_2(sub_lang)}"]
    cmd += [*vargs, *(aargs if has_a else ["-an"]), "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp)]
    emit("progress", 0)
    try:
        run_encode(cmd, total, emit, label, cwd=cwd)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def join_audio(pieces, dst, *, afmt, kbps, ffmpeg, ffprobe, emit, title=None, cover=None, afx=None,
               label="Joining clips", speed=1.0) -> Path:
    infos = [media_info(p, ffprobe) for p in pieces]
    sr = infos[0]["sr"]
    total = sum(i["duration"] for i in infos)
    graph = ";".join(_audio_chain(i, inf["adur"], sr, extra=(afx or [""] * len(infos))[i])
                     for i, inf in enumerate(infos))
    fast = abs(float(speed or 1.0) - 1.0) > 1e-6
    graph += ";" + "".join(f"[a{i}]" for i in range(len(pieces))) + \
        f"concat=n={len(pieces)}:v=0:a=1" + (f"[ac];[ac]{atempo(speed)}[a]" if fast else "[a]")
    if fast:
        total /= float(speed)
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for p in pieces:
        cmd += ["-i", str(p)]
    use_cover = bool(cover) and afmt in ("mp3", "m4a")
    if use_cover:
        cmd += ["-i", str(cover)]
    cmd += ["-filter_complex", graph, "-map", "[a]"]
    if use_cover:
        cmd += ["-map", f"{len(pieces)}:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    if afmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-id3v2_version", "3", "-write_id3v1", "1"]
    elif afmt == "m4a":
        cmd += ["-c:a", "aac", "-b:a", f"{kbps}k", "-movflags", "+faststart"]
    else:
        s24 = any(str(i["acodec"]).endswith("24le") for i in infos)
        cmd += ["-c:a", "pcm_s24le" if s24 else "pcm_s16le"]
    if title:
        cmd += ["-metadata", f"title={title}"]
    cmd += ["-progress", "pipe:1", "-nostats", str(tmp)]
    emit("progress", 0)
    try:
        run_encode(cmd, total, emit, label)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def export_multi(kind, src, clips, outdir, *, local, join, name, params, ffmpeg, ffprobe, emit, info=None, fx=None):
    """Several clips of one source -> one file (clips one after another) or one file per clip.
    kind: 'mp4' | 'mp3' | 'gif'   clips: [(start, end[, label]), ...] in seconds   params: settings of the format.
    fx: crop / output size / upscaling / volume curve / subtitles (see export_fx)."""
    labels = [str(c[2]) if len(c) > 2 and c[2] else "" for c in clips]
    clips = [(float(c[0] or 0.0), float(c[1])) for c in clips]
    if not clips:
        raise RuntimeError("Add at least one clip.")
    for s, e in clips:
        if e <= s:
            raise RuntimeError(f"Clip {fmt_t(s)} – {fmt_t(e)}: the end must be after the start.")
    n = len(clips)
    outdir = Path(outdir)
    ext = _kind_ext(kind, params)
    if kind == "gif":
        too_long = [k + 1 for k, (s, e) in enumerate(clips) if e - s > GIF_MAX + 0.01]
        if join and sum(e - s for s, e in clips) > GIF_MAX + 0.01:
            raise RuntimeError(f"Joined GIFs can be at most {GIF_MAX} s – shorten or remove clips.")
        if not join and too_long:
            raise RuntimeError(f"GIFs can be at most {GIF_MAX} s – clip {too_long[0]} is longer.")

    if fx_needed(kind, fx):
        return export_fx(kind, src, clips, labels, outdir, local=local, join=join, name=name, params=params,
                         fx=fx, ffmpeg=ffmpeg, ffprobe=ffprobe, emit=emit, info=info)
    if not join:
        files = []
        for k, (s, e) in enumerate(clips):
            nm = unique_name(outdir, clip_file_name(name, k, labels[k]), ext) if name else None
            files += _single_export(kind, src, s, e, outdir, local, params, nm, ffmpeg, ffprobe,
                                    _sub_emit(emit, k, n, f"Clip {k + 1}/{n}"))
        return [Path(f) for f in files]

    tmp = outdir / f".ytclip_join_{os.getpid()}_{int(time.time() * 1000) % 100000}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        pieces = []
        for k, (s, e) in enumerate(clips):
            pieces.append(_piece(kind, src, s, e, tmp, k, local, params, ffmpeg, ffprobe,
                                 _sub_emit(emit, k, n + 1, f"Clip {k + 1}/{n}")))
        jemit = _sub_emit(emit, n, n + 1, "Joining")
        dst = outdir / ((safe_name(name) if name else "clips") + ext)
        if kind == "mp4":
            codec, profile = params["codec"], params["profile"]
            enc = check_encoder(params["encoder"], ffmpeg, emit, codec)
            total = sum(e - s for s, e in clips)
            vargs, aargs = encode_args(enc, params["size"], params["target_mb"], total, codec, profile)
            jemit("status", f"{n} clips …")
            return [join_video(pieces, dst, vargs=vargs, aargs=aargs, ffmpeg=ffmpeg, ffprobe=ffprobe, emit=jemit)]
        if kind == "mp3":
            cover = None
            if params["afmt"] in ("mp3", "m4a"):
                try:
                    at = clips[0][0] + min(1.0, (clips[0][1] - clips[0][0]) / 2)
                    cover = save_thumbnail(src if not local else str(src), tmp / "cover.jpg", ffmpeg=ffmpeg,
                                           info=info, at=at)
                except Exception:  # noqa: BLE001 - no cover is fine
                    cover = None
            return [join_audio(pieces, dst, afmt=params["afmt"], kbps=params["kbps"], ffmpeg=ffmpeg,
                               ffprobe=ffprobe, emit=jemit, title=dst.stem, cover=cover)]
        # GIF: join to a clean intermediate, then the usual two-pass palette
        mid = tmp / "joined.mp4"
        join_video(pieces, mid, vargs=["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p"],
                   aargs=[], ffmpeg=ffmpeg, ffprobe=ffprobe, emit=_sub_emit(emit, n, n + 2, "Joining"), audio=False)
        dur = media_info(mid, ffprobe)["duration"]
        return [gif_encode(mid, dst, None, None, dur, params["width"], params["fps"], params["colors"], ffmpeg,
                           _sub_emit(emit, n + 1, n + 2, "GIF"))]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- streamed preview (no download)

STREAM_CHUNK = 2 * 1024 * 1024   # bytes per request to YouTube (big open requests get throttled)


_NET: dict = {"ydl": None, "key": None}
_NET_LOCK = threading.Lock()


def _net_ydl():
    """One yt-dlp instance for the proxy's requests: the same network code, login, proxy settings and certificates
    as yt-dlp's own downloads – on some PCs YouTube refuses everything else (403)."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return None
    key = repr(sorted((k, str(v)) for k, v in YDL_EXTRA.items())) + f"|{_LOGIN['ver']}"   # new login -> new instance
    with _NET_LOCK:
        if _NET["ydl"] is None or _NET["key"] != key:
            # the old one is just dropped: closing it would write its cookies back (e.g. after signing out)
            _NET["ydl"] = YoutubeDL({"quiet": True, "no_warnings": True, "logger": _Silent(),
                                     **{k: v for k, v in YDL_EXTRA.items() if k != "login"}})
            add_login(_NET["ydl"])
            _NET["key"] = key
        return _NET["ydl"]


def _stream_fmt(f, info) -> dict:
    hdrs = {k: v for k, v in dict(f.get("http_headers") or info.get("http_headers") or {}).items()
            if k.lower() not in ("accept-encoding", "range")}
    ck = _cookie_header(f.get("cookies") or info.get("cookies"))   # TikTok & co. need their cookies
    if ck:
        hdrs["Cookie"] = ck
    return {"url": f["url"], "headers": hdrs, "size": f.get("filesize") or None, "ext": f.get("ext") or "mp4",
            "height": f.get("height"), "fps": f.get("fps")}


STREAM_QUALITIES = (360, 480, 720, 1080)


def stream_choices(info) -> dict:
    """The preview stream in a few qualities: {'auto': …, 360: …, 720: …} (only heights the video really has)."""
    out = {"auto": pick_streams(info)}
    if not out["auto"]:
        return out
    seen = set()
    for q in STREAM_QUALITIES:
        st = pick_streams(info, q)
        h = st and st["video"].get("height")
        if st and h and h not in seen and min(h, 9999) <= q:
            seen.add(h)
            out[q] = st
    return out


def pick_streams(info, target=None) -> dict | None:
    """Plain HTTP files of the video for the player: one with picture + sound if there is one (≤720p),
    else a picture-only file (around 480p, H.264 preferred) plus a sound-only file. With `target` (a height):
    the picture closest to it (not above), with a separate sound file if needed."""
    fmts = [f for f in info.get("formats") or []
            if f.get("url") and str(f.get("protocol") or "") in ("http", "https")
            and not f.get("fragments") and f.get("ext") in ("mp4", "webm", "m4a")]

    def has_v(f):
        return f.get("vcodec") not in (None, "none")

    def has_a(f):
        return f.get("acodec") not in (None, "none")

    def short(f):   # vertical videos (TikTok, Reels, Shorts): the short side counts
        w, h = f.get("width") or 0, f.get("height") or 0
        return min(w, h) if w and h else h

    def vrank(f):
        h = short(f)
        return (abs(min(h, 720) - 480) if h else 9999, 0 if str(f.get("vcodec") or "").startswith("avc") else 1,
                f.get("tbr") or 0)

    if target:
        vids = [f for f in fmts if has_v(f) and short(f) and short(f) <= target]
        if not vids:
            return None
        top = max(short(f) for f in vids)
        cands = [f for f in vids if short(f) == top]
        v = min(cands, key=lambda f: (0 if has_a(f) else 1, 0 if str(f.get("vcodec") or "").startswith("avc") else 1,
                                      f.get("tbr") or 0))
        if has_a(v):
            return {"video": _stream_fmt(v, info), "audio": None, "fps": v.get("fps")}
        auds = [f for f in fmts if has_a(f) and not has_v(f)]
        a = min(auds, key=lambda f: (0 if f.get("ext") == "m4a" else 1, abs((f.get("abr") or 128) - 128))) if auds else None
        return {"video": _stream_fmt(v, info), "audio": _stream_fmt(a, info) if a else None, "fps": v.get("fps")}
    both = [f for f in fmts if has_v(f) and has_a(f) and short(f) <= 720]
    if both:
        best = min(both, key=vrank)
        return {"video": _stream_fmt(best, info), "audio": None, "fps": best.get("fps")}
    vids = [f for f in fmts if has_v(f) and not has_a(f) and short(f) <= 720]
    auds = [f for f in fmts if has_a(f) and not has_v(f)]
    if not vids:
        big = [f for f in fmts if has_v(f) and has_a(f)]      # only big files with picture + sound: take the smallest
        if not big:
            return None
        best = min(big, key=lambda f: (short(f) or 9999, f.get("tbr") or 0))
        return {"video": _stream_fmt(best, info), "audio": None, "fps": best.get("fps")}
    v = min(vids, key=vrank)
    a = min(auds, key=lambda f: (0 if f.get("ext") == "m4a" else 1, abs((f.get("abr") or 128) - 128))) if auds else None
    return {"video": _stream_fmt(v, info), "audio": _stream_fmt(a, info) if a else None, "fps": v.get("fps")}


class StreamProxy:
    """Tiny local web server for the player: it asks for byte ranges, the proxy fetches them from YouTube in
    small pieces (with the same headers yt-dlp uses). Nothing is written to disk, there are no ads."""

    def __init__(self):
        import http.server
        proxy = self
        self.items: dict[str, dict] = {}
        self._n = 0
        self.last_error = ""      # what YouTube answered when a request failed (for the log)

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_HEAD(self):
                proxy._serve(self, head=True)

            def do_GET(self):
                proxy._serve(self, head=False)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add(self, item: dict) -> str:
        self._n += 1
        key = f"s{self._n}"
        self.items[key] = dict(item)
        return f"http://127.0.0.1:{self.port}/{key}.{item.get('ext') or 'mp4'}"

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _open(item, a, b):
        hdrs = {**item["headers"], "Range": f"bytes={a}-{b}", "Accept-Encoding": "identity"}
        ydl = _net_ydl()
        if ydl is not None:
            from yt_dlp.networking import Request
            hdrs.pop("Cookie", None)        # yt-dlp adds the cookies itself (same as for its own downloads)
            return ydl.urlopen(Request(item["url"], headers=hdrs, extensions={"timeout": 20}))
        import urllib.request
        return urllib.request.urlopen(urllib.request.Request(item["url"], headers=hdrs), timeout=20)

    def _fail(self, ex) -> None:
        msg = clean_error(ex).splitlines()[0][:200] if str(ex) else type(ex).__name__
        self.last_error = msg

    def _size(self, item) -> int:
        if not item.get("size"):
            with self._open(item, 0, 0) as r:
                m = re.search(r"/(\d+)", r.headers.get("Content-Range", ""))
                item["size"] = int(m.group(1)) if m else int(r.headers.get("Content-Length") or 0)
        return int(item["size"])

    def _serve(self, h, head):
        item = self.items.get(h.path.lstrip("/").split(".")[0])
        if item is None:
            h.send_error(404)
            return
        try:
            total = self._size(item)
        except Exception as ex:  # noqa: BLE001 - expired link, no internet, 403 …
            self._fail(ex)
            h.send_error(502)
            return
        m = re.match(r"bytes=(\d*)-(\d*)", h.headers.get("Range") or "")
        start, end = 0, total - 1
        if m and m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total - 1
        elif m and m.group(2):
            start = max(0, total - int(m.group(2)))
        end = min(end, total - 1)
        if start > end:
            h.send_response(416)
            h.send_header("Content-Range", f"bytes */{total}")
            h.send_header("Content-Length", "0")
            h.end_headers()
            return
        h.send_response(206 if m else 200)
        h.send_header("Content-Type", {"mp4": "video/mp4", "m4a": "audio/mp4", "webm": "video/webm"}
                      .get(item.get("ext"), "application/octet-stream"))
        h.send_header("Accept-Ranges", "bytes")
        h.send_header("Content-Length", str(end - start + 1))
        if m:
            h.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        h.end_headers()
        if head:
            return
        pos = start
        while pos <= end:
            b = min(end, pos + STREAM_CHUNK - 1)
            try:
                r = self._open(item, pos, b)
            except Exception as ex:  # noqa: BLE001 - YouTube said no (403 …), no internet
                self._fail(ex)
                break
            client_gone = False
            with r:
                while True:
                    try:
                        data = r.read(65536)
                    except Exception as ex:  # noqa: BLE001
                        self._fail(ex)
                        data = b""
                    if not data:
                        break
                    try:
                        h.wfile.write(data)
                    except OSError:      # the player jumped elsewhere or stopped - normal
                        client_gone = True
                        break
                    pos += len(data)
            if client_gone or pos <= b:  # YouTube sent less than asked -> stop cleanly
                break
        if pos <= end:
            h.close_connection = True


# ----------------------------------------------------------------------------- crop / size / volume / subtitles

def _even(x) -> int:
    return max(2, int(round(float(x) / 2.0)) * 2)


FREE_BOX = (0.1, 0.1, 0.8, 0.8)


def crop_rect(box, W, H, aspect):
    """box: (x, y, w, h) as fractions of the frame -> (cw, ch, cx, cy) in pixels with exactly this aspect
    (FREE: exactly the box, any shape)."""
    if isinstance(aspect, str):       # FREE
        x, y, w, h = box if box else FREE_BOX
        cw = min(_even(max(16.0, w * W)), W - W % 2)
        ch = min(_even(max(16.0, h * H)), H - H % 2)
        cx = min(max(0, int(round(x * W))), W - cw)
        cy = min(max(0, int(round(y * H))), H - ch)
        return cw, ch, cx, cy
    aw, ah = aspect
    x, y, w, h = box if box else (0.0, 0.0, 1.0, 1.0)
    cw = max(16.0, w * W, h * H * aw / ah)   # the box was drawn on the (smaller) preview -> don't lose a pixel
    ch = cw * ah / aw
    if ch > H:
        ch, cw = H, H * aw / ah
    if cw > W:
        cw, ch = W, W * ah / aw
    cw, ch = min(_even(cw), W - W % 2), min(_even(ch), H - H % 2)
    if box is None:   # centered
        cx, cy = (W - cw) // 2, (H - ch) // 2
    else:
        cx = min(max(0, int(round(x * W))), W - cw)
        cy = min(max(0, int(round(y * H))), H - ch)
    return cw, ch, cx, cy


def center_box(aspect, W, H):
    """Biggest centered box with this aspect, as fractions (FREE: a centered box over 80 % of the picture)."""
    if isinstance(aspect, str):       # FREE
        return FREE_BOX
    cw, ch, cx, cy = crop_rect(None, W, H, aspect)
    return (cx / W, cy / H, cw / W, ch / H)


def out_dims(cw, ch, short, aspect=None):
    """Size of the result: the crop itself, or scaled so that the short side is `short` px
    (with a crop format the exact ratio of the format, e.g. 1080 × 1920 for 9:16)."""
    if not short:
        return _even(cw), _even(ch)
    if aspect and not isinstance(aspect, str):
        cw, ch = aspect
    if cw <= ch:
        return _even(short), _even(short * ch / cw)
    return _even(short * cw / ch), _even(short)


def target_dims(cw, ch, up, aspect=None):
    """Size of the result for an upscale setting: None (keep), ("x", factor) or ("short", px)."""
    if not up:
        return _even(cw), _even(ch)
    kind, v = up
    if kind == "x":
        return _even(cw * v), _even(ch * v)
    return out_dims(cw, ch, v, aspect)


def _vpts(points):
    """[t, gain] or [t, gain, ease] -> sorted [(t, gain, ease)]"""
    return sorted(((float(p[0]), max(0.0, float(p[1])), (p[2] if len(p) > 2 else "linear") or "linear")
                   for p in points), key=lambda q: q[0])


def ease_f(kind, u) -> float:
    """0..1 -> 0..1 for the curve between two points (Easy ease = slow out of the first point, slow into the next)."""
    u = min(max(u, 0.0), 1.0)
    if kind == "ease":
        return u * u * (3 - 2 * u)
    if kind == "in":
        return u * u
    if kind == "out":
        return u * (2 - u)
    if kind == "hold":
        return 0.0
    return u


def vol_at(points, t) -> float:
    """Value of the volume curve at time t (1.0 = unchanged). Each point says how it goes on to the next one."""
    pts = _vpts(points)
    if not pts:
        return 1.0
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, g0, e0), (t1, g1, _e1) in zip(pts, pts[1:]):
        if t < t1:
            return g0 + (g1 - g0) * ease_f(e0, (t - t0) / (t1 - t0)) if t1 > t0 else g1
    return pts[-1][1]


def _ease_expr(kind, u) -> str:
    if kind == "ease":
        return f"({u})*({u})*(3-2*({u}))"
    if kind == "in":
        return f"({u})*({u})"
    if kind == "out":
        return f"({u})*(2-({u}))"
    if kind == "hold":
        return "0"
    return f"({u})"


def vol_filter(points, offset) -> str:
    """FFmpeg filter for the volume curve; t = 0 is `offset` on the source timeline.
    Small audio frames (256 samples ≈ 5 ms) so the curve is smooth without zipper noise."""
    pts = [(t - offset, g, e) for t, g, e in _vpts(points)]
    if not pts or all(abs(g - 1.0) < 1e-4 for _t, g, _e in pts):
        return ""
    expr = f"{pts[-1][1]:.4f}"
    for (t0, g0, e0), (t1, g1, _e1) in reversed(list(zip(pts, pts[1:]))):
        if t1 - t0 < 1e-6:
            seg = f"{g1:.4f}"
        else:
            u = f"(t-({t0:.4f}))/{t1 - t0:.4f}"
            seg = f"{g0:.4f}+({g1 - g0:.4f})*{_ease_expr(e0, u)}"
        expr = f"if(lt(t,{t1:.4f}),{seg},{expr})"
    expr = f"if(lt(t,{pts[0][0]:.4f}),{pts[0][1]:.4f},{expr})"
    return f"asetnsamples=n=256:p=0,volume=eval=frame:volume='{expr}'"


def clip_file_name(base, k, label="") -> str:
    lab = safe_name(label)[:60].strip() if label else ""
    return f"{base}_{k + 1:02d}" + (f" {lab}" if lab else "")


def fx_needed(kind, fx) -> bool:
    """Does this export need the extra encode step (crop, size, volume curve, subtitles in the picture)?"""
    if not fx:
        return False
    if kind in ("mp4", "gif") and (fx.get("aspect") or (kind == "mp4" and fx.get("up"))):
        return True
    if abs(float(fx.get("speed") or 1.0) - 1.0) > 1e-6:
        return True
    if kind in ("mp4", "mp3") and any(abs(float(p[1]) - 1.0) > 1e-4 for p in fx.get("vol") or []):
        return True
    subs = fx.get("subs") or {}
    return bool(subs.get("cues")) and (subs.get("mode") == "burn" and kind in ("mp4", "gif")
                                       or subs.get("mode") == "track" and kind == "mp4")


# ---- subtitles

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?")
_TAG = re.compile(r"<[^>]*>")


def _ts(text) -> float:
    m = _TS.search(text)
    if not m:
        raise ValueError(text)
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (int((ms or "0").ljust(3, "0")) / 1000)


def _clean_text(t) -> str:
    import html
    t = html.unescape(_TAG.sub("", t)).replace("​", "")
    return "\n".join(x.strip() for x in t.splitlines() if x.strip())


def parse_srt_vtt(text):
    """SRT or WebVTT -> [(start, end, text)]. Rolling YouTube auto captions (each line repeated in the next
    cue) are reduced to the new lines."""
    cues, prev = [], []
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    for block in re.split(r"\n\s*\n", text):
        lines = block.strip("\n").split("\n")
        idx = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if idx is None:
            continue
        a, b = lines[idx].split("-->", 1)
        try:
            s, e = _ts(a), _ts(b.strip().split(" ")[0])
        except ValueError:
            continue
        body = [x for x in _clean_text("\n".join(lines[idx + 1:])).split("\n") if x]
        new = [x for x in body if x not in prev]
        prev = body
        if not new or e <= s:
            continue
        cues.append([s, e, "\n".join(new)])
    return _tidy_cues(cues)


def parse_json3(data):
    import json as _json
    d = _json.loads(data) if isinstance(data, (str, bytes)) else data
    cues = []
    for ev in d.get("events") or []:
        if ev.get("aAppend") or not ev.get("segs"):
            continue
        txt = _clean_text("".join(s.get("utf8", "") for s in ev["segs"]))
        if not txt:
            continue
        s = ev.get("tStartMs", 0) / 1000
        e = s + (ev.get("dDurationMs") or 2000) / 1000
        cues.append([s, e, txt])
    return _tidy_cues(cues)


def parse_ass(text):
    cues, fmt = [], None
    for line in text.replace("\r", "").splitlines():
        if line.startswith("Format:") and fmt is None:
            fmt = [x.strip().lower() for x in line[7:].split(",")]
        elif line.startswith("Dialogue:"):
            f = fmt or ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
            parts = line[9:].split(",", len(f) - 1)
            try:
                s, e = _ts(parts[f.index("start")]), _ts(parts[f.index("end")])
            except (ValueError, IndexError):
                continue
            txt = re.sub(r"\{[^}]*\}", "", parts[-1]).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
            txt = _clean_text(txt)
            if txt and e > s:
                cues.append([s, e, txt])
    return _tidy_cues(cues)


def parse_subs(data, ext="") -> list:
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    ext = ext.lower().lstrip(".")
    if ext == "json3" or data.lstrip().startswith("{"):
        return parse_json3(data)
    if ext in ("ass", "ssa") or "[Script Info]" in data[:200]:
        return parse_ass(data)
    return parse_srt_vtt(data)


def _tidy_cues(cues):
    """Sorted, no overlaps (one line after the other), at least 0.2 s each."""
    cues = sorted(([float(s), float(e), t] for s, e, t in cues), key=lambda c: c[0])
    out = []
    for i, c in enumerate(cues):
        if i + 1 < len(cues) and cues[i + 1][0] > c[0]:
            c[1] = min(c[1], cues[i + 1][0])
        if c[1] - c[0] >= 0.05:
            out.append((round(c[0], 3), round(c[1], 3), c[2]))
    return out


def cue_at(cues, t):
    for s, e, txt in cues:
        if s <= t < e:
            return txt
        if s > t:
            break
    return ""


def _srt_ts(t) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cues, dst) -> Path:
    lines = []
    for i, (s, e, txt) in enumerate(cues, 1):
        lines += [str(i), f"{_srt_ts(s)} --> {_srt_ts(e)}", txt, ""]
    Path(dst).write_text("\n".join(lines), encoding="utf-8")
    return Path(dst)


def map_cues(cues, segs):
    """Cues of the source timeline -> cues of the result. segs: [(start, end, offset_in_result)]."""
    out = []
    for s0, e0, off in segs:
        for s, e, txt in cues:
            if e <= s0 or s >= e0:
                continue
            a, b = max(s, s0) - s0 + off, min(e, e0) - s0 + off
            if b - a >= 0.05:
                out.append((a, b, txt))
    return out


def _ass_color(hexcol, alpha=0) -> str:
    c = str(hexcol or "#ffffff").lstrip("#")
    c = (c + "ffffff")[:6]
    return f"&H{alpha:02X}{c[4:6]}{c[2:4]}{c[0:2]}".upper()


def sub_layout(w, h, style=None):
    """Font size, outline and position of the subtitles for a w × h picture (same for preview and export).
    -> (font px, outline px, anchor x, anchor y) – the anchor is the bottom center of the text."""
    st = {**SUB_STYLE, **(style or {})}
    fs = max(8.0, min(w, h) * 0.055 * float(st.get("size") or 100) / 100)
    pos = st.get("pos")
    if pos:
        ax, ay = pos[0] * w, pos[1] * h
    else:
        ax, ay = w / 2, h * (1 - (0.17 if h > w * 1.2 else 0.06))
    return fs, max(1.5, fs * 0.075), ax, ay


def write_ass(cues, dst, w, h, style=None) -> Path:
    """Burned-in subtitles in the chosen font, size, colors and position (default: bottom center, on tall
    9:16 videos a bit higher so TikTok / Reels / Shorts buttons don't cover them)."""
    def ts(t):
        cs = int(round(max(0.0, t) * 100))
        return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"
    st = {**SUB_STYLE, **(style or {})}
    fs, ol, ax, ay = sub_layout(w, h, st)
    fs = round(fs)
    mv = round(h - ay)
    ml = round(w * 0.07)
    font = str(st.get("font") or "Arial").replace(",", " ")
    bold = -1 if st.get("bold") else 0
    pos = f"{{\\an2\\pos({ax:.0f},{ay:.0f})}}" if st.get("pos") else ""
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{font},{fs},{_ass_color(st.get('color'))},{_ass_color(st.get('color'))},"
            f"{_ass_color(st.get('outline'))},{_ass_color(st.get('outline'), 0x64)},{bold},0,0,0,100,100,0,0,1,"
            f"{ol:.1f},{max(0.0, fs * 0.03):.1f},2,{ml},{ml},{mv},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    for s, e, txt in cues:
        t = txt.replace("{", "(").replace("}", ")").replace("\n", "\\N")
        ev.append(f"Dialogue: 0,{ts(s)},{ts(e)},Default,,0,0,0,,{pos}{t}")
    Path(dst).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
    return Path(dst)


_ISO2 = {"en": "eng", "de": "ger", "fr": "fre", "es": "spa", "it": "ita", "ja": "jpn", "ko": "kor", "zh": "chi",
         "pt": "por", "ru": "rus", "nl": "dut", "pl": "pol", "tr": "tur", "ar": "ara", "hi": "hin", "sv": "swe"}


def _iso639_2(lang) -> str:
    code = str(lang or "").split("-")[0].lower()
    return _ISO2.get(code, code if len(code) == 3 else "und")


def _lang_name(code) -> str:
    names = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "ja": "Japanese",
             "ko": "Korean", "zh": "Chinese", "pt": "Portuguese", "ru": "Russian", "nl": "Dutch", "pl": "Polish",
             "tr": "Turkish", "ar": "Arabic", "hi": "Hindi", "sv": "Swedish", "id": "Indonesian", "vi": "Vietnamese"}
    base = str(code).split("-")[0].lower()
    return names.get(base, str(code))


def list_subs(info) -> list:
    """Subtitles of a video for the menu: the real ones first, then the automatic ones (original language,
    English and German translations)."""
    out = []
    for key, fmts in (info.get("subtitles") or {}).items():
        if key == "live_chat" or not fmts:
            continue
        name = next((f.get("name") for f in fmts if f.get("name")), "") or _lang_name(key)
        out.append({"label": name, "kind": "yt", "key": key})
    auto = info.get("automatic_captions") or {}
    orig = [k for k in auto if k.endswith("-orig")]
    lang = info.get("language")
    seen = set()
    for key in orig + ([lang] if lang in auto else []):
        base = key.replace("-orig", "")
        if base in seen:
            continue
        seen.add(base)
        out.append({"label": f"{_lang_name(base)} (automatic)", "kind": "yt-auto", "key": key})
    for key in ("en", "de"):
        if key in auto and key not in seen:
            seen.add(key)
            out.append({"label": f"{_lang_name(key)} (automatic, translated)", "kind": "yt-auto", "key": key})
    return out


def sidecar_subs(path) -> list:
    """Subtitle files next to a video: movie.srt, movie.en.srt, movie.de.vtt …"""
    p = Path(path)
    out = []
    try:
        for f in sorted(p.parent.iterdir()):
            if f.suffix.lower() in (".srt", ".vtt", ".ass", ".ssa") and f.name.lower().startswith(p.stem.lower()):
                out.append({"label": f"{f.name} (file next to the video)", "kind": "file", "key": str(f)})
    except OSError:
        pass
    return out


def fetch_subs(url, item, ffmpeg=None) -> list:
    """Loads one entry of list_subs / local_info['subs'] (or a file) -> cues."""
    kind, key = item.get("kind"), item.get("key")
    if kind == "file":
        p = Path(key)
        return parse_subs(p.read_bytes(), p.suffix)
    if kind == "embedded":
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(url), "-map", f"0:s:{key}",
                            "-f", "srt", "-"], capture_output=True, timeout=180, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("Could not read the subtitles: " + r.stderr.decode("utf-8", "replace").strip()[-200:])
        return parse_srt_vtt(r.stdout.decode("utf-8", "replace"))
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ytclip_subs_") as td:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
                "writesubtitles": kind == "yt", "writeautomaticsub": kind == "yt-auto",
                "subtitleslangs": [key], "subtitlesformat": "json3/srt/vtt/best",
                "outtmpl": str(Path(td) / "subs.%(ext)s"), "logger": _Silent(), **YDL_EXTRA}
        ydl_extract(opts, url, download=True)
        files = [f for f in Path(td).iterdir() if f.is_file()]
        if not files:
            raise RuntimeError("These subtitles could not be downloaded.")
        f = files[0]
        return parse_subs(f.read_bytes(), f.suffix)


def save_srts(files, clips, cues, join) -> list:
    """.srt next to the results (times of the result). files: the media files in clip order."""
    out = []
    if not cues or not files:
        return out
    groups = [list(range(len(clips)))] if join else [[k] for k in range(len(clips))]
    for f, g in zip(files, groups):
        segs, off = [], 0.0
        for k in g:
            s, e = clips[k][0], clips[k][1]
            segs.append((s, e, off))
            off += e - s
        mapped = map_cues(cues, segs)
        if mapped:
            out.append(write_srt(mapped, Path(f).with_suffix(".srt")))
    return out


# ---- the export with effects

def _clip_names(outdir, name, labels, join, ext, base):
    if join:
        return [name or unique_name(outdir, base, ext)]
    return [unique_name(outdir, clip_file_name(name or base, k, labels[k]), ext) for k in range(len(labels))]


def export_fx(kind, src, clips, labels, outdir, *, local, join, name, params, fx, ffmpeg, ffprobe, emit, info=None):
    """Clips -> pieces in a good intermediate quality -> crop / scale / volume curve / subtitles
    in one more encode. join: all clips in one file, else one file per clip."""
    n = len(clips)
    ext = _kind_ext(kind, params)
    base = safe_name((info or {}).get("title") or Path(str(src)).stem or "clip")
    names = _clip_names(outdir, name, labels, join, ext, base)
    groups = [list(range(n))] if join else [[k] for k in range(n)]
    aspect = fx.get("aspect") if kind in ("mp4", "gif") else None
    boxes = list(fx.get("boxes") or []) + [None] * n
    subs = fx.get("subs") or {}
    cues = subs.get("cues") or []
    mode = subs.get("mode") if cues else None
    if kind == "mp3":
        mode = None
    elif kind == "gif" and mode == "track":
        mode = "burn"
    vol = fx.get("vol") or []
    speed = float(fx.get("speed") or 1.0)
    steps = n + len(groups)
    step = [0]

    def sub(label):
        e = _sub_emit(emit, step[0], steps, label)
        step[0] += 1
        return e

    tmp = (Path(outdir) / f".ytclip_fx_{os.getpid()}_{int(time.time() * 1000) % 100000}").resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        pieces = []
        for k, (s, e) in enumerate(clips):
            pieces.append(_piece(kind, src, s, e, tmp, k, local, params, ffmpeg, ffprobe,
                                 sub(f"Clip {k + 1}/{n}" if n > 1 else "Clip")))
        for gi, g in enumerate(groups):
            gemit = sub("Saving" if len(groups) == 1 else f"File {gi + 1}/{len(groups)}")
            dst = Path(outdir) / (names[gi] + ext)
            ps = [pieces[k] for k in g]
            infos = [media_info(p, ffprobe) for p in ps]
            afx = [vol_filter(vol, clips[k][0]) if kind in ("mp4", "mp3") else "" for k in g]
            if kind == "mp3":
                cover = None
                if params["afmt"] in ("mp3", "m4a"):
                    try:
                        at = clips[g[0]][0] + min(1.0, (clips[g[0]][1] - clips[g[0]][0]) / 2)
                        cover = save_thumbnail(src if not local else str(src), tmp / f"cover{gi}.jpg", ffmpeg=ffmpeg,
                                               info=info, at=at)
                    except Exception:  # noqa: BLE001
                        cover = None
                results.append(join_audio(ps, dst, afmt=params["afmt"], kbps=params["kbps"], ffmpeg=ffmpeg,
                                          ffprobe=ffprobe, emit=gemit, title=dst.stem, cover=cover, afx=afx,
                                          label="Saving", speed=speed))
                continue
            # picture: crop per clip, one output size for the file
            crops = []
            for k, inf in zip(g, infos):
                crops.append(crop_rect(boxes[k], inf["width"], inf["height"], aspect) if aspect else None)
            cw, ch = (crops[0][0], crops[0][1]) if aspect else (infos[0]["width"], infos[0]["height"])
            W, H = target_dims(cw, ch, fx.get("up") if kind == "mp4" else None, aspect)
            segs, off = [], 0.0
            for k, inf in zip(g, infos):
                segs.append((clips[k][0], clips[k][1], off))
                off += inf["vdur"]
            mapped = map_cues(cues, segs) if mode else []
            if mode == "track" and speed != 1.0:     # a subtitle track runs on the sped-up timeline
                mapped = [(a / speed, b / speed, t) for a, b, t in mapped]
            post_vf, track = "", None
            if mode == "burn" and mapped:
                style = subs.get("style") or {}
                write_ass(mapped, tmp / f"subs{gi}.ass", W, H, style)
                fdir = tmp / "fonts"
                n_fonts = collect_fonts(style, fdir)
                post_vf = f"ass=subs{gi}.ass" + (":fontsdir=fonts" if n_fonts else "")
            elif mode == "track" and mapped:
                track = write_srt(mapped, tmp / f"subs{gi}.srt").name
            if kind == "mp4":
                codec, profile = params["codec"], params["profile"]
                enc = check_encoder(params["encoder"], ffmpeg, emit, codec)
                total = sum(inf["vdur"] for inf in infos) / speed
                vargs, aargs = encode_args(enc, params["size"], params["target_mb"], total, codec, profile)
                results.append(join_video(ps, dst, vargs=vargs, aargs=aargs, ffmpeg=ffmpeg, ffprobe=ffprobe,
                                          emit=gemit, crops=crops, size=(W, H), afx=afx, post_vf=post_vf,
                                          sub_track=track, sub_lang=subs.get("lang"), cwd=str(tmp),
                                          label="Saving", infos=infos, speed=speed))
            else:  # GIF: clean intermediate with crop + subtitles, then the usual palette
                mid = tmp / f"gif{gi}.mp4"
                join_video(ps, mid, vargs=["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt",
                                           "yuv420p"], aargs=[], ffmpeg=ffmpeg, ffprobe=ffprobe, emit=gemit,
                           audio=False, crops=crops, size=(W, H), post_vf=post_vf, cwd=str(tmp), infos=infos,
                           speed=speed)
                dur = media_info(mid, ffprobe)["duration"]
                results.append(gif_encode(mid, dst, None, None, dur, params["width"], params["fps"], params["colors"],
                                          ffmpeg, gemit))
        return results
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- AI upscaling (ncnn / Vulkan)
# Runs on NVIDIA, AMD and Intel graphics (Vulkan), no CUDA / Python AI packages. Each engine is downloaded on
# first use; Settings show its version and whether GitHub has a newer one.

UPSCALE_DIR = APP_DIR / "upscalers"
ENGINES = {
    "esrgan": {"name": "Real-ESRGAN", "repo": "xinntao/Real-ESRGAN", "exe": "realesrgan-ncnn-vulkan",
               "asset": r"^realesrgan-ncnn-vulkan-(\d{8})-windows\.zip$", "version": "20220424", "mb": 45,
               "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
                      "realesrgan-ncnn-vulkan-20220424-windows.zip",
               "sha256": "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
               "about": "UltraSharp, Siax, Nomos8kSC, HFA2k and the classic models"},
    "cugan": {"name": "Real-CUGAN", "repo": "nihui/realcugan-ncnn-vulkan", "exe": "realcugan-ncnn-vulkan",
              "asset": r"^realcugan-ncnn-vulkan-(\d{8})-windows\.zip$", "version": "20220728", "mb": 44,
              "url": "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/"
                     "realcugan-ncnn-vulkan-20220728-windows.zip",
              "sha256": "c6e08d46c11704b1e3a1ada9ddd591cb5005f52f132136c8633ba25def400e01",
              "about": "anime – Real-CUGAN Pro"},
}


_UPS = "https://raw.githubusercontent.com/upscayl/upscayl/a00d55fee90e0f9435d5eaa86e76700df8199af8/resources/models/"
_CUS = "https://raw.githubusercontent.com/upscayl/custom-models/4b6d2cfa59c7442af115dfc6e50fd8d7d40b96ef/models/"
# Extra models for Real-ESRGAN (ncnn files, converted by the Upscayl project); downloaded when first used.
AI_FILES = {
    "ultrasharp": {"name": "UltraSharp", "model": "ultrasharp-4x", "base": _UPS, "mb": 32,
                   "param": "0136ca83686809a8f17f7111f11b951e8db93610e24b7f4137c9ffe4dbc4a806",
                   "bin": "fb3e279d40d4cddb44db4e684d59e68d0aa39852c8cc14dc3f23ccc7e6eee9c1"},
    "siax": {"name": "Siax (large)", "model": "4x_NMKD-Siax_200k", "base": _CUS, "mb": 64,
             "param": "519bffb4912e295155d3cb5d6a29639d217ccca55f80962d8f677ef777a65b7a",
             "bin": "b2abdffa30fb15be752ac681e0c0edf8b543745c33a989aadc9d7d3394dd3110"},
    "nomos": {"name": "Nomos8kSC", "model": "4xNomos8kSC", "base": _CUS, "mb": 32,
              "param": "4576ed5c2fc5fa250d3c3d585ef02248f26abdfc1867088078f501fe71e5d61e",
              "bin": "da16e3880d87b177b7c6b659bbd880f8a101b868eb9ebc08d69eaa6d3edc4517"},
    "hfa2k": {"name": "HFA2k", "model": "4xHFA2k", "base": _CUS, "mb": 32,
              "param": "4576ed5c2fc5fa250d3c3d585ef02248f26abdfc1867088078f501fe71e5d61e",
              "bin": "8a135402b4f39286121b76abb47601a6b7b7e8d4f3e999a5aaa45ed277824fb4"},
}
MODELS_DIR = UPSCALE_DIR / "models"     # the folder name must contain "models" for realesrgan-ncnn-vulkan


def ai_file_ok(key) -> bool:
    m = AI_FILES[key]["model"]
    return (MODELS_DIR / f"{m}.param").is_file() and (MODELS_DIR / f"{m}.bin").is_file()


def install_ai_file(key, progress=None) -> None:
    """Downloads one extra model (.param + .bin, both checked against their SHA-256)."""
    import hashlib
    import urllib.request
    f = AI_FILES[key]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    total = f["mb"] * 1048576
    done = 0
    for ext in ("param", "bin"):
        dst = MODELS_DIR / f"{f['model']}.{ext}"
        part = dst.with_suffix(f".{ext}.part")
        h = hashlib.sha256()
        req = urllib.request.Request(f["base"] + f"{f['model']}.{ext}", headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(min(99.0, done / total * 100))
            if h.hexdigest() != f[ext]:
                raise RuntimeError(f"The model {f['name']} is damaged (checksum does not match) – please try again.")
            os.replace(part, dst)
        finally:
            part.unlink(missing_ok=True)
    if progress:
        progress(100.0)


def remove_ai_file(key) -> None:
    m = AI_FILES[key]["model"]
    for ext in ("param", "bin"):
        (MODELS_DIR / f"{m}.{ext}").unlink(missing_ok=True)


def engine_dir(key) -> Path:
    return UPSCALE_DIR / key


def engine_exe(key) -> Path | None:
    d = engine_dir(key)
    for name in (ENGINES[key]["exe"] + ".exe", ENGINES[key]["exe"]):
        if (d / name).is_file():
            return d / name
    return None


def engine_version(key) -> str | None:
    if not engine_exe(key):
        return None
    try:
        return (engine_dir(key) / "version.txt").read_text(encoding="utf-8").strip() or "?"
    except OSError:
        return "?"


def engine_latest(key, timeout=15.0) -> dict:
    """Newest Windows build on GitHub -> {'version', 'url', 'sha256' (or None), 'mb'}; the known build if GitHub
    can't be asked."""
    e = ENGINES[key]
    best = {"version": e["version"], "url": e["url"], "sha256": e["sha256"], "mb": e["mb"]}
    data = json.loads(fetch_bytes(f"https://api.github.com/repos/{e['repo']}/releases?per_page=20", timeout=timeout,
                                  headers={"Accept": "application/vnd.github+json"}))
    for rel in data if isinstance(data, list) else []:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        for a in rel.get("assets") or []:
            m = re.match(e["asset"], a.get("name") or "")
            if m and m.group(1) > best["version"]:
                dig = str(a.get("digest") or "")
                best = {"version": m.group(1), "url": a.get("browser_download_url"),
                        "sha256": dig.split(":", 1)[1] if dig.startswith("sha256:") else None,
                        "mb": round((a.get("size") or 0) / 1048576) or e["mb"]}
    return best


def install_engine(key, rel=None, progress=None) -> Path:
    """Downloads an upscaler (the known build, or `rel` from engine_latest) and puts it into UPSCALE_DIR/key."""
    import hashlib
    import urllib.request
    import zipfile
    e = ENGINES[key]
    rel = rel or {"version": e["version"], "url": e["url"], "sha256": e["sha256"], "mb": e["mb"]}
    if not str(rel.get("url", "")).startswith("https://github.com/"):
        raise RuntimeError("Unexpected download address.")
    UPSCALE_DIR.mkdir(parents=True, exist_ok=True)
    zpath = UPSCALE_DIR / f"{key}_download.zip"
    tmp = UPSCALE_DIR / f"{key}_new"
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(rel["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0) or int(rel.get("mb") or 45) * 1048576
            done = 0
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(min(99.0, done / total * 100))
        if rel.get("sha256") and h.hexdigest() != rel["sha256"]:
            raise RuntimeError("The download is damaged (checksum does not match) – please try again.")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        with zipfile.ZipFile(zpath) as z:
            names = [m.filename.replace("\\", "/") for m in z.infolist()]
            tops = {n.split("/", 1)[0] for n in names if "/" in n}
            strip = (tops.pop() + "/") if len(tops) == 1 and all("/" in n for n in names) else ""
            for m, nm in zip(z.infolist(), names):
                rel_name = nm[len(strip):] if strip and nm.startswith(strip) else nm
                if not rel_name or rel_name.endswith("/") or ".." in rel_name.split("/"):
                    continue
                if rel_name.startswith("models") or rel_name.lower().endswith((".exe", ".dll")):
                    out = tmp / rel_name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        (tmp / "version.txt").write_text(str(rel["version"]), encoding="utf-8")
        shutil.rmtree(engine_dir(key), ignore_errors=True)
        os.replace(tmp, engine_dir(key))
    finally:
        zpath.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    if progress:
        progress(100.0)
    exe = engine_exe(key)
    if not exe:
        raise RuntimeError(f"{e['name']} could not be installed.")
    return exe


def remove_engine(key) -> None:
    shutil.rmtree(engine_dir(key), ignore_errors=True)


def ensure_engine(key, emit) -> Path:
    exe = engine_exe(key)
    if exe:
        return exe
    e = ENGINES[key]
    emit("log", f"Downloading the upscaler {e['name']} (≈ {e['mb']} MB, only once) …")
    emit("status", f"Downloading {e['name']} …")
    return install_engine(key, progress=lambda p: emit("progress", p))


def ai_plan(model_label, factor, video=False) -> dict:
    """What runs for this model and factor: {'engine', 'args', 'native', 'name', 'file'}."""
    engine, model, file_key, _h = AI_MODELS.get(model_label) or AI_MODELS[DEFAULT_AI_MODEL]
    name = model_label.split(" –")[0]
    if engine == "cugan":
        if factor <= 2:
            return {"engine": "cugan", "native": 2, "name": name, "file": None,
                    "args": ["-s", "2", "-n", "-1", "-m", "models-pro"]}
        return {"engine": "cugan", "native": 4, "name": name, "file": None,
                "args": ["-s", "4", "-n", "-1", "-m", "models-se"]}
    if file_key:
        return {"engine": "esrgan", "native": 4, "name": name, "file": file_key,
                "args": ["-n", model, "-s", "4", "-m", str(MODELS_DIR)]}
    return {"engine": "esrgan", "native": 4, "name": name, "file": None, "args": ["-n", model, "-s", "4", "-m", "models"]}


def run_engine(plan, src, dst, on_tick=None) -> None:
    """Upscales a picture or a folder of pictures with the engine of `plan` (PNG out)."""
    exe = engine_exe(plan["engine"])
    if not exe:
        raise RuntimeError(f"{ENGINES[plan['engine']]['name']} is not installed.")
    args = list(plan["args"])
    i = args.index("-m")
    if not Path(args[i + 1]).is_absolute():
        args[i + 1] = str(exe.parent / args[i + 1])
    cmd = [str(exe), "-i", str(src), "-o", str(dst), *args, "-f", "png"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(exe.parent),
                            creationflags=NO_WINDOW)
    err: list[bytes] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    while proc.poll() is None:
        if on_tick:
            on_tick()
        time.sleep(0.4)
    reader.join(5)
    if proc.returncode != 0 or (Path(dst).suffix and not Path(dst).is_file()):
        lines = [x for x in b"".join(err).decode("utf-8", "replace").splitlines()
                 if x.strip() and not re.match(r"^\s*\d+(\.\d+)?%\s*$", x)]
        tail = "\n".join(lines[-4:])
        hint = (" Your graphics card needs Vulkan support (a current NVIDIA / AMD / Intel driver)."
                if re.search(r"vulkan|gpu|device", tail, re.I) or not tail else "")
        raise RuntimeError(f"AI upscaling failed.{hint}" + (f"\n{tail}" if tail else ""))


AI_PX_MAX = 16384     # longest side we make


def ai_target(w, h, ai) -> tuple[int, int]:
    """Final size for a w×h picture: factor × size, or the long side set to ai['px'] (aspect kept)."""
    if ai.get("px"):
        s_ = min(int(ai["px"]), AI_PX_MAX) / max(w, h)
        return max(1, round(w * s_)), max(1, round(h * s_))
    f = int(ai.get("factor") or 1)
    return w * f, h * f


def ai_upscale_image(src, dst, ai, *, ffmpeg, emit) -> Path:
    """One picture -> AI upscaled to 2× / 4× or to a pixel size (long side), PNG or JPG by the name of dst.
    Big targets run the AI twice (e.g. a 360p thumbnail to 8K); the last step scales to the exact size."""
    import tempfile
    model_label = ai.get("model")
    with tempfile.TemporaryDirectory(prefix="ytclip_ai_") as td:
        inp = Path(td) / "in.png"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), str(inp)],
                       check=True, capture_output=True, creationflags=NO_WINDOW)
        w, h = _png_size(inp)
        ow, oh = ai_target(w, h, ai)
        need = max(ow / w, oh / h)
        plan = ai_plan(model_label, 2 if need <= 2 else 4)
        ensure_engine(plan["engine"], emit)
        if plan["file"] and not ai_file_ok(plan["file"]):
            f = AI_FILES[plan["file"]]
            emit("log", f"Downloading the AI model {f['name']} (≈ {f['mb']} MB, only once) …")
            emit("status", f"Downloading the AI model {f['name']} …")
            install_ai_file(plan["file"], progress=lambda v: emit("progress", v))
        passes = 2 if need > plan["native"] * 1.15 else 1
        cur = inp
        for i in range(passes):
            emit("status", f"AI upscaling → {ow}×{oh} px ({plan['name']})" + (f" · step {i + 1}/2" if passes > 1 else "")
                 + " …")
            emit("progress", None)
            nxt = Path(td) / f"out{i}.png"
            run_engine(plan, cur, nxt)
            cur = nxt
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(cur)]
        if _png_size(cur) != (ow, oh):
            cmd += ["-vf", f"scale={ow}:{oh}:flags=lanczos"]
        if Path(dst).suffix.lower() in (".jpg", ".jpeg"):
            cmd += ["-q:v", "2"]
        r = subprocess.run(cmd + [str(dst)], capture_output=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("FFmpeg error:\n" + r.stderr.decode("utf-8", "replace").strip()[-300:])
    emit("log", f"  AI upscaled: {w}×{h} → {ow}×{oh} px ({plan['name']})")
    return Path(dst)


# ----------------------------------------------------------------------------- still frame

def _cookie_header(s) -> str:
    """yt-dlp's cookie string (name=value; Domain=…; Path=…) -> value of an HTTP Cookie header."""
    attrs = {"domain", "path", "expires", "version", "max-age", "secure", "httponly", "samesite", "comment"}
    out = []
    for part in str(s or "").split(";"):
        part = part.strip()
        if "=" in part and part.split("=", 1)[0].strip().lower() not in attrs:
            out.append(part)
    return "; ".join(out)


def _still_format(height, direct=False) -> dict:
    """Best picture up to `height`, H.264 / MP4 first (quick to seek). direct: only plain files (no HLS / DASH
    playlists) – the local proxy can only pass those on."""
    lim = f"[height<={height}]" if height else ""
    alts = [f"bv*{lim}", f"b{lim}"] + (["bv*", "b"] if lim else [])
    if direct:
        alts = [x + "[protocol^=http][protocol!*=dash]" for x in alts] + alts
    fmt = "/".join(alts)
    return {"format": fmt, "format_sort": [f"res:{height}" if height else "res", "fps", "vcodec:h264", "ext:mp4"]}


def media_url(url, height=None) -> dict:
    """The best picture up to `height` as a stream item (address + the HTTP headers yt-dlp uses) – for single
    frames."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
            "logger": _Silent(), **_still_format(height, direct=True), **YDL_EXTRA}
    info = ydl_extract(opts, url, download=False)
    f = (info.get("requested_formats") or [info])[0]
    return _stream_fmt(f, info)


def section_file(url, height, seek, outdir, *, ffmpeg, emit) -> Path:
    """Second way for single frames: yt-dlp cuts a short piece starting exactly at `seek` (the same way clips are
    downloaded), stored lossless -> its first frame is the wanted one."""
    opts = _base_opts(outdir, "", True, emit, name="frame_piece")
    opts.update({**_still_format(height), "overwrites": True,
                 "download_ranges": make_ranges(seek, seek + 0.5),
                 "force_keyframes_at_cuts": True,
                 "external_downloader_args": {"ffmpeg_o": ["-map", "0:v:0", "-c:v", "libx264", "-preset", "ultrafast",
                                                            "-qp", "0", "-an", "-sn", "-f", "mp4"]}})
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    info = ydl_extract(opts, url, download=True)
    files = collect_files(info)
    if not files:
        raise RuntimeError("No piece was downloaded.")
    return Path(files[0])


def picture_file(url, height, outdir, *, ffmpeg, emit) -> Path:
    """Last way for single frames: yt-dlp downloads the whole picture-only file (no sound) – works wherever
    downloads work."""
    opts = _base_opts(outdir, "", False, emit, name="frame_source")
    opts.update({**_still_format(height), "overwrites": True})
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    info = ydl_extract(opts, url, download=True)
    files = collect_files(info)
    if not files:
        raise RuntimeError("The video could not be downloaded.")
    return Path(files[0])


def _png_size(path):
    import struct
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def export_still(src, t, fps, dst, *, local, height, aspect, box, up=None, ffmpeg, ffprobe, emit,
                 short=None, ai=None) -> Path:
    """The frame shown in the preview at time t, in full quality, as PNG (with crop / size)."""
    import tempfile
    fps = fps if fps and fps > 1 else 30.0
    frame = int(t * fps + 1e-3)
    seek = max(0.0, frame / fps - 0.5 / fps)        # first frame at or after this = the frame on screen
    with tempfile.TemporaryDirectory(prefix="ytclip_still_") as td:
        raw = Path(td) / "frame.png"

        def grab(inp, at=None):
            at = seek if at is None else at
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *(["-ss", f"{at:.4f}"] if at else []),
                   "-i", str(inp), "-frames:v", "1", "-update", "1", str(raw)]
            r = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=NO_WINDOW)
            ok = r.returncode == 0 and raw.is_file() and raw.stat().st_size > 0
            return ok, r.stderr.decode("utf-8", "replace").strip()

        def why(err, extra=""):
            last = (err.splitlines()[-1] if err else "") or "no picture"
            return f"{extra}; {last}" if extra else last

        if local:
            emit("status", "Grabbing the frame …")
            ok, err = grab(src)
        else:
            # 1) YouTube refuses FFmpeg's own requests (403) – the small local proxy fetches only the needed parts
            #    in pieces through yt-dlp's network code, like the preview player (fast, nothing downloaded)
            emit("status", "Finding the full-quality video …")
            item = media_url(src, height)
            proxy = StreamProxy()
            try:
                emit("status", "Grabbing the frame …")
                ok, err = grab(proxy.add(item))
            finally:
                proxy.close()
            if not ok:
                # 2) a half-second piece, cut by yt-dlp like a clip download
                emit("log", f"Reading the frame straight from YouTube didn't work ({why(err, proxy.last_error)}) – "
                            "downloading a short piece instead.")
                emit("status", "Downloading a short piece for the frame …")
                emit("progress", None)
                try:
                    ok, err = grab(section_file(src, height, seek, Path(td) / "piece", ffmpeg=ffmpeg, emit=emit), 0)
                except Exception as ex:  # noqa: BLE001
                    ok, err = False, clean_error(ex)
            if not ok:
                # 3) the whole picture-only file (slow for long videos, but works wherever downloads work)
                emit("log", f"The short piece didn't work either ({why(err)}) – downloading the picture-only file.")
                emit("status", "Downloading the video (picture only) for the frame …")
                emit("progress", None)
                ok, err = grab(picture_file(src, height, Path(td) / "src", ffmpeg=ffmpeg, emit=emit))
        if not ok:
            raise RuntimeError("Could not grab the frame:\n" + err[-300:])
        W, H = _png_size(raw)
        crop = crop_rect(box, W, H, aspect) if aspect else None
        cw, ch = (crop[0], crop[1]) if crop else (W, H)
        if up is None and short:
            up = ("short", short)
        ow, oh = target_dims(cw, ch, up, aspect)
        img = raw
        if crop:
            img = Path(td) / "crop.png"
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf",
                            f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}", str(img)],
                           check=True, capture_output=True, creationflags=NO_WINDOW)
        if ai and (ai.get("factor") or ai.get("px")):
            return ai_upscale_image(img, dst, ai, ffmpeg=ffmpeg, emit=emit)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(img)]
        if _png_size(img) != (ow, oh):
            cmd += ["-vf", f"scale={ow}:{oh}:flags=lanczos"]
        r = subprocess.run(cmd + [str(dst)], capture_output=True, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("FFmpeg error:\n" + r.stderr.decode("utf-8", "replace").strip()[-300:])
    return Path(dst)


# ----------------------------------------------------------------------------- history of links

def history_dir() -> Path:
    return Path(PATHS["history"])


def _history_file(root=None) -> Path:
    return Path(root or history_dir()) / "history.json"


def _thumbs(root=None) -> Path:
    return Path(root or history_dir()) / "thumbnails"


def _is_thumb(p: Path) -> bool:
    return p.suffix.lower() == ".jpg" and re.fullmatch(r"[0-9a-f]{16}", p.stem) is not None


def history_load(root=None) -> list:
    try:
        data = json.loads(_history_file(root).read_text(encoding="utf-8"))
        return [x for x in data if isinstance(x, dict) and x.get("url")]
    except (OSError, ValueError):
        return []


def _history_save(items, root=None) -> None:
    try:
        f = _history_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[:HISTORY_MAX], indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass


def history_thumb_path(url) -> Path:
    import hashlib
    return _thumbs() / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".jpg")


def history_add(url, info, thumb_jpg: bytes | None = None) -> None:
    items = [x for x in history_load() if x.get("url") != url]
    entry = {"url": url, "title": info.get("title") or url, "channel": info.get("channel") or "",
             "duration": info.get("duration"), "added": time.time(),
             "site": {"Youtube": "YouTube", "YoutubeTab": "YouTube"}.get(info.get("site") or "", info.get("site") or "")}
    if thumb_jpg:
        try:
            p = history_thumb_path(url)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(thumb_jpg)
            entry["thumb"] = p.name
        except OSError:
            pass
    items.insert(0, entry)
    for old in items[HISTORY_MAX:]:
        if old.get("thumb"):
            (_thumbs() / old["thumb"]).unlink(missing_ok=True)
    _history_save(items)


def history_remove(url) -> None:
    items = history_load()
    for x in items:
        if x.get("url") == url and x.get("thumb"):
            (_thumbs() / x["thumb"]).unlink(missing_ok=True)
    _history_save([x for x in items if x.get("url") != url])


def _clear_history_at(root) -> None:
    """Removes only what the app wrote (history.json + its small pictures) – the folder may be the user's own."""
    _history_file(root).unlink(missing_ok=True)
    Path(_history_file(root).with_suffix(".tmp")).unlink(missing_ok=True)
    th = _thumbs(root)
    if th.is_dir():
        for f in th.iterdir():
            if _is_thumb(f):
                f.unlink(missing_ok=True)
        try:
            th.rmdir()
        except OSError:
            pass


def history_clear() -> None:
    _clear_history_at(history_dir())


def history_stats(root=None) -> dict:
    items = history_load(root)
    th = _thumbs(root)
    size = sum(f.stat().st_size for f in th.iterdir() if _is_thumb(f)) if th.is_dir() else 0
    f = _history_file(root)
    return {"links": len(items), "bytes": size + (f.stat().st_size if f.is_file() else 0)}


def history_migrate() -> None:
    """Up to 2.7: APP_DIR/history.json + the pictures loose in APP_DIR/history -> everything in one folder."""
    root = DEFAULT_PATHS["history"]
    old = APP_DIR / "history.json"
    try:
        if old.is_file() and not _history_file(root).exists():
            root.mkdir(parents=True, exist_ok=True)
            os.replace(old, _history_file(root))
        if root.is_dir():
            for f in root.iterdir():
                if _is_thumb(f):
                    _thumbs(root).mkdir(exist_ok=True)
                    os.replace(f, _thumbs(root) / f.name)
    except OSError:
        pass


def history_move(new_root) -> int:
    """Moves the history (links + pictures) into another folder; a history already there is merged.
    -> number of links in the new folder."""
    old_root, new_root = history_dir(), Path(new_root)
    if old_root.resolve() == new_root.resolve():
        return len(history_load())
    new_root.mkdir(parents=True, exist_ok=True)
    mine, there = history_load(old_root), history_load(new_root)
    urls = {x["url"] for x in there}
    merged = sorted(there + [x for x in mine if x["url"] not in urls], key=lambda x: -float(x.get("added") or 0))
    for x in mine:
        if x.get("thumb") and (_thumbs(old_root) / x["thumb"]).is_file():
            dst = _thumbs(new_root) / x["thumb"]
            if not dst.exists():
                dst.parent.mkdir(exist_ok=True)
                shutil.move(str(_thumbs(old_root) / x["thumb"]), str(dst))
    _history_save(merged, new_root)
    _clear_history_at(old_root)
    PATHS["history"] = new_root
    return len(merged[:HISTORY_MAX])


def remove_old_upscaler() -> None:
    """The AI upscaler is gone since 2.8 – its download (≈ 45 MB) and added models are removed once."""
    for name in ("upscaler", "upscaler_new", "models"):
        shutil.rmtree(APP_DIR / name, ignore_errors=True)
    (APP_DIR / "upscaler_download.zip").unlink(missing_ok=True)


# ---- YouTube login (own sign-in window -> cookies.txt for yt-dlp)

LOGIN_COOKIES = {"LOGIN_INFO", "SAPISID", "__Secure-3PAPISID", "__Secure-1PSID", "SID"}


# The login is kept encrypted with Windows' own protection (DPAPI): readable only by your Windows user on this PC
# – a copied file is useless. yt-dlp gets the cookies handed in memory (no readable cookies file at all).

LOGIN_DAT = APP_DIR / "youtube_login.dat"
_LOGIN = {"text": None, "ver": 0}          # the login (Netscape cookie text) in memory while the app runs
_PROTECT = {"ok": None}
_DAT_MAGIC = b"YTD1"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(b):
        buf = (ctypes.c_ubyte * max(1, len(b))).from_buffer_copy(b or b"\0")
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    inp, k1 = blob(data)
    ent, k2 = blob(b"tfrog YouTube Downloader login")
    out = BLOB()
    desc = ctypes.c_wchar_p("YouTube Downloader login") if protect else None
    if not fn(ctypes.byref(inp), ctypes.cast(desc, ctypes.c_void_p) if desc else None, ctypes.byref(ent), None, None,
              0x1, ctypes.byref(out)):                                  # 0x1: never show a dialog
        raise OSError(f"Windows couldn't {'en' if protect else 'de'}crypt the login ({ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _protect(data: bytes) -> bytes:
    if os.environ.get("YTD_TEST_PROTECT"):                          # tests on Linux: a stand-in for DPAPI
        return b"T" + base64.b64encode(data[::-1])
    return _dpapi(data, True)


def _unprotect(data: bytes) -> bytes:
    if os.environ.get("YTD_TEST_PROTECT"):
        if not data.startswith(b"T"):
            raise OSError("not ours")
        return base64.b64decode(data[1:])[::-1]
    return _dpapi(data, False)


def can_protect() -> bool:
    """Encryption works on this PC (checked once)."""
    if _PROTECT["ok"] is None:
        try:
            _PROTECT["ok"] = (WIN or bool(os.environ.get("YTD_TEST_PROTECT"))) and _unprotect(_protect(b"ytd")) == b"ytd"
        except Exception:  # noqa: BLE001
            _PROTECT["ok"] = False
    return _PROTECT["ok"]


def _netscape(cookies) -> str:
    lines = ["# Netscape HTTP Cookie File", "# YouTube login of the YouTube Downloader – keep it private.", ""]
    for dom, cpath, secure, exp, name, value, http_only in cookies:
        if "youtube.com" not in dom or not name:
            continue
        sub = "TRUE" if dom.startswith(".") else "FALSE"
        pre = "#HttpOnly_" if http_only else ""
        lines.append("\t".join([pre + dom, sub, cpath or "/", "TRUE" if secure else "FALSE", str(int(exp or 0)),
                                name, value]))
    return "\n".join(lines) + "\n"


def _save_login_text(text: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if can_protect():
        tmp = LOGIN_DAT.with_suffix(".tmp")
        tmp.write_bytes(_DAT_MAGIC + _protect(text.encode("utf-8")))
        os.replace(tmp, LOGIN_DAT)
        COOKIE_FILE.unlink(missing_ok=True)                 # no readable copy left
    else:                                                   # encryption not available: as before (plain file)
        tmp = COOKIE_FILE.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, COOKIE_FILE)
        LOGIN_DAT.unlink(missing_ok=True)
    _LOGIN["text"] = text
    _LOGIN["ver"] += 1


def login_text() -> str | None:
    """The saved login as cookie text (decrypted in memory) – None if there is none / it can't be read here."""
    if _LOGIN["text"] is not None:
        return _LOGIN["text"]
    text = None
    if LOGIN_DAT.exists():
        try:
            raw = LOGIN_DAT.read_bytes()
            if raw.startswith(_DAT_MAGIC):
                text = _unprotect(raw[len(_DAT_MAGIC):]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - other PC / other Windows user -> not signed in
            text = None
    elif COOKIE_FILE.exists():                              # up to 2.9.2: plain file -> encrypted now
        try:
            text = COOKIE_FILE.read_text(encoding="utf-8", errors="replace")
            if can_protect():
                _save_login_text(text)
        except OSError:
            text = None
    _LOGIN["text"] = text
    return text


def write_cookie_file(cookies, path=None) -> int:
    """cookies: [(domain, path, secure, expires (epoch, 0 = session), name, value, http_only)] -> the app's login
    (encrypted), or a plain Netscape cookies.txt at `path`. -> number of YouTube cookies."""
    text = _netscape(cookies)
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        _save_login_text(text)
    return sum(1 for c in cookies if "youtube.com" in c[0] and c[4])


def _cookie_lines(path=None):
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
    else:
        text = login_text() or ""
    for line in text.splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and "youtube.com" in parts[0]:
            yield parts


def read_cookie_names(path=None) -> set:
    return {parts[5] for parts in _cookie_lines(path)}


def read_cookie_values(path=None) -> dict:
    return {parts[5]: parts[6].strip() for parts in _cookie_lines(path)}


def login_state() -> dict:
    """{'signed_in': bool, 'since': epoch or None}"""
    ok = bool(read_cookie_names() & LOGIN_COOKIES)
    since = None
    if ok:
        for f in (LOGIN_DAT, COOKIE_FILE):
            try:
                since = f.stat().st_mtime
                break
            except OSError:
                continue
    return {"signed_in": ok, "since": since}


def logged_in() -> bool:
    return bool(YDL_EXTRA.get("login"))


def apply_login() -> bool:
    """Use the saved YouTube login for every yt-dlp call (or nothing if there is none)."""
    for k in ("cookiefile", "cookiesfrombrowser", "login"):
        YDL_EXTRA.pop(k, None)
    if login_state()["signed_in"]:
        YDL_EXTRA["login"] = _LOGIN["ver"] or 1      # marker only; the cookies are handed in by add_login()
        return True
    return False


def add_login(ydl) -> None:
    """Hands the saved login to a yt-dlp instance – in memory, nothing is written to disk."""
    text = login_text() if logged_in() else None
    if not text:
        return
    import io
    from yt_dlp.cookies import YoutubeDLCookieJar
    jar = YoutubeDLCookieJar(io.StringIO(text))
    jar.load()
    for c in jar:
        ydl.cookiejar.set_cookie(c)


def import_cookie_file(src) -> int:
    """A cookies.txt exported from a browser (e.g. with "Get cookies.txt LOCALLY") -> the app's login."""
    names = read_cookie_names(src)
    if not names & LOGIN_COOKIES:
        raise RuntimeError("No YouTube login in this file – export the cookies while you are signed in on youtube.com.")
    _save_login_text(Path(src).read_text(encoding="utf-8", errors="replace"))
    return len(names)


def sign_out() -> None:
    for f in (LOGIN_DAT, COOKIE_FILE):
        f.unlink(missing_ok=True)
    _LOGIN["text"] = None
    _LOGIN["ver"] += 1
    for k in ("cookiefile", "login"):
        YDL_EXTRA.pop(k, None)
    clear_account()


# ---- which account is signed in (name + profile picture for the app)

ACCOUNT_FILE = APP_DIR / "account.json"
ACCOUNT_PIC = APP_DIR / "account.jpg"
_YT = "https://www.youtube.com"


def _sid_auth(cookies: dict, origin=_YT) -> str:
    """The Authorization header YouTube's own page sends for signed-in requests (SAPISIDHASH …)."""
    import hashlib
    ts = str(int(time.time()))
    out = []
    for scheme, names in (("SAPISIDHASH", ("SAPISID", "__Secure-3PAPISID")),
                          ("SAPISID1PHASH", ("__Secure-1PAPISID",)), ("SAPISID3PHASH", ("__Secure-3PAPISID",))):
        sid = next((cookies[n] for n in names if cookies.get(n)), None)
        if sid:
            out.append(f"{scheme} {ts}_{hashlib.sha1(f'{ts} {sid} {origin}'.encode()).hexdigest()}")
    return " ".join(out)


def _web_client_version() -> str:
    for mod in ("yt_dlp.extractor.youtube._base", "yt_dlp.extractor.youtube"):
        try:
            import importlib
            v = importlib.import_module(mod).INNERTUBE_CLIENTS["web"]["INNERTUBE_CONTEXT"]["client"]["clientVersion"]
            if v:
                return v
        except Exception:  # noqa: BLE001
            continue
    return "2.20251120.01.00"


def _yt_text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if "simpleText" in v:
            return str(v["simpleText"])
        if "runs" in v:
            return "".join(str(r.get("text", "")) for r in v["runs"] if isinstance(r, dict))
        if "content" in v:
            return str(v["content"])
    return ""


def _best_thumb(t) -> str:
    """{'thumbnails': [...]} or {'sources': [...]} -> address of the biggest picture (asked for at 176 px)."""
    t = t or {}
    th = [x for x in (t.get("thumbnails") or t.get("sources") or []) if isinstance(x, dict) and x.get("url")]
    if not th:
        return ""
    url = max(th, key=lambda x: x.get("width") or 0)["url"]
    url = "https:" + url if url.startswith("//") else url
    return re.sub(r"=s\d+-", "=s176-", url)          # sharper picture


def parse_accounts(data) -> dict:
    """YouTube's account menu / account switcher -> the active account {'name', 'handle', 'email', 'photo'}."""
    items, stack = [], [data]
    while stack:
        o = stack.pop(0)
        if isinstance(o, dict):
            if "accountName" in o and any(k in o for k in ("accountPhoto", "channelHandle", "email", "accountByline")):
                items.append(o)
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    if not items:
        return {}
    h = next((i for i in items if i.get("isSelected") is True), items[0])
    byline = _yt_text(h.get("accountByline")).strip()
    handle = _yt_text(h.get("channelHandle")).strip() or (byline if byline.startswith("@") else "")
    email = _yt_text(h.get("email")).strip() or (byline if "@" in byline[1:] and " " not in byline else "")
    return {"name": _yt_text(h.get("accountName")).strip(), "handle": handle, "email": email,
            "photo": _best_thumb(h.get("accountPhoto"))}


parse_account_menu = parse_accounts


def parse_home_avatar(html: str) -> str:
    """The round picture in the top right of youtube.com (only from the top bar, not the videos below)."""
    i = html.find('"topbarMenuButtonRenderer"')
    if i < 0:
        return ""
    seg = html[i:i + 6000]
    m = re.search(r'"avatar"\s*:\s*\{\s*"thumbnails"\s*:\s*(\[[^\]]*\])', seg)
    if m:
        try:
            return _best_thumb({"thumbnails": json.loads(m.group(1))})
        except ValueError:
            pass
    m = re.search(r'"(https://yt\d\.(?:ggpht|googleusercontent)\.com/[^"\\]+)"', seg)
    return re.sub(r"=s\d+-", "=s176-", m.group(1)) if m else ""


def ytdlp_versions(timeout=10.0) -> dict:
    """{'installed': on disk, 'loaded': running in the app, 'latest': on PyPI (None if not reachable)}"""
    import importlib.metadata
    try:
        installed = importlib.metadata.version("yt-dlp")
    except Exception:  # noqa: BLE001
        installed = None
    loaded = installed
    if "yt_dlp.version" in sys.modules:
        loaded = getattr(sys.modules["yt_dlp.version"], "__version__", installed)
    try:
        latest = json.loads(fetch_bytes("https://pypi.org/pypi/yt-dlp/json", timeout=timeout))["info"]["version"]
    except Exception:  # noqa: BLE001
        latest = None
    return {"installed": installed, "loaded": loaded, "latest": latest}


def _ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "?"


def _json_reply(raw: bytes):
    txt = raw.decode("utf-8", "replace")
    return json.loads(txt[txt.find("{"):]) if "{" in txt else {}       # some answers start with )]}'


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"


def _account_via_ytdlp(ydl, notes) -> dict:
    """Like yt-dlp's own signed-in requests: YouTube's start page (-> its settings + the picture in the top bar),
    then the account menu with exactly the headers yt-dlp sends."""
    info = {}
    ie = ydl.get_info_extractor("Youtube")
    ie.initialize()
    page = ie._download_webpage(_YT + "/", None, note=False, errnote=False, fatal=True,
                                headers={"Accept-Language": "en-US,en;q=0.8"})
    cfg = ie.extract_ytcfg(None, page) or {}
    if cfg and not cfg.get("LOGGED_IN"):
        notes.append("start page: YouTube does not see you as signed in")
    photo = parse_home_avatar(page)
    if photo:
        info["photo"] = photo
    try:
        data = ie._call_api("account/account_menu", {}, None, fatal=True, note=False,
                            headers=ie.generate_api_headers(ytcfg=cfg), context=ie._extract_context(cfg))
        got = parse_accounts(data)
        if got:
            info = {**got, "photo": got.get("photo") or info.get("photo", "")}
        else:
            notes.append("account menu: no account in the answer (" + ", ".join(list(data)[:5]) + ")")
    except Exception as ex:  # noqa: BLE001
        notes.append(f"account menu: {clean_error(ex)[:160]}")
    return info


def fetch_account(timeout=20.0) -> dict:
    """Asks YouTube with the saved login which account it is -> saved in account.json (+ the picture).
    Three ways, the first that knows the name wins; what didn't work is written to account_lookup.txt."""
    cookies = read_cookie_values()
    if not cookies:
        raise RuntimeError("Not signed in.")
    ydl = _net_ydl()
    if ydl is None:
        raise RuntimeError("yt-dlp is missing.")
    from yt_dlp.networking import Request
    notes, info = [], {}
    # 1) the way yt-dlp itself talks to YouTube when signed in
    try:
        info = _account_via_ytdlp(ydl, notes)
    except Exception as ex:  # noqa: BLE001
        notes.append(f"start page: {clean_error(ex)[:160]}")
    # 2) the account switcher (needs only the cookies)
    if not info.get("name"):
        try:
            with ydl.urlopen(Request(_YT + "/getAccountSwitcherEndpoint",
                                     headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.8",
                                              "Referer": _YT + "/"}, extensions={"timeout": timeout})) as r:
                got = parse_accounts(_json_reply(r.read()))
            if got.get("name"):
                info = {**got, "photo": got.get("photo") or info.get("photo", "")}
            else:
                notes.append("account switcher: no account in the answer")
        except Exception as ex:  # noqa: BLE001
            notes.append(f"account switcher: {clean_error(ex)[:160]}")
    # 3) the account menu, headers built here
    if not info.get("name"):
        ver = _web_client_version()
        headers = {"Content-Type": "application/json", "Origin": _YT, "X-Origin": _YT, "Referer": _YT + "/",
                   "X-Goog-AuthUser": "0", "X-Youtube-Client-Name": "1", "X-Youtube-Client-Version": ver,
                   "X-Youtube-Bootstrap-Logged-In": "true", "User-Agent": _UA}
        auth = _sid_auth(cookies, _YT)
        if auth:
            headers["Authorization"] = auth
        body = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": ver, "hl": "en"}}}).encode()
        try:
            with ydl.urlopen(Request(_YT + "/youtubei/v1/account/account_menu?prettyPrint=false", data=body,
                                     headers=headers, extensions={"timeout": timeout})) as r:
                got = parse_accounts(_json_reply(r.read()))
            if got.get("name") or got.get("photo"):
                info = {**info, **{k: v for k, v in got.items() if v}}
            else:
                notes.append("account menu (2): no account in the answer")
        except Exception as ex:  # noqa: BLE001
            notes.append(f"account menu (2): {clean_error(ex)[:160]}")
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        (APP_DIR / "account_lookup.txt").write_text(
            time.strftime("%Y-%m-%d %H:%M:%S") + f"  yt-dlp {_ytdlp_version()}\n"
            + (f"found: name={'yes' if info.get('name') else 'no'}, picture={'yes' if info.get('photo') else 'no'}\n")
            + "".join(f"- {n}\n" for n in notes), encoding="utf-8")
    except OSError:
        pass
    if not info.get("name") and not info.get("photo"):
        raise RuntimeError("; ".join(notes) or "YouTube didn't say which account this is.")
    pic = ""
    if info.get("photo"):
        try:
            data = fetch_bytes(info["photo"], timeout=timeout)
            if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF":
                APP_DIR.mkdir(parents=True, exist_ok=True)
                ACCOUNT_PIC.write_bytes(data)
                pic = str(ACCOUNT_PIC)
        except Exception:  # noqa: BLE001 - name without picture is fine
            pass
    out = {"name": info.get("name", ""), "handle": info.get("handle", ""), "email": info.get("email", ""),
           "picture": pic, "checked": time.time()}
    if not pic:
        ACCOUNT_PIC.unlink(missing_ok=True)
    tmp = ACCOUNT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ACCOUNT_FILE)
    return out


def load_account() -> dict:
    """The saved account (name, picture …) – {} if not signed in or not known yet."""
    if not login_state()["signed_in"]:
        return {}
    try:
        d = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
        if d.get("picture") and not Path(d["picture"]).is_file():
            d["picture"] = ""
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def clear_account() -> None:
    ACCOUNT_FILE.unlink(missing_ok=True)
    ACCOUNT_PIC.unlink(missing_ok=True)


# ---- sign-in with the default browser

_CHROMIUM = {"chrome": "Chrome", "msedge": "Edge", "brave": "Brave", "vivaldi": "Vivaldi", "opera": "Opera",
             "launcher": "Opera", "chromium": "Chromium", "google-chrome": "Chrome", "google-chrome-stable": "Chrome",
             "microsoft-edge": "Edge", "brave-browser": "Brave", "thorium": "Thorium", "yandex": "Yandex"}
_FIREFOX = {"firefox": "Firefox", "librewolf": "LibreWolf", "waterfox": "Waterfox", "floorp": "Floorp",
            "zen": "Zen"}


def _browser_from_exe(exe) -> dict | None:
    stem = Path(exe).stem.lower()
    if stem in _CHROMIUM:
        return {"name": _CHROMIUM[stem], "kind": "chromium", "exe": str(exe)}
    if stem in _FIREFOX:
        return {"name": _FIREFOX[stem], "kind": "firefox", "exe": str(exe)}
    return None


def default_browser() -> dict | None:
    """The browser Windows opens links with -> {'name', 'kind': 'chromium' | 'firefox', 'exe'} or None."""
    over = os.environ.get("YTD_BROWSER")
    if over:
        return _browser_from_exe(over)
    if WIN:
        import shlex
        import winreg
        for proto in ("https", "http"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\Shell\Associations"
                                                               rf"\UrlAssociations\{proto}\UserChoice") as k:
                    progid = winreg.QueryValueEx(k, "ProgId")[0]
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command") as k:
                    cmd = winreg.QueryValueEx(k, "")[0]
            except OSError:
                continue
            exe = cmd.split('"')[1] if cmd.startswith('"') else shlex.split(cmd, posix=False)[0]
            b = _browser_from_exe(exe)
            if b and Path(b["exe"]).exists():
                return b
        return None
    try:   # Linux / macOS (for testing)
        desk = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True,
                              timeout=5).stdout.strip().replace(".desktop", "")
    except (OSError, subprocess.SubprocessError):
        desk = ""
    for name in ([desk] if desk else []) + ["google-chrome", "chromium", "microsoft-edge", "brave-browser", "firefox"]:
        exe = shutil.which(name)
        if exe:
            return _browser_from_exe(exe) or _browser_from_exe(name) and {**_browser_from_exe(name), "exe": exe}
    return None


def _has_login(rows) -> bool:
    names = {r[4] for r in rows if "youtube.com" in r[0]}
    return "LOGIN_INFO" in names and bool(names & {"SAPISID", "__Secure-3PAPISID", "SID", "__Secure-1PSID"})


def chromium_browsers() -> list:
    """Installed Chrome-like browsers (the sign-in extension runs in these) -> [{'name', 'kind', 'exe'}]."""
    out, seen = [], set()

    def add(b):
        if b and b["kind"] == "chromium" and Path(b["exe"]).exists() and b["exe"].lower() not in seen:
            seen.add(b["exe"].lower())
            out.append(b)
    add(default_browser())
    if WIN:
        import winreg
        for exe in ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe"):
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        add(_browser_from_exe(winreg.QueryValueEx(k, "")[0]))
                except OSError:
                    continue
    else:
        for name in ("google-chrome", "chromium", "microsoft-edge", "brave-browser"):
            exe = shutil.which(name)
            if exe:
                b = _browser_from_exe(name)
                add(b and {**b, "exe": exe})
    return out


def open_in_browser(b, url, profile=None) -> bool:
    """Opens url as a new tab in the browser that is already running (or starts it) – in the given profile, so
    Chrome's "Who's using Chrome?" picker doesn't come in between. url None: a new window (new tab page).
    Note: Chrome ignores chrome:// addresses given this way (security)."""
    try:
        cmd = [b["exe"], *([f"--profile-directory={profile}"] if profile else []), *([url] if url else [])]
        subprocess.Popen(cmd, creationflags=NO_WINDOW, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, KeyError, TypeError):
        return False


_USER_DATA_WIN = {"Chrome": r"Google\Chrome\User Data", "Edge": r"Microsoft\Edge\User Data",
                  "Brave": r"BraveSoftware\Brave-Browser\User Data", "Vivaldi": r"Vivaldi\User Data",
                  "Chromium": r"Chromium\User Data", "Thorium": r"Thorium\User Data"}
_USER_DATA_NIX = {"Chrome": ".config/google-chrome", "Chromium": ".config/chromium", "Edge": ".config/microsoft-edge",
                  "Brave": ".config/BraveSoftware/Brave-Browser"}


def browser_user_data(b):
    """The folder with the browser's profiles ("User Data") or None."""
    over = os.environ.get("YTD_BROWSER_USER_DATA")
    if over:
        return Path(over)
    if not b:
        return None
    if WIN:
        rel = _USER_DATA_WIN.get(b["name"])
        p = Path(os.environ.get("LOCALAPPDATA", "")) / rel if rel else None
    else:
        rel = _USER_DATA_NIX.get(b["name"])
        p = Path.home() / rel if rel else None
    return p if p and (p / "Local State").exists() else None


def _has_ext(profile_dir: Path) -> bool:
    for fn in ("Secure Preferences", "Preferences"):
        try:
            d = json.loads((profile_dir / fn).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if EXT_ID in (((d.get("extensions") or {}).get("settings")) or {}):
            return True
    return False


def browser_profiles(b) -> list:
    """The browser's profiles in its own order -> [{'dir', 'name', 'who', 'ext': extension added, 'last'}]."""
    ud = browser_user_data(b)
    if not ud:
        return []
    try:
        prof = json.loads((ud / "Local State").read_text(encoding="utf-8", errors="replace")).get("profile") or {}
    except (OSError, ValueError):
        return []
    cache = prof.get("info_cache") or {}
    order = [d for d in (prof.get("profiles_order") or []) if d in cache]
    order += [d for d in cache if d not in order]
    last = prof.get("last_used") or (order[0] if order else "")
    out = []
    for d in order:
        v = cache.get(d) or {}
        out.append({"dir": d, "name": v.get("name") or d, "who": v.get("gaia_name") or v.get("user_name") or "",
                    "ext": _has_ext(ud / d), "last": d == last})
    return out


# ---- the sign-in extension: a small helper in your own Chrome hands the YouTube login to this app

EXT_DIR = APP_DIR / "chrome-extension"
EXT_ID = "mdhangbfgllnapcnookjceagljebgnmb"            # fixed by the key in the manifest
EXT_ORIGIN = f"chrome-extension://{EXT_ID}"
BRIDGE_PORTS = (47815, 47816, 47817)
EXT_FILES = {
    "manifest.json": json.dumps({
        "manifest_version": 3,
        "name": "YouTube Downloader – Login",
        "version": "1.1",
        "description": "Hands your YouTube login to the YouTube Downloader app on this PC – only when the app asks for "
                       "it, only to this PC (127.0.0.1), nowhere else.",
        "key": "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5ohi/zflHEKTNyvDtx+8B2tqrNr8f90JSz+9+6+H0sn2FGedFlrpwQUQdQoNDILkByHmB7DMP+dSQvxw0/yWfnXVSJ4u7hGnBqJP60AKITFHdFpdQwssM6o/ZZSJGIrfNGs2/VgfhxY2gWrzyp8ZkAa6VLQM37p67MwN9i9k3HYp5upfIeqTVAINGvvkcyKZgfNJc2O1in9z1H3swrsgle6Gq0y9Gqp7cStyAp3VEhWn3T1zvO4T3jaY9dYGUXKlMkUvKbHdtgQqW1h4Rk5j9Dnbe+9iedEzWl437Q3i2dv+bIhOXK+T4IfSPMkyM7ESK8fRFjWFNvTbvpHHGz7PcwIDAQAB",
        "permissions": ["cookies", "alarms"],
        "host_permissions": ["https://*.youtube.com/*", "http://127.0.0.1/*"],
        "background": {"service_worker": "background.js"},
        "icons": {"16": "icon.png", "48": "icon.png", "128": "icon.png"},
    }, indent=2),
    "background.js": """// YouTube Downloader – Login helper.
// Asks the YouTube Downloader app on this PC (127.0.0.1) whether it wants the YouTube login. Only if it does
// (after "Sign in" in the app) AND proves it is the real app (it knows the key in pair.json, written by the
// app when it set up this extension), the youtube.com cookies go to it – to nothing else, nowhere else.
const PORTS = [%PORTS%];
let debounce = null;
const enc = new TextEncoder();
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");

async function pairKey() {
  const r = await fetch(chrome.runtime.getURL("pair.json"), {cache: "no-store"});
  const k = (await r.json()).key || "";
  const bytes = new Uint8Array(k.match(/../g).map(h => parseInt(h, 16)));
  return crypto.subtle.importKey("raw", bytes, {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
}

async function mac(key, msg) {
  return hex(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}

async function sync(reason) {
  let key;
  try { key = await pairKey(); } catch (e) { return; }
  for (const port of PORTS) {
    const n = hex(crypto.getRandomValues(new Uint8Array(16)));
    let st = null;
    try {
      const r = await fetch(`http://127.0.0.1:${port}/ytd/state?n=${n}`, {cache: "no-store", headers: {"X-Ytd": "2"}});
      if (!r.ok) continue;
      st = await r.json();
    } catch (e) { continue; }
    if (!st || st.app !== "ytd") continue;
    // is it really the app? (another program on this port can't know the key)
    if (st.proof !== await mac(key, `state|${n}|${st.want ? 1 : 0}`)) continue;
    if (!st.want) return;
    const all = await chrome.cookies.getAll({domain: "youtube.com"});
    const cookies = all.map(c => ({domain: c.domain, path: c.path, secure: c.secure, httpOnly: c.httpOnly,
                                   session: c.session, expires: c.expirationDate || 0, name: c.name, value: c.value}));
    const body = JSON.stringify({reason, ts: Date.now(), n, cookies});
    try {
      await fetch(`http://127.0.0.1:${port}/ytd/cookies`, {method: "POST", cache: "no-store",
        headers: {"Content-Type": "application/json", "X-Ytd": "2", "X-Ytd-Mac": await mac(key, "cookies|" + body)},
        body});
    } catch (e) {}
    return;
  }
}

function every30s() {
  chrome.alarms.get("ytd-sync", a => { if (!a) chrome.alarms.create("ytd-sync", {periodInMinutes: 0.5}); });
}

chrome.cookies.onChanged.addListener(info => {
  if (!(info.cookie.domain || "").endsWith("youtube.com")) return;
  clearTimeout(debounce);
  debounce = setTimeout(() => sync("change"), 1500);
});
chrome.alarms.onAlarm.addListener(a => { if (a.name === "ytd-sync") sync("tick"); });
chrome.runtime.onInstalled.addListener(() => { every30s(); sync("installed"); });
chrome.runtime.onStartup.addListener(() => { every30s(); sync("startup"); });
every30s();
""".replace("%PORTS%", ", ".join(str(x) for x in BRIDGE_PORTS)),
}
EXT_ICON = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAALnUlEQVR42u2dz28cRRbHP9Uz/hHHJN7EsZdkNzIsBEh2c/BKOaAIRSwnI06sFIQiZY9cUZJL/gi4GAmEOCDlkJX2RgSSpZUQilBksbGUSEGAViBnMSRrZ2Nwgu3xdO2hqpiadndPezzj6e68r1Tqdnump7q+33pV9ar6FQgEAoFAIBAIBAKBQCAQCAQCgUAgEAgEAoFAICgbVJ4yo+PzozLmWe18djNd1zEZ1aUWgCUyaHF/7RWOzlOh7KDYlcdDq7IKu1FGqoMPVLH3q7ebUQ1VoI/Gsd9LfZHzPu+a+46fKl4KvKQiyRejS6GX6l7aiKQasG6PNe/v9ci5+3sDqClzbFc0FVth6j0XgKvp0cxoGAcmgMPAGDAMDNrjY8Buez4E7PLSoCV0IEKyI7RIqHsicWnNimEV+MVLD4EV4AHwsz1ftce7wDzwnYI7MZVuW5ZBbafG+8RreB54BTgFPAfs7XLbq7O2uV22mirh2GksA18CnwIfKfg8iYuuCsCv9drUzjPAG8CJuHYrhZC0zp3Ke4e1zU6i3kpn0XvuuP7ULPAucElBrRPWIMsTBd75lIY5DdqmUJuMbNhzLamjKbRlW4uU75yGqTiOukK+hgEN014GNrSxBkLSzqa6LXv397Q2factiUBlJV8Z1Y0D/wBO2k6OM0+C3sE1sxXgKvBXBXccZ9sWgEf+b4F/Akdtj7ZPyj5XcJzcAv6i4McsIlAZnRW7gM+ASSG/ECK4Drxgh5ipTrZW5tsp6AMhvxDosxxNAh9Y7lI5DlqN8zX8DTgt5BdOBKc1nLUcVrbUBHiTMvut82FfRoshyE/HEOCedcotJU1CBSmmXwPngVEymBJBrhBYzkaB85bLIJMF0KCUGVeOAt/QcOkqKddCeiKXgacVLDpuW1kA116cBka88b6Awq31qFsOT0e4TRWAaz9esyoS8ostAm259LmNbwI8p8/vga8x07MigmI3AwoztXxEwe2oc6ia0Hk4YcmvF3AePqVrFJhWMLXINIRh2ZqBQcvpbY/j1FHAn3dobn2HB0ch1OvpqTzkRzuDk3H/rCZ8+Ei5WkI7rjl0CI4fT//sjRvw/feN75QHz8RV6mpCB/BgaYZ+zuQPDMDMDBw9mv75W7dgchLW18siAhXhNEwUgDdGHCnV2F9r2LULDh40Zj4NBw+az66tte4vFEsAI3HewGqMA6iCWZhZspZQQ60GlYo5j5LrrtVqZTP9Dv3e/M6vDqG4TuAQZsVu+bx/WWq0UmV9+cetwk50BLkP/sZrAgTlwYjltqlixwlg1K7LFwdQubyBA5bbRAHgCaB8PgBkYsjjNrUJOJDkNxZQ9PUBB7JYgDEpr9JiLMts4KiUU2mxP4sA9kk5PZoC0CKA0mNftIMfZwFkCVh5I8HsTbMArqe4R8qrtNgTHeEFMRNBj4kFoMzu4KYJocB/D8BOBO2S8iothtxLIo7zaB9gALN8SFBODFqOE4eB/Z4ApAkoXxMwGJ3qD2LeK5P3/yj1e4N9cQJQXhMgAii3APp9zqsxH6gW6pEqlfRFHG6dU3ULj1WtmtRqTaDWrZeY5QvVaBNQjXktrFjvAWQlYGkp21Ivrc1ny4lN/FZjFBIUaqn3mTONlb5BStYHBmB4uPV9h4fh7bfNolBS3i8As4L40qUirR4OYi28FwHsWGGiZAWBOV67pnuGa9ea81KMdMznPNhiyBhytco3CGBqCj75xFxbXTWrejc24lNWJH2/VjO/AfDxx+a3g6Boq4hVmgU4XqhYeUqZY6Wi9fvvm1q5saF1GHa+toehubfW5rcqleY8FCcd3xRLsLACcObXkXDxYoOwer1z5Pv3unixQXyxTH8mAfypkFEzlWrUyNdf13p1tWENtgt3j9VVc29ncYpX8136Y5oAjhU6fGq1ao4nT2q9sGCIq9XaJ999d2HB3NP/jeKmY2kCeDYSnLi4InjySa3n5toXgfvO3Jy5V7HJ97l8Nk0AT3mBn4sb8ds1B3v2aH3lSoPQLJ3DMGyQf+WKuYd/z2ILoK7hqTQBPKFhvfAC8MfmSmk9Pd3ozKWJIAwbHb7p6UY7X8zOXpwA1jU8kSaA32l4WAoBOOIceefOpY8Q/Gvnzm3+fjkE8FDDoTgBuBVBBzQsl0YAzgK4tvvVV7VeWdk8QnDnKyvmM669L25PP0kAy9q+HdS0RZ8ngBFtAgr2XgBunO2n7RDiRHDihNbz841+gWvv5+fN/7bb2et0vjsrgEVt3/xOEsCQhv94HYZy7bLhiD18WOvZ2YYFmJ0118oxzEvaXURbbod8zlVMdJCvgD/0LD6wy8n+/Sa5mbcggLt34f797c2+VSpmCnn3bvjwQ3Pt7Fl48KDxv+3ke2QExsaa8720ZFLvZg0dl/8GnolGCYnOC9zsmQVQqpFmZ02vfH3dpHpd65mZzvTK477fqXvOzJi8unyHoXkW/9l6ZwFuJIaJ8xTxc0/jA2htauKBAyZHbiWPUqZmuc9sN16gUo2VRJ0IDunyNDbWHJBSKfMsQWCsS29C0LgCW4lw3bQ4ILBRJX/KxaSlC9bkm9JarbNC64Y57na+t4efIlzHrv9bzkWEEFdD/ZrUm9pThnzrCLepEULuyeLZ0uJelgghIoDyYilLgIhFKadHWwB3pZxKi7tp0cJdR+G/uV0g6oaFeVyG7fKUz45qEOFWJ70X4DcB+XsSt+I3z8jPkC9uJfBiFguwCKyRp2ihrlZNTMBbb+XbAkxMNP9NbraNWfMEoNME8D/gPman8HwFeR4fhzffpFBvLuUH9y23LZuAhxiX4fiOWwBXYGHY2N7Fv16ElzH9l1Vdft3zdMKN3b4FWLHcxjcBzjdsZ4rWe1qA9TrcvAlHjjR3rJRKf/8vr5tU3bzZmOPonYDXlXX/qiQL4E0S3O+ZO9gRfuECjI6a7VsGBooVy9/V8rU1uH7dPEvvmgTtNQFEp4Hjto2rAws9E4Azld9+C6dOweOPw+BgnodYySJeXYUfftgsjN4IYCE6ERQnAFfCX+em4+cXIAXepaT3HcKv4ob3SWEz/tVzX4ArsKLMAu7klHN7PoDrZNg30K2KmMVsN9r7rWPzUYgUeKOIiuVyNm4fiCAildDuLXsb+MLeQDaOoNAbRWjgi7h9g5P8/e7aZW+/GUGxN4++nMS3ivmGG7CMAt8g0cOLvk/QMvC0Mu8EbFoJHKcIbTcYXATe83agFhQLdcvde5b8StwycJUgHeXtMPEljY0GAinXQm0SdQ94DrsQJE4AQcK4QWM6DIvAhajzQFCI2h8A5y2HgUroy6kWjYjba/YycBqoIaFk8w7H0d8VvOY4zB4ybHNToDB7CHwGTIoICkH+deAF4BdAq5SRXNDCheRmCB8ALwO37A/UpKxzS/4t4GXLGarFMD7I4Ed0zqEfgReBq/aH6uIkyk2Hr245uQq8qODHOKdPWwKIiOAO8BLwDsbFGIgQek58YLl4B3hJwZ2s5LfjWQi88ykNc5EgBDUNG6WJLpK/KB8btoz98p3TMBXHUXtxY1uLQNlhRV0bs3MGeAM4EeOJClNcySrlb9WJvJIPT1zSNZ3h8+65g5jnnwXeBS4pI4oKEKotuu7VNp6uaXih4XngFeCUdT7s7XLB6i0WJF0KtqwSjp3GMsYp9ynwkYLPk7jYEQFErUHk+jgwARzG7Fg9jJlaHsbsS7jbng/ZIaZLblOjAW9/G7eLSYXiOWM2bO/cpTXMestVO0RzyS3EfYCJz7BiP7OCeZtnHvjO9sGaKmE7tb4rZtVmRgH1djNk79FvCXf72/RHzvsj4ujzvuOnitdRdUdnSv3krIafQq+T5Y6OUD+tRwiu2Wvr3v/88w28xZltVriKHdvXuxM7vjNiSGq3oqb6VzOuHrFpZ90sQJWhrMJulJHKYaFspbPYy2fRGa/rJAebQCAQCAQCgUAgEAgEAoFAIBAIBAKBQCAQCAQCQTfwf/Ghian5CPOHAAAAAElFTkSuQmCC")


BRIDGE_KEY_FILE = APP_DIR / "bridge.key"


def bridge_key() -> bytes:
    """The key the app and its extension share (made once per PC) – proves to the extension that it talks to
    this app and not to another program on the same port."""
    try:
        k = bytes.fromhex(BRIDGE_KEY_FILE.read_text(encoding="ascii").strip())
        if len(k) == 32:
            return k
    except (OSError, ValueError):
        pass
    import secrets
    k = secrets.token_bytes(32)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    BRIDGE_KEY_FILE.write_text(k.hex(), encoding="ascii")
    return k


def bridge_mac(msg: str) -> str:
    import hashlib
    import hmac
    return hmac.new(bridge_key(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def write_extension() -> Path:
    """Puts the extension's files into EXT_DIR (only what changed – Chrome loads it from there)."""
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    files = list(EXT_FILES.items()) + [("icon.png", EXT_ICON), ("pair.json", json.dumps({"key": bridge_key().hex()}))]
    for name, data in files:
        f = EXT_DIR / name
        raw = data.encode("utf-8") if isinstance(data, str) else data
        try:
            if f.read_bytes() == raw:
                continue
        except OSError:
            pass
        f.write_bytes(raw)
    return EXT_DIR


def extensions_page(b) -> str:
    return {"Edge": "edge://extensions/", "Brave": "brave://extensions/", "Opera": "opera://extensions",
            "Vivaldi": "vivaldi://extensions/"}.get((b or {}).get("name"), "chrome://extensions/")


def cookie_rows(cookies) -> list:
    """The extension's cookie list -> rows for write_cookie_file (YouTube only)."""
    rows = []
    for c in cookies if isinstance(cookies, list) else []:
        if not isinstance(c, dict) or "youtube.com" not in str(c.get("domain", "")) or not c.get("name"):
            continue
        exp = 0 if c.get("session") else int(float(c.get("expires") or 0))
        rows.append((str(c["domain"]), str(c.get("path") or "/"), bool(c.get("secure")), exp, str(c["name"]),
                     str(c.get("value", "")), bool(c.get("httpOnly"))))
    return rows


class LoginBridge:
    """Tiny local server (127.0.0.1 only) the Chrome extension talks to: 'do you want the login?' and the
    cookies. Accepts cookies only from the extension and only while want() is true."""
    def __init__(self, want, on_event):
        self.want, self.on_event = want, on_event
        self.seen = 0.0                 # last time the extension asked
        self.old_ext = 0.0              # last time an extension of 2.9.2 (without the key) asked
        self.port = None
        self.httpd = None
        self.lock = threading.Lock()

    def start(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        bridge = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _ours(self, ver="2"):
                # only straight to 127.0.0.1 (no web page pretending to be this PC), with the extension's own
                # header (web pages can't send it without asking first) and, if any, its own origin
                host = (self.headers.get("Host") or "").lower()
                origin = self.headers.get("Origin")
                return (host in (f"127.0.0.1:{bridge.port}", f"localhost:{bridge.port}")
                        and self.headers.get("X-Ytd") == ver and origin in (None, "", EXT_ORIGIN))

            def do_GET(self):
                from urllib.parse import parse_qs, urlsplit
                u = urlsplit(self.path)
                if u.path != "/ytd/state":
                    return self._reply(404, {})
                if self._ours("1"):                 # the extension of 2.9.2: has to be reloaded in Chrome
                    bridge.old_ext = time.time()
                    return self._reply(200, {"app": "ytd", "want": False})
                nonce = (parse_qs(u.query).get("n") or [""])[0]
                if not self._ours() or not re.fullmatch(r"[0-9a-f]{16,64}", nonce):
                    return self._reply(404, {})
                bridge.seen = time.time()
                want = bool(bridge.want())
                self._reply(200, {"app": "ytd", "want": want, "proof": bridge_mac(f"state|{nonce}|{int(want)}")})

            def do_POST(self):
                import hmac
                if self.path.split("?")[0] != "/ytd/cookies" or not self._ours():
                    return self._reply(403, {})
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > 512 * 1024:
                    return self._reply(413, {})
                raw = self.rfile.read(n).decode("utf-8", "replace")
                if not hmac.compare_digest(self.headers.get("X-Ytd-Mac") or "", bridge_mac("cookies|" + raw)):
                    return self._reply(403, {})     # not from the extension with this PC's key
                try:
                    data = json.loads(raw)
                except ValueError:
                    return self._reply(400, {})
                if abs(time.time() * 1000 - float(data.get("ts") or 0)) > 10 * 60 * 1000:
                    return self._reply(403, {})     # an old message played again
                bridge.seen = time.time()
                self._reply(200, bridge.take(data.get("cookies")))

        for port in BRIDGE_PORTS:
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
                self.port = port
                break
            except OSError:
                continue
        if self.httpd is not None:
            self.httpd.daemon_threads = True
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def take(self, cookies) -> dict:
        if not self.want():
            return {"ok": False, "why": "not wanted"}
        rows = cookie_rows(cookies)
        if not _has_login(rows):
            self.on_event(("no_login", None))
            return {"ok": False, "why": "not signed in to YouTube in this browser"}
        with self.lock:
            old = read_cookie_values()
            new = {r[4]: r[5] for r in rows}
            if new == old:
                self.on_event(("same", None))
                return {"ok": True, "changed": False}
            write_cookie_file(rows)
            apply_login()
            who = lambda v: (v.get("LOGIN_INFO"), v.get("SID") or v.get("__Secure-3PSID"))
            self.on_event(("login", who(old) != who(new)))      # True: other account (or first time)
        return {"ok": True, "changed": True}

    def close(self):
        h, self.httpd = self.httpd, None
        if h is not None:
            def stop():
                h.shutdown()
                h.server_close()
            threading.Thread(target=stop, daemon=True).start()


# ---- sign-in without the extension: an own browser window

def _free_port() -> int:
    import socket
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


class BrowserSignIn:
    """Opens the default browser with its own profile (your normal browser stays untouched) on the YouTube
    sign-in page. As soon as YouTube shows you as signed in, the login is saved for yt-dlp and the window closes.
    Chrome, Edge, Brave, Opera, Vivaldi: read through the browser's local debug connection (only while the
    window is open). Firefox: read from its profile."""

    def __init__(self, browser):
        self.b = browser
        self.proc = None
        self.port = None
        self.profile = SIGNIN_DIR / ("firefox" if browser["kind"] == "firefox" else "chromium")
        self.seen = False          # the browser answered at least once
        self.t0 = 0.0

    def start(self):
        self.profile.mkdir(parents=True, exist_ok=True)
        if self.b["kind"] == "firefox":
            cmd = [self.b["exe"], "-profile", str(self.profile), "-no-remote", "-new-instance", LOGIN_URL]
        else:
            self.port = _free_port()
            cmd = [self.b["exe"], f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}",
                   "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                   "--new-window", *os.environ.get("YTD_BROWSER_ARGS", "").split(), LOGIN_URL]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.t0 = time.time()

    # chromium: DevTools protocol over a local websocket
    def _cdp(self, method, params=None, timeout=8.0):
        from websockets.sync.client import connect
        info = json.loads(fetch_bytes(f"http://127.0.0.1:{self.port}/json/version", timeout=3).decode("utf-8"))
        with connect(info["webSocketDebuggerUrl"], open_timeout=timeout, max_size=None,
                     additional_headers=None) as ws:
            ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            end = time.time() + timeout
            while time.time() < end:
                msg = json.loads(ws.recv(timeout=max(0.5, end - time.time())))
                if msg.get("id") == 1:
                    if "error" in msg:
                        raise RuntimeError(msg["error"].get("message", "DevTools error"))
                    return msg.get("result") or {}
        raise TimeoutError(method)

    def _chromium_rows(self):
        res = self._cdp("Storage.getCookies")
        return [(c.get("domain", ""), c.get("path", "/"), bool(c.get("secure")),
                 0 if c.get("session") or (c.get("expires") or -1) < 0 else int(c["expires"]),
                 c.get("name", ""), c.get("value", ""), bool(c.get("httpOnly"))) for c in res.get("cookies", [])]

    def _firefox_rows(self):
        import sqlite3
        import tempfile
        db = self.profile / "cookies.sqlite"
        if not db.exists():
            return []
        with tempfile.TemporaryDirectory(prefix="ytd_ff_") as td:
            for suf in ("", "-wal", "-shm"):
                f = Path(str(db) + suf)
                if f.exists():
                    try:
                        shutil.copyfile(f, Path(td) / ("cookies.sqlite" + suf))
                    except OSError:
                        pass
            con = sqlite3.connect(str(Path(td) / "cookies.sqlite"))
            try:
                rows = con.execute("SELECT host, path, isSecure, expiry, name, value, isHttpOnly FROM moz_cookies "
                                   "WHERE host LIKE '%youtube.com'").fetchall()
            finally:
                con.close()
        return [(h, p, bool(sec), int(exp // 1000 if exp > 10 ** 11 else exp), n, v, bool(ho))
                for h, p, sec, exp, n, v, ho in rows]

    def poll(self) -> str:
        """-> 'waiting' | 'done' | 'closed'"""
        running = self.proc is not None and self.proc.poll() is None
        try:
            rows = self._firefox_rows() if self.b["kind"] == "firefox" else self._chromium_rows()
            self.seen = True
            self.misses = 0
        except Exception:  # noqa: BLE001 - not reachable (yet / any more)
            rows = None
            self.misses = getattr(self, "misses", 0) + 1
        if rows and _has_login(rows):
            write_cookie_file(rows)
            self.close()
            return "done"
        if self.b["kind"] == "firefox":
            return "waiting" if running else "closed"
        if rows is None and ((self.seen and self.misses >= 3) or (not self.seen and time.time() - self.t0 > 45)):
            return "closed"      # window closed (or the browser never opened)
        return "waiting"

    def close(self):
        if self.b["kind"] != "firefox" and self.port:
            try:
                self._cdp("Browser.close", timeout=3)
            except Exception:  # noqa: BLE001
                pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def login_hint(msg) -> str:
    """Extra hint when YouTube wants a login (age-restricted or members-only videos) or the login expired."""
    if not re.search(r"log ?in|sign in|cookies|members[- ]only|age[- ]restricted|confirm your age|inappropriate",
                     msg or "", re.I):
        return ""
    if logged_in():
        return "\nTip: your YouTube login may have expired – Settings → YouTube login → Sign in again."
    return "\nTip: this video needs a YouTube login – Settings → YouTube login → Sign in."


# ----------------------------------------------------------------------------- repair

def _sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def repair_app_file(script, emit):
    """The app file against the repo: newer there or damaged here -> loaded again. -> (state, text, restart)"""
    try:
        info = check_app_update()
    except Exception as ex:  # noqa: BLE001
        return "warn", f"GitHub not reachable – not checked ({clean_error(ex)[:80]})", False
    same = _ver(info.get("version")) == _ver(APP_VERSION)
    try:
        intact = bool(info.get("sha256")) and _sha256_file(script) == info["sha256"]
    except OSError:
        intact = False
    if same and intact:
        return "ok", f"version {APP_VERSION} is complete", False
    if not info.get("newer") and not same:
        return "ok", f"version {APP_VERSION} (newer than the one on GitHub)", False
    install_app_update(info, script, emit)
    if info.get("newer"):
        return "fixed", f"updated to {info.get('version')} – restart the app", True
    return "fixed", "the app file was damaged or changed – loaded again from GitHub, restart the app", True


def repair_tools(ffmpeg, ffprobe):
    bad = []
    for name, exe in (("FFmpeg", ffmpeg), ("FFprobe", ffprobe)):
        try:
            r = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True, timeout=20,
                               creationflags=NO_WINDOW) if exe else None
            if r is None or r.returncode != 0:
                bad.append(name)
        except (OSError, subprocess.SubprocessError):
            bad.append(name)
    if bad:
        return "error", (" and ".join(bad) + " missing or broken – start the setup (YouTube-Downloader.exe) again, "
                         "it repairs the installation"), False
    return "ok", "FFmpeg and FFprobe work", False


def repair_extension():
    """Puts the extension's files back (same key – the pairing stays)."""
    before = {}
    for f in EXT_DIR.glob("*") if EXT_DIR.exists() else []:
        try:
            before[f.name] = f.read_bytes()
        except OSError:
            pass
    write_extension()
    changed = [f.name for f in EXT_DIR.glob("*") if before.get(f.name) != f.read_bytes()]
    if changed:
        return "fixed", ("files restored (" + ", ".join(changed) + ") – if you added it in Chrome: click ↻ at "
                         "“YouTube Downloader – Login” on the extensions page"), False
    return "ok", "files complete", False


def repair_login():
    _LOGIN["text"] = None
    if LOGIN_DAT.exists() and login_text() is None:
        sign_out()
        return "fixed", "the saved login couldn't be read (other PC / Windows user?) – removed, please sign in again", False
    if COOKIE_FILE.exists() and can_protect():
        login_text()                                   # turns the plain file into the encrypted one
        return "fixed", "the login is stored encrypted now", False
    apply_login()
    return "ok", "signed in" if login_state()["signed_in"] else "not signed in (nothing to check)", False


def repair_settings():
    try:
        raw = CFG_FILE.read_text(encoding="utf-8")
        json.loads(raw) if raw.strip() else {}
        return "ok", "settings file is fine", False
    except FileNotFoundError:
        return "ok", "no settings file yet", False
    except (OSError, ValueError):
        try:
            os.replace(CFG_FILE, CFG_FILE.with_name("config.broken.json"))
        except OSError:
            pass
        return "fixed", "the settings file was damaged – set aside (config.broken.json), saved again", False


def repair_leftovers(signing_in=False):
    n = 0
    for pat in ("*.tmp", "*.new"):
        for f in APP_DIR.glob(pat):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    if not signing_in and SIGNIN_DIR.exists():
        shutil.rmtree(SIGNIN_DIR, ignore_errors=True)
        n += 1
    return ("fixed", f"{n} leftover file{'s' if n != 1 else ''} removed", False) if n else \
        ("ok", "nothing left over", False)


# ----------------------------------------------------------------------------- fonts for burned-in subtitles

def system_font_files(family) -> list:
    """Font files of an installed font family (Windows registry: for all users and per user)."""
    if not WIN or not family:
        return []
    import winreg
    out, fam = [], family.lower()
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                n = name.lower()
                if n == fam or n.startswith(fam + " ") or n.startswith(fam + " (") or n.startswith(fam + " & "):
                    f = Path(val) if os.path.isabs(val) else windir / val
                    if f.is_file():
                        out.append(f)
    return out


def collect_fonts(style, dst_dir) -> int:
    """Copies the subtitle font (own file, or the installed family) next to the .ass so libass finds it."""
    files = []
    ff = (style or {}).get("font_file")
    if ff and Path(ff).is_file():
        files.append(Path(ff))
    files += system_font_files((style or {}).get("font"))
    if not files:
        return 0
    Path(dst_dir).mkdir(parents=True, exist_ok=True)
    for f in files[:12]:
        try:
            shutil.copyfile(f, Path(dst_dir) / f.name)
        except OSError:
            pass
    return len(files)


def install_font(path) -> Path:
    """Keeps a copy of a font file in the app folder (loaded again at every start)."""
    src = Path(path)
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = FONTS_DIR / src.name
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    return dst


# ----------------------------------------------------------------------------- app update from GitHub

def _ver(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0"))[:4])


def _latest_base(timeout=8.0) -> str:
    """Raw address of the newest commit. 'main' itself comes through GitHub's cache, which can show the old
    version for ~5 minutes after an update – the commit's own address is always right."""
    if UPDATE_BASE != f"https://raw.githubusercontent.com/{UPDATE_REPO}/main/":
        return UPDATE_BASE
    try:
        sha = fetch_bytes(f"https://api.github.com/repos/{UPDATE_REPO}/commits/main", timeout=timeout,
                          headers={"Accept": "application/vnd.github.sha"}).decode("ascii", "replace").strip()
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return f"https://raw.githubusercontent.com/{UPDATE_REPO}/{sha}/"
    except Exception:  # noqa: BLE001 - GitHub API limit / offline -> the normal address
        pass
    return UPDATE_BASE


def check_app_update(timeout=15.0) -> dict:
    """version.json of the repo -> {'version', 'newer': bool, 'notes', 'base', …}"""
    base = _latest_base()
    data = fetch_bytes(base + f"version.json?t={int(time.time())}", timeout=timeout)
    info = json.loads(data.decode("utf-8-sig"))
    info["newer"] = _ver(info.get("version")) > _ver(APP_VERSION)
    info["base"] = base
    return info


def install_app_update(info, script, emit) -> Path:
    """Downloads the new app file, checks it (checksum + Python syntax), installs new packages if needed,
    keeps the old one as .bak and puts the new one in place. The app restarts afterwards."""
    import hashlib
    script = Path(script)
    name = info.get("file") or "tfrog_ytclip.pyw"
    if "/" in name or "\\" in name:
        raise RuntimeError("Invalid update file name.")
    base = info.get("base") or UPDATE_BASE
    if not str(base).startswith(f"https://raw.githubusercontent.com/{UPDATE_REPO}/"):
        base = UPDATE_BASE
    emit("status", f"Downloading version {info.get('version')} …")
    data = fetch_bytes(base + f"{name}?t={int(time.time())}", timeout=60)
    if info.get("sha256") and hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise RuntimeError("The download doesn't match the checksum – try again in a few minutes.")
    compile(data.decode("utf-8"), name, "exec")         # never install a broken file
    extra = {}
    for f in info.get("extra") or []:
        if isinstance(f, str) and "/" not in f and "\\" not in f and f != name:
            try:
                extra[f] = fetch_bytes(base + f, timeout=60)
            except Exception:  # noqa: BLE001 - optional files (icon …)
                pass
    pip = [x for x in info.get("pip") or [] if isinstance(x, str) and re.match(r"^[\w.\[\],<>=!-]+$", x)]
    if pip:
        emit("status", "Installing new packages …")
        py = Path(sys.executable)
        if py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists():
            py = py.with_name("python.exe")
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", *pip],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("Installing packages failed:\n" + (r.stderr or r.stdout).strip()[-500:])
    if script.exists():
        shutil.copyfile(script, script.with_name(script.name + ".bak"))
    tmp = script.with_name(script.name + ".new")
    tmp.write_bytes(data)
    os.replace(tmp, script)
    for f, b in extra.items():
        try:
            (script.parent / f).write_bytes(b)
        except OSError:
            pass
    return script

# ----------------------------------------------------------------------------- GUI (PySide6)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
from PySide6.QtCore import Qt, Signal  # noqa: E402

try:   # video player (PySide6-Addons); the app works without it
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
    PLAYER_OK = True
except Exception:  # noqa: BLE001
    PLAYER_OK = False

AA = QtGui.QPainter.RenderHint.Antialiasing
SMOOTH = QtGui.QPainter.RenderHint.SmoothPixmapTransform


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lum(h):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _mix(a, b, t):
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(_rgb(a), _rgb(b)))


def theme_colors(theme: str, accent: str) -> dict:
    c = dict(THEMES.get(theme, THEMES[DEFAULT_THEME]))
    c["accent"] = accent
    c["on_accent"] = "#0b0b0c" if _lum(accent) > 0.35 else "#ffffff"
    c["accent_hover"] = _mix(accent, "#ffffff" if c["dark"] else "#000000", 0.15)
    c["accent_soft"] = _mix(c["panel"], accent, 0.14)
    c["warn"], c["err"] = WARN_COLOR, ERR_COLOR
    return c


def _arrow_svg(color: str) -> str:
    d = APP_DIR / "ui"
    p = d / f"arrow_{color.lstrip('#')}.svg"
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
                         f'<path d="M1 1l4 4 4-4" fill="none" stroke="{color}" stroke-width="1.6" '
                         'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    except OSError:
        pass
    return str(p).replace("\\", "/")


def _check_svg(color: str) -> str:
    d = APP_DIR / "ui"
    p = d / f"check_{color.lstrip('#')}.svg"
    try:
        d.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                         f'<path d="M2.5 6.2l2.4 2.4 4.6-5" fill="none" stroke="{color}" stroke-width="1.8" '
                         'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    except OSError:
        pass
    return str(p).replace("\\", "/")


def build_qss(c: dict) -> str:
    arrow = _arrow_svg(c["muted"])
    check = _check_svg(c["on_accent"])
    mono = "Consolas, 'Cascadia Mono', 'JetBrains Mono', monospace"
    return f"""
QWidget {{ color: {c['text']}; font-size: 13px; }}
QMainWindow, QDialog, QWidget#root {{ background: {c['bg']}; }}
QToolTip {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px 8px; }}
QFrame#card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 24px; font-weight: 700; }}
QLabel#sub {{ color: {c['muted']}; }}
QLabel#section {{ color: {c['muted']}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#muted, QLabel#field {{ color: {c['muted']}; }}
QLabel#muted[state="ok"] {{ color: {c['accent']}; font-weight: 600; }}
QLabel#dragchip {{ background: {c['panel2']}; border: 1px dashed {c['accent']}; border-radius: 8px;
    padding: 6px 10px; font-weight: 600; }}
QLabel#stepnum {{ background: {c['accent']}; color: {c['on_accent']}; border-radius: 12px; font-weight: 700; }}
QLabel#hint {{ color: {c['muted']}; font-size: 12px; }}
QLabel#hint[state="warn"] {{ color: {c['warn']}; }}
QLabel#hint[state="error"] {{ color: {c['err']}; }}
QLabel#vtitle {{ font-size: 15px; font-weight: 600; }}
QLabel#status {{ color: {c['muted']}; font-size: 12px; }}
QLabel#status[state="ok"] {{ color: {c['accent']}; }}
QLabel#status[state="error"] {{ color: {c['err']}; }}
QLabel#ext {{ color: {c['muted']}; font-family: {mono}; }}
QLabel#len {{ color: {c['accent']}; font-family: {mono}; font-size: 12px; }}
QLabel#brand {{ color: {c['border_hi']}; font-size: 10px; font-weight: 700; letter-spacing: 2px; }}
QLineEdit {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 8px 11px;
    selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QLineEdit:hover {{ border-color: {c['border_hi']}; }}
QLineEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled {{ color: {c['muted']}; }}
QLineEdit#url {{ font-size: 14px; padding: 11px 13px; }}
QLineEdit#time {{ font-family: {mono}; }}
QLineEdit[state="error"] {{ border-color: {c['err']}; }}
QComboBox {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 7px 11px; }}
QComboBox:hover {{ border-color: {c['border_hi']}; }}
QComboBox:focus, QComboBox:on {{ border-color: {c['accent']}; }}
QComboBox:disabled {{ color: {c['muted']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{ background: {c['panel2']}; border: 1px solid {c['border']}; padding: 4px;
    outline: none; selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QPushButton {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 8px 14px; }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['on_accent']}; border: none; border-radius: 12px;
    padding: 14px; font-size: 15px; font-weight: 700; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#primary:disabled {{ background: {c['panel2']}; color: {c['muted']}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {c['muted']}; padding: 6px 8px; }}
QPushButton#ghost:hover {{ color: {c['text']}; }}
QPushButton#ghost:disabled {{ color: {c['border_hi']}; }}
QPushButton#ghost[state="ok"] {{ color: {c['accent']}; font-weight: 700; }}
QPushButton#ghost[state="new"] {{ background: {c['accent']}; color: {c['on_accent']}; font-weight: 700;
    border-radius: 11px; padding: 5px 12px; }}
QPushButton#ghost[state="new"]:hover {{ background: {c['accent_hover']}; color: {c['on_accent']}; }}
QPushButton#ghost[state="new"]:disabled {{ background: {c['panel2']}; color: {c['muted']}; }}
QPushButton#chip {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 12px;
    padding: 4px 12px; font-size: 12px; min-height: 16px; }}
QPushButton#chip:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
QPushButton#chip:disabled {{ color: {c['muted']}; }}
QPushButton#chip[state="on"] {{ border-color: {c['accent']}; color: {c['accent']}; }}
QPushButton#srcChip {{ background: transparent; border: none; color: {c['muted']}; padding: 2px 4px; font-size: 12px; }}
QPushButton#srcChip:hover {{ color: {c['accent']}; }}
QPushButton#srcChip:disabled {{ color: {c['muted']}; }}
QMenu {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px 6px 26px; border-radius: 6px; color: {c['text']}; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['on_accent']}; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QMenu::indicator {{ width: 12px; height: 12px; left: 8px; }}
QFrame#segmented {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#segInd {{ background: {c['accent']}; border: none; border-radius: 9px; }}
QPushButton#segBtn {{ background: transparent; border: none; color: {c['muted']}; padding: 9px 10px; font-weight: 600; }}
QPushButton#segBtn:checked {{ color: {c['on_accent']}; }}
QPushButton#segBtn:hover:!checked {{ color: {c['text']}; }}
QProgressBar {{ background: {c['panel2']}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QPlainTextEdit {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 12px; color: {c['muted']};
    font-family: {mono}; font-size: 11px; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {c['border_hi']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QCheckBox {{ spacing: 9px; }}
QCheckBox:disabled {{ color: {c['muted']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {c['border_hi']};
    background: {c['field']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{check}"); }}
QSlider::groove:horizontal {{ height: 4px; background: {c['panel2']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['text']}; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: {c['accent']}; }}
QPushButton#transport {{ padding: 0; min-width: 34px; max-width: 34px; min-height: 30px; max-height: 30px;
    border-radius: 9px; font-size: 13px; }}
QLabel#ptime {{ color: {c['muted']}; font-family: {mono}; font-size: 12px; }}
QListWidget#clips {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 12px; outline: none;
    padding: 3px; }}
QListWidget#clips::item {{ border-radius: 8px; margin: 1px 0; }}
QListWidget#clips::item:selected {{ background: {c['accent_soft']}; }}
QListWidget#clips::item:hover:!selected {{ background: {c['panel2']}; }}
QWidget#cliprow {{ background: transparent; }}
QLabel#clipno {{ color: {c['accent']}; font-weight: 700; font-family: {mono}; }}
QLabel#cliptime {{ font-family: {mono}; font-size: 12px; }}
QPushButton#mini {{ background: transparent; border: none; color: {c['muted']}; padding: 2px 5px; font-size: 13px;
    min-width: 20px; }}
QPushButton#mini:hover {{ color: {c['accent']}; }}
QPushButton#mini:disabled {{ color: {c['border']}; }}
QPushButton#swatch {{ border-radius: 16px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
    padding: 0; border: 3px solid {c['bg']}; }}
QPushButton#swatch:checked {{ border: 3px solid {c['text']}; }}
QPushButton#swatch:hover {{ border: 3px solid {c['border_hi']}; }}
QPushButton#swatch:checked:hover {{ border: 3px solid {c['text']}; }}
QPushButton#tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    color: {c['muted']}; padding: 6px 2px 7px 2px; margin-right: 14px; font-weight: 600; }}
QPushButton#tab:hover {{ color: {c['text']}; }}
QPushButton#tab:checked {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QPushButton#tab:disabled {{ color: {c['border_hi']}; }}
QFrame#tabline {{ background: {c['border']}; border: none; min-height: 1px; max-height: 1px; }}
QTableWidget#lines {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 12px;
    gridline-color: {c['border']}; outline: none; selection-background-color: {c['accent_soft']};
    selection-color: {c['text']}; }}
QHeaderView::section {{ background: {c['panel2']}; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['border']}; padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['panel2']}; border: none; }}
QTableWidget#lines QLineEdit {{ padding: 1px 6px; border-radius: 5px; }}
QPushButton#colorbtn {{ min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; padding: 0;
    border-radius: 8px; border: 2px solid {c['border_hi']}; }}
QListWidget#history, QListWidget#lines {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 12px;
    outline: none; padding: 4px; }}
QListWidget#history::item, QListWidget#lines::item {{ border-radius: 8px; padding: 4px; }}
QListWidget#history::item:selected, QListWidget#lines::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QListWidget#history::item:hover:!selected, QListWidget#lines::item:hover:!selected {{ background: {c['panel2']}; }}
"""


def set_dark_titlebar(widget, dark: bool) -> None:
    if not WIN:
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 / older Win10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def repolish(w) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def set_state(w, state: str) -> None:
    if w.property("state") != state:
        w.setProperty("state", state)
        repolish(w)


# ---- custom widgets ----------------------------------------------------------------

def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tip_html(title: str, text: str = "") -> str:
    """Rich-text tooltip (rich text wraps nicely instead of one endless line)."""
    if not text:
        return f"<div>{_esc(title)}</div>"
    return f"<b>{_esc(title)}</b><br>{_esc(text)}"


def tip(w, title: str, text: str = ""):
    w.setToolTip(tip_html(title, text))
    return w


class TipFilter(QtCore.QObject):
    """App-wide switch for the hover help (Settings)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True

    def eventFilter(self, obj, ev):
        return ev.type() == QtCore.QEvent.Type.ToolTip and not self.enabled


class Spinner(QtWidgets.QWidget):
    def __init__(self, parent=None, size=26):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.color = QtGui.QColor(DEFAULT_ACCENT)
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self):
        self._timer.start()
        self.show()
        self.raise_()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 7) % 360
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        pen = QtGui.QPen(self.color, 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        r = QtCore.QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.drawArc(r, -self._angle * 16, 270 * 16)


class Segmented(QtWidgets.QFrame):
    """Segmented control with a sliding highlight."""
    changed = Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self._ind = QtWidgets.QFrame(self)
        self._ind.setObjectName("segInd")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self._btns = {}
        for key, label in items:
            b = QtWidgets.QPushButton(label)
            b.setObjectName("segBtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_value(k, animate=True, emit=True))
            lay.addWidget(b, 1)
            self._btns[key] = b
        self._ind.lower()
        self._value = items[0][0]
        self._btns[self._value].setChecked(True)
        self._anim = QtCore.QPropertyAnimation(self._ind, b"geometry", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def value(self):
        return self._value

    def set_tips(self, tips: dict):
        for k, (title, text) in tips.items():
            if k in self._btns:
                tip(self._btns[k], title, text)

    def set_value(self, key, animate=False, emit=False):
        if key not in self._btns:
            return
        changed = key != self._value
        self._value = key
        for k, b in self._btns.items():
            b.setChecked(k == key)
        self._place(animate)
        if emit and changed:
            self.changed.emit(key)

    def _place(self, animate):
        target = self._btns[self._value].geometry()
        if not target.isValid():
            return
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._ind.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._ind.setGeometry(target)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QtCore.QTimer.singleShot(0, lambda: self._place(False))

    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, lambda: self._place(False))


class RangeSlider(QtWidgets.QWidget):
    """Timeline with two handles (start/end of the clip), the player position and the other clips."""
    changed = Signal(float, float)
    dragged = Signal(str, float)   # handle ('lo' / 'hi' / 'mid') and its time -> the player shows that frame

    M = 12  # horizontal margin

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._max, self._lo, self._hi = 1.0, 0.0, 1.0
        self._drag = None
        self._hover = None
        self._grab = 0.0
        self._play = None
        self._others = []
        self.c = theme_colors(DEFAULT_THEME, DEFAULT_ACCENT)

    def set_colors(self, c):
        self.c = c
        self.update()

    def set_playhead(self, t):
        self._play = t
        self.update()

    def set_others(self, segs):
        """Other clips (multi-clip mode): [(start, end, label)]"""
        self._others = list(segs)
        self.update()

    def set_duration(self, d):
        self._max = max(float(d), 0.1)
        self._lo, self._hi = 0.0, self._max
        self.update()

    def duration(self):
        return self._max

    def set_range(self, lo, hi):
        lo = min(max(0.0, lo), self._max)
        hi = min(max(lo + 0.1, hi), self._max)
        self._lo, self._hi = lo, hi
        self.update()

    def values(self):
        return self._lo, self._hi

    def _x(self, v):
        return self.M + (self.width() - 2 * self.M) * v / self._max

    def _v(self, x):
        v = (x - self.M) / max(1, self.width() - 2 * self.M) * self._max
        return round(min(max(0.0, v), self._max), 1)

    def _hit(self, x):
        dl, dh = abs(x - self._x(self._lo)), abs(x - self._x(self._hi))
        if min(dl, dh) <= 12:
            return "lo" if dl < dh or (dl == dh and x < self._x(self._lo)) else "hi"
        if self._x(self._lo) < x < self._x(self._hi):
            return "mid"
        return "lo" if dl < dh else "hi"

    def mousePressEvent(self, e):
        x = e.position().x()
        self._drag = self._hit(x)
        self._grab = self._v(x) - self._lo
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag is None:
            h = self._hit(x)
            h = h if h != "mid" else None
            if h != self._hover:
                self._hover = h
                self.update()
            return
        v = self._v(x)
        if self._drag == "lo":
            self._lo = min(v, self._hi - 0.1)
        elif self._drag == "hi":
            self._hi = max(v, self._lo + 0.1)
        else:
            span = self._hi - self._lo
            lo = min(max(0.0, round(v - self._grab, 1)), self._max - span)
            self._lo, self._hi = lo, lo + span
        self.update()
        self.changed.emit(self._lo, self._hi)
        self.dragged.emit(self._drag, self._hi if self._drag == "hi" else self._lo)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def paintEvent(self, _e):
        c = self.c
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        y = 16
        track = QtCore.QRectF(self.M, y - 3, self.width() - 2 * self.M, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(c["panel2"]))
        p.drawRoundedRect(track, 3, 3)
        if self._others:
            f0 = self.font()
            f0.setPointSizeF(max(7.0, f0.pointSizeF() - 2))
            f0.setBold(True)
            p.setFont(f0)
            for lo, hi, lab in self._others:
                a, b = self._x(lo), self._x(hi)
                col = QtGui.QColor(c["accent"])
                col.setAlpha(80)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(QtCore.QRectF(a, y - 7, max(3.0, b - a), 14), 4, 4)
                if b - a > 14:
                    p.setPen(QtGui.QColor(c["text"]))
                    p.drawText(QtCore.QRectF(a, y - 7, b - a, 14), Qt.AlignmentFlag.AlignCenter, str(lab))
            p.setPen(Qt.PenStyle.NoPen)
        x1, x2 = self._x(self._lo), self._x(self._hi)
        p.setBrush(QtGui.QColor(c["accent"]))
        p.drawRoundedRect(QtCore.QRectF(x1, y - 3, max(2.0, x2 - x1), 6), 3, 3)
        for name, x in (("lo", x1), ("hi", x2)):
            r = 9 if (self._hover == name or self._drag == name) else 7.5
            p.setBrush(QtGui.QColor(c["text"] if c["dark"] else "#ffffff"))
            p.setPen(QtGui.QPen(QtGui.QColor(c["accent"]), 2.5))
            p.drawEllipse(QtCore.QPointF(x, y), r, r)
        f = self.font()
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.setPen(QtGui.QColor(c["muted"]))
        fm = QtGui.QFontMetrics(f)
        t1, t2 = fmt_ts(self._lo), fmt_ts(self._hi)
        w1, w2 = fm.horizontalAdvance(t1), fm.horizontalAdvance(t2)
        lx = min(max(0, x1 - w1 / 2), self.width() - w1)
        rx = min(max(0, x2 - w2 / 2), self.width() - w2)
        if rx < lx + w1 + 6:  # labels would overlap -> push apart
            rx = min(self.width() - w2, lx + w1 + 6)
            lx = min(lx, rx - w1 - 6)
        p.drawText(QtCore.QPointF(lx, y + 24), t1)
        p.drawText(QtCore.QPointF(rx, y + 24), t2)
        if self._play is not None:
            xp = self._x(min(max(0.0, self._play), self._max))
            p.setPen(QtGui.QPen(QtGui.QColor(c["text"]), 2))
            p.drawLine(QtCore.QPointF(xp, y - 11), QtCore.QPointF(xp, y + 11))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(c["text"]))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(xp - 4, y - 14), QtCore.QPointF(xp + 4, y - 14),
                                           QtCore.QPointF(xp, y - 9)]))


class Thumb(QtWidgets.QWidget):
    """16:9 preview with rounded corners, fade-in, a duration badge and an overlay
    (e.g. 'Load video preview' / download progress). Clickable."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        sp = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumSize(320, 180)
        self.c = theme_colors(DEFAULT_THEME, DEFAULT_ACCENT)
        self._pix = None
        self._text = "Paste a YouTube link to see a preview"
        self._badge = ""
        self._overlay = ""
        self._ov_frac = None
        self._alpha = 1.0
        self._fade = QtCore.QVariantAnimation(self)
        self._fade.setDuration(350)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._on_fade)
        self.spinner = Spinner(self, 34)

    def set_colors(self, c):
        self.c = c
        self.spinner.color = QtGui.QColor(c["accent"])
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int(w * 9 / 16)

    def sizeHint(self):
        return QtCore.QSize(520, 292)

    def set_overlay(self, text="", frac=None):
        self._overlay, self._ov_frac = text, frac
        self.setCursor(Qt.CursorShape.PointingHandCursor if text.startswith("▶") else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def set_text(self, text):
        self._pix, self._text, self._badge = None, text, ""
        self.spinner.stop()
        self.update()

    def set_loading(self):
        self._pix, self._text, self._badge = None, "", ""
        self.spinner.start()
        self.update()

    def set_image(self, data, badge=""):
        self.spinner.stop()
        self._badge = badge
        pix = None
        if data:
            img = QtGui.QImage()
            if img.loadFromData(data):
                pix = QtGui.QPixmap.fromImage(img)
        self._pix = pix
        self._text = "" if pix else "No preview image"
        self._alpha = 0.0
        self._fade.start()
        self.update()

    def _on_fade(self, v):
        self._alpha = float(v)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.spinner.move((self.width() - self.spinner.width()) // 2, (self.height() - self.spinner.height()) // 2)

    def paintEvent(self, _e):
        c = self.c
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(SMOOTH)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QtGui.QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QtGui.QColor(c["field"]))
        if self._pix is not None and not self._pix.isNull():
            p.save()
            p.setClipPath(path)
            p.setOpacity(self._alpha)
            pw, ph = self._pix.width(), self._pix.height()
            s = max(r.width() / pw, r.height() / ph)
            w, h = pw * s, ph * s
            p.drawPixmap(QtCore.QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), self._pix,
                         QtCore.QRectF(0, 0, pw, ph))
            p.restore()
            if self._badge:
                f = self.font()
                f.setBold(True)
                p.setFont(f)
                fm = QtGui.QFontMetrics(f)
                bw, bh = fm.horizontalAdvance(self._badge) + 14, fm.height() + 6
                br = QtCore.QRectF(r.right() - bw - 10, r.bottom() - bh - 10, bw, bh)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(0, 0, 0, 170))
                p.drawRoundedRect(br, 6, 6)
                p.setPen(QtGui.QColor("#ffffff"))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, self._badge)
        elif self._text:
            p.setPen(QtGui.QColor(c["muted"]))
            p.drawText(r.adjusted(20, 0, -20, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)
        if self._overlay:
            f = self.font()
            if f.pointSizeF() > 0:
                f.setPointSizeF(f.pointSizeF() + 0.5)
            f.setBold(True)
            p.setFont(f)
            fm = QtGui.QFontMetrics(f)
            bw, bh = fm.horizontalAdvance(self._overlay) + 34, fm.height() + (22 if self._ov_frac is not None else 16)
            br = QtCore.QRectF(r.center().x() - bw / 2, r.center().y() - bh / 2, bw, bh)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 175))
            p.drawRoundedRect(br, bh / 2 if self._ov_frac is None else 12, bh / 2 if self._ov_frac is None else 12)
            p.setPen(QtGui.QColor("#ffffff"))
            tr = QtCore.QRectF(br.left(), br.top() + (2 if self._ov_frac is None else 4), br.width(), fm.height() + 12)
            p.drawText(tr if self._ov_frac is not None else br, Qt.AlignmentFlag.AlignCenter, self._overlay)
            if self._ov_frac is not None:
                bar = QtCore.QRectF(br.left() + 17, br.bottom() - 10, br.width() - 34, 3)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(255, 255, 255, 60))
                p.drawRoundedRect(bar, 1.5, 1.5)
                p.setBrush(QtGui.QColor(c["accent"]))
                p.drawRoundedRect(QtCore.QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, self._ov_frac)),
                                                3), 1.5, 1.5)
        p.setPen(QtGui.QPen(QtGui.QColor(c["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class VideoCanvas(QtWidgets.QWidget):
    """Shows the frames of the player (from a QVideoSink) and draws on top: the crop box (drag to move,
    corners to resize, the format stays; "Custom": any shape, sides too) and the current subtitle line."""
    boxChanged = Signal(object)    # (x, y, w, h) as fractions of the frame
    subMoved = Signal(object)      # (x, y) bottom center of the subtitles as fractions of the picture, or None

    H = 12  # corner grab size

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.c = theme_colors(DEFAULT_THEME, DEFAULT_ACCENT)
        self.img = None
        self.aspect = None
        self.box = None
        self.box_label = ""            # text in the corner of the box (format or the size in px)
        self.sub_text = ""
        self.sub_style = dict(SUB_STYLE)
        self.ghost = False
        self._sub_rect = None
        self._sub_grab = None
        self._drag = None
        self._grab = None
        self.sink = None
        if PLAYER_OK:
            try:
                self.sink = QVideoSink(self)
                self.sink.videoFrameChanged.connect(self._on_frame)
            except Exception:  # noqa: BLE001
                self.sink = None

    def set_colors(self, c):
        self.c = c
        self.update()

    def _on_frame(self, frame):
        try:
            img = frame.toImage()
        except Exception:  # noqa: BLE001
            return
        if img is not None and not img.isNull():
            self.img = img
            if self.aspect and self.box is None:
                self.reset_box()
            self.update()

    def clear(self):
        self.img = None
        self.update()

    def frame_size(self):
        return (self.img.width(), self.img.height()) if self.img is not None else None

    # crop box
    def set_aspect(self, aspect, box=None):
        self.aspect = aspect
        self.box = box
        if aspect and box is None:
            self.reset_box(emit=False)
        self.update()

    def set_box(self, box):
        self.box = box
        if self.aspect and box is None:
            self.reset_box(emit=False)
        self.update()

    def reset_box(self, emit=True):
        fs = self.frame_size()
        if not self.aspect or not fs:
            return
        self.box = center_box(self.aspect, *fs)
        self.update()
        if emit:
            self.boxChanged.emit(self.box)

    def set_sub(self, text):
        if text != self.sub_text:
            self.sub_text = text
            self.update()

    def set_sub_style(self, style):
        self.sub_style = dict(style)
        self.update()

    def set_ghost(self, on):
        if on != self.ghost:
            self.ghost = on
            self.update()

    def _sub_area(self):
        b = self._box_rect()
        return b if b is not None else self._frame_rect()

    def _frame_rect(self):
        r = QtCore.QRectF(self.rect())
        if self.img is None:
            return r
        iw, ih = self.img.width(), self.img.height()
        s = min(r.width() / iw, r.height() / ih)
        w, h = iw * s, ih * s
        return QtCore.QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def _box_rect(self):
        if not self.aspect or self.box is None or self.img is None:
            return None
        f = self._frame_rect()
        x, y, w, h = self.box
        return QtCore.QRectF(f.left() + x * f.width(), f.top() + y * f.height(), w * f.width(), h * f.height())

    def _hit(self, pos):
        b = self._box_rect()
        if b is None:
            return None
        for name, pt in (("tl", b.topLeft()), ("tr", b.topRight()), ("bl", b.bottomLeft()), ("br", b.bottomRight())):
            if abs(pos.x() - pt.x()) <= self.H and abs(pos.y() - pt.y()) <= self.H:
                return name
        if self.aspect == FREE:            # any shape: the sides can be pulled too
            inx, iny = b.left() < pos.x() < b.right(), b.top() < pos.y() < b.bottom()
            for name, near in (("l", iny and abs(pos.x() - b.left()) <= self.H * 0.75),
                               ("r", iny and abs(pos.x() - b.right()) <= self.H * 0.75),
                               ("t", inx and abs(pos.y() - b.top()) <= self.H * 0.75),
                               ("b", inx and abs(pos.y() - b.bottom()) <= self.H * 0.75)):
                if near:
                    return name
        return "move" if b.contains(pos) else "outside"

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MouseButton.LeftButton and self._sub_rect is not None \
                and self._sub_rect.adjusted(-6, -6, 6, 6).contains(pos) and self.img is not None:
            a = self._sub_area()
            _fs, _ol, ax, ay = sub_layout(a.width(), a.height(), self.sub_style)
            self._sub_grab = (pos, QtCore.QPointF(a.left() + ax, a.top() + ay))
            self._drag = "sub"
            return
        if e.button() != Qt.MouseButton.LeftButton or self._box_rect() is None:
            return super().mousePressEvent(e)
        hit = self._hit(pos)
        b = self._box_rect()
        if hit == "outside":   # jump: center the box on the click
            f = self._frame_rect()
            nb = QtCore.QRectF(b)
            nb.moveCenter(pos)
            self._apply_rect(nb, f)
            hit, b = "move", self._box_rect()
        self._drag = hit
        self._grab = (pos, QtCore.QRectF(b))

    def mouseDoubleClickEvent(self, e):
        if self._sub_rect is not None and self._sub_rect.adjusted(-6, -6, 6, 6).contains(e.position()):
            self.sub_style["pos"] = None          # back to the default place
            self.update()
            self.subMoved.emit(None)
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag == "sub":
            p0, anchor = self._sub_grab
            a = self._sub_area()
            nx = (anchor.x() + pos.x() - p0.x() - a.left()) / max(1.0, a.width())
            ny = (anchor.y() + pos.y() - p0.y() - a.top()) / max(1.0, a.height())
            nx, ny = min(max(nx, 0.03), 0.97), min(max(ny, 0.05), 0.99)
            if abs(nx - 0.5) < 0.02:
                nx = 0.5                     # snaps to the middle
            self.sub_style["pos"] = (round(nx, 4), round(ny, 4))
            self.update()
            self.subMoved.emit(self.sub_style["pos"])
            return
        if self._drag is None:
            if self._sub_rect is not None and self._sub_rect.adjusted(-6, -6, 6, 6).contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return
            hit = self._hit(pos)
            cur = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                   "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                   "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                   "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                   "move": Qt.CursorShape.SizeAllCursor, "outside": Qt.CursorShape.PointingHandCursor}.get(hit)
            self.setCursor(cur or Qt.CursorShape.ArrowCursor)
            return
        f = self._frame_rect()
        p0, b0 = self._grab
        if self._drag == "move":
            nb = b0.translated(pos - p0)
        elif self.aspect == FREE:          # free: every side follows the mouse on its own
            d = self._drag
            mn = min(f.width(), f.height()) * 0.05
            le, to, ri, bo = b0.left(), b0.top(), b0.right(), b0.bottom()
            dx, dy = pos.x() - p0.x(), pos.y() - p0.y()
            if d in ("tl", "bl", "l"):
                le = min(max(le + dx, f.left()), ri - mn)
            if d in ("tr", "br", "r"):
                ri = max(min(ri + dx, f.right()), le + mn)
            if d in ("tl", "tr", "t"):
                to = min(max(to + dy, f.top()), bo - mn)
            if d in ("bl", "br", "b"):
                bo = max(min(bo + dy, f.bottom()), to + mn)
            nb = QtCore.QRectF(QtCore.QPointF(le, to), QtCore.QPointF(ri, bo))
        else:
            aw, ah = self.aspect
            anchor = {"tl": b0.bottomRight(), "tr": b0.bottomLeft(), "bl": b0.topRight(), "br": b0.topLeft()}[self._drag]
            dx, dy = abs(pos.x() - anchor.x()), abs(pos.y() - anchor.y())
            w = max(dx, dy * aw / ah)
            w = max(w, min(f.width(), f.height()) * 0.08)
            sx = -1 if self._drag in ("tl", "bl") else 1
            sy = -1 if self._drag in ("tl", "tr") else 1
            # keep it inside the frame
            maxw = (anchor.x() - f.left()) if sx < 0 else (f.right() - anchor.x())
            maxh = (anchor.y() - f.top()) if sy < 0 else (f.bottom() - anchor.y())
            w = min(w, maxw, maxh * aw / ah)
            h = w * ah / aw
            nb = QtCore.QRectF(anchor.x() if sx > 0 else anchor.x() - w, anchor.y() if sy > 0 else anchor.y() - h, w, h)
        self._apply_rect(nb, f)

    def _apply_rect(self, nb, f):
        nb = QtCore.QRectF(nb)
        if nb.width() > f.width():
            nb.setWidth(f.width())
        if nb.height() > f.height():
            nb.setHeight(f.height())
        nb.moveLeft(min(max(nb.left(), f.left()), f.right() - nb.width()))
        nb.moveTop(min(max(nb.top(), f.top()), f.bottom() - nb.height()))
        self.box = ((nb.left() - f.left()) / f.width(), (nb.top() - f.top()) / f.height(),
                    nb.width() / f.width(), nb.height() / f.height())
        self.update()
        self.boxChanged.emit(self.box)

    def mouseReleaseEvent(self, e):
        was = self._drag
        self._drag = None
        if was == "sub":
            self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        c = self.c
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(SMOOTH)
        r = QtCore.QRectF(self.rect())
        path = QtGui.QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.setClipPath(path)
        p.fillRect(r, QtGui.QColor("#000"))
        if self.img is None:
            return
        f = self._frame_rect()
        p.drawImage(f, self.img)
        b = self._box_rect()
        area = b if b is not None else f
        if b is not None:
            shade = QtGui.QPainterPath()
            shade.addRect(f)
            inner = QtGui.QPainterPath()
            inner.addRect(b)
            p.fillPath(shade.subtracted(inner), QtGui.QColor(0, 0, 0, 150))
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 55), 1))
            for k in (1, 2):
                p.drawLine(QtCore.QPointF(b.left() + b.width() * k / 3, b.top()),
                           QtCore.QPointF(b.left() + b.width() * k / 3, b.bottom()))
                p.drawLine(QtCore.QPointF(b.left(), b.top() + b.height() * k / 3),
                           QtCore.QPointF(b.right(), b.top() + b.height() * k / 3))
            p.setPen(QtGui.QPen(QtGui.QColor(c["accent"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(b)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(c["accent"]))
            for pt in (b.topLeft(), b.topRight(), b.bottomLeft(), b.bottomRight()):
                p.drawRoundedRect(QtCore.QRectF(pt.x() - 5, pt.y() - 5, 10, 10), 2.5, 2.5)
            if self.aspect == FREE:        # grips in the middle of the sides
                cx, cy = b.center().x(), b.center().y()
                for rr in (QtCore.QRectF(cx - 9, b.top() - 3, 18, 6), QtCore.QRectF(cx - 9, b.bottom() - 3, 18, 6),
                           QtCore.QRectF(b.left() - 3, cy - 9, 6, 18), QtCore.QRectF(b.right() - 3, cy - 9, 6, 18)):
                    p.drawRoundedRect(rr, 3, 3)
            lab = self.box_label or ("Custom" if self.aspect == FREE else f"{self.aspect[0]}:{self.aspect[1]}")
            fn = self.font()
            fn.setBold(True)
            fn.setPointSizeF(max(7.5, fn.pointSizeF() - 1))
            p.setFont(fn)
            fm = QtGui.QFontMetrics(fn)
            tr = QtCore.QRectF(b.left() + 6, b.top() + 6, fm.horizontalAdvance(lab) + 12, fm.height() + 4)
            p.setBrush(QtGui.QColor(0, 0, 0, 160))
            p.drawRoundedRect(tr, 5, 5)
            p.setPen(QtGui.QColor("#fff"))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, lab)
        self._sub_rect = None
        text = self.sub_text or ("Subtitle text – drag me" if self.ghost else "")
        if text:
            st = self.sub_style
            fs, ol, ax, ay = sub_layout(area.width(), area.height(), st)
            fn = QtGui.QFont(st.get("font") or "Arial")
            fn.setBold(bool(st.get("bold")))
            fn.setPixelSize(max(6, int(round(fs))))
            fm = QtGui.QFontMetricsF(fn)
            lines = []
            for para in text.split("\n"):
                cur = ""
                for w in para.split(" "):
                    t = (cur + " " + w).strip()
                    if cur and fm.horizontalAdvance(t) > area.width() * 0.86:
                        lines.append(cur)
                        cur = w
                    else:
                        cur = t
                lines.append(cur)
            cx, bottom = area.left() + ax, area.top() + ay
            tp = QtGui.QPainterPath()
            y = bottom - fm.descent() - (len(lines) - 1) * fm.lineSpacing()
            for ln in lines:
                tp.addText(QtCore.QPointF(cx - fm.horizontalAdvance(ln) / 2, y), fn, ln)
                y += fm.lineSpacing()
            p.save()
            if not self.sub_text:
                p.setOpacity(0.55)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(st.get("outline") or "#000"), ol * 2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(tp)
            p.fillPath(tp, QtGui.QColor(st.get("color") or "#fff"))
            p.restore()
            self._sub_rect = tp.boundingRect()
            if self._drag == "sub" or not self.sub_text:
                p.setPen(QtGui.QPen(QtGui.QColor(c["accent"]), 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(self._sub_rect.adjusted(-6, -4, 6, 4))


class VideoView(QtWidgets.QWidget):
    """16:9 area: the thumbnail, or the video of the built-in player (with crop box / subtitles on top)."""

    def __init__(self, thumb, parent=None):
        super().__init__(parent)
        sp = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumSize(320, 180)
        self.thumb = thumb
        self.stack = QtWidgets.QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(thumb)
        self.video = None
        if PLAYER_OK:
            cv = VideoCanvas()
            if cv.sink is not None:
                self.video = cv
                self.stack.addWidget(cv)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int(w * 9 / 16)

    def sizeHint(self):
        return QtCore.QSize(560, 315)

    def show_video(self, on):
        self.stack.setCurrentWidget(self.video if (on and self.video is not None) else self.thumb)

    def showing_video(self):
        return self.video is not None and self.stack.currentWidget() is self.video


class TabBar(QtWidgets.QWidget):
    """Flat tabs with an underline; a dot after the name shows that something is switched on there."""
    changed = Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.btns, self.names, self._val = {}, {}, items[0][0]
        group = QtWidgets.QButtonGroup(self)
        for key, text in items:
            b = QtWidgets.QPushButton(text)
            b.setObjectName("tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_value(k, emit=True))
            group.addButton(b)
            row.addWidget(b)
            self.btns[key], self.names[key] = b, text
        row.addStretch(1)
        lay.addLayout(row)
        line = QtWidgets.QFrame()
        line.setObjectName("tabline")
        lay.addWidget(line)
        self.btns[self._val].setChecked(True)

    def value(self):
        return self._val

    def set_value(self, key, emit=False):
        if key not in self.btns:
            return
        self._val = key
        self.btns[key].setChecked(True)
        if emit:
            self.changed.emit(key)

    def set_badge(self, key, on):
        self.btns[key].setText(self.names[key] + ("  •" if on else ""))

    def set_shown(self, key, on):
        """Hides a tab that can't be used right now (e.g. Volume for GIFs); if it was open, Output opens."""
        b = self.btns.get(key)
        if b is None:
            return
        b.setVisible(bool(on))
        if not on and self._val == key:
            first = next(k for k, x in self.btns.items() if not x.isHidden())
            self.set_value(first, emit=True)

    def shown(self, key):
        return not self.btns[key].isHidden()

    def set_tips(self, tips):
        for k, (t, x) in tips.items():
            tip(self.btns[k], t, x)


class VolumeLane(QtWidgets.QWidget):
    """Volume curve over the clip: click to add a point, drag to move, right-click / double-click / Del to delete.
    100 % = unchanged, up to 200 %. Points are [time, gain, ease] – the ease shapes the way to the next point."""
    changed = Signal()
    seek = Signal(float)
    selected = Signal(object)     # the selected point (list) or None

    M = 14
    TOP, BOT = 10, 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(118)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.c = theme_colors(DEFAULT_THEME, DEFAULT_ACCENT)
        self.pts: list[list] = []
        self.sel = None
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.lo, self.hi = 0.0, 10.0
        self.play = None
        self._drag = None
        self._hover = None
        self._mouse = None

    def set_colors(self, c):
        self.c = c
        self.update()

    def set_points(self, pts):
        self.pts = pts      # shared list (absolute times)
        self.update()

    def set_range(self, lo, hi):
        self.lo, self.hi = float(lo), max(float(lo) + 0.05, float(hi))
        self.update()

    def set_playhead(self, t):
        self.play = t
        self.update()

    def _x(self, t):
        return self.M + (self.width() - 2 * self.M) * (t - self.lo) / (self.hi - self.lo)

    def _t(self, x):
        t = self.lo + (x - self.M) / max(1, self.width() - 2 * self.M) * (self.hi - self.lo)
        return min(max(self.lo, t), self.hi)

    def _y(self, g):
        return self.TOP + (self.height() - self.TOP - self.BOT) * (1 - g / 2.0)

    def _g(self, y):
        g = (1 - (y - self.TOP) / max(1, self.height() - self.TOP - self.BOT)) * 2.0
        g = min(max(0.0, g), 2.0)
        return 1.0 if abs(g - 1.0) < 0.05 else round(g, 3)

    def _near(self, pos):
        for i, pt in enumerate(self.pts):
            t, g = pt[0], pt[1]
            if self.lo - 0.001 <= t <= self.hi + 0.001 and abs(self._x(t) - pos.x()) <= 8 and abs(self._y(g) - pos.y()) <= 8:
                return i
        return None

    def select(self, pt):
        self.sel = pt
        self.selected.emit(pt)
        self.update()

    def delete(self, pt):
        if pt in self.pts:
            self.pts.remove(pt)
        if self.sel is pt:
            self.select(None)
        self._drag = None
        self.changed.emit()
        self.update()

    def mousePressEvent(self, e):
        pos = e.position()
        i = self._near(pos)
        if e.button() == Qt.MouseButton.RightButton:
            if i is not None:
                self.delete(self.pts[i])
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if i is None:
            pt = [round(self._t(pos.x()), 3), self._g(pos.y()), "linear"]
            self.pts.append(pt)
            self.pts.sort(key=lambda q: q[0])
            self.changed.emit()
        else:
            pt = self.pts[i]
        self._drag = pt
        self.select(pt)

    def mouseDoubleClickEvent(self, e):
        i = self._near(e.position())
        if i is not None:
            self.delete(self.pts[i])

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel is not None:
            self.delete(self.sel)
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._mouse = pos
        if self._drag is not None:
            self._drag[0] = round(self._t(pos.x()), 3)
            self._drag[1] = self._g(pos.y())
            self.pts.sort(key=lambda q: q[0])
            self.changed.emit()
            self.selected.emit(self._drag)
        else:
            self._hover = self._near(pos)
            self.setCursor(Qt.CursorShape.SizeAllCursor if self._hover is not None else Qt.CursorShape.CrossCursor)
        self.update()

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self.seek.emit(self._drag[0])
        self._drag = None

    def leaveEvent(self, _e):
        self._mouse = None
        self._hover = None
        self.update()

    def paintEvent(self, _e):
        c = self.c
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(QtGui.QColor(c["border"]), 1))
        p.setBrush(QtGui.QColor(c["field"]))
        p.drawRoundedRect(r, 12, 12)
        x0, x1 = self._x(self.lo), self._x(self.hi)
        fn = self.font()
        fn.setPointSizeF(max(7.0, fn.pointSizeF() - 2))
        p.setFont(fn)
        for g, lab in ((2.0, "200 %"), (1.0, "100 %"), (0.0, "0")):
            y = self._y(g)
            pen = QtGui.QPen(QtGui.QColor(c["border_hi"] if g == 1.0 else c["border"]), 1,
                             Qt.PenStyle.DashLine if g == 1.0 else Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(x0, y), QtCore.QPointF(x1, y))
            p.setPen(QtGui.QColor(c["muted"]))
            p.drawText(QtCore.QPointF(x1 - QtGui.QFontMetrics(fn).horizontalAdvance(lab), y - 3), lab)
        # curve over the visible range
        poly = QtGui.QPolygonF()
        n = 120
        for k in range(n + 1):
            t = self.lo + (self.hi - self.lo) * k / n
            poly.append(QtCore.QPointF(self._x(t), self._y(min(2.0, vol_at(self.pts, t)))))
        fill = QtGui.QPolygonF(poly)
        fill.append(QtCore.QPointF(x1, self._y(0)))
        fill.append(QtCore.QPointF(x0, self._y(0)))
        col = QtGui.QColor(c["accent"])
        col.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPolygon(fill)
        p.setPen(QtGui.QPen(QtGui.QColor(c["accent"]), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(poly)
        for i, pt in enumerate(self.pts):
            t, g = pt[0], pt[1]
            if not (self.lo - 0.001 <= t <= self.hi + 0.001):
                continue
            big = i == self._hover or pt is self._drag or pt is self.sel
            p.setPen(QtGui.QPen(QtGui.QColor(c["accent"]), 2))
            p.setBrush(QtGui.QColor(c["accent"]) if pt is self.sel else QtGui.QColor(c["text"] if c["dark"] else "#fff"))
            ctr = QtCore.QPointF(self._x(t), self._y(min(2.0, g)))
            if len(pt) > 2 and pt[2] not in ("linear", None):     # eased points are drawn as diamonds (like AE)
                rr = 7 if big else 5.5
                p.drawPolygon(QtGui.QPolygonF([ctr + QtCore.QPointF(0, -rr), ctr + QtCore.QPointF(rr, 0),
                                               ctr + QtCore.QPointF(0, rr), ctr + QtCore.QPointF(-rr, 0)]))
            else:
                p.drawEllipse(ctr, 6 if big else 4.5, 6 if big else 4.5)
        if self.play is not None and self.lo <= self.play <= self.hi:
            xp = self._x(self.play)
            p.setPen(QtGui.QPen(QtGui.QColor(c["text"]), 1.5))
            p.drawLine(QtCore.QPointF(xp, self.TOP - 4), QtCore.QPointF(xp, self._y(0) + 2))
        p.setPen(QtGui.QColor(c["muted"]))
        p.drawText(QtCore.QPointF(x0, self.height() - 7), fmt_tf(self.lo))
        t2 = fmt_tf(self.hi)
        p.drawText(QtCore.QPointF(x1 - QtGui.QFontMetrics(fn).horizontalAdvance(t2), self.height() - 7), t2)
        if self._mouse is not None and (self._drag is not None or self._hover is not None or True):
            if self._drag is not None:
                t, g = self._drag[0], self._drag[1]
            elif self._hover is not None:
                t, g = self.pts[self._hover][0], self.pts[self._hover][1]
            else:
                t, g = self._t(self._mouse.x()), self._g(self._mouse.y())
            lab = f"{fmt_tf(t)} · {g * 100:.0f} %"
            fm = QtGui.QFontMetrics(fn)
            w = fm.horizontalAdvance(lab)
            p.setPen(QtGui.QColor(c["text"]))
            p.drawText(QtCore.QPointF((self.width() - w) / 2, self.height() - 7), lab)


class Clip(list):
    """[start, end] of a clip + its name (e.g. a chapter title) and its crop box."""

    def __init__(self, s, e, label="", box=None):
        super().__init__([float(s), float(e)])
        self.label = label
        self.box = box


class HistoryDialog(QtWidgets.QDialog):
    """All links you pasted, newest first, with a small picture. Double-click opens one."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("History")
        self.resize(660, 620)
        self.chosen = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label("History", "h1"))
        head.addStretch(1)
        self.count = label("", "muted")
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(head)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search title, channel or link …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("history")
        self.list.setIconSize(QtCore.QSize(128, 72))
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(lambda _it: self._open())
        lay.addWidget(self.list, 1)
        bot = QtWidgets.QHBoxLayout()
        for txt, fn, title, text in (("Copy link", self._copy, "Copy link", "Copies the link of the selected entry."),
                                     ("Remove", self._remove, "Remove", "Removes the selected entry from the history."),
                                     ("Clear all", self._clear, "Clear all", "Empties the whole history.")):
            b = tip(QtWidgets.QPushButton(txt), title, text)
            b.setObjectName("ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            bot.addWidget(b)
        bot.addStretch(1)
        ok = QtWidgets.QPushButton("Open")
        ok.setObjectName("primary")
        ok.setMinimumWidth(120)
        ok.clicked.connect(self._open)
        bot.addWidget(ok)
        lay.addLayout(bot)
        self._fill()

    def _fill(self):
        self.list.clear()
        items = history_load()
        blank = QtGui.QPixmap(128, 72)
        blank.fill(QtGui.QColor(0, 0, 0, 0))
        for x in items:
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(x.get("added") or 0))
            meta = "  ·  ".join(v for v in (x.get("channel"), fmt_ts(x["duration"]) if x.get("duration") else "",
                                            x.get("site"), when) if v)
            it = QtWidgets.QListWidgetItem(f"{x.get('title') or x['url']}\n{meta}")
            it.setData(Qt.ItemDataRole.UserRole, x["url"])
            it.setToolTip(x["url"])
            pix = None
            if x.get("thumb"):
                pm = QtGui.QPixmap(str(history_dir() / "thumbnails" / x["thumb"]))
                if not pm.isNull():
                    pix = QtGui.QPixmap(128, 72)
                    pix.fill(QtGui.QColor(0, 0, 0, 0))
                    pp = QtGui.QPainter(pix)
                    pp.setRenderHint(SMOOTH)
                    sc = pm.scaled(128, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    pp.drawPixmap((128 - sc.width()) // 2, (72 - sc.height()) // 2, sc)
                    pp.end()
            it.setIcon(QtGui.QIcon(pix or blank))
            it.setSizeHint(QtCore.QSize(0, 82))
            self.list.addItem(it)
        self.count.setText(f"{len(items)} links")
        if self.list.count():
            self.list.setCurrentRow(0)
        self._filter(self.search.text())

    def _filter(self, text):
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower() and t not in str(it.data(Qt.ItemDataRole.UserRole)).lower())

    def _sel(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None and not it.isHidden() else None

    def _open(self):
        url = self._sel()
        if url:
            self.chosen = url
            self.accept()

    def _copy(self):
        url = self._sel()
        if url:
            QtWidgets.QApplication.clipboard().setText(url)

    def _remove(self):
        url = self._sel()
        if url:
            row = self.list.currentRow()
            history_remove(url)
            self._fill()
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    def _clear(self):
        if QtWidgets.QMessageBox.question(self, "Clear history", "Remove all links from the history?") \
                == QtWidgets.QMessageBox.StandardButton.Yes:
            history_clear()
            self._fill()


class SubsEditor(QtWidgets.QDialog):
    """Read and edit the subtitles: change text and times, add / delete lines, shift everything, copy, save.
    Click a line to jump there in the preview. Changes are used right away (preview + export)."""
    changed = Signal(object)    # list of (start, end, text)
    jump = Signal(float)

    COLS = ("Start", "End", "Text")

    def __init__(self, parent, cues, title, playhead):
        super().__init__(parent)
        self.setWindowTitle(f"Subtitles – {title}")
        self.resize(760, 680)
        self.cues = [list(c) for c in cues]
        self._title = title
        self._playhead = playhead
        self._busy = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(label("Subtitles", "h1"))
        head.addStretch(1)
        self.count = label("", "muted")
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(head)
        lay.addWidget(label("Double-click a cell to edit it. “ / ” in the text = new line. Click a line to jump there.",
                            "hint"))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search the text …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setObjectName("lines")
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        hh = self.table.horizontalHeader()      # fixed widths: "resize to contents" re-measures every row on each edit
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        tw = QtGui.QFontMetrics(self.table.font()).horizontalAdvance("0:00:00.00") + 26
        self.table.setColumnWidth(0, tw)
        self.table.setColumnWidth(1, tw)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                                   | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.itemChanged.connect(self._edited)
        self.table.cellClicked.connect(lambda r, _c: self._jump(r))
        lay.addWidget(self.table, 1)
        r1 = QtWidgets.QHBoxLayout()
        r1.setSpacing(6)
        for txt, fn, title, text in (
                ("+ Line here", self._add, "New line", "Adds a 2-second line at the preview position."),
                ("Delete", self._delete, "Delete", "Removes the selected lines."),
                ("Start = playhead", lambda: self._set_time(0), "Start = playhead",
                 "The selected line starts at the current preview position."),
                ("End = playhead", lambda: self._set_time(1), "End = playhead",
                 "The selected line ends at the current preview position.")):
            b = tip(QtWidgets.QPushButton(txt), title, text)
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            r1.addWidget(b)
        r1.addStretch(1)
        r1.addWidget(label("Shift all", "field"))
        self.shift = QtWidgets.QLineEdit()
        self.shift.setObjectName("time")
        self.shift.setFixedWidth(84)
        self.shift.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shift.setPlaceholderText("± s")
        self.shift.returnPressed.connect(lambda: self._shift())
        tip(self.shift, "Shift all", "Moves every line earlier (−) or later (+) – for subtitles that are out of sync.")
        b = QtWidgets.QPushButton("Apply")
        b.setObjectName("chip")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(self._shift)
        r1.addWidget(self.shift)
        r1.addWidget(b)
        lay.addLayout(r1)
        bot = QtWidgets.QHBoxLayout()
        b1 = tip(QtWidgets.QPushButton("Copy text"), "Copy text", "Copies all lines (without times).")
        b1.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(
            "\n".join(t.replace("\n", " ") for _s, _e, t in self.cues)))
        b2 = tip(QtWidgets.QPushButton("Save .srt …"), "Save .srt", "Saves all subtitles (with your changes).")
        b2.clicked.connect(self._save)
        close = QtWidgets.QPushButton("Close")
        close.setObjectName("primary")
        close.setMinimumWidth(110)
        close.clicked.connect(self.accept)
        bot.addWidget(b1)
        bot.addWidget(b2)
        bot.addStretch(1)
        bot.addWidget(close)
        lay.addLayout(bot)
        self._fill()

    @staticmethod
    def _cells(c):
        return fmt_tc(c[0]), fmt_tc(c[1]), c[2].replace("\n", " / ")

    def _fill(self, select=None):
        """Builds the whole table (only when lines are added or change their order)."""
        self._busy = True
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setRowCount(len(self.cues))
        for r, c in enumerate(self.cues):
            for col, val in enumerate(self._cells(c)):
                it = QtWidgets.QTableWidgetItem(val)
                if col < 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, it)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._busy = False
        self.count.setText(f"{len(self.cues)} lines")
        self._filter(self.search.text())
        if select is not None and 0 <= select < len(self.cues):
            self.table.selectRow(select)
            self.table.scrollToItem(self.table.item(select, 0))

    def _update_row(self, r):
        """Only this row's cells – fast, whatever the number of lines."""
        self._busy = True
        self.table.blockSignals(True)
        for col, val in enumerate(self._cells(self.cues[r])):
            it = self.table.item(r, col)
            if it is not None and it.text() != val:
                it.setText(val)
        self.table.blockSignals(False)
        self._busy = False

    def _send(self):
        self.changed.emit([(round(a, 3), round(b, 3), t) for a, b, t in self.cues if b > a and t.strip()])

    def _emit_one(self, c):
        """A line was changed: update its row – the table is only rebuilt if the order changed."""
        r = self.cues.index(c)
        self.cues.sort(key=lambda x: x[0])
        r2 = self.cues.index(c)
        if r2 == r:
            self._update_row(r)
        else:
            self._fill(r2)
        self._send()

    def _filter(self, text):
        t = text.strip().lower()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 2)
            self.table.setRowHidden(r, bool(t) and (it is None or t not in it.text().lower()))

    def _emit(self, select=None):
        self.cues.sort(key=lambda c: c[0])
        self._fill(select)
        self._send()

    def _edited(self, it):
        if self._busy:
            return
        r, col = it.row(), it.column()
        if r >= len(self.cues):
            return
        c = self.cues[r]
        if col < 2:
            try:
                v = parse_time(it.text())
                if v is None:
                    raise ValueError
            except ValueError:
                QtWidgets.QApplication.beep()
                self._update_row(r)
                return
            c[col] = v
            if c[1] <= c[0]:
                c[1] = c[0] + 0.5 if col == 0 else c[1]
                c[0] = min(c[0], c[1] - 0.1)
        else:
            c[2] = "\n".join(x.strip() for x in it.text().split(" / ")).strip()
        self._emit_one(c)

    def _rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _jump(self, r):
        if 0 <= r < len(self.cues) and not self._busy:
            self.jump.emit(float(self.cues[r][0]))

    def _add(self):
        t = self._playhead() or 0.0
        c = [round(t, 3), round(t + 2.0, 3), "…"]
        nxt = [x[0] for x in self.cues if x[0] > t]
        if nxt:
            c[1] = max(c[0] + 0.3, min(c[1], min(nxt)))
        self.cues.append(c)
        self._emit(self.cues.index(c))
        r = self.cues.index(c)
        self.table.editItem(self.table.item(r, 2))

    def _delete(self):
        rows = self._rows()
        if not rows:
            return
        self.cues = [c for i, c in enumerate(self.cues) if i not in rows]
        self._busy = True
        self.table.blockSignals(True)
        for r in reversed(rows):
            self.table.removeRow(r)
        self.table.blockSignals(False)
        self._busy = False
        self.count.setText(f"{len(self.cues)} lines")
        if self.cues:
            self.table.selectRow(min(rows[0], len(self.cues) - 1))
        self._send()

    def _set_time(self, col):
        rows = self._rows()
        t = self._playhead()
        if not rows or t is None:
            return
        c = self.cues[rows[0]]
        c[col] = round(t, 3)
        if c[1] <= c[0]:
            if col == 0:
                c[1] = c[0] + 1.0
            else:
                c[0] = max(0.0, c[1] - 1.0)
        self._emit_one(c)

    def _shift(self):
        try:
            d = float(self.shift.text().replace(",", ".").replace("s", "").strip() or 0)
        except ValueError:
            set_state(self.shift, "error")
            return
        set_state(self.shift, "")
        if not d:
            return
        self.cues = [[max(0.0, a + d), max(0.05, b + d), t] for a, b, t in self.cues]
        self.shift.clear()
        self._emit()

    def _save(self):
        out = self.parent().outdir.text().strip() or str(Path.home() / "Downloads")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save subtitles",
                                                        str(Path(out) / (safe_name(self._title) + ".srt")),
                                                        "Subtitles (*.srt)")
        if path:
            write_srt([tuple(c) for c in self.cues], path)


class ChaptersDialog(QtWidgets.QDialog):
    """Pick chapters -> they become clips."""

    def __init__(self, parent, chapters):
        super().__init__(parent)
        self.setWindowTitle("Chapters")
        self.resize(520, 520)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Chapters → clips", "h1"))
        lay.addWidget(label("Ticked chapters become clips (with the chapter name). You can still change every "
                            "clip afterwards.", "hint"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("lines")
        for i, (s, e, title) in enumerate(chapters):
            it = QtWidgets.QListWidgetItem(f"{i + 1:>2}   {title or 'Chapter ' + str(i + 1)}     {fmt_tf(s)} – {fmt_tf(e)}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        for txt, st in (("All", Qt.CheckState.Checked), ("None", Qt.CheckState.Unchecked)):
            b = QtWidgets.QPushButton(txt)
            b.setObjectName("ghost")
            b.clicked.connect(lambda _=False, st=st: [self.list.item(i).setCheckState(st) for i in range(self.list.count())])
            row.addWidget(b)
        row.addStretch(1)
        self.seg_join = Segmented([("separate", "One file each"), ("join", "Join")])
        self.seg_join.setFixedWidth(230)
        self.seg_join.set_tips({"separate": ("One file each", "Every chapter becomes its own file, named after the "
                                                              "chapter."),
                                "join": ("Join", "The ticked chapters one after another in one file.")})
        row.addWidget(self.seg_join)
        lay.addLayout(row)
        bot = QtWidgets.QHBoxLayout()
        bot.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("Use as clips")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        bot.addWidget(cancel)
        bot.addWidget(ok)
        lay.addLayout(bot)
        self.chapters = chapters

    def picked(self):
        return [self.chapters[i] for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class ClipRow(QtWidgets.QWidget):
    """One row of the clip list: number, times, length, play / up / down / delete."""
    action = Signal(str, int)   # 'play' | 'up' | 'down' | 'del', row

    def __init__(self, idx, s, e, n, parent=None, name=""):
        super().__init__(parent)
        self.setObjectName("cliprow")
        self.name = name
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 4, 2)
        lay.setSpacing(8)
        self.no = label(f"{idx + 1}", "clipno")
        self.no.setFixedWidth(18)
        self.times = label("", "cliptime")
        self.length = label("", "muted")
        lay.addWidget(self.no)
        lay.addWidget(self.times)
        lay.addWidget(self.length)
        lay.addStretch(1)
        for key, txt, title, text in (("play", "▶", "Play this clip", "Plays it in the preview."),
                                      ("up", "↑", "Move up", "Clips are joined in this order."),
                                      ("down", "↓", "Move down", "Clips are joined in this order."),
                                      ("del", "✕", "Remove clip", "")):
            b = tip(QtWidgets.QPushButton(txt), title, text)
            b.setObjectName("mini")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k, self.idx))
            lay.addWidget(b)
            setattr(self, f"btn_{key}", b)
        self.set_clip(idx, s, e, n)

    def set_clip(self, idx, s, e, n):
        self.idx = idx
        self.no.setText(f"{idx + 1}")
        self.times.setText(f"{fmt_tf(s)} – {fmt_tf(e)}")
        ln = f"{e - s:.2f} s".replace(".00 s", " s") if e - s < 60 else fmt_tf(e - s)
        nm = self.name if len(self.name) <= 22 else self.name[:21] + "…"
        self.length.setText(ln + (f"  ·  {nm}" if nm else ""))
        self.length.setToolTip(tip_html(self.name) if self.name else "")
        self.btn_up.setEnabled(idx > 0)
        self.btn_down.setEnabled(idx < n - 1)


def card():
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 20)
    lay.setSpacing(12)
    return f, lay


def label(text, name=None):
    lbl = QtWidgets.QLabel(text)
    if name:
        lbl.setObjectName(name)
    return lbl


def section(text):
    return label(text.upper(), "section")


class PathLabel(QtWidgets.QLabel):
    """A folder path in one line, shortened in the middle when there is no room (full path on hover)."""
    def __init__(self):
        super().__init__()
        self.setObjectName("muted")
        self._full = ""
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def set_path(self, text):
        self._full = str(text)
        tip(self, "Folder", self._full)
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(40, self.width())))


def round_pixmap(path, size, dpr=1.0):
    """Picture file -> round QPixmap (None if it can't be read)."""
    img = QtGui.QImage(str(path)) if path else QtGui.QImage()
    if img.isNull():
        return None
    px = int(round(size * dpr))
    img = img.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QtGui.QPixmap(px, px)
    out.fill(Qt.GlobalColor.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(AA)
    path_ = QtGui.QPainterPath()
    path_.addEllipse(0, 0, px, px)
    p.setClipPath(path_)
    p.drawImage(QtCore.QRectF(0, 0, px, px), img,
                QtCore.QRectF((img.width() - px) / 2, (img.height() - px) / 2, px, px))
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


class AccountChip(QtWidgets.QAbstractButton):
    """Profile picture + name of the signed-in YouTube account. Small in the window header, big in the Settings."""
    def __init__(self, big=False):
        super().__init__()
        self.big = big
        self.c = theme_colors(DEFAULT_THEME, DEFAULT_ACCENT)
        self.acc = {}
        self._pix = None
        self.av = 40 if big else 26
        self.busy = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVisible(False)

    def set_colors(self, c):
        self.c = c
        self.update()

    def set_account(self, acc):
        """acc: {} = not signed in (hidden); {'signed_in': True, 'name', 'handle', 'email', 'picture'}"""
        self.acc = dict(acc or {})
        self._pix = round_pixmap(self.acc.get("picture"), self.av, self.devicePixelRatioF()) if self.acc else None
        self.setVisible(bool(self.acc))
        name, sub = self._lines()
        tipt = f"Signed in to YouTube as {name}" + (f" ({sub})" if sub else "") if self.acc.get("name") else \
            "Signed in to YouTube"
        more = " – click to look up name and picture again." if self.big else " – click for the Settings."
        self.setToolTip(tip_html("YouTube account", tipt + more))
        self.updateGeometry()
        self.update()

    def _lines(self):
        a = self.acc
        name = a.get("name") or "Signed in"
        sub = "  ·  ".join(x for x in (a.get("handle"), a.get("email")) if x)
        if self.big and self.busy:
            sub = "Looking up name and picture …"
        elif not a.get("name") and not sub:
            sub = "Name and picture not found – click to try again" if self.big else ""
        return name, sub

    def sizeHint(self):
        fm = self.fontMetrics()
        name, sub = self._lines()
        if self.big:
            bf = QtGui.QFont(self.font())
            bf.setBold(True)
            w = max(QtGui.QFontMetrics(bf).horizontalAdvance(name), fm.horizontalAdvance(sub))
            return QtCore.QSize(min(4 + self.av + 12 + w + 14, 380), self.av + 8)
        return QtCore.QSize(3 + self.av + 8 + min(fm.horizontalAdvance(name), 170) + 10 + 4, 32)

    def enterEvent(self, e):
        super().enterEvent(e)
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.update()

    def paintEvent(self, _e):
        c = self.c
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        hover = self.underMouse()
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(c["panel2"]))
            p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16 if not self.big else 24, 16 if not self.big else 24)
        x0 = 4 if self.big else 3
        y0 = (self.height() - self.av) / 2
        r = QtCore.QRectF(x0, y0, self.av, self.av)
        name, sub = self._lines()
        if self._pix is not None:
            p.drawPixmap(r.topLeft(), self._pix)
        else:                                   # no picture: first letter on the accent color, like Google does
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(c["accent"]))
            p.drawEllipse(r)
            f = QtGui.QFont(self.font())
            f.setBold(True)
            f.setPixelSize(int(self.av * 0.46))
            p.setFont(f)
            p.setPen(QtGui.QColor(c["on_accent"]))
            letter = (self.acc.get("name") or "").strip()[:1].upper() or "✓"
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, letter)
        p.setPen(Qt.PenStyle.NoPen)                 # small "signed in" dot
        if not self.big:
            p.setBrush(QtGui.QColor(c["panel"]))
            p.drawEllipse(QtCore.QPointF(r.right() - 3, r.bottom() - 3), 5, 5)
            p.setBrush(QtGui.QColor("#3ddc84"))
            p.drawEllipse(QtCore.QPointF(r.right() - 3, r.bottom() - 3), 3.2, 3.2)
        tx = r.right() + (12 if self.big else 8)
        tw = self.width() - tx - (12 if self.big else 10)
        fm = self.fontMetrics()
        if self.big:
            bf = QtGui.QFont(self.font())
            bf.setBold(True)
            p.setFont(bf)
            p.setPen(QtGui.QColor(c["text"]))
            p.drawText(QtCore.QRectF(tx, y0, tw, self.av / 2), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       QtGui.QFontMetrics(bf).elidedText(name, Qt.TextElideMode.ElideRight, int(tw)))
            p.setFont(self.font())
            p.setPen(QtGui.QColor(c["muted"]))
            p.drawText(QtCore.QRectF(tx, y0 + self.av / 2, tw, self.av / 2),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(sub, Qt.TextElideMode.ElideRight, int(tw)))
        else:
            p.setFont(self.font())
            p.setPen(QtGui.QColor(c["text"] if hover else c["muted"]))
            p.drawText(QtCore.QRectF(tx, 0, tw, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, int(tw)))
        p.end()


class MuteButton(QtWidgets.QAbstractButton):
    """Speaker next to the preview volume: 0, 1 or 2 sound waves for the level, crossed out when silent."""
    def __init__(self):
        super().__init__()
        self.c = theme_colors(DEFAULT_THEME, DEFAULT_ACCENT)
        self.level = 80
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_colors(self, c):
        self.c = c
        self.update()

    def set_level(self, v):
        self.level = int(v)
        self.update()

    def enterEvent(self, e):
        super().enterEvent(e)
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.update()

    def paintEvent(self, _e):
        c = self.c
        p = QtGui.QPainter(self)
        p.setRenderHint(AA)
        hover = self.underMouse() and self.isEnabled()
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(c["panel2"]))
            p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        col = QtGui.QColor(c["text"] if hover else c["muted"])
        if not self.isEnabled():
            col = QtGui.QColor(c["border"])
        p.translate(self.width() / 2 - 9, self.height() / 2 - 8)     # icon box 18 × 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        body = QtGui.QPainterPath()
        body.addRoundedRect(QtCore.QRectF(0.5, 5.2, 4.2, 5.6), 1.2, 1.2)
        body.addPolygon(QtGui.QPolygonF([QtCore.QPointF(3.6, 5.4), QtCore.QPointF(8.6, 1.4),
                                         QtCore.QPointF(8.6, 14.6), QtCore.QPointF(3.6, 10.6)]))
        p.drawPath(body.simplified())
        pen = QtGui.QPen(col, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.level <= 0:
            pen.setColor(QtGui.QColor(c["accent"]) if self.isEnabled() else col)
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(11.6, 5.2), QtCore.QPointF(17.2, 10.8))
            p.drawLine(QtCore.QPointF(17.2, 5.2), QtCore.QPointF(11.6, 10.8))
        else:
            p.setPen(pen)
            waves = [3.4] + ([6.6] if self.level >= 50 else [])
            for r in waves:
                p.drawArc(QtCore.QRectF(8.6 - r, 8 - r, 2 * r, 2 * r), -50 * 16, 100 * 16)
        p.end()


def _dir_buttons(on_open, on_change, on_default):
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(6)
    b_open = tip(QtWidgets.QPushButton("Open folder"), "Open folder", "Shows the folder in Explorer.")
    b_change = tip(QtWidgets.QPushButton("Change …"), "Change folder",
                   "Pick another folder – what is saved now moves along.")
    b_def = tip(QtWidgets.QPushButton("Default"), "Default folder", "Back to the app's own folder (moves along).")
    b_def.setObjectName("ghost")
    for b, fn in ((b_open, on_open), (b_change, on_change), (b_def, on_default)):
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(fn)
        row.addWidget(b)
    return row, b_def


class FolderDragChip(QtWidgets.QLabel):
    """A folder you can drag (e.g. onto Chrome's extensions page in developer mode = loads it)."""
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.setText(f"📁  {self.path.name}")
        self.setObjectName("dragchip")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._p0 = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._p0 = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._p0 is None or (e.position().toPoint() - self._p0).manhattanLength() < 6:
            return
        self._p0 = None
        md = QtCore.QMimeData()
        md.setUrls([QtCore.QUrl.fromLocalFile(str(self.path))])
        drag = QtGui.QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(self.grab())
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.LinkAction)

    def mouseReleaseEvent(self, e):
        self._p0 = None


class ExtSetupDialog(QtWidgets.QDialog):
    """Once per PC: add the app's sign-in extension to Chrome (developer mode -> Load unpacked or drag the folder
    onto the page). Closes by itself as soon as the extension reports in."""
    WITHOUT = 2                     # result: sign in without the extension (own window) instead
    def __init__(self, main, b):
        super().__init__(main)
        self.main, self.b = main, b
        self.setWindowTitle("Sign-in extension")
        self.setModal(True)
        self.setMinimumWidth(720)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinimumSize)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        name = b["name"]
        lay.addWidget(label(f"Add the sign-in extension to {name} – once", "h1"))
        intro = label(f"With it, “Sign in” opens a normal tab in your {name} with your Google accounts. It hands only "
                      "the YouTube login to this app on this PC and keeps it up to date. "
                      f"{name} doesn't let programs add extensions themselves – so it's three steps, once.", "muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        tipl = label("Tip: a second Google account is the safest choice – YouTube can limit accounts that are used "
                     "with download tools.", "hint")
        tipl.setWordWrap(True)
        lay.addWidget(tipl)

        def step(n, text, *widgets):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            num = label(str(n), "stepnum")
            num.setFixedSize(24, 24)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(6)
            lab = label(text)
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.RichText)
            col.addWidget(lab)
            if widgets:
                wr = QtWidgets.QHBoxLayout()
                wr.setSpacing(6)
                for w in widgets:
                    wr.addWidget(w)
                wr.addStretch(1)
                col.addLayout(wr)
            row.addLayout(col, 1)
            lay.addLayout(row)

        # which profile (Chrome's "Who's using Chrome?")
        self.profiles = browser_profiles(b)
        self.cb_prof = QtWidgets.QComboBox()
        pick = self.main._login_profile()
        for i, pr in enumerate(self.profiles):
            self.cb_prof.addItem(pr["name"] + (f"  –  {pr['who']}" if pr["who"] and pr["who"] != pr["name"] else "")
                                 + ("  (extension added)" if pr["ext"] else ""), pr["dir"])
            if pr["dir"] == pick:
                self.cb_prof.setCurrentIndex(i)
        page = extensions_page(b)
        b_open = QtWidgets.QPushButton(f"Open {name}")
        b_open.clicked.connect(self._open_page)
        how = f"then press <b>Ctrl+V</b> and <b>Enter</b> in the address bar (<b>{page.rstrip('/')}</b> is copied)."
        if len(self.profiles) > 1:
            step(1, f"Pick your YouTube profile and open {name}, {how}", self.cb_prof, b_open)
        else:
            step(1, f"Open {name}, {how}", b_open)
        step(2, "Switch on <b>Developer mode</b> (top right on that page).")
        self.path = QtWidgets.QLineEdit(str(EXT_DIR))
        self.path.setReadOnly(True)
        self.path.setMinimumWidth(300)
        b_copy = QtWidgets.QPushButton("Copy path")
        b_copy.clicked.connect(self._copy)
        step(3, "Drag this folder onto the extensions page – or <b>Load unpacked</b> → paste the path → "
                "<b>Select folder</b>:",
             FolderDragChip(EXT_DIR), self.path, b_copy)
        self.state = label("Waiting for the extension …", "muted")
        self.state.setWordWrap(True)
        lay.addSpacing(4)
        lay.addWidget(self.state)
        bot = QtWidgets.QHBoxLayout()
        nox = tip(QtWidgets.QPushButton("Sign in without the extension instead …"), "Without the extension",
                  f"Opens {name} in an own, empty window – sign in there with e-mail and password. Nothing to add, "
                  "but your accounts aren't there and the login isn't kept up to date.")
        nox.setObjectName("ghost")
        nox.clicked.connect(lambda: self.done(self.WITHOUT))
        bot.addWidget(nox)
        bot.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        bot.addWidget(cancel)
        lay.addLayout(bot)
        self._t0 = time.time()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._check)
        self.timer.start()

    def profile(self):
        return self.cb_prof.currentData() if self.cb_prof.count() else None

    def _open_page(self):
        page = extensions_page(self.b).rstrip("/")
        QtWidgets.QApplication.clipboard().setText(page)
        prof = self.profile()
        if prof:
            self.main.cfg["chrome_profile"] = prof
        ok = open_in_browser(self.b, None, prof)
        self.state.setText((f"{self.b['name']} opened – " if ok else "") + f"“{page}” is copied: Ctrl+V and Enter in "
                           "the address bar. Waiting for the extension …")

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(str(EXT_DIR))
        self.state.setText("Path copied – paste it into the folder field of “Load unpacked”.")

    def _check(self):
        if self.main._ext_outdated() and not self.main._ext_connected(20):
            self.state.setText("The extension is already there but got an update: on the extensions page click ↻ "
                               "(reload) at “YouTube Downloader – Login”.")
            set_state(self.state, "")
        if self.main.login_bridge.seen >= self._t0 - 1 or self.main._ext_connected(20):
            self.timer.stop()
            prof = self.profile()
            if prof:
                self.main.cfg["chrome_profile"] = prof
            signed = not self.main._pending_signin
            self.state.setText("✓ Extension added – " + ("signed in." if signed else "opening the YouTube sign-in …"))
            set_state(self.state, "ok")
            QtCore.QTimer.singleShot(900, self.accept)


class RepairDialog(QtWidgets.QDialog):
    """Checks the app and puts right what is broken. Settings, history and login stay."""
    class _Sig(QtCore.QObject):
        step = QtCore.Signal(str, str, str, bool)
        done = QtCore.Signal()

    ITEMS = [("app", "App file"), ("ytdlp", "yt-dlp"), ("tools", "FFmpeg"), ("ext", "Sign-in extension"),
             ("login", "YouTube login"), ("settings", "Settings"), ("left", "Leftover files")]
    ICON = {"ok": "✓", "fixed": "✓", "warn": "⚠", "error": "✕", "run": "…"}

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Repair")
        self.setModal(True)
        self.setMinimumWidth(620)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Repair", "h1"))
        intro = label("Checks the app and puts right what is broken: loads the app file again if it's damaged, puts "
                      "yt-dlp in again, checks FFmpeg, restores the sign-in extension and the files. Your settings, "
                      "history and YouTube login stay.", "muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.rows = {}
        for i, (key, name) in enumerate(self.ITEMS):
            grid.addWidget(label(name, "field"), i, 0, Qt.AlignmentFlag.AlignTop)
            st = label("–", "muted")
            st.setWordWrap(True)
            grid.addWidget(st, i, 1)
            self.rows[key] = st
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addSpacing(6)
        bot = QtWidgets.QHBoxLayout()
        self.btn_restart = QtWidgets.QPushButton("Restart app")
        self.btn_restart.setObjectName("primary")
        self.btn_restart.setVisible(False)
        self.btn_restart.clicked.connect(self.main._restart)
        self.btn_go = QtWidgets.QPushButton("Repair now")
        self.btn_go.setObjectName("primary")
        self.btn_go.setMinimumWidth(130)
        self.btn_go.clicked.connect(self._go)
        close = QtWidgets.QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.reject)
        bot.addWidget(close)
        bot.addStretch(1)
        bot.addWidget(self.btn_restart)
        bot.addWidget(self.btn_go)
        lay.addLayout(bot)
        self.sig = self._Sig()
        self.sig.step.connect(self._show)
        self.sig.done.connect(self._finished)
        self.restart = False

    def _show(self, key, state, text, restart):
        lab = self.rows[key]
        lab.setText(f"{self.ICON.get(state, '')}  {text}")
        c = self.main.c if hasattr(self.main, "c") else theme_colors(self.main.theme, self.main.accent)
        col = {"fixed": "#3ddc84", "warn": c["warn"], "error": c["err"]}.get(state)
        lab.setStyleSheet(f"color: {col}; font-weight: 600;" if col else "")
        self.restart = self.restart or restart

    def _finished(self):
        self.main._save_settings()                 # (a set-aside settings file is written again right away)
        self.btn_go.setText("Repair again")
        self.btn_go.setEnabled(True)
        self.btn_restart.setVisible(self.restart)
        self.main._login_state_changed()

    def _go(self):
        if self.main.busy:
            QtWidgets.QMessageBox.information(self, "Repair", "Wait until the download is finished.")
            return
        self.btn_go.setEnabled(False)
        self.btn_restart.setVisible(False)
        self.restart = False
        for key, _ in self.ITEMS:
            self._show(key, "", "–", False)
        m = self.main
        script = Path(__file__).resolve()
        steps = [
            ("app", lambda: repair_app_file(script, m.emit)),
            ("ytdlp", lambda: ("fixed", "put in again (newest version)", True) if update_ytdlp(m.emit, force=True)
             else ("error", "couldn't put it in again – see Details at the bottom of the window", False)),
            ("tools", lambda: repair_tools(m.ffmpeg, m.ffprobe)),
            ("ext", repair_extension),
            ("login", repair_login),
            ("settings", repair_settings),
            ("left", lambda: repair_leftovers(signing_in=m._signin is not None)),
        ]

        def work():
            for key, fn in steps:
                self.sig.step.emit(key, "run", "checking …", False)
                try:
                    state, text, restart = fn()
                except Exception as ex:  # noqa: BLE001
                    state, text, restart = "error", clean_error(ex)[:200], False
                self.sig.step.emit(key, state, text, restart)
            m.emit("log", "Repair finished.")
            self.sig.done.emit()
        threading.Thread(target=work, daemon=True).start()


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent, theme, accent, tips_on, apply, apply_tips, auto_pv=True, apply_pv=None,
                 pv_mode="download", apply_mode=None):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(840)
        self._apply, self._apply_tips = apply, apply_tips
        self.theme, self.accent = theme, accent
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)
        outer.addWidget(label("Settings", "h1"))
        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(36)
        outer.addLayout(cols, 1)
        lay = QtWidgets.QVBoxLayout()
        lay.setSpacing(12)
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(12)
        cols.addLayout(lay, 1)
        cols.addLayout(right, 1)

        lay.addWidget(section("Theme"))
        self.seg = Segmented([(k, k) for k in THEMES])
        self.seg.set_tips({k: (k, ITEM_HELP.get(k, "")) for k in THEMES})
        self.seg.set_value(theme)
        self.seg.changed.connect(self._theme)
        lay.addWidget(self.seg)
        lay.addSpacing(4)
        lay.addWidget(section("Accent color"))
        grid = QtWidgets.QHBoxLayout()
        grid.setSpacing(8)
        self.group = QtWidgets.QButtonGroup(self)
        self.swatches = {}
        for name, col in ACCENTS:
            b = QtWidgets.QPushButton()
            b.setObjectName("swatch")
            b.setCheckable(True)
            tip(b, name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"background: {col};")
            b.clicked.connect(lambda _=False, c=col: self._accent(c))
            self.group.addButton(b)
            grid.addWidget(b)
            self.swatches[col.lower()] = b
        grid.addStretch(1)
        lay.addLayout(grid)
        row = QtWidgets.QHBoxLayout()
        self.btn_custom = tip(QtWidgets.QPushButton("Custom color …"), "Custom color",
                              "Pick any color for buttons, highlights and the progress bar.")
        self.btn_custom.clicked.connect(self._custom)
        self.lbl_hex = label("", "muted")
        row.addWidget(self.btn_custom)
        row.addWidget(self.lbl_hex)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(4)
        lay.addWidget(section("Help"))
        self.cb_tips = QtWidgets.QCheckBox("Show help when hovering over buttons and options")
        self.cb_tips.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_tips, "Hover help", "Short explanations like this one. Turn off once you know the app.")
        self.cb_tips.setChecked(tips_on)
        self.cb_tips.toggled.connect(self._apply_tips)
        lay.addWidget(self.cb_tips)
        lay.addSpacing(4)
        lay.addWidget(section("History"))
        self.cb_hist = QtWidgets.QCheckBox("Remember the links I paste (with a small picture)")
        self.cb_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_hist, "History", "Saved only on this PC. Open it with the History button next to the link field.")
        self.cb_hist.setChecked(bool(parent.cfg.get("history", True)))
        self.cb_hist.toggled.connect(self._hist_toggled)
        lay.addWidget(self.cb_hist)
        pr = QtWidgets.QHBoxLayout()
        pr.setSpacing(8)
        self.lbl_hist_dir = PathLabel()
        self.lbl_hist_info = label("", "muted")
        pr.addWidget(self.lbl_hist_dir, 1)
        pr.addWidget(self.lbl_hist_info)
        lay.addLayout(pr)
        hr, self.btn_hist_def = _dir_buttons(lambda: self._open_dir("history"), lambda: self._change_dir("history"),
                                             lambda: self._default_dir("history"))
        hr.addStretch(1)
        self.btn_hist_clear = tip(QtWidgets.QPushButton("Clear history"), "Clear history", "Removes all saved links.")
        self.btn_hist_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_clear.clicked.connect(self._hist_clear)
        hr.addWidget(self.btn_hist_clear)
        lay.addLayout(hr)
        lay.addWidget(section("AI upscalers"))
        self._build_ai_rows(lay)
        lay.addStretch(1)

        right.addWidget(section("Video preview"))
        self.seg_pv = Segmented([("download", "Download small copy"), ("stream", "Stream from YouTube")])
        self.seg_pv.set_tips({
            "download": ("Download small copy (standard)", "Downloads a small copy first (360p, less for long videos) "
                                                           "and plays that – the most reliable way. Jumping and frame "
                                                           "steps are snappy and it works offline once loaded."),
            "stream": ("Stream from YouTube", "Plays the video straight from YouTube – starts at once, nothing is "
                                              "saved, no ads. Needs internet while you work. If YouTube refuses the "
                                              "stream on your PC, a small copy is downloaded instead.")})
        self.seg_pv.set_value(pv_mode if pv_mode in ("stream", "download") else "download")
        if apply_mode:
            self.seg_pv.changed.connect(apply_mode)
        right.addWidget(self.seg_pv)
        self.cb_pv = QtWidgets.QCheckBox(f"Load the preview by itself (downloads: videos up to "
                                         f"{PREVIEW_AUTO_MAX // 60} min)")
        self.cb_pv.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_pv, "Automatic preview", "Starts the preview as soon as you paste a link. Off: click the "
                                             "picture to start it.")
        self.cb_pv.setChecked(auto_pv)
        if apply_pv:
            self.cb_pv.toggled.connect(apply_pv)
        right.addWidget(self.cb_pv)
        self.cb_keep = QtWidgets.QCheckBox("Keep the downloaded small copies (open at once next time)")
        self.cb_keep.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_keep, "Keep small copies", "Off: the small preview copies are deleted when you close the app. "
                                               "On: they stay in the folder below and are used again when you open "
                                               "the same video (also from the history).")
        self.cb_keep.setChecked(parent._keep_pv())
        self.cb_keep.toggled.connect(self._keep_toggled)
        right.addWidget(self.cb_keep)
        pr = QtWidgets.QHBoxLayout()
        pr.setSpacing(8)
        self.lbl_pv_dir = PathLabel()
        self.lbl_pv_info = label("", "muted")
        pr.addWidget(self.lbl_pv_dir, 1)
        pr.addWidget(self.lbl_pv_info)
        right.addLayout(pr)
        vr, self.btn_pv_def = _dir_buttons(lambda: self._open_dir("preview"), lambda: self._change_dir("preview"),
                                           lambda: self._default_dir("preview"))
        vr.addStretch(1)
        self.btn_pv_clear = tip(QtWidgets.QPushButton("Delete copies"), "Delete copies",
                                "Deletes the small preview copies in this folder now (not your downloads).")
        self.btn_pv_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pv_clear.clicked.connect(self._pv_clear)
        vr.addWidget(self.btn_pv_clear)
        right.addLayout(vr)
        if not PLAYER_OK:
            self.seg_pv.setEnabled(False)
            self.cb_pv.setEnabled(False)
            self.cb_pv.setText("Video preview not available (run the setup again)")
        right.addSpacing(4)
        right.addWidget(section("YouTube login"))
        self.acc_card = AccountChip(big=True)
        self.acc_card.set_colors(theme_colors(self.main.theme, self.main.accent))
        self.acc_card.clicked.connect(lambda: self.main._refresh_account(force=True))
        right.addWidget(self.acc_card, 0, Qt.AlignmentFlag.AlignLeft)
        self.lbl_login = label("", "muted")
        self.lbl_login.setWordWrap(True)
        right.addWidget(self.lbl_login)
        lr = QtWidgets.QHBoxLayout()
        lr.setSpacing(6)
        self.btn_login = QtWidgets.QPushButton()
        self.btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login.clicked.connect(self._login_clicked)
        self.btn_cookies = tip(QtWidgets.QPushButton("Load cookies.txt …"), "Load cookies.txt",
                               "Alternative if Google doesn't let you sign in here: export your YouTube cookies from "
                               "your browser (e.g. with the extension “Get cookies.txt LOCALLY”) and load the file.")
        self.btn_cookies.setObjectName("ghost")
        self.btn_cookies.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cookies.clicked.connect(self._load_cookies)
        self.btn_login2 = QtWidgets.QPushButton("Sign in without extension …")
        self.btn_login2.setObjectName("ghost")
        self.btn_login2.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login2.clicked.connect(lambda: (self.main._sign_in_window(), self.show_login_state()))
        lr.addWidget(self.btn_login)
        lr.addWidget(self.btn_login2)
        lr.addStretch(1)
        right.addLayout(lr)
        lr2 = QtWidgets.QHBoxLayout()
        lr2.setContentsMargins(0, 0, 0, 0)
        lr2.addWidget(self.btn_cookies)
        lr2.addStretch(1)
        right.addLayout(lr2)
        self.lbl_login_tip = label("Tip: a second Google account is the safest choice – YouTube can limit accounts "
                                   "that are used with download tools.", "hint")
        self.lbl_login_tip.setWordWrap(True)
        right.addWidget(self.lbl_login_tip)
        right.addStretch(1)
        self.show_login_state()
        self.refresh_dirs()

        bot = QtWidgets.QHBoxLayout()
        reset = tip(QtWidgets.QPushButton("Reset to default"), "Reset to default",
                    "Dark theme, red accent and hover help on.")
        reset.setObjectName("ghost")
        reset.clicked.connect(self._reset)
        repair = tip(QtWidgets.QPushButton("Repair …"), "Repair",
                     "Checks the app and puts right what is broken (app file, yt-dlp, FFmpeg, sign-in extension, "
                     "login, settings). Your settings, history and login stay.")
        repair.setObjectName("ghost")
        repair.clicked.connect(lambda: RepairDialog(self.main).exec())
        done = QtWidgets.QPushButton("Done")
        done.setObjectName("primary")
        done.setMinimumWidth(110)
        done.clicked.connect(self.accept)
        bot.addWidget(reset)
        bot.addWidget(repair)
        bot.addStretch(1)
        bot.addWidget(done)
        outer.addLayout(bot)
        self._sync()

    def show_login_state(self):
        self._show_login_state()
        QtCore.QTimer.singleShot(0, self._fit)

    def _show_login_state(self):
        st = login_state()
        pending = bool(self.main._pending_signin)
        si = self.main._signin
        b = self.main._login_browser()
        bname = b["name"] if b else "Chrome"
        self.btn_cookies.setEnabled(not pending and si is None)
        self.btn_login2.setVisible(not st["signed_in"] and not pending and si is None)
        self.btn_cookies.setVisible(not st["signed_in"] or pending or si is not None)
        self.lbl_login_tip.setVisible(not st["signed_in"])
        if si is not None:
            self.acc_card.set_account({})
            self.lbl_login.setText(f"Sign in to YouTube in the {si.b['name']} window that opened. As soon as YouTube "
                                   "shows you as signed in, the app takes the login and closes that window.")
            self.btn_login.setText("Cancel sign-in")
            self.btn_login.setEnabled(True)
            tip(self.btn_login, "Cancel sign-in", f"Closes the {si.b['name']} sign-in window.")
            return
        if pending:
            self.acc_card.set_account({})
            self.lbl_login.setText(f"Sign in to YouTube in the {bname} tab that opened, or pick your account there. "
                                   "As soon as YouTube shows you as signed in, the app takes the login by itself.")
            self.btn_login.setText("Cancel sign-in")
            self.btn_login.setEnabled(True)
            tip(self.btn_login, "Cancel sign-in", "Stops waiting for the login.")
            return
        self.acc_card.set_account(self.main.account if st["signed_in"] else {})
        if st["signed_in"]:
            when = time.strftime("%d.%m.%Y", time.localtime(st["since"])) if st["since"] else ""
            who = "" if self.main.account.get("name") else " to YouTube"
            since = f" since {when}" if when else ""
            if self.main.cfg.get("login_via") == "chrome":
                if self.main._ext_outdated():
                    keep = ("– the extension got an update: click ↻ (reload) at “YouTube Downloader – Login” on "
                            f"{extensions_page(b)} or restart {bname}")
                elif self.main._ext_connected(600):
                    keep = "keeps the login up to date"
                else:
                    keep = "keeps the login up to date while it is open"
                self.lbl_login.setText(f"✓ Signed in{who}{since} – used for every download. {bname} {keep}.")
            else:
                self.lbl_login.setText(f"✓ Signed in{who}{since}. Used for every download – needed for "
                                       "age-restricted or members-only videos.")
            self.btn_login.setText("Sign out")
            self.btn_login.setEnabled(True)
            tip(self.btn_login, "Sign out", "Removes the YouTube login from this app.")
        else:
            self.lbl_login.setText("Not signed in. Only needed for age-restricted or members-only videos – "
                                   "your login stays on this PC.")
            self.btn_login.setText(f"Sign in with {bname} …")
            self.btn_login.setEnabled(b is not None)
            wb = self.main._window_browser()
            self.btn_login2.setEnabled(wb is not None)
            tip(self.btn_login2, "Sign in without the extension",
                f"Opens {wb['name'] if wb else 'your browser'} in an own, empty window – sign in there with "
                "e-mail and password. Nothing to install, but your accounts aren't there and the login isn't kept up "
                "to date: when it expires, sign in again. The window and its data are deleted right after the "
                "sign-in.")
            tip(self.btn_login, "Sign in", f"Opens a new tab in your {bname} with Google's account choice – your "
                                           "accounts are there as usual. The app's small extension hands the YouTube "
                                           "login to the app (only YouTube, only to this PC). The first time it shows "
                                           "you how to add the extension. Note: YouTube can limit accounts that are "
                                           "used with download tools – a second account is the safe choice.")

    class _AiSig(QtCore.QObject):
        latest = QtCore.Signal(str, object)
        prog = QtCore.Signal(str, float)
        done = QtCore.Signal(str, str)
        mprog = QtCore.Signal(str, float)
        mdone = QtCore.Signal(str, str)

    def _build_ai_rows(self, lay):
        """One line per upscaler: version, newer one on GitHub? Install / Update / Remove."""
        self.ai_sig = self._AiSig()
        self.ai_sig.latest.connect(self._ai_latest_in)
        self.ai_sig.prog.connect(lambda k, v: self._ai_show(k, f"downloading … {v:.0f} %"))
        self.ai_sig.done.connect(self._ai_done)
        self.ai_rows, self.ai_latest, self.ai_busy = {}, {}, set()
        self.mf_rows = {}
        self.ai_sig.mprog.connect(lambda k, v: self._mf_show(k, f"downloading … {v:.0f} %"))
        self.ai_sig.mdone.connect(self._mf_done)
        for key, e in ENGINES.items():
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            name = tip(label(e["name"], "field"), e["name"], f"AI upscaler for {e['about']}.")
            st = label("", "hint")
            act = QtWidgets.QPushButton("")
            act.setObjectName("ghost")
            act.setCursor(Qt.CursorShape.PointingHandCursor)
            act.clicked.connect(lambda _=False, k=key: self._ai_install(k))
            rem = QtWidgets.QPushButton("Remove")
            rem.setObjectName("ghost")
            rem.setCursor(Qt.CursorShape.PointingHandCursor)
            rem.clicked.connect(lambda _=False, k=key: self._ai_remove(k))
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(name)
            col.addWidget(st)
            st.setWordWrap(False)
            st.setMinimumWidth(10)
            st.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
            row.addLayout(col, 1)
            row.addWidget(act)
            row.addWidget(rem)
            lay.addLayout(row)
            self.ai_rows[key] = (st, act, rem)
            self._ai_show(key)
        for key, f in AI_FILES.items():
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            lab = next((k for k, v in AI_MODELS.items() if v[2] == key), f["name"])
            name = tip(label(lab, "field"), f["name"], AI_MODELS.get(lab, ("", "", "", ""))[3]
                       + " Runs with Real-ESRGAN.")
            st = label("", "hint")
            st.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(name)
            col.addWidget(st)
            act = QtWidgets.QPushButton("Download")
            act.setObjectName("ghost")
            act.setCursor(Qt.CursorShape.PointingHandCursor)
            act.clicked.connect(lambda _=False, k=key: self._mf_install(k))
            rem = QtWidgets.QPushButton("Remove")
            rem.setObjectName("ghost")
            rem.setCursor(Qt.CursorShape.PointingHandCursor)
            rem.clicked.connect(lambda _=False, k=key: self._mf_remove(k))
            row.addLayout(col, 1)
            row.addWidget(act)
            row.addWidget(rem)
            lay.addLayout(row)
            self.mf_rows[key] = (st, act, rem)
            self._mf_show(key)

        def check():
            for k in ENGINES:
                try:
                    self.ai_sig.latest.emit(k, engine_latest(k))
                except Exception:  # noqa: BLE001 - offline / GitHub limit: just no update info
                    self.ai_sig.latest.emit(k, None)
        threading.Thread(target=check, daemon=True).start()

    def _ai_latest_in(self, key, rel):
        self.ai_latest[key] = rel if rel else False
        self._ai_show(key)

    def _ai_show(self, key, busy_text=None):
        st, act, rem = self.ai_rows[key]
        e = ENGINES[key]
        ver = engine_version(key)
        rel = self.ai_latest.get(key)
        set_state(act, "")
        if busy_text:
            st.setText(f"{busy_text}")
            act.setVisible(False)
            rem.setVisible(False)
            return
        if not ver:
            st.setText(f"not installed · ≈ {e['mb']} MB")
            st.setToolTip("Downloaded by itself the first time it's used – or now with Install.")
            act.setText("Install")
            act.setVisible(True)
            rem.setVisible(False)
            return
        rem.setVisible(True)
        if rel is None:
            st.setText(f"version {ver} · checking …")
            act.setVisible(False)
        elif rel and _ver(rel["version"]) > _ver(ver):
            st.setText(f"version {ver}")
            act.setText(f"Update → {rel['version']}")
            set_state(act, "new")
            act.setVisible(True)
        else:
            st.setText(f"version {ver} · " + ("up to date ✓" if rel else "no update check (offline?)"))
            act.setVisible(False)

    def _ai_install(self, key):
        if key in self.ai_busy:
            return
        self.ai_busy.add(key)
        rel = self.ai_latest.get(key) or None
        self._ai_show(key, "downloading …")

        def work():
            try:
                install_engine(key, rel, progress=lambda v: self.ai_sig.prog.emit(key, v))
                self.ai_sig.done.emit(key, "")
            except Exception as ex:  # noqa: BLE001
                self.ai_sig.done.emit(key, clean_error(ex))
        threading.Thread(target=work, daemon=True).start()

    def _ai_done(self, key, err):
        self.ai_busy.discard(key)
        if err:
            self.main._on_log(f"✕ {ENGINES[key]['name']}: {err}")
            self._ai_show(key)
            self.ai_rows[key][0].setText("✕ " + err.splitlines()[0][:160])
        else:
            self.main._on_log(f"✓ {ENGINES[key]['name']} {engine_version(key)} installed.")
            self._ai_show(key)
        self.main._ai_changed()

    def _mf_show(self, key, busy=None):
        st, act, rem = self.mf_rows[key]
        f = AI_FILES[key]
        if busy:
            st.setText(busy)
            act.setVisible(False)
            rem.setVisible(False)
            return
        ok = ai_file_ok(key)
        st.setText(f"model · {f['mb']} MB on disk" if ok else f"not downloaded · ≈ {f['mb']} MB")
        act.setVisible(not ok)
        rem.setVisible(ok)

    def _mf_install(self, key):
        self._mf_show(key, "downloading …")

        def work():
            try:
                install_ai_file(key, progress=lambda v: self.ai_sig.mprog.emit(key, v))
                self.ai_sig.mdone.emit(key, "")
            except Exception as ex:  # noqa: BLE001
                self.ai_sig.mdone.emit(key, clean_error(ex))
        threading.Thread(target=work, daemon=True).start()

    def _mf_done(self, key, err):
        self._mf_show(key)
        if err:
            self.mf_rows[key][0].setText("✕ " + err.splitlines()[0][:160])
            self.main._on_log(f"✕ {AI_FILES[key]['name']}: {err}")
        self.main._ai_changed()

    def _mf_remove(self, key):
        remove_ai_file(key)
        self._mf_show(key)
        self.main._ai_changed()

    def _ai_remove(self, key):
        remove_engine(key)
        self._ai_show(key)
        self.main._ai_changed()

    def _fit(self):
        if self.isVisible():
            self.layout().activate()
            need = self.sizeHint().height()
            if need > self.height():
                self.resize(self.width(), need)

    def _login_clicked(self):
        if self.main._pending_signin or self.main._signin is not None:
            self.main._cancel_sign_in()
        elif login_state()["signed_in"]:
            self.main._sign_out()
        else:
            self.main._sign_in()
        self.show_login_state()

    def _load_cookies(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load cookies.txt", str(Path.home() / "Downloads"),
                                                        "Cookies (*.txt);;All files (*.*)")
        if not path:
            return
        try:
            import_cookie_file(path)
        except Exception as ex:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "YouTube login", clean_error(ex))
            return
        apply_login()
        self.main.cfg["login_via"] = "file"
        self.main._pending_signin = 0.0
        self.main._on_log("✓ YouTube login loaded from a cookies file.")
        self.main._refresh_account(force=True)
        self.show_login_state()

    def _hist_toggled(self, on):
        self.main.cfg["history"] = bool(on)
        save_cfg(self.main.cfg)

    def _hist_clear(self):
        if QtWidgets.QMessageBox.question(self, "Clear history", "Remove all links from the history?") \
                == QtWidgets.QMessageBox.StandardButton.Yes:
            history_clear()
            self.refresh_dirs()

    # ---- folders of the history and the small preview copies
    def refresh_dirs(self):
        hs = history_stats()
        self.lbl_hist_dir.set_path(history_dir())
        self.lbl_hist_info.setText(f"{hs['links']} link{'s' if hs['links'] != 1 else ''} · {fmt_bytes(hs['bytes'])}")
        self.btn_hist_def.setVisible(bool(self.main.cfg.get("history_dir")))
        self.btn_hist_clear.setEnabled(hs["links"] > 0)
        ps = preview_stats()
        self.lbl_pv_dir.set_path(preview_dir())
        self.lbl_pv_info.setText(f"{ps['files']} cop{'ies' if ps['files'] != 1 else 'y'} · {fmt_bytes(ps['bytes'])}")
        self.btn_pv_def.setVisible(bool(self.main.cfg.get("preview_dir")))
        self.btn_pv_clear.setEnabled(ps["files"] > 0)

    def _open_dir(self, key):
        d = history_dir() if key == "history" else preview_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            return QtWidgets.QMessageBox.warning(self, "Folder", clean_error(ex))
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(d)))

    def _change_dir(self, key):
        cur = history_dir() if key == "history" else preview_dir()
        what = "the history" if key == "history" else "the small preview copies"
        path = QtWidgets.QFileDialog.getExistingDirectory(self, f"Folder for {what}",
                                                          str(cur if cur.exists() else Path.home()))
        if path:
            self.main._set_dir(key, path)
            self.refresh_dirs()

    def _default_dir(self, key):
        self.main._set_dir(key, None)
        self.refresh_dirs()

    def _keep_toggled(self, on):
        self.main.cfg["keep_previews"] = bool(on)
        save_cfg(self.main.cfg)

    def _pv_clear(self):
        st = preview_stats()
        if QtWidgets.QMessageBox.question(
                self, "Delete copies", f"Delete the {st['files']} small preview cop{'ies' if st['files'] != 1 else 'y'} "
                                       f"({fmt_bytes(st['bytes'])})?") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        n = preview_cleanup(False)
        left = preview_stats()["files"]
        self.main._pv_cache = {k: v for k, v in self.main._pv_cache.items() if Path(v).exists()}
        self.main._on_log(f"Deleted {n} preview cop{'ies' if n != 1 else 'y'}."
                          + (f" {left} still open in the player – deleted when the app closes." if left else ""))
        self.refresh_dirs()

    def _reset(self):
        self.seg.set_value(DEFAULT_THEME, animate=True)
        self._theme(DEFAULT_THEME)
        self._accent(DEFAULT_ACCENT)
        self.cb_tips.setChecked(True)

    def _sync(self):
        b = self.swatches.get(self.accent.lower())
        self.group.setExclusive(False)
        for s in self.swatches.values():
            s.setChecked(False)
        self.group.setExclusive(True)
        if b:
            b.setChecked(True)
        self.lbl_hex.setText(self.accent.upper())

    def _theme(self, t):
        self.theme = t
        self._apply(self.theme, self.accent)
        set_dark_titlebar(self, THEMES[t]["dark"])

    def _accent(self, col):
        self.accent = col
        self._sync()
        self._apply(self.theme, self.accent)

    def _custom(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.accent), self, "Accent color")
        if col.isValid():
            self._accent(col.name())

    def showEvent(self, e):
        super().showEvent(e)
        set_dark_titlebar(self, THEMES.get(self.theme, THEMES[DEFAULT_THEME])["dark"])


class Bridge(QtCore.QObject):
    sig = Signal(str, object)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.busy = False
        self.update_done = threading.Event()
        self.last_clip = ""
        self.last_files: list[str] = []
        self.info: dict = {}
        self.info_url = ""
        self._req = 0
        self.bridge = Bridge()
        self.bridge.sig.connect(self._dispatch)
        self.player = None
        self.audio_out = None
        self._pv_state = ""            # "", "offer", "loading", "error", "ready"
        self._pv_cache: dict[str, str] = {}
        for key in ("history", "preview"):
            d = self.cfg.get(f"{key}_dir")
            PATHS[key] = Path(d) if d else DEFAULT_PATHS[key]
        history_migrate()
        preview_cleanup(self._keep_pv())
        if not self.cfg.get("upscaler_removed"):
            threading.Thread(target=remove_old_upscaler, daemon=True).start()
            self.cfg["upscaler_removed"] = True
        self._clip_stop = None
        self._seek_target = None
        self._pos_hint = (None, 0.0)     # last position we jumped to + when (for fast frame steps)
        self.aplayer = None              # sound of a streamed preview, when picture and sound are separate files
        self.a_out2 = None
        self._proxy = None
        self._pv_kind = ""               # "stream", "copy" or "file"
        self._stream_failed: set[str] = set()
        self.clips: list[Clip] = []
        self.cur = 0
        self._loading_clip = False
        self.box = None                  # crop box (fractions of the frame) of the clip being edited
        self.vol_pts: list[list[float]] = []   # volume curve [time, gain] on the source timeline
        self.sub_cues: list = []
        self.sub_items: list = []
        self._sub_req = 0
        self.lines_dlg = None
        self._login_noted = False
        self._pending_signin = 0.0          # time "Sign in" was clicked (0 = not waiting for the Chrome login)
        self._signin = None                  # sign-in without the extension (own browser window) while it runs
        self._resetting = False
        self._out_vol = None
        apply_login()
        self.cfg.pop("browser", None)
        if SIGNIN_DIR.exists():              # the own browser profile of the old sign-in (up to 2.9.1) is not used any more
            shutil.rmtree(SIGNIN_DIR, ignore_errors=True)
        try:
            write_extension()
        except OSError:
            pass
        self.login_bridge = LoginBridge(self._bridge_wants, lambda ev: self.emit("bridge", ev))
        self.login_bridge.start()
        st = self.cfg.get("sub_style") if isinstance(self.cfg.get("sub_style"), dict) else {}
        self.sub_style = {**SUB_STYLE, **{k: v for k, v in st.items() if k in SUB_STYLE}}
        if self.sub_style.get("pos"):
            self.sub_style["pos"] = tuple(self.sub_style["pos"])
        self._font_files: dict[str, str] = {}
        self._load_app_fonts()
        self._app_update = None
        self.account = {}

        refresh_path()
        self.ffmpeg = find_tool("ffmpeg")
        self.ffprobe = find_tool("ffprobe")
        self.deno = find_tool("deno")

        self.setWindowTitle(APP)
        icon = Path(__file__).with_name("icon.ico")
        if icon.exists():
            self.setWindowIcon(QtGui.QIcon(str(icon)))
        self.setAcceptDrops(True)
        self.tip_filter = TipFilter(self)
        self.tip_filter.enabled = bool(self.cfg.get("tooltips", True))
        QtWidgets.QApplication.instance().installEventFilter(self.tip_filter)
        self._build()
        self._apply_sub_style_ui()
        self.theme = self.cfg.get("theme") if self.cfg.get("theme") in THEMES else DEFAULT_THEME
        if not self.cfg.get("accent_v28") and str(self.cfg.get("accent", "")).lower() == "#c4f240":
            self.cfg["accent"] = DEFAULT_ACCENT          # the old default (lime) -> the new one (red)
        self.cfg["accent_v28"] = True
        if not self.cfg.get("preview_v29"):
            self.cfg["preview_mode"] = "download"       # new standard: small copy; streaming is an option
        self.cfg["preview_v29"] = True
        self.accent = self.cfg.get("accent") or DEFAULT_ACCENT
        self.apply_theme(self.theme, self.accent, save=False)
        self._load_settings()

        self._fetch_timer = QtCore.QTimer(self)
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.setInterval(600)
        self._fetch_timer.timeout.connect(self._start_fetch)
        self._resume_check = None
        self._seek_timer = QtCore.QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(35)
        self._seek_timer.timeout.connect(self._do_seek)

        QtWidgets.QApplication.instance().applicationStateChanged.connect(
            lambda st: self._grab_clipboard() if st == Qt.ApplicationState.ApplicationActive else None)
        QtCore.QTimer.singleShot(400, self._grab_clipboard)
        self._check_tools()
        self._maybe_update()
        QtCore.QTimer.singleShot(1200, self._refresh_account)
        # new app version: look on every start and every 2 hours – the Update button lights up when there is one
        QtCore.QTimer.singleShot(3000, lambda: self._check_app_update(manual=False))
        self._app_upd_timer = QtCore.QTimer(self)
        self._app_upd_timer.setInterval(2 * 3600 * 1000)
        self._app_upd_timer.timeout.connect(lambda: (self._check_app_update(manual=False), self._check_ytdlp()))
        QtCore.QTimer.singleShot(4500, self._check_ytdlp)
        self._app_upd_timer.start()

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QtWidgets.QVBoxLayout(root)
        v.setContentsMargins(26, 22, 26, 14)
        v.setSpacing(16)

        head = QtWidgets.QHBoxLayout()
        tl = QtWidgets.QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(label(APP, "h1"))
        tl.addWidget(label("Paste a link or open your own video  ·  video, audio or GIF", "sub"))
        head.addLayout(tl)
        head.addStretch(1)
        self.btn_settings = tip(QtWidgets.QPushButton("⚙  Settings"), "Settings",
                                "Theme, accent color and this hover help (can be turned off there).")
        self.btn_settings.setObjectName("ghost")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self._settings)
        self.chip_account = AccountChip()
        self.chip_account.clicked.connect(self._settings)
        head.addWidget(self.chip_account, 0, Qt.AlignmentFlag.AlignTop)
        head.addSpacing(4)
        head.addWidget(self.btn_settings, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        v.addLayout(body, 1)

        # ---- left: source + clip
        left, L = card()
        L.addWidget(section("Source"))
        row = QtWidgets.QHBoxLayout()
        self.url = QtWidgets.QLineEdit()
        self.url.setObjectName("url")
        self.url.setPlaceholderText("Paste a YouTube link … or drop a video file here")
        self.url.setClearButtonEnabled(True)
        self.url.textChanged.connect(self._url_changed)
        tip(self.url, "Source", "A YouTube link (videos, Shorts, music) or the path of a file on your PC. "
                                "You can also drop a file or link onto the window.")
        self.btn_paste = tip(QtWidgets.QPushButton("Paste"), "Paste",
                             "Insert the link from the clipboard. YouTube links you copy are picked up automatically.")
        self.btn_paste.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_paste.clicked.connect(self._paste)
        self.btn_file = QtWidgets.QPushButton("Open file …")
        self.btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.btn_file, "Open file", "Use a video or audio file from your computer – cut it, "
                                        "convert it, extract the audio or make a GIF.")
        self.btn_file.clicked.connect(self._open_file)
        self.btn_hist = tip(QtWidgets.QPushButton("History"), "History",
                            "All links you pasted before, with a small picture. Double-click one to open it again.")
        self.btn_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist.clicked.connect(self._show_history)
        row.addWidget(self.url, 1)
        row.addWidget(self.btn_paste)
        row.addWidget(self.btn_file)
        row.addWidget(self.btn_hist)
        L.addLayout(row)
        self.thumb = Thumb()
        self.thumb.clicked.connect(self._thumb_clicked)
        self.vview = VideoView(self.thumb)
        self.canvas = self.vview.video
        if self.canvas is not None:
            self.canvas.boxChanged.connect(self._box_changed)
            self.canvas.subMoved.connect(self._sub_moved)
        L.addWidget(self.vview)
        self.transport = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(self.transport)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(6)
        trl = QtWidgets.QHBoxLayout()
        trl.setSpacing(6)
        self.btn_prev_f = tip(QtWidgets.QPushButton("◀|"), "Previous frame", "← or ,   (Shift + ← = 1 second back)")
        self.btn_play = tip(QtWidgets.QPushButton("▶"), "Play / pause", "Space")
        self.btn_next_f = tip(QtWidgets.QPushButton("|▶"), "Next frame", "→ or .   (Shift + → = 1 second ahead)")
        for b_, fn in ((self.btn_prev_f, lambda: self._step(-1)), (self.btn_play, self._toggle_play),
                       (self.btn_next_f, lambda: self._step(1))):
            b_.setObjectName("transport")
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
            b_.setAutoRepeat(b_ is not self.btn_play)
            b_.setAutoRepeatDelay(350)
            b_.setAutoRepeatInterval(60)
            b_.clicked.connect(fn)
        self.ed_tc = tip(QtWidgets.QLineEdit("0:00.00"), "Timecode",
                         "Position of the preview. Type a time and press Enter to jump there: 1:31.24 · 1:02:03 · "
                         "90s (a plain number like 10 means minute 10).")
        self.ed_tc.setObjectName("time")
        self.ed_tc.setFixedWidth(92)
        self.ed_tc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ed_tc.returnPressed.connect(self._tc_entered)
        self.ed_tc.textEdited.connect(lambda _t: set_state(self.ed_tc, ""))
        self.lbl_ptime = label("/ 0:00", "ptime")
        self.seek = tip(QtWidgets.QSlider(Qt.Orientation.Horizontal), "Position", "Drag to move through the video.")
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(lambda v: self._seek_to(v / 1000))
        self.vol = tip(QtWidgets.QSlider(Qt.Orientation.Horizontal), "Volume",
                       "How loud the preview plays (only for listening – the download keeps its sound; change that "
                       "in the Volume tab).")
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(64)
        self.vol.valueChanged.connect(self._on_volume)
        self.btn_mute = tip(MuteButton(), "Mute", "Click to mute the preview, click again to get the volume back "
                                                  "it had before (key M).")
        self.btn_mute.clicked.connect(self._toggle_mute)
        self._vol_restore = 80              # level the speaker button goes back to after muting
        self._vol_settle = QtCore.QTimer(self)
        self._vol_settle.setSingleShot(True)
        self._vol_settle.setInterval(700)
        self._vol_settle.timeout.connect(self._remember_vol)
        trl.addWidget(self.btn_prev_f)
        trl.addWidget(self.btn_play)
        trl.addWidget(self.btn_next_f)
        trl.addSpacing(4)
        trl.addWidget(self.ed_tc)
        trl.addWidget(self.lbl_ptime)
        trl.addSpacing(4)
        trl.addWidget(self.seek, 1)
        trl.addSpacing(2)
        trl.addWidget(self.btn_mute)
        trl.addWidget(self.vol)
        tv.addLayout(trl)
        tr2 = QtWidgets.QHBoxLayout()
        tr2.setSpacing(6)
        self.btn_play_clip = tip(QtWidgets.QPushButton("▷ Play clip"), "Play the clip",
                                 "Plays from the clip start to the clip end.")
        self.btn_set_in = tip(QtWidgets.QPushButton("⇤ Start here"), "Start here",
                              "Sets the clip start to the current position (key I).")
        self.btn_set_out = tip(QtWidgets.QPushButton("End here ⇥"), "End here",
                               "Sets the clip end to the current position (key O).")
        for b_, fn in ((self.btn_play_clip, self._play_clip), (self.btn_set_in, self._set_in),
                       (self.btn_set_out, self._set_out)):
            b_.setObjectName("chip")
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
            b_.clicked.connect(fn)
            tr2.addWidget(b_)
        self.btn_still = tip(QtWidgets.QPushButton("↓ Save frame"), "Save frame",
                             "Saves the frame you see as a PNG in full quality (not the preview quality) – with the "
                             "crop from the Frame tab.")
        self.btn_still.setObjectName("chip")
        self.btn_still.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_still.clicked.connect(self._save_still)
        tr2.addSpacing(6)
        tr2.addWidget(self.btn_still)
        self.ai_factor, self.ai_px, self.ai_model = None, None, DEFAULT_AI_MODEL
        self.btn_ai = QtWidgets.QPushButton("✦ AI upscale: off")
        self.btn_ai.setObjectName("chip")
        self.btn_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai.clicked.connect(self._ai_menu)
        tr2.addWidget(self.btn_ai)
        tr2.addStretch(1)
        self.lbl_pv_src = QtWidgets.QPushButton("")
        self.lbl_pv_src.setObjectName("srcChip")
        self.lbl_pv_src.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_pv_src.clicked.connect(self._pv_src_menu)
        tr2.addWidget(self.lbl_pv_src)
        tv.addLayout(tr2)
        self.transport.hide()
        L.addWidget(self.transport)
        self.vtitle = label("", "vtitle")
        self.vtitle.setWordWrap(True)
        self.vmeta = label("", "muted")
        self.vmeta.setWordWrap(True)
        L.addWidget(self.vtitle)
        mr = QtWidgets.QHBoxLayout()
        mr.addWidget(self.vmeta, 1)
        self.btn_thumb = QtWidgets.QPushButton("↓  Save thumbnail")
        self.btn_thumb.setObjectName("chip")
        self.btn_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.btn_thumb, "Save thumbnail", "Saves the video thumbnail as a JPG in the output folder. "
                                              "For your own files: the frame at the clip start.")
        self.btn_thumb.clicked.connect(self._save_thumb_now)
        self.btn_thumb.hide()
        mr.addWidget(self.btn_thumb, 0, Qt.AlignmentFlag.AlignTop)
        L.addLayout(mr)
        L.addSpacing(4)

        ch = QtWidgets.QHBoxLayout()
        ch.addWidget(section("Clip"))
        ch.addSpacing(8)
        self.lbl_len = label("", "len")
        ch.addWidget(self.lbl_len)
        ch.addStretch(1)
        self.btn_chapters = tip(QtWidgets.QPushButton("Chapters"), "Chapters",
                                "The video has chapters – pick some and they become clips (one file per chapter, "
                                "named after it, or joined).")
        self.btn_chapters.setObjectName("chip")
        self.btn_chapters.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_chapters.clicked.connect(self._chapters)
        self.btn_chapters.hide()
        ch.addWidget(self.btn_chapters)
        ch.addSpacing(6)
        self.seg_clips = Segmented([("one", "One clip"), ("multi", "Several clips")])
        self.seg_clips.set_tips({"one": ("One clip", "Cut one part of the video (or take all of it)."),
                                 "multi": ("Several clips", "Pick as many parts as you like – save them as one "
                                                            "file (one after another) or each as its own file. "
                                                            "Works for video, audio and GIF.")})
        self.seg_clips.setFixedWidth(236)
        self.seg_clips.changed.connect(self._clip_mode_changed)
        ch.addWidget(self.seg_clips)
        L.addLayout(ch)
        self.slider = RangeSlider()
        self.slider.changed.connect(self._slider_changed)
        self.slider.dragged.connect(self._on_handle_dragged)
        tip(self.slider, "Clip range", "Drag the handles to set start and end, or drag the middle to move the "
                                       "whole range.")
        self.slider.hide()
        L.addWidget(self.slider)
        tr = QtWidgets.QHBoxLayout()
        tr.setSpacing(8)
        self.t_from = QtWidgets.QLineEdit()
        self.t_to = QtWidgets.QLineEdit()
        tip(self.t_from, "From", "Start time. 10 = minute 10, 1:30, 1:02:30 or 90s. Empty = from the beginning.")
        tip(self.t_to, "To", "End time, same formats. Empty = to the end.")
        for w, ph in ((self.t_from, "start"), (self.t_to, "end")):
            w.setObjectName("time")
            w.setPlaceholderText(ph)
            w.setFixedWidth(96)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.textEdited.connect(self._times_edited)
            w.editingFinished.connect(self._times_committed)
        tr.addWidget(label("from", "field"))
        tr.addWidget(self.t_from)
        tr.addWidget(label("to", "field"))
        tr.addWidget(self.t_to)
        tr.addSpacing(6)
        self.chips = []
        for txt, secs in (("5 s", 5), ("10 s", 10), ("30 s", 30), ("Whole", None)):
            b = QtWidgets.QPushButton(txt)
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            tip(b, txt, f"Makes the clip {secs} seconds long, starting at 'from'." if secs
                else "Clears the times and uses the whole video.")
            b.clicked.connect(lambda _=False, s=secs: self._chip(s))
            tr.addWidget(b)
            self.chips.append(b)
        tr.addStretch(1)
        L.addLayout(tr)
        self.clip_hint = label("", "hint")
        self.clip_hint.setWordWrap(True)
        L.addWidget(self.clip_hint)
        L.addStretch(1)
        body.addWidget(left, 11)

        # ---- right: output
        right, R = card()
        self.multi_box = QtWidgets.QWidget()
        mb = QtWidgets.QVBoxLayout(self.multi_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(8)
        mh = QtWidgets.QHBoxLayout()
        mh.addWidget(section("Clips"))
        mh.addSpacing(6)
        self.lbl_clips = label("", "muted")
        mh.addWidget(self.lbl_clips)
        mh.addStretch(1)
        self.seg_join = Segmented([("join", "Join"), ("separate", "One file each")])
        self.seg_join.setFixedWidth(220)
        mh.addWidget(self.seg_join)
        mh.addSpacing(6)
        self.btn_add_clip = tip(QtWidgets.QPushButton("+ Add clip"), "Add clip",
                                "Adds a new clip at the player position (or after the last clip). "
                                "Then drag the handles or type the times.")
        self.btn_add_clip.setObjectName("chip")
        self.btn_add_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_clip.clicked.connect(self._add_clip)
        mh.addWidget(self.btn_add_clip)
        mb.addLayout(mh)
        self.clip_list = tip(QtWidgets.QListWidget(), "Clips", "Click a clip to edit it with the timeline on the "
                                                               "left. Joined clips play in this order.")
        self.clip_list.setObjectName("clips")
        self.clip_list.setFixedHeight(118)
        self.clip_list.currentRowChanged.connect(self._select_clip)
        mb.addWidget(self.clip_list)
        self.seg_join.set_tips({"join": ("Join", "All clips one after another in a single file – frame-accurate, "
                                                 "with tiny fades at the cuts so the sound doesn't click."),
                                "separate": ("One file per clip", "Every clip becomes its own file "
                                                                  "(name_01, name_02 … if you give a name).")})
        self.seg_join.changed.connect(lambda _k: (self._update_clip_info(), self._set_button_text()))
        mb.addSpacing(4)
        self.multi_box.hide()
        R.addWidget(self.multi_box)
        R.addWidget(section("Format"))
        self.seg = Segmented([("mp4", "Video"), ("mp3", "Audio"), ("gif", "GIF")])
        self.seg.set_tips({"mp4": ("Video", "MP4 (H.264 / H.265) or ProRes MOV for editing."),
                           "mp3": ("Audio", "Only the sound: MP3, WAV or M4A."),
                           "gif": ("GIF", f"Short looping animation without sound – up to {GIF_MAX} s.")})
        self.seg.changed.connect(self._mode_changed)
        R.addWidget(self.seg)
        R.addSpacing(2)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._page_mp4())
        self.stack.addWidget(self._page_audio())
        self.stack.addWidget(self._page_gif())
        self.tabs = TabBar([("out", "Output"), ("frame", "Frame"), ("volume", "Volume"), ("subs", "Subtitles")])
        self.tabs.set_tips({
            "out": ("Output", "Codec, quality and size of the file."),
            "frame": ("Frame", "Crop to 9:16, 1:1 … (for TikTok, Reels, Shorts) and the output size."),
            "volume": ("Volume", "Make parts of the clip quieter or louder – fades, ducking, muting."),
            "subs": ("Subtitles", "Load the video's subtitles (or your own file), read them, burn them into the "
                                  "picture or save them as .srt.")})
        self.tabs.changed.connect(self._tab_changed)
        R.addWidget(self.tabs)
        self.tabstack = QtWidgets.QStackedWidget()
        outw = QtWidgets.QWidget()
        ov = QtWidgets.QVBoxLayout(outw)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(10)
        ov.addWidget(self.stack)
        sr = QtWidgets.QHBoxLayout()
        sr.setSpacing(12)
        h_speed = ("Makes the saved file faster or slower (picture and sound; the voice keeps its pitch). The preview "
                   "plays at this speed too.")
        self.lbl_speed = self._field("Speed", "Speed", h_speed)
        self.cb_speed = self._combo(SPEEDS, "Speed", h_speed)
        self.cb_speed.setCurrentText(DEFAULT_SPEED)
        self.cb_speed.currentTextChanged.connect(self._speed_changed)
        sr.addWidget(self.lbl_speed)
        sr.addWidget(self.cb_speed, 1)
        ov.addLayout(sr)
        self.tabstack.addWidget(outw)
        # one label column for the format pages and the Speed row (so the boxes line up)
        grids = [self.stack.widget(i).layout() for i in range(self.stack.count())]
        col = self.lbl_speed.sizeHint().width()
        for g_ in grids:
            if isinstance(g_, QtWidgets.QGridLayout):
                for r_ in range(g_.rowCount()):
                    it = g_.itemAtPosition(r_, 0)
                    if it is not None and it.widget() is not None and g_.getItemPosition(g_.indexOf(it.widget()))[3] == 1:
                        col = max(col, it.widget().sizeHint().width())
        for g_ in grids:
            if isinstance(g_, QtWidgets.QGridLayout):
                g_.setColumnMinimumWidth(0, col)
        self.lbl_speed.setFixedWidth(col)
        self.tabstack.addWidget(self._page_frame())
        self.tabstack.addWidget(self._page_volume())
        self.tabstack.addWidget(self._page_subs())
        R.addWidget(self.tabstack)
        R.addSpacing(2)
        R.addWidget(section("Save as"))
        nr = QtWidgets.QHBoxLayout()
        self.name = QtWidgets.QLineEdit()
        self.name.setClearButtonEnabled(True)
        tip(self.name, "File name", "Leave empty to use the video title. An existing file is never "
                                    "overwritten – a number is added instead.")
        self.lbl_ext = tip(label(".mp4", "ext"), "File type", "Set by the format you picked.")
        nr.addWidget(self.name, 1)
        nr.addWidget(self.lbl_ext)
        R.addLayout(nr)
        fr = QtWidgets.QHBoxLayout()
        self.outdir = QtWidgets.QLineEdit()
        tip(self.outdir, "Output folder", "Where the files are saved.")
        self.btn_browse = tip(QtWidgets.QPushButton("Browse …"), "Browse", "Choose the output folder.")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self._pick_dir)
        fr.addWidget(self.outdir, 1)
        fr.addWidget(self.btn_browse)
        R.addLayout(fr)
        self.cb_thumb = QtWidgets.QCheckBox("Also save the thumbnail as JPG")
        self.cb_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_thumb, "Thumbnail as JPG", "Saved next to the file with the same name. "
                                               "For your own videos: the frame at the clip start.")
        R.addWidget(self.cb_thumb)
        R.addStretch(1)
        self.btn = QtWidgets.QPushButton("Download MP4")
        self.btn.setObjectName("primary")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.start)
        R.addWidget(self.btn)
        self.pb = QtWidgets.QProgressBar()
        self.pb.setTextVisible(False)
        self.pb.setRange(0, 1000)
        self.pb.setValue(0)
        self._pb_anim = QtCore.QPropertyAnimation(self.pb, b"value", self)
        self._pb_anim.setDuration(260)
        self._pb_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        R.addWidget(self.pb)
        self.status = label("Ready.", "status")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(34)
        self.status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        R.addWidget(self.status)
        body.addWidget(right, 9)

        # ---- details + footer
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFixedHeight(130)
        self.log.hide()
        v.addWidget(self.log)
        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(4)
        self.btn_details = QtWidgets.QPushButton("▸  Details")
        self.btn_open = QtWidgets.QPushButton("Open folder")
        self.btn_show = QtWidgets.QPushButton("Show file")
        self.btn_upd = QtWidgets.QPushButton("Update yt-dlp")
        self.btn_app_upd = QtWidgets.QPushButton("Update app")
        for b in (self.btn_details, self.btn_open, self.btn_show, self.btn_upd, self.btn_app_upd):
            b.setObjectName("ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_details.clicked.connect(self._toggle_log)
        self.btn_open.clicked.connect(self._open_dir)
        self.btn_show.clicked.connect(self._reveal)
        self.btn_show.setEnabled(False)
        self.btn_upd.clicked.connect(lambda: self._run_update(manual=True))
        self.btn_app_upd.clicked.connect(self._app_update_clicked)
        tip(self.btn_app_upd, "Update app", f"Loads the newest version of this app from github.com/{UPDATE_REPO} "
                                            "and restarts it. Your settings stay.")
        tip(self.btn_details, "Details", "Shows the full log – useful if something goes wrong.")
        tip(self.btn_open, "Open folder", "Opens the output folder in Explorer.")
        tip(self.btn_show, "Show file", "Shows the last saved file in Explorer.")
        tip(self.btn_upd, "Update yt-dlp", "yt-dlp does the YouTube part. If downloads suddenly fail, "
                                           "an update usually fixes it (also runs automatically once a day).")
        foot.addWidget(self.btn_details)
        foot.addWidget(self.btn_open)
        foot.addWidget(self.btn_show)
        foot.addStretch(1)
        foot.addWidget(self.btn_app_upd)
        foot.addWidget(self.btn_upd)
        foot.addSpacing(10)
        self.lbl_ver = tip(label(f"v{APP_VERSION}", "brand"), f"Version {APP_VERSION}")
        foot.addWidget(self.lbl_ver, 0, Qt.AlignmentFlag.AlignBottom)
        foot.addSpacing(6)
        brand = label("TFROG", "brand")
        tip(brand, "made by tfrog")
        foot.addWidget(brand, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(foot)
        for key, fn in (("Space", self._toggle_play), ("I", self._set_in), ("O", self._set_out),
                        (",", lambda: self._step(-1)), (".", lambda: self._step(1)), ("M", self._toggle_mute)):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.activated.connect(fn)

    def _grid(self):
        w = QtWidgets.QWidget()
        g = QtWidgets.QGridLayout(w)
        g.setContentsMargins(0, 4, 0, 0)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.setColumnStretch(1, 1)
        return w, g

    def _combo(self, items, title=None, text=""):
        c = QtWidgets.QComboBox()
        c.addItems(list(items))
        c.setCursor(Qt.CursorShape.PointingHandCursor)
        for i, it in enumerate(items):
            if it in ITEM_HELP:
                c.setItemData(i, tip_html(it, ITEM_HELP[it]), Qt.ItemDataRole.ToolTipRole)
        if title:
            def upd(cur, c=c):
                h = ITEM_HELP.get(cur)
                c.setToolTip(tip_html(title, text) + (f"<br><br><b>{_esc(cur)}</b> – {_esc(h)}" if h else ""))
            c.currentTextChanged.connect(upd)
            upd(c.currentText())
        return c

    @staticmethod
    def _field(text, title, help_):
        return tip(label(text, "field"), title, help_)

    def _page_mp4(self):
        w, g = self._grid()
        h_codec = "How the video is compressed. Hover over the entries in the list for details."
        h_quality = "Maximum resolution. If the video doesn't have it, the next best is used."
        h_size = "How strongly the video is compressed – smaller files, a bit less detail."
        h_enc = "What does the encoding work. NVIDIA is much faster if you have such a graphics card."
        self.cb_codec = self._combo(CODECS, "Codec", h_codec)
        self.cb_codec.currentTextChanged.connect(self._codec_changed)
        self.cb_quality = self._combo(QUALITIES, "Quality", h_quality)
        self.cb_size = self._combo(SIZES, "Size", h_size)
        self.cb_size.currentTextChanged.connect(self._size_changed)
        self.target_mb = QtWidgets.QLineEdit()
        self.target_mb.setObjectName("time")
        self.target_mb.setFixedWidth(70)
        self.target_mb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip(self.target_mb, "Target size", "File size in MB, e.g. 25 for Discord or 50. Audio is included.")
        self.lbl_mb = label("MB", "field")
        self.cb_encoder = self._combo(ENCODERS, "Encoder", h_enc)
        self.lbl_size = self._field("Size", "Size", h_size)
        self.lbl_encoder = self._field("Encoder", "Encoder", h_enc)
        g.addWidget(self._field("Codec", "Codec", h_codec), 0, 0)
        g.addWidget(self.cb_codec, 0, 1, 1, 3)
        g.addWidget(self._field("Quality", "Quality", h_quality), 1, 0)
        g.addWidget(self.cb_quality, 1, 1, 1, 3)
        g.addWidget(self.lbl_size, 2, 0)
        self._mp4_grid = g
        g.addWidget(self.cb_size, 2, 1, 1, 3)
        g.addWidget(self.target_mb, 2, 2)
        g.addWidget(self.lbl_mb, 2, 3)
        g.addWidget(self.lbl_encoder, 3, 0)
        g.addWidget(self.cb_encoder, 3, 1, 1, 3)
        self.size_hint = label("", "hint")
        self.size_hint.setWordWrap(True)
        g.addWidget(self.size_hint, 4, 1, 1, 3)
        g.setRowStretch(5, 1)       # spare height goes below, not between the rows
        return w

    # ------------------------------------------------------------------ AI upscaling (pictures only)
    def _speed(self) -> float:
        return SPEEDS.get(self.cb_speed.currentText(), 1.0)

    def _speed_changed(self, _t=None):
        sp = self._speed()
        set_state(self.cb_speed, "on" if sp != 1.0 else "")
        for pl in (getattr(self, "player", None), getattr(self, "aplayer", None)):
            if pl is not None:
                pl.setPlaybackRate(sp)
        if hasattr(self, "_update_clip_info"):
            self._update_clip_info()

    def _ai(self):
        """{'factor', 'model'} or None – for Save frame and Save thumbnail."""
        if self.ai_px:
            return {"factor": None, "px": self.ai_px, "model": self.ai_model}
        return {"factor": self.ai_factor, "px": None, "model": self.ai_model} if self.ai_factor else None

    def _ai_changed(self):
        b = getattr(self, "btn_ai", None)
        if b is None:
            return
        ai = self._ai()
        size = f"{ai['px']} px" if ai and ai["px"] else f"{ai['factor']}×" if ai else ""
        b.setText(f"✦ AI {size} · {ai['model'].split(' –')[0]}" if ai else "✦ AI upscale: off")
        set_state(b, "on" if ai else "")
        self._ai_tip()

    def _ai_tip(self):
        ai = self._ai()
        need = []
        if ai:
            plan = ai_plan(ai["model"], ai["factor"] or 4)
            if not engine_exe(plan["engine"]):
                need.append(f"{ENGINES[plan['engine']]['name']} ≈ {ENGINES[plan['engine']]['mb']} MB")
            if plan["file"] and not ai_file_ok(plan["file"]):
                need.append(f"model ≈ {AI_FILES[plan['file']]['mb']} MB")
        tip(self.btn_ai, "AI upscaling for pictures",
            "Makes Save frame and Save thumbnail bigger and sharper with AI (videos stay as they are). Click to pick "
            "the size and the model." + (f" Downloaded once on first use: {', '.join(need)}." if need else "")
            + " Needs a graphics card with Vulkan (NVIDIA, AMD or Intel).")

    def _ai_menu(self):
        m = QtWidgets.QMenu(self)
        m.setToolTipsVisible(True)
        hdr = m.addAction("Size")
        hdr.setEnabled(False)
        g1 = QtGui.QActionGroup(m)
        for lab, f in AI_UPSCALES.items():
            a = m.addAction(lab if f else "Off (normal size)")
            a.setCheckable(True)
            a.setChecked(f == self.ai_factor and not self.ai_px)
            a.setActionGroup(g1)
            a.triggered.connect(lambda _=False, f=f: self._set_ai(factor=f))
        sub = m.addMenu("Size in pixels (long side)" + (f"  ·  {self.ai_px} px" if self.ai_px else ""))
        sub.setToolTipsVisible(True)
        known = False
        for px, name in AI_PX_PRESETS:
            a = sub.addAction(f"{px} px  –  {name}")
            a.setCheckable(True)
            a.setChecked(px == self.ai_px)
            known |= px == self.ai_px
            a.setActionGroup(g1)
            a.triggered.connect(lambda _=False, px=px: self._set_ai(px=px))
        sub.addSeparator()
        a = sub.addAction(f"Custom: {self.ai_px} px …" if self.ai_px and not known else "Custom …")
        a.setCheckable(True)
        a.setChecked(bool(self.ai_px) and not known)
        a.setActionGroup(g1)
        a.setToolTip("Type the size of the longer side – the other side follows the picture's shape.")
        a.triggered.connect(self._ai_px_custom)
        g2 = QtGui.QActionGroup(m)
        for i, (lab, (eng, _model, fk, hlp)) in enumerate(AI_MODELS.items()):
            if i in (0, 4):
                m.addSeparator()
                h = m.addAction("Photos, films, games" if i == 0 else "Anime, drawings")
                h.setEnabled(False)
            miss = (fk and not ai_file_ok(fk)) or not engine_exe(eng)
            size = (AI_FILES[fk]["mb"] if fk and not ai_file_ok(fk) else 0) + \
                   (0 if engine_exe(eng) else ENGINES[eng]["mb"])
            a = m.addAction(lab + (f"   ↓ {size} MB" if miss else ""))
            a.setToolTip(hlp)
            a.setCheckable(True)
            a.setChecked(lab == self.ai_model)
            a.setActionGroup(g2)
            a.triggered.connect(lambda _=False, lab=lab: self._set_ai(model=lab))
        m.addSeparator()
        m.addAction("Models and updates in Settings …").triggered.connect(self._settings)
        m.exec(self.btn_ai.mapToGlobal(QtCore.QPoint(0, self.btn_ai.height() + 2)))

    def _ai_px_custom(self):
        v, ok = QtWidgets.QInputDialog.getInt(self, "AI upscaling", "Longer side of the picture in pixels:",
                                              self.ai_px or 3840, 256, AI_PX_MAX, 64)
        if ok:
            self._set_ai(px=v)
        else:
            self._ai_changed()

    def _set_ai(self, factor=0, model=None, px=None):
        if px:
            self.ai_px, self.ai_factor = int(px), None
        elif factor != 0:
            self.ai_factor, self.ai_px = factor, None
        if model:
            self.ai_model = model
            if not self.ai_factor and not self.ai_px:
                self.ai_factor = 4
        self.cfg["ai_up"] = next(k for k, v in AI_UPSCALES.items() if v == self.ai_factor)
        self.cfg["ai_px"] = self.ai_px
        self.cfg["ai_model"] = self.ai_model
        save_cfg(self.cfg)
        self._ai_changed()

    def _page_audio(self):
        w, g = self._grid()
        h_fmt = "The audio file type. Hover over the entries in the list for details."
        h_rate = "Higher = better sound and bigger file."
        self.cb_afmt = self._combo(AUDIO_FORMATS, "Format", h_fmt)
        self.cb_afmt.currentTextChanged.connect(self._afmt_changed)
        self.cb_mp3 = self._combo(MP3_QUALITIES, "Bitrate", h_rate)
        self.lbl_bitrate = self._field("Bitrate", "Bitrate", h_rate)
        g.addWidget(self._field("Format", "Format", h_fmt), 0, 0)
        g.addWidget(self.cb_afmt, 0, 1)
        g.addWidget(self.lbl_bitrate, 1, 0)
        g.addWidget(self.cb_mp3, 1, 1)
        self.audio_hint = label("", "hint")
        self.audio_hint.setWordWrap(True)
        g.addWidget(self.audio_hint, 2, 1)
        g.setRowStretch(3, 1)
        return w

    def _page_gif(self):
        w, g = self._grid()
        h_w = "Width of the GIF – height follows the video. Bigger = much larger file."
        h_fps = "Frames per second. More = smoother motion and a bigger file."
        h_col = "GIFs can show at most 256 colors. Fewer colors = smaller file, more banding."
        self.cb_gif_w = self._combo(GIF_WIDTHS, "Width", h_w)
        self.cb_gif_fps = self._combo(GIF_FPS, "Frame rate", h_fps)
        self.cb_gif_col = self._combo(GIF_COLORS, "Colors", h_col)
        g.addWidget(self._field("Width", "Width", h_w), 0, 0)
        g.addWidget(self.cb_gif_w, 0, 1)
        g.addWidget(self._field("Frame rate", "Frame rate", h_fps), 1, 0)
        g.addWidget(self.cb_gif_fps, 1, 1)
        g.addWidget(self._field("Colors", "Colors", h_col), 2, 0)
        g.addWidget(self.cb_gif_col, 2, 1)
        g.addWidget(label(f"Best for short clips – {GIF_RECOMMENDED} s or less (max {GIF_MAX} s).", "hint"), 3, 1)
        return w

    def _page_frame(self):
        w, g = self._grid()
        h_fmt = ("Crops the picture to this format. A box appears in the preview: drag it to move, drag a corner to "
                 "resize. Custom: any shape – pull the corners and sides, or type the size. With several clips every "
                 "clip keeps its own box.")
        self.seg_aspect = Segmented([(k, k) for k in ASPECTS])
        self.seg_aspect.set_tips({"Off": ("Off", "Keep the whole picture."),
                                  "16:9": ("16:9", "Landscape – YouTube, TV."),
                                  "9:16": ("9:16", "Vertical – Shorts, Reels, TikTok."),
                                  "1:1": ("1:1", "Square."),
                                  "4:3": ("4:3", "Classic TV / old camcorder format."),
                                  "Custom": ("Custom", "Any shape: pull the corners and the sides of the box in the "
                                                       "preview as you like, or type the exact size in pixels.")})
        self.seg_aspect.changed.connect(self._aspect_changed)
        g.addWidget(self._field("Format", "Format", h_fmt), 0, 0)
        g.addWidget(self.seg_aspect, 0, 1, 1, 2)
        self.frame_hint = label("", "hint")
        self.frame_hint.setWordWrap(True)
        g.addWidget(self.frame_hint, 1, 1, 1, 2)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        self.btn_center = tip(QtWidgets.QPushButton("Center box"), "Center box",
                              "Puts the box in the middle again, as big as possible.")
        self.btn_center.setObjectName("chip")
        self.btn_center.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_center.clicked.connect(self._center_box)
        row.addWidget(self.btn_center)
        # Custom: exact size in pixels
        self.free_row = QtWidgets.QWidget()
        fr = QtWidgets.QHBoxLayout(self.free_row)
        fr.setContentsMargins(8, 0, 0, 0)
        fr.setSpacing(6)
        self.ed_cw, self.ed_ch = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for ed, what in ((self.ed_cw, "Width"), (self.ed_ch, "Height")):
            ed.setValidator(QtGui.QIntValidator(16, 16384, ed))
            ed.setFixedWidth(64)
            ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip(ed, f"{what} in pixels", "Size of the crop in pixels of the video (even numbers – odd ones are "
                                         "rounded). Enter keeps the middle of the box where it is.")
            ed.editingFinished.connect(self._free_size_typed)
        fr.addWidget(label("Size", "muted"))
        fr.addWidget(self.ed_cw)
        fr.addWidget(label("×", "muted"))
        fr.addWidget(self.ed_ch)
        fr.addWidget(label("px", "muted"))
        self.free_row.setVisible(False)
        row.addWidget(self.free_row)
        row.addStretch(1)
        g.addLayout(row, 2, 1, 1, 2)
        g.setRowStretch(3, 1)
        return w

    def _page_volume(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(10)
        self.lane = VolumeLane()
        self.lane.set_points(self.vol_pts)
        self.lane.changed.connect(self._vol_changed)
        self.lane.seek.connect(lambda t: self._seek_to(t) if self._has_media() else None)
        tip(self.lane, "Volume curve", "Shows the clip you are editing. Click to add a point, drag it, right-click, "
                                       "double-click or Del removes it. The middle line is 100 % (unchanged). "
                                       "Click a point to type its time, value and curve below.")
        self.lane.selected.connect(self._vol_selected)
        v.addWidget(self.lane)
        pr = QtWidgets.QHBoxLayout()
        pr.setSpacing(6)
        self.lbl_pt = label("Point", "field")
        self.ed_pt_t = tip(QtWidgets.QLineEdit(), "Time of the point",
                           "Type a timecode and press Enter: 1:31.24 · 1:02:03.50 · 90s.")
        self.ed_pt_t.setObjectName("time")
        self.ed_pt_t.setFixedWidth(100)
        self.ed_pt_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ed_pt_t.returnPressed.connect(self._vol_time_entered)
        self.ed_pt_t.editingFinished.connect(self._vol_time_entered)
        self.ed_pt_t.textEdited.connect(lambda _t: set_state(self.ed_pt_t, ""))
        self.ed_pt_g = tip(QtWidgets.QLineEdit(), "Volume of the point", "0 – 200 %, 100 = unchanged.")
        self.ed_pt_g.setObjectName("time")
        self.ed_pt_g.setFixedWidth(58)
        self.ed_pt_g.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ed_pt_g.returnPressed.connect(self._vol_gain_entered)
        self.ed_pt_g.editingFinished.connect(self._vol_gain_entered)
        self.ed_pt_g.textEdited.connect(lambda _t: set_state(self.ed_pt_g, ""))
        self.cb_ease = self._combo(EASES, "Curve to the next point",
                                   "Linear: straight line. Easy ease: starts and ends softly (like After Effects F9). "
                                   "Ease in / out: soft at the start / end only. Hold: stays, then jumps.")
        self.cb_ease.currentTextChanged.connect(self._vol_ease_picked)
        self.btn_pt_del = tip(QtWidgets.QPushButton("✕"), "Delete point", "Or press Del in the curve.")
        self.btn_pt_del.setObjectName("mini")
        self.btn_pt_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pt_del.clicked.connect(lambda: self.lane.delete(self.lane.sel) if self.lane.sel is not None else None)
        pr.addWidget(self.lbl_pt)
        pr.addWidget(self.ed_pt_t)
        pr.addWidget(self.ed_pt_g)
        pr.addWidget(label("%", "field"))
        pr.addWidget(self.cb_ease, 1)
        pr.addWidget(self.btn_pt_del)
        v.addLayout(pr)
        self._vol_selected(None)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        for txt, fn, title, text in (
                ("+ Point here", self._vol_point, "Point at the playhead", "Adds a point at the current preview "
                                                                           "position (with the current volume)."),
                ("Fade in", lambda: self._vol_fade(True), "Fade in", "Sound comes up over the first second of the clip "
                                                                     "(Easy ease – change it per point)."),
                ("Fade out", lambda: self._vol_fade(False), "Fade out", "Sound goes down over the last second "
                                                                        "(Easy ease)."),
                ("Reset", self._vol_reset, "Reset", "Removes the whole curve (100 % everywhere).")):
            b = tip(QtWidgets.QPushButton(txt), title, text)
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.vol_hint = label("", "hint")
        self.vol_hint.setWordWrap(True)
        v.addWidget(self.vol_hint)
        v.addStretch(1)
        return w

    def _page_subs(self):
        w, g = self._grid()
        h_src = ("Subtitles of the video (real ones and YouTube's automatic ones), subtitles inside your file, or "
                 "your own .srt / .vtt / .ass file.")
        h_mode = "Burned in: always visible, works everywhere. As track: can be switched on and off in the player."
        h_font = "Any installed font – or load a .ttf / .otf file. Used in the preview and when burning in."
        h_look = "Size, text color, outline color and bold."
        self.cb_subs = QtWidgets.QComboBox()
        self.cb_subs.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_subs, "Subtitles", h_src)
        self.cb_subs.activated.connect(self._sub_picked)
        self.seg_submode = Segmented([("none", "Not in the video"), ("burn", "Burned in"), ("track", "As track")])
        self.seg_submode.set_tips({"none": ("Not in the video", "The subtitles are only shown here (and saved as "
                                                                ".srt if ticked)."),
                                   "burn": ("Burned in", "Part of the picture – in your font, size, colors and "
                                                         "position."),
                                   "track": ("As track", "A subtitle track in the MP4 / MOV that players can switch "
                                                         "on and off (the player decides how it looks).")})
        self.seg_submode.changed.connect(lambda _k: self._subs_ui())
        self.cb_font = QtWidgets.QFontComboBox()
        self.cb_font.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_font.setEditable(False)
        tip(self.cb_font, "Font", h_font)
        self.cb_font.currentFontChanged.connect(lambda f: self._sub_style_set(font=f.family()))
        self.btn_font = tip(QtWidgets.QPushButton("Load font …"), "Load font", "Use a .ttf / .otf file. It is kept "
                                                                              "in the app and stays in this list.")
        self.btn_font.setObjectName("chip")
        self.btn_font.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_font.clicked.connect(self._load_font)
        self.sp_size = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        self.sp_size.setRange(40, 300)
        self.sp_size.setSingleStep(5)
        self.sp_size.setPageStep(10)
        self.sp_size.setFixedWidth(96)
        self.sp_size.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.sp_size, "Size", "100 % = about 5.5 % of the picture height (of the short side).")
        self.lbl_size_pct = label("100 %", "ptime")
        self.lbl_size_pct.setFixedWidth(42)
        self.sp_size.valueChanged.connect(lambda v: (self.lbl_size_pct.setText(f"{v} %"), self._sub_style_set(size=v)))
        self.btn_col = tip(QtWidgets.QPushButton(), "Text color")
        self.btn_ol = tip(QtWidgets.QPushButton(), "Outline color")
        for b, key in ((self.btn_col, "color"), (self.btn_ol, "outline")):
            b.setObjectName("colorbtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._pick_sub_color(k))
        self.cb_bold = QtWidgets.QCheckBox("Bold")
        self.cb_bold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_bold.toggled.connect(lambda v: self._sub_style_set(bold=v))
        self.cb_srt = QtWidgets.QCheckBox("Also save as .srt next to the file")
        self.cb_srt.setCursor(Qt.CursorShape.PointingHandCursor)
        tip(self.cb_srt, "Save .srt", "With the times of your clip (or of the joined clips) – and your changes.")
        self.cb_srt.toggled.connect(lambda _v: self._subs_ui())
        self.btn_lines = tip(QtWidgets.QPushButton("Edit lines …"), "Edit lines",
                             "All lines with their times: change text and times, add or delete lines, shift "
                             "everything, search, copy or save.")
        self.btn_pos = tip(QtWidgets.QPushButton("Reset position"), "Reset position",
                           "Back to the bottom center (double-click the text in the preview does the same).")
        for b in (self.btn_lines, self.btn_pos):
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lines.clicked.connect(self._show_lines)
        self.btn_pos.clicked.connect(lambda: self._sub_style_set(pos=None))
        g.addWidget(self._field("Subtitles", "Subtitles", h_src), 0, 0)
        g.addWidget(self.cb_subs, 0, 1)
        self.sub_status = label("", "hint")
        g.addWidget(self.sub_status, 1, 1)
        g.addWidget(self._field("In the video", "In the video", h_mode), 2, 0)
        g.addWidget(self.seg_submode, 2, 1)
        g.addWidget(self._field("Font", "Font", h_font), 3, 0)
        fr = QtWidgets.QHBoxLayout()
        fr.setSpacing(6)
        fr.addWidget(self.cb_font, 1)
        fr.addWidget(self.btn_font)
        g.addLayout(fr, 3, 1)
        g.addWidget(self._field("Look", "Look", h_look), 4, 0)
        lr = QtWidgets.QHBoxLayout()
        lr.setSpacing(8)
        lr.addWidget(self.sp_size)
        lr.addWidget(self.lbl_size_pct)
        lr.addWidget(self.btn_col)
        lr.addWidget(label("text", "field"))
        lr.addWidget(self.btn_ol)
        lr.addWidget(label("outline", "field"))
        lr.addSpacing(6)
        lr.addWidget(self.cb_bold)
        lr.addStretch(1)
        g.addLayout(lr, 4, 1)
        g.addWidget(self.cb_srt, 5, 1)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.btn_lines)
        row.addWidget(self.btn_pos)
        row.addStretch(1)
        g.addLayout(row, 6, 1)
        self.sub_hint = label("Drag the text in the preview to place it anywhere in the picture.", "hint")
        self.sub_hint.setWordWrap(True)
        g.addWidget(self.sub_hint, 7, 1)
        g.setRowStretch(8, 1)
        self._fill_subs([])
        return w

    # ------------------------------------------------------------------ subtitle look
    def _load_app_fonts(self):
        self._font_files = {}
        for f in sorted(FONTS_DIR.glob("*")) if FONTS_DIR.is_dir() else []:
            if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                fid = QtGui.QFontDatabase.addApplicationFont(str(f))
                for fam in QtGui.QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []:
                    self._font_files[fam] = str(f)

    def _apply_sub_style_ui(self):
        st = self.sub_style
        for w_ in (self.cb_font, self.sp_size, self.cb_bold):
            w_.blockSignals(True)
        self.cb_font.setCurrentFont(QtGui.QFont(st.get("font") or "Arial"))
        self.sp_size.setValue(int(st.get("size") or 100))
        self.lbl_size_pct.setText(f"{int(st.get('size') or 100)} %")
        self.cb_bold.setChecked(bool(st.get("bold")))
        for w_ in (self.cb_font, self.sp_size, self.cb_bold):
            w_.blockSignals(False)
        self.btn_col.setStyleSheet(f"background: {st.get('color')};")
        self.btn_ol.setStyleSheet(f"background: {st.get('outline')};")
        self.btn_pos.setEnabled(bool(st.get("pos")))
        if self.canvas is not None:
            self.canvas.set_sub_style(st)

    def _sub_style_set(self, **kw):
        if "font" in kw:
            kw["font_file"] = self._font_files.get(kw["font"], "")
        self.sub_style.update(kw)
        self.cfg["sub_style"] = {k: v for k, v in self.sub_style.items()}
        self._apply_sub_style_ui()

    def _sub_moved(self, pos):
        self.sub_style["pos"] = pos
        self.cfg["sub_style"] = dict(self.sub_style)
        self.btn_pos.setEnabled(bool(pos))

    def _pick_sub_color(self, key):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.sub_style.get(key) or "#ffffff"), self,
                                              "Text color" if key == "color" else "Outline color")
        if col.isValid():
            self._sub_style_set(**{key: col.name()})

    def _load_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load a font", self.cfg.get("last_font_dir") or
                                                        str(Path.home()), "Fonts (*.ttf *.otf *.ttc)")
        if not path:
            return
        self.cfg["last_font_dir"] = str(Path(path).parent)
        try:
            f = install_font(path)
        except OSError as ex:
            return self._on_error(f"Font not loaded: {ex}")
        fid = QtGui.QFontDatabase.addApplicationFont(str(f))
        fams = QtGui.QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if not fams:
            return self._on_error("This font file can't be read.")
        for fam in fams:
            self._font_files[fam] = str(f)
        self._sub_style_set(font=fams[0])
        self._on_status(f"Font “{fams[0]}” loaded.")

    # ------------------------------------------------------------------ frame tab
    def _tab_changed(self, key):
        self.tabstack.setCurrentIndex(["out", "frame", "volume", "subs"].index(key))
        self._fit_stack(self.tabstack)
        if self.canvas is not None:
            self.canvas.set_ghost(key == "subs" and bool(self.sub_cues) and self.seg.value() != "mp3")
        if key == "volume":
            self._lane_range()
        if key == "frame":
            self._frame_info()

    def _aspect(self):
        return ASPECTS.get(self.seg_aspect.value()) if self.seg.value() in ("mp4", "gif") else None

    def _aspect_changed(self, _key=None):
        aspect = ASPECTS.get(self.seg_aspect.value())
        for c in self.clips:
            c.box = None
        self.box = None
        if self.canvas is not None:
            self.canvas.set_aspect(self._aspect())
            self.box = self.canvas.box
            if self._multi() and self.clips:
                self.clips[self.cur].box = self.box
            if aspect and self._pv_state == "offer" and self._is_info_current():
                self._thumb_clicked()          # the box needs the picture
        self._frame_info()

    def _center_box(self):
        if self.canvas is not None and self.canvas.frame_size():
            self.canvas.reset_box()
        elif self._aspect():
            self._box_changed(None)

    def _free_size_typed(self):
        """Custom: the typed size (px) -> box, the middle of the box stays where it is."""
        d = self._src_dims()
        if self._aspect() != FREE or not d:
            return
        W, H = d
        try:
            w, h = int(self.ed_cw.text()), int(self.ed_ch.text())
        except ValueError:
            self._frame_info()
            return
        w, h = min(max(16, w), W), min(max(16, h), H)
        x, y, bw, bh = self.box or center_box(FREE, W, H)
        mx, my = x + bw / 2, y + bh / 2
        nw, nh = w / W, h / H
        box = (min(max(mx - nw / 2, 0.0), 1.0 - nw), min(max(my - nh / 2, 0.0), 1.0 - nh), nw, nh)
        if self.canvas is not None:
            self.canvas.set_box(box)
        self._box_changed(box)

    def _box_changed(self, box):
        self.box = box
        if self._multi() and self.clips and self.cur < len(self.clips):
            self.clips[self.cur].box = box
        self._frame_info()

    def _src_dims(self):
        """Width × height of the picture that will be downloaded (or of the file)."""
        if not self._is_info_current():
            return None
        w, h = self.info.get("width"), self.info.get("height")
        if not w or not h:
            fs = self.canvas.frame_size() if self.canvas is not None else None
            if not fs:
                return None
            w, h = fs
            if not self.info.get("local"):
                h0 = 1080
                w, h = round(w * h0 / h), h0
        q = QUALITIES.get(self.cb_quality.currentText()) if self.seg.value() == "mp4" else None
        if q and not self.info.get("local") and h > q and w >= h:
            w, h = round(w * q / h), q
        elif q and not self.info.get("local") and w < h and w > q:   # vertical video: the short side is limited
            w, h = q, round(h * q / w)
        return int(w), int(h)

    def _frame_dims(self):
        """-> (crop w, crop h, result w, result h) or None."""
        d = self._src_dims()
        if not d:
            return None
        W, H = d
        aspect = self._aspect()
        cw, ch = (crop_rect(self.box, W, H, aspect)[:2]) if aspect else (W, H)
        ow, oh = target_dims(cw, ch, None, aspect)
        return cw, ch, ow, oh

    def _frame_info(self):
        mode = self.seg.value()
        is_mp4 = mode == "mp4"
        self.seg_aspect.setEnabled(mode in ("mp4", "gif"))
        self.btn_center.setVisible(bool(self._aspect()) and self.canvas is not None)
        aspect = self._aspect()
        self.free_row.setVisible(aspect == FREE)
        dims = self._frame_dims() if mode != "mp3" else None
        if mode == "mp3":
            ftxt = "Audio has no picture – switch to Video or GIF to crop."
        elif dims:
            cw, ch, ow, oh = dims
            ftxt = f"Crop {ow} × {oh}" if aspect else f"Picture {cw} × {ch}"
            if aspect == FREE:
                for ed, v in ((self.ed_cw, ow), (self.ed_ch, oh)):
                    if not ed.hasFocus():
                        ed.setText(str(v))
                W, H = self._src_dims()
                ftxt = f"Crop {ow} × {oh} of {W} × {H}"
            if not is_mp4:
                ftxt += "  ·  the GIF width is set in Output"
            if aspect == FREE and self.canvas is not None:
                ftxt += ".  Pull the corners or sides of the box in the preview."
            elif aspect and self.canvas is not None:
                ftxt += ".  Drag the box in the preview."
        else:
            ftxt = "Paste a link or open a file – the sizes appear here." if aspect else ""
        if self.canvas is not None:
            lab = f"{dims[2]} × {dims[3]}" if aspect == FREE and dims else ""
            if lab != self.canvas.box_label:
                self.canvas.box_label = lab
                self.canvas.update()
        self.frame_hint.setText(ftxt)
        self._badges()

    def _badges(self):
        mode = self.seg.value()
        self.tabs.set_badge("frame", bool(self._aspect()))
        self.tabs.set_badge("volume", mode in ("mp4", "mp3") and any(abs(q[1] - 1) > 1e-4 for q in self.vol_pts))
        self.tabs.set_badge("subs", bool(self.sub_cues) and (self.seg_submode.value() != "none" or self.cb_srt.isChecked()))

    # ------------------------------------------------------------------ volume tab
    def _lane_range(self):
        rng = self._cur_range()
        dur = self._duration()
        if rng:
            self.lane.set_range(*rng)
        elif dur:
            self.lane.set_range(0, dur)
        mode = self.seg.value()
        self.lane.setEnabled(mode != "gif")
        self.vol_hint.setText("GIFs have no sound." if mode == "gif" else
                              "Click the line to add points and drag them; click a point to type its exact time, "
                              "value and curve. In the preview you hear the curve up to 100 %.")

    def _vol_changed(self):
        self._badges()
        self._apply_gain()

    def _vol_point(self):
        t = self._player_pos()
        rng = self._cur_range()
        if t is None:
            t = rng[0] if rng else 0.0
        if rng:
            t = min(max(t, rng[0]), rng[1])
        g = vol_at(self.vol_pts, t)
        pt = [round(t, 3), round(g, 3), "linear"]
        self.vol_pts[:] = [q for q in self.vol_pts if abs(q[0] - t) > 0.01] + [pt]
        self.vol_pts.sort(key=lambda q: q[0])
        self.lane.select(pt)
        self._vol_changed()

    def _vol_fade(self, fade_in):
        rng = self._cur_range()
        if not rng:
            return
        s, e = rng
        d = min(1.0, (e - s) / 3)
        a, b = (s, s + d) if fade_in else (e - d, e)
        ga, gb = (0.0, vol_at(self.vol_pts, b) or 1.0) if fade_in else (vol_at(self.vol_pts, a) or 1.0, 0.0)
        nxt = "linear"
        self.vol_pts[:] = [q for q in self.vol_pts if not (a - 0.001 <= q[0] <= b + 0.001)] + \
            [[a, ga, "ease"], [b, gb, nxt]]
        self.vol_pts.sort(key=lambda q: q[0])
        self.lane.select(None)
        self._vol_changed()

    def _vol_reset(self):
        self.vol_pts.clear()
        self.lane.select(None)
        self._vol_changed()

    def _vol_selected(self, pt):
        on = pt is not None
        for w_ in (self.lbl_pt, self.ed_pt_t, self.ed_pt_g, self.cb_ease, self.btn_pt_del):
            w_.setEnabled(on)
        if not on:
            for ed in (self.ed_pt_t, self.ed_pt_g):
                ed.clear()
            self.ed_pt_t.setPlaceholderText("click a point")
            return
        if not self.ed_pt_t.hasFocus():
            self.ed_pt_t.setText(fmt_tc(pt[0]))
            set_state(self.ed_pt_t, "")
        if not self.ed_pt_g.hasFocus():
            self.ed_pt_g.setText(f"{pt[1] * 100:.0f}")
            set_state(self.ed_pt_g, "")
        ease = pt[2] if len(pt) > 2 else "linear"
        label_ = next((k for k, v_ in EASES.items() if v_ == ease), "Linear")
        self.cb_ease.blockSignals(True)
        self.cb_ease.setCurrentText(label_)
        self.cb_ease.blockSignals(False)

    def _vol_time_entered(self):
        pt = self.lane.sel
        if pt is None:
            return
        try:
            t = parse_time(self.ed_pt_t.text())
            if t is None:
                raise ValueError
        except ValueError:
            set_state(self.ed_pt_t, "error")
            return
        dur = self._duration()
        if dur:
            t = min(t, dur)
        if abs(t - pt[0]) < 1e-4:
            return
        pt[0] = round(t, 3)
        self.vol_pts.sort(key=lambda q: q[0])
        lo, hi = self.lane.lo, self.lane.hi
        if not lo <= t <= hi and dur:          # point is outside the clip -> show the whole video
            self.lane.set_range(0, dur)
        self.ed_pt_t.setText(fmt_tc(pt[0]))
        set_state(self.ed_pt_t, "")
        self.lane.update()
        self._vol_changed()

    def _vol_gain_entered(self):
        pt = self.lane.sel
        if pt is None:
            return
        try:
            g = float(self.ed_pt_g.text().replace(",", ".").replace("%", "").strip()) / 100
        except ValueError:
            set_state(self.ed_pt_g, "error")
            return
        g = min(max(g, 0.0), 2.0)
        if abs(g - pt[1]) < 1e-4:
            return
        pt[1] = round(g, 4)
        self.ed_pt_g.setText(f"{g * 100:.0f}")
        self.lane.update()
        self._vol_changed()

    def _vol_ease_picked(self, label_):
        pt = self.lane.sel
        if pt is None:
            return
        while len(pt) < 3:
            pt.append("linear")
        pt[2] = EASES.get(label_, "linear")
        self.lane.update()
        self._vol_changed()

    def _apply_gain(self, t=None, force=False):
        """Slider volume × volume curve on the audio output – only when the value really changes (setting the
        volume on every frame can lock up the audio output on Windows while a video is loading)."""
        if self._resetting:
            return
        if t is None and self.vol_pts:
            t = self._player_pos()
        gain = vol_at(self.vol_pts, t) if (self.vol_pts and t is not None and self.seg.value() != "gif") else 1.0
        v = round(min(1.0, max(0.0, self.vol.value() / 100 * gain)), 3)
        if not force and self._out_vol is not None and abs(v - self._out_vol) < 0.005:
            return
        self._out_vol = v
        for out in (self.audio_out, self.a_out2):
            if out is not None:
                out.setVolume(v)

    # ------------------------------------------------------------------ subtitles tab
    def _fill_subs(self, items):
        self.sub_items = list(items)
        self.cb_subs.blockSignals(True)
        self.cb_subs.clear()
        self.cb_subs.addItem("Off")
        for it in self.sub_items:
            self.cb_subs.addItem(it["label"])
        self.cb_subs.addItem("Load a file …")
        self.cb_subs.blockSignals(False)
        self.sub_status.setText("" if items else ("No subtitles found in this video – you can load a file."
                                                  if self._is_info_current() else ""))
        self._set_cues([], None)

    def _sub_picked(self, idx):
        n = len(self.sub_items)
        if idx <= 0:
            return self._set_cues([], None)
        if idx == n + 1:
            start = self.cfg.get("last_subs") or (str(Path(self.info["local"]).parent) if self.info.get("local")
                                                  else str(Path.home()))
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open subtitles", start,
                                                            "Subtitles (*.srt *.vtt *.ass *.ssa);;All files (*.*)")
            if not path:
                self.cb_subs.setCurrentIndex(0)
                return self._set_cues([], None)
            self.cfg["last_subs"] = str(Path(path).parent)
            item = {"label": Path(path).name, "kind": "file", "key": path}
            self.sub_items.append(item)
            self.cb_subs.blockSignals(True)
            self.cb_subs.insertItem(n + 1, item["label"])
            self.cb_subs.setCurrentIndex(n + 1)
            self.cb_subs.blockSignals(False)
        else:
            item = self.sub_items[idx - 1]
        self._sub_req += 1
        req, url = self._sub_req, self.info.get("local") or self.url.text().strip()
        self.sub_status.setText("Loading subtitles …")
        set_state(self.sub_status, "")
        ffmpeg = self.ffmpeg

        def work():
            try:
                cues = fetch_subs(url, item, ffmpeg)
                self.emit("subs", (req, cues, item, ""))
            except Exception as ex:  # noqa: BLE001
                self.emit("subs", (req, [], item, clean_error(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _on_subs(self, val):
        req, cues, item, err = val
        if req != self._sub_req:
            return
        if err or not cues:
            self.sub_status.setText(("✕ " + err.splitlines()[0][:120]) if err else "These subtitles are empty.")
            set_state(self.sub_status, "error")
            self._set_cues([], None)
            return
        self._set_cues(cues, item)

    def _set_cues(self, cues, item):
        self.sub_cues = cues
        self.sub_lang = (item or {}).get("key") if (item or {}).get("kind", "").startswith("yt") else None
        if cues:
            last = cues[-1][1]
            self.sub_status.setText(f"{len(cues)} lines · up to {fmt_ts(last)}")
            set_state(self.sub_status, "")
        if self.lines_dlg is not None:
            self.lines_dlg.close()
            self.lines_dlg = None
        self._subs_ui()
        self._update_sub_overlay()

    def _cues_edited(self, cues):
        self.sub_cues = list(cues)
        self.sub_status.setText(f"{len(cues)} lines · edited")
        set_state(self.sub_status, "")
        self._update_sub_overlay()
        self._badges()

    def _subs_ui(self):
        mode = self.seg.value()
        has = bool(self.sub_cues)
        self.seg_submode.setEnabled(has and mode != "mp3")
        self.cb_srt.setEnabled(has)
        self.btn_lines.setEnabled(has)
        look = has and mode != "mp3"
        for w_ in (self.cb_font, self.btn_font, self.sp_size, self.btn_col, self.btn_ol, self.cb_bold):
            w_.setEnabled(look)
        self.btn_pos.setEnabled(look and bool(self.sub_style.get("pos")))
        self.sub_hint.setVisible(look)
        if mode == "gif" and self.seg_submode.value() == "track":
            self.seg_submode.set_value("burn")
        if self.canvas is not None:
            self.canvas.set_ghost(look and self.tabs.value() == "subs")
        self._badges()

    def _update_sub_overlay(self, t=None):
        if self.canvas is None:
            return
        if t is None:
            t = self._player_pos()
        self.canvas.set_sub(cue_at(self.sub_cues, t) if (self.sub_cues and t is not None) else "")

    def _show_lines(self):
        if not self.sub_cues:
            return
        if self.lines_dlg is None:
            self.lines_dlg = SubsEditor(self, self.sub_cues, self.info.get("title") or "subtitles", self._player_pos)
            self.lines_dlg.jump.connect(lambda t: (self._stop_playback(), self._seek_to(t)) if self._has_media() else None)
            self.lines_dlg.changed.connect(self._cues_edited)
            self.lines_dlg.finished.connect(lambda _r: setattr(self, "lines_dlg", None))
        self.lines_dlg.show()
        self.lines_dlg.raise_()

    # ------------------------------------------------------------------ chapters / history / still
    def _chapters(self):
        ch = self.info.get("chapters") if self._is_info_current() else None
        if not ch or self.busy:
            return
        dlg = ChaptersDialog(self, ch)
        dlg.seg_join.set_value("join" if self.seg_join.value() == "join" and self._multi() else "separate")
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        picked = dlg.picked()
        if not picked:
            return
        self.clips = [Clip(s, e, title, self.box) for s, e, title in picked]
        self.cur = 0
        self.seg_join.set_value(dlg.seg_join.value())
        if not self._multi():
            self.seg_clips.set_value("multi", animate=True)
            self.multi_box.setVisible(True)
        self._refresh_clip_list()
        self._select_clip(0)
        self._update_clip_info()
        self._set_button_text()

    def _show_history(self):
        dlg = HistoryDialog(self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted and dlg.chosen:
            self.url.setText(dlg.chosen)
            self.name.clear()

    def _history_add(self, url, info, data):
        if not self.cfg.get("history", True) or info.get("local"):
            return
        jpg = None
        if data:
            img = QtGui.QImage()
            if img.loadFromData(data):
                img = img.scaled(256, 144, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                buf = QtCore.QBuffer()
                buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "JPG", 82)
                jpg = bytes(buf.data())
        try:
            history_add(url, info, jpg)
        except Exception as ex:  # noqa: BLE001
            self._on_log(f"History: {ex}")

    def _save_still(self):
        if not self._has_media() or self.busy or not self._is_info_current():
            return
        if self.info.get("local") and not self.info.get("has_video", True):
            return
        t = self._player_pos() or 0.0
        self._stop_playback()
        outdir = Path(self.outdir.text().strip() or Path.home() / "Downloads")
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            return self._on_error(f"Invalid folder: {ex}")
        base = self.name.text().strip() or safe_name(self.info.get("title") or "frame")
        tc = fmt_tc(t).replace(":", "-").replace(".", "_")
        dst = outdir / (unique_name(outdir, f"{base}_{tc}", ".png") + ".png")
        local = bool(self.info.get("local"))
        src = self.info["local"] if local else self.url.text().strip()
        fps = float(self.info.get("fps") or 0) or self._fps()
        aspect = self._aspect() if self.seg.value() != "mp3" else None
        height = QUALITIES.get(self.cb_quality.currentText())
        self._on_log(f"\n— Frame at {fmt_tc(t)} → {dst.name}")
        self._set_busy(True)
        self._on_status("Saving frame …")
        self._on_progress(None)
        box = self.box
        ai = self._ai()
        if ai:
            self._on_log(f"  AI upscaling {ai['px']} px" if ai["px"] else f"  AI upscaling {ai['factor']}×"
                         + f" · {ai['model']}")

        def work():
            try:
                if not local:
                    self.update_done.wait()
                f = export_still(src, t, fps, dst, local=local, height=height, aspect=aspect, box=box,
                                 ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, emit=self.emit, ai=ai)
                self.emit("done", [str(f)])
            except Exception as ex:  # noqa: BLE001
                self.emit("error", clean_error(ex))
        threading.Thread(target=work, daemon=True).start()

    def _bridge_wants(self) -> bool:
        """The extension may hand over the login: while signing in, and later (to keep it fresh) if the login came
        from it."""
        if self._pending_signin and time.time() - self._pending_signin < 15 * 60:
            return True
        return self.cfg.get("login_via") == "chrome" and logged_in()

    def _ext_connected(self, within=90) -> bool:
        return time.time() - self.login_bridge.seen < within

    def _ext_outdated(self) -> bool:
        """An extension from 2.9.2 asks (without the key) and the new one doesn't: Chrome has to reload it."""
        return time.time() - self.login_bridge.old_ext < 120 and not self._ext_connected(120)

    def _login_browser(self):
        """The Chrome-like browser for the sign-in: the default one if it is one, else an installed one."""
        bs = chromium_browsers()
        return bs[0] if bs else None

    def _sign_in(self):
        """Sign-in in your own Chrome: a new tab with Google's account choice; the app's extension hands the login
        over (and keeps it up to date)."""
        if self.login_bridge.port is None:
            return self._on_error("The sign-in can't start: the ports 47815–47817 on this PC are taken by another "
                                  "program. Restart the PC or use Settings → YouTube login → Load cookies.txt.")
        b = self._login_browser()
        if b is None:
            return self._on_error("The sign-in needs Chrome, Edge, Brave, Opera or Vivaldi – none was found. You can "
                                  "use Settings → YouTube login → Load cookies.txt instead.")
        self._pending_signin = time.time()
        self._login_state_changed()
        if self._ext_connected():
            self._open_login_tab(b)
            return
        dlg = ExtSetupDialog(self, b)
        res = dlg.exec()
        if res == ExtSetupDialog.WITHOUT:
            self._pending_signin = 0.0
            self._sign_in_window()
            return
        if res != QtWidgets.QDialog.DialogCode.Accepted:
            if self._pending_signin:
                self._cancel_sign_in()
            return
        if self._pending_signin:                   # not signed in by the extension's first message already
            self._open_login_tab(b)

    def _login_profile(self):
        """The browser profile for the sign-in: the chosen one, else the one with the extension, else the last used."""
        prs = browser_profiles(self._login_browser())
        dirs = [p["dir"] for p in prs]
        if self.cfg.get("chrome_profile") in dirs:
            return self.cfg["chrome_profile"]
        with_ext = [p["dir"] for p in prs if p["ext"]]
        if with_ext:
            return with_ext[0]
        return next((p["dir"] for p in prs if p["last"]), dirs[0] if dirs else None)

    def _open_login_tab(self, b):
        if not open_in_browser(b, LOGIN_URL, self._login_profile()):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(LOGIN_URL))
        self._on_log(f"Sign-in: opened a tab in {b['name']} – waiting for the YouTube login …")
        self._on_status(f"Sign in to YouTube in the new {b['name']} tab (or pick your account) – the app takes the "
                        "login by itself.")
        set_state(self.status, "")
        QtCore.QTimer.singleShot(15 * 60 * 1000 + 500, self._signin_timeout)

    def _signin_timeout(self):
        if self._pending_signin and time.time() - self._pending_signin >= 15 * 60:
            self._pending_signin = 0.0
            self._on_status("Sign-in took too long – try again.")
            self._login_state_changed()

    def _on_bridge(self, ev):
        kind, val = ev
        if kind == "login":
            first = bool(self._pending_signin)
            self._pending_signin = 0.0
            self.cfg["login_via"] = "chrome"
            LOGIN_NOTE.clear()
            self._login_noted = False
            self._login_warned = False
            if first:
                b = self._login_browser()
                with_ext = [p["dir"] for p in browser_profiles(b) if p["ext"]]
                if len(with_ext) == 1:
                    self.cfg["chrome_profile"] = with_ext[0]     # the sign-in opens there from now on
                self._on_log(f"✓ Signed in to YouTube (via {b['name'] if b else 'Chrome'}) – the extension keeps the "
                             "login up to date.")
                self._on_status("✓  Signed in to YouTube.")
                set_state(self.status, "ok")
                self.raise_()
                self.activateWindow()
            if first or val:                       # first time or another account -> name + picture
                self._refresh_account(force=True)
            self._login_state_changed()
        elif kind == "no_login" and self._pending_signin:
            dlg = getattr(self, "settings_dlg", None)
            if dlg is not None:
                dlg.show_login_state()

    def _sign_in_window(self):
        """Sign-in without the extension: the default browser in an own, empty profile; the login is picked up by
        itself, then the window and its profile are deleted."""
        if self._signin is not None or self._pending_signin:
            return
        b = self._window_browser()
        if not b:
            return self._on_error("No default browser found that the app can use (Chrome, Edge, Brave, Opera, "
                                  "Vivaldi or Firefox). Use Settings → YouTube login → Load cookies.txt instead.")
        si = BrowserSignIn(b)
        try:
            si.start()
        except OSError as ex:
            return self._on_error(f"Could not open {b['name']}: {ex}")
        self._signin = si
        self._on_log(f"Sign-in: opened {b['name']} with its own profile – waiting for the YouTube login …")
        self._on_status(f"Sign in to YouTube in the {b['name']} window that just opened – it closes by itself.")
        set_state(self.status, "")
        self._login_state_changed()

        def work():
            end = time.time() + 15 * 60
            state = "waiting"
            while state == "waiting" and time.time() < end and self._signin is si:
                time.sleep(1.5)
                try:
                    state = si.poll()
                except Exception as ex:  # noqa: BLE001
                    state = "error:" + clean_error(ex)
            if self._signin is not si:
                return                      # cancelled
            if state == "waiting":
                si.close()
                state = "timeout"
            self.emit("signin", state)
        threading.Thread(target=work, daemon=True).start()

    def _on_signin(self, state):
        si, self._signin = self._signin, None
        self._drop_signin_profile()             # the window's own profile (a whole Google login) is not kept
        name = si.b["name"] if si else "the browser"
        if state == "done" and apply_login():
            LOGIN_NOTE.clear()
            self._login_noted = False
            self.cfg["login_via"] = "window"
            self._on_log(f"✓ Signed in to YouTube (via {name}) – the login is used for every download.")
            self._refresh_account(force=True)
            self._on_status("✓  Signed in to YouTube.")
            set_state(self.status, "ok")
            self.raise_()
            self.activateWindow()
        elif state == "closed":
            self._on_status(f"The {name} window was closed before YouTube showed you as signed in – not signed in.")
        elif state == "timeout":
            self._on_status("Sign-in took too long – try again.")
        else:
            self._on_error(f"Sign-in with {name} didn't work: {state.split(':', 1)[-1]}\n"
                           "You can use Settings → YouTube login → Load cookies.txt instead.")
        self._login_state_changed()

    def _window_browser(self):
        if not hasattr(self, "_default_browser"):
            self._default_browser = default_browser()
        return self._default_browser

    def _drop_signin_profile(self):
        def work():
            for _ in range(20):                  # the browser may still hold its files for a moment
                shutil.rmtree(SIGNIN_DIR, ignore_errors=True)
                if not SIGNIN_DIR.exists():
                    return
                time.sleep(1.0)
        threading.Thread(target=work, daemon=True).start()

    def _cancel_sign_in(self):
        si, self._signin = self._signin, None
        if si is not None:
            def close():
                si.close()
                self._drop_signin_profile()
            threading.Thread(target=close, daemon=True).start()
        self._pending_signin = 0.0
        self._on_status("Sign-in cancelled.")
        self._login_state_changed()

    def _refresh_account(self, force=False):
        """Which account is signed in (name + picture): from the saved file, looked up again in the background
        after a sign-in or when it's older than half a day."""
        if not login_state()["signed_in"]:
            self.account = {}
            self._head_account({})
            return
        acc = load_account()
        self.account = {"signed_in": True, **acc}
        self._head_account(self.account)
        if not force and acc and time.time() - float(acc.get("checked") or 0) < 12 * 3600:
            return
        if getattr(self, "_acc_busy", False):
            return
        self._acc_busy = True
        self._acc_card_busy(True)

        def work():
            try:
                self.emit("account", ("ok", fetch_account()))
            except Exception as ex:  # noqa: BLE001
                self.emit("account", ("err", clean_error(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _acc_card_busy(self, on):
        dlg = getattr(self, "settings_dlg", None)
        if dlg is not None and hasattr(dlg, "acc_card"):
            dlg.acc_card.busy = on
            dlg.acc_card.set_account(self.account)

    def _on_account(self, val):
        kind, v = val
        self._acc_busy = False
        dlg = getattr(self, "settings_dlg", None)
        if dlg is not None and hasattr(dlg, "acc_card"):
            dlg.acc_card.busy = False
        if not login_state()["signed_in"]:          # signed out meanwhile
            clear_account()
            self.account = {}
        elif kind == "ok":
            self.account = {"signed_in": True, **v}
            if v.get("name"):
                self._on_log(f"YouTube account: {v['name']}" + (f" ({v['handle']})" if v.get("handle") else ""))
        else:
            self._on_log(f"Couldn't read name and picture of the YouTube account – {v}")
        self._head_account(self.account)
        self._login_state_changed()

    def _login_state_changed(self):
        if not login_state()["signed_in"] and self.account:
            self.account = {}
            self._head_account({})
        dlg = getattr(self, "settings_dlg", None)
        if dlg is not None:
            dlg.show_login_state()

    def _sign_out(self):
        self._pending_signin = 0.0
        self.cfg.pop("login_via", None)             # the extension doesn't hand over anything any more
        sign_out()
        self._on_log("Signed out of YouTube.")
        self._on_status("Signed out of YouTube.")
        self._login_state_changed()

    def _fx(self, mode):
        """Crop / size / volume / subtitles for export_multi (None if nothing is switched on)."""
        aspect = self._aspect()
        boxes = [c.box for c in self.clips] if self._multi() else [self.box]
        sub_mode = self.seg_submode.value()
        fx = {
            "aspect": aspect, "boxes": boxes,
            "vol": [tuple(q) for q in self.vol_pts] if mode in ("mp4", "mp3") else [],
            "subs": {"cues": self.sub_cues, "mode": None if sub_mode == "none" else sub_mode,
                     "lang": self.sub_lang, "style": dict(self.sub_style)} if self.sub_cues else None,
            "speed": self._speed(),
        }
        return fx

    def _srt_job(self):
        return self.sub_cues if (self.sub_cues and self.cb_srt.isChecked()) else None

    # ------------------------------------------------------------------ settings / theme
    def _load_settings(self):
        c = self.cfg

        def pick(combo, key, options, default):
            val = c.get(key)
            combo.setCurrentText(val if val in options else default)

        if str(c.get("encoder", "")).startswith("NVIDIA"):  # labels of older versions
            c["encoder"] = ENCODERS[1]
        pick(self.cb_codec, "codec", CODECS, DEFAULT_CODEC)
        pick(self.cb_quality, "quality", QUALITIES, DEFAULT_QUALITY)
        pick(self.cb_size, "size", SIZES, DEFAULT_SIZE)
        pick(self.cb_encoder, "encoder", ENCODERS, DEFAULT_ENCODER)
        pick(self.cb_speed, "speed", SPEEDS, DEFAULT_SPEED)
        self.ai_factor = AI_UPSCALES.get(c.get("ai_up"))
        self.ai_px = int(c["ai_px"]) if str(c.get("ai_px") or "").isdigit() else None
        self.ai_model = c.get("ai_model") if c.get("ai_model") in AI_MODELS else DEFAULT_AI_MODEL
        self._ai_changed()
        if hasattr(self, "tabstack"):
            self._fit_stack(self.stack)
            self._fit_stack(self.tabstack)
        pick(self.cb_afmt, "audio_format", AUDIO_FORMATS, DEFAULT_AUDIO)
        pick(self.cb_mp3, "mp3_quality", MP3_QUALITIES, DEFAULT_MP3)
        pick(self.cb_gif_w, "gif_width", GIF_WIDTHS, "480 px")
        pick(self.cb_gif_fps, "gif_fps", GIF_FPS, "15 fps")
        pick(self.cb_gif_col, "gif_colors", GIF_COLORS, "Best (256 colors)")
        self.target_mb.setText(f"{c.get('target_mb', 50):g}")
        self.cb_thumb.setChecked(bool(c.get("save_thumb", False)))
        self.outdir.setText(c.get("outdir") or str(Path.home() / "Downloads"))
        self.vol.setValue(int(c.get("volume", 80)))
        self._vol_restore = self.vol.value() or int(c.get("vol_restore") or 80)
        self._vol_settle.stop()
        self.btn_mute.set_level(self.vol.value())
        self.seg_join.set_value("separate" if c.get("join") == "separate" else "join")
        self.seg_aspect.set_value(c.get("aspect") if c.get("aspect") in ASPECTS else "Off")
        self.seg_submode.set_value(c.get("sub_mode") if c.get("sub_mode") in ("none", "burn", "track") else "none")
        self.cb_srt.setChecked(bool(c.get("save_srt", False)))
        mode = c.get("mode") if c.get("mode") in EXT else "mp4"
        self.seg.set_value(mode)
        self._codec_changed(self.cb_codec.currentText())
        self._afmt_changed(self.cb_afmt.currentText())
        self._mode_changed(mode)
        geo = c.get("geometry")
        if geo:
            try:
                self.restoreGeometry(QtCore.QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        if c.get("layout_v") != 4 and not self.isMaximized():   # 2.5: tabs + player need a bit more room
            scr = self.screen().availableGeometry() if self.screen() else None
            w, h = max(self.width(), 1240), max(self.height(), 940)
            if scr is not None:
                w, h = min(w, scr.width() - 40), min(h, scr.height() - 40)
            self.resize(w, h)
            c["layout_v"] = 4
        self._aspect_changed()

    def _save_settings(self):
        self.cfg.update(
            quality=self.cb_quality.currentText(), size=self.cb_size.currentText(),
            encoder=self.cb_encoder.currentText(), mp3_quality=self.cb_mp3.currentText(),
            ai_up=next(k for k, v in AI_UPSCALES.items() if v == self.ai_factor), ai_px=self.ai_px,
            speed=self.cb_speed.currentText(),
            ai_model=self.ai_model,
            codec=self.cb_codec.currentText(), audio_format=self.cb_afmt.currentText(),
            tooltips=self.tip_filter.enabled,
            gif_width=self.cb_gif_w.currentText(), gif_fps=self.cb_gif_fps.currentText(),
            gif_colors=self.cb_gif_col.currentText(), outdir=self.outdir.text().strip(),
            mode=self.seg.value(), theme=self.theme, accent=self.accent, save_thumb=self.cb_thumb.isChecked(),
            volume=self.vol.value(), vol_restore=self._vol_restore, join=self.seg_join.value(),
            aspect=self.seg_aspect.value(),
            sub_mode=self.seg_submode.value(), save_srt=self.cb_srt.isChecked(),
            geometry=bytes(self.saveGeometry().toBase64()).decode())
        try:
            self.cfg["target_mb"] = float(self.target_mb.text().replace(",", "."))
        except ValueError:
            pass
        save_cfg(self.cfg)

    def apply_theme(self, theme, accent, save=True):
        self.theme, self.accent = theme, accent
        c = theme_colors(theme, accent)
        QtWidgets.QApplication.instance().setStyleSheet(build_qss(c))
        self.slider.set_colors(c)
        self.thumb.set_colors(c)
        self.lane.set_colors(c)
        self.btn_mute.set_colors(c)
        self.chip_account.set_colors(c)
        dlg = getattr(self, "settings_dlg", None)
        if dlg is not None and hasattr(dlg, "acc_card"):
            dlg.acc_card.set_colors(c)
        if self.canvas is not None:
            self.canvas.set_colors(c)
        set_dark_titlebar(self, c["dark"])
        if save:
            self.cfg.update(theme=theme, accent=accent)
            save_cfg(self.cfg)

    def set_tooltips(self, on):
        self.tip_filter.enabled = bool(on)
        if not on:
            QtWidgets.QToolTip.hideText()
        self.cfg["tooltips"] = bool(on)
        save_cfg(self.cfg)

    def _set_preview_mode(self, mode):
        self.cfg["preview_mode"] = mode
        save_cfg(self.cfg)

    def _set_auto_preview(self, on):
        self.cfg["auto_preview"] = bool(on)
        save_cfg(self.cfg)

    def _keep_pv(self) -> bool:
        return bool(self.cfg.get("keep_previews", False))

    def _set_dir(self, key, path):
        """New folder for the history or the small preview copies (None = default); what is there moves along."""
        new = Path(path) if path else DEFAULT_PATHS[key]
        old = Path(PATHS[key])
        if key == "history":
            try:
                n = history_move(new)
            except OSError as ex:
                return self._on_error(f"The history could not be moved: {clean_error(ex)}")
            self._on_log(f"History is now kept in {new} ({n} link{'s' if n != 1 else ''}).")
        else:
            try:
                new.mkdir(parents=True, exist_ok=True)
            except OSError as ex:
                return self._on_error(f"Invalid folder: {clean_error(ex)}")
            PATHS["preview"] = new
            files = preview_files(old) if old.resolve() != new.resolve() else []
            self._on_log(f"Small preview copies are now kept in {new}.")
            if files:
                def move():
                    done = 0
                    for f in files:
                        try:
                            shutil.move(str(f), str(new / f.name))
                            done += 1
                        except OSError:          # still open in the player
                            pass
                    self.emit("log", f"Moved {done} of {len(files)} preview cop{'ies' if len(files) != 1 else 'y'} "
                                     "to the new folder.")
                threading.Thread(target=move, daemon=True).start()
        self.cfg[f"{key}_dir"] = str(new) if path else ""
        save_cfg(self.cfg)

    def _settings(self):
        dlg = SettingsDialog(self, self.theme, self.accent, self.tip_filter.enabled,
                             self.apply_theme, self.set_tooltips, bool(self.cfg.get("auto_preview", True)),
                             self._set_auto_preview, self.cfg.get("preview_mode", "download"), self._set_preview_mode)
        self.settings_dlg = dlg
        dlg.exec()
        self.settings_dlg = None
        self._frame_info()

    def showEvent(self, e):
        super().showEvent(e)
        set_dark_titlebar(self, THEMES.get(self.theme, THEMES[DEFAULT_THEME])["dark"])

    # ------------------------------------------------------------------ format / size
    def _codec(self):
        return CODECS.get(self.cb_codec.currentText(), CODECS[DEFAULT_CODEC])

    def _afmt(self):
        return AUDIO_FORMATS.get(self.cb_afmt.currentText(), "mp3")

    def _ext(self, mode=None):
        mode = mode or self.seg.value()
        if mode == "mp4":
            return video_ext(self._codec()[0])
        if mode == "mp3":
            return "." + self._afmt()
        return ".gif"

    def _refresh_ext(self):
        self.lbl_ext.setText(self._ext())
        self._set_button_text()

    @staticmethod
    def _fit_stack(stack):
        """A stacked widget is as high as its current page (not as its biggest one)."""
        for i in range(stack.count()):
            pol = QtWidgets.QSizePolicy.Policy.Preferred if i == stack.currentIndex() else QtWidgets.QSizePolicy.Policy.Ignored
            stack.widget(i).setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, pol)
        stack.adjustSize()

    def _mode_changed(self, mode):
        self.stack.setCurrentIndex(["mp4", "mp3", "gif"].index(mode))
        self.tabs.set_shown("frame", mode != "mp3")      # audio has no picture
        self.tabs.set_shown("volume", mode != "gif")     # GIFs have no sound
        self._fit_stack(self.stack)
        self._fit_stack(self.tabstack)
        self._refresh_ext()
        self._update_clip_info()
        if self.canvas is not None:
            self.canvas.set_aspect(self._aspect(), self.box)
        self._frame_info()
        self._lane_range()
        self._subs_ui()

    def _codec_changed(self, _name=None):
        prores = self._codec()[0] == "prores"
        for w in (self.lbl_size, self.cb_size, self.lbl_encoder, self.cb_encoder):
            w.setVisible(not prores)
        self._size_changed(self.cb_size.currentText())
        self._refresh_ext()

    def _afmt_changed(self, _name=None):
        a = self._afmt()
        self.lbl_bitrate.setVisible(a != "wav")
        self.cb_mp3.setVisible(a != "wav")
        self.audio_hint.setText(AUDIO_HINTS[a])
        self._refresh_ext()

    def _is_local(self):
        return bool(self.info.get("local")) and self.info_url == self.url.text().strip()

    def _set_button_text(self):
        if not self.busy:
            local = self._is_local()
            mode, ext = self.seg.value(), self._ext()[1:].upper()
            verb = {"mp4": "Export" if local else "Download", "mp3": "Extract" if local else "Download",
                    "gif": "Create"}[mode]
            if self._multi():
                n = len(self.clips)
                if self.seg_join.value() == "join":
                    txt = f"{verb} {ext}  ·  {n} clip{'s' if n != 1 else ''} joined"
                else:
                    txt = f"{verb} {n} {ext}{'s' if n != 1 else ''}"
            else:
                txt = f"{verb} {ext}"
            self.btn.setText(txt)
            tip(self.btn, self.btn.text(), "Starts – the file is saved to the output folder. "
                                           "Enter in any field does the same.")

    def _size_changed(self, name):
        codec, profile = self._codec()
        mb = SIZES.get(name) == "mb" and codec != "prores"
        self._mp4_grid.removeWidget(self.cb_size)
        self._mp4_grid.addWidget(self.cb_size, 2, 1, 1, 1 if mb else 3)
        self.target_mb.setVisible(mb)
        self.lbl_mb.setVisible(mb)
        if codec == "prores":
            hint = PRORES_HINTS.get(profile, "") + " · audio as uncompressed PCM"
        elif codec == "hevc" and SIZES.get(name) is None:
            hint = "High-quality H.265 (the YouTube file is re-encoded)"
        else:
            hint = SIZE_HINTS.get(name, "")
        self.size_hint.setText(hint)

    # ------------------------------------------------------------------ preview fetch
    def _url_changed(self, text):
        self._fetch_timer.start()

    def _start_fetch(self):
        url = self.url.text().strip()
        if url == self.info_url and self.info:
            return
        self._req += 1
        req = self._req
        self.info, self.info_url = {}, ""
        self.slider.hide()
        self.btn_thumb.hide()
        self.vol_pts.clear()            # new video = new volume curve (before the player is touched)
        self.lane.select(None)
        self._reset_player()
        self._apply_gain(force=True)    # back to the plain volume of the slider
        self.clips, self.cur = [], 0
        self._refresh_clip_list()
        self._clear_times()
        self._set_button_text()
        self.btn_chapters.hide()
        self._sub_req += 1
        self._fill_subs([])
        self.box = None
        for c in self.clips:
            c.box = None
        if self.canvas is not None:
            self.canvas.clear()
            self.canvas.set_aspect(self._aspect())
        self._frame_info()
        lp = local_path(url)
        if lp:
            self.thumb.set_loading()
            self.vtitle.setText(lp.name)
            self.vmeta.setText("Reading file …")
            ffmpeg, ffprobe = self.ffmpeg, self.ffprobe

            def work_local():
                try:
                    if not ffprobe:
                        raise RuntimeError("FFprobe not found – please run the setup again.")
                    li = local_info(lp, ffprobe)
                    dur = li["duration"]
                    data = grab_frame(lp, min((dur or 0) * 0.1, 5.0), ffmpeg, width=960) \
                        if (ffmpeg and li["vcodec"]) else None
                    if li["vcodec"]:
                        parts = [f"{li['width']}×{li['height']}" if li["width"] else "",
                                 f"{li['fps']:.3g} fps" if li["fps"] else "", li["vcodec"]]
                    else:
                        parts = ["audio", li["acodec"] or ""]
                    meta = {"title": lp.stem, "local": str(lp), "duration": dur, "has_video": bool(li["vcodec"]),
                            "fps": li["fps"], "width": li["width"], "height": li["height"],
                            "chapters": li["chapters"], "subs": li["subs"],
                            "channel": "Your file  ·  " + " · ".join(x for x in parts if x)}
                    self.emit("meta", (req, url, meta, data))
                except Exception as ex:  # noqa: BLE001
                    self.emit("meta_err", (req, clean_error(ex)))
            threading.Thread(target=work_local, daemon=True).start()
            return
        if url and ANY_URL.match(url) and not YT_URL.match(url):
            self.thumb.set_text("Only YouTube links (and your own files) are supported.")
            self.vtitle.setText("")
            self.vmeta.setText("")
            self._update_clip_info()
            return
        if not re.match(r"https?://\S+\.\S+", url):
            self.thumb.set_text("Paste a YouTube link to see a preview")
            self.vtitle.setText("")
            self.vmeta.setText("")
            self._update_clip_info()
            return
        self.thumb.set_loading()
        self.vtitle.setText("Loading video info …")
        self.vmeta.setText("")

        def work():
            try:
                self.update_done.wait()
                info = fetch_info(url)
                data = None
                if info.get("thumb"):
                    try:
                        data = fetch_bytes(info["thumb"])
                    except Exception:
                        data = None
                self.emit("meta", (req, url, info, data))
            except Exception as ex:  # noqa: BLE001
                self.emit("meta_err", (req, clean_error(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _on_meta(self, val):
        req, url, info, data = val
        if req != self._req:
            return
        self.info, self.info_url = info, url
        dur = info.get("duration")
        badge = fmt_ts(dur) if dur else ""
        self.thumb.set_image(data, badge)
        self.vtitle.setText(info.get("title") or "")
        meta = [x for x in (info.get("channel"), fmt_ts(dur) if dur else "") if x]
        if info.get("playlist"):
            meta.append(f"playlist · {info['playlist']} videos (only the linked video is downloaded)")
        self.vmeta.setText("  ·  ".join(meta))
        if dur:
            self.slider.set_duration(dur)
            self.slider.show()
        self.btn_thumb.setVisible(bool(info.get("has_video")) if info.get("local")
                                  else bool(info.get("thumbs") or info.get("thumb")))
        self._times_committed()
        if self._multi():
            self._init_clips()
        self._update_clip_info()
        self._set_button_text()
        ch = info.get("chapters") or []
        self.btn_chapters.setText(f"≡  Chapters ({len(ch)})")
        self.btn_chapters.setVisible(len(ch) > 1)
        self._fill_subs(info.get("subs") or [])
        self._frame_info()
        self._lane_range()
        self._history_add(url, info, data)
        self._setup_preview(info, url)

    def _on_meta_err(self, val):
        req, msg = val
        if req != self._req:
            return
        self.btn_thumb.hide()
        first = (msg or "").splitlines()[0][:140] if msg else ""
        self.thumb.set_text("Couldn't load this video" + (f":\n{first}" if first else "."))
        self.vtitle.setText("")
        self.vmeta.setText((msg.splitlines()[0][:160] if msg else "") + login_hint(msg).replace("\n", "  "))
        self._update_clip_info()

    # ------------------------------------------------------------------ clip range
    def _duration(self):
        return self.info.get("duration") if self.info_url == self.url.text().strip() else None

    def _range(self):
        """-> (start, end) in seconds or None; raises ValueError for bad input."""
        s, e = parse_time(self.t_from.text()), parse_time(self.t_to.text())
        return s, e

    def _slider_changed(self, lo, hi):
        dur = self.slider.duration()
        self.t_from.setText("" if lo < 0.005 else fmt_tf(lo))
        self.t_to.setText("" if hi > dur - 0.005 else fmt_tf(hi))
        set_state(self.t_from, "")
        set_state(self.t_to, "")
        self._update_clip_info()

    def _times_edited(self, *_):
        self._update_clip_info()

    def _times_committed(self):
        try:
            s, e = self._range()
        except ValueError:
            return
        dur = self._duration()
        if dur and self.slider.isVisible():
            self.slider.set_range(s or 0.0, e if e is not None else dur)

    def _chip(self, secs):
        if secs is None:
            self._clear_times()
            if self.slider.isVisible():
                self.slider.set_range(0, self.slider.duration())
        else:
            try:
                s = parse_time(self.t_from.text()) or 0.0
            except ValueError:
                s = 0.0
            dur = self._duration()
            e = s + secs
            if dur:
                e = min(e, dur)
                s = max(0.0, min(s, e - 0.1))
            self.t_from.setText("" if s < 0.005 else fmt_tf(s))
            self.t_to.setText(fmt_tf(e))
            self._times_committed()
        self._update_clip_info()

    def _clear_times(self):
        self.t_from.setText("")
        self.t_to.setText("")

    def _update_clip_info(self):
        """Length label, hints (GIF limits) and the default file name."""
        if hasattr(self, "lane"):
            self._lane_range()
        if self._multi():
            return self._update_multi_info()
        mode = self.seg.value()
        dur = self._duration()
        ok = True
        try:
            s, e = self._range()
            set_state(self.t_from, "")
            set_state(self.t_to, "")
        except ValueError:
            bad = []
            for w in (self.t_from, self.t_to):
                try:
                    parse_time(w.text())
                    set_state(w, "")
                except ValueError:
                    set_state(w, "error")
                    bad.append(w)
            self.lbl_len.setText("")
            self._hint("Time not recognized – e.g. 10 (= minute 10), 1:30, 1:02:30 or 90s", "error")
            self._update_name(None, None)
            return
        if s is not None and e is not None and e <= s:
            self.lbl_len.setText("")
            self._hint("'to' must be after 'from'.", "error")
            self._update_name(s, e)
            return
        full = (s in (None, 0)) and e is None
        length = None
        if full:
            length = dur
        elif e is not None:
            length = e - (s or 0)
        elif dur:
            length = dur - (s or 0)
        if dur and s and s >= dur:
            self._hint("The start is past the end of the video.", "error")
            ok = False
        self.lbl_len.setText(("whole video · " if full else "clip · ") + fmt_ts(length) if length else
                             ("whole video" if full else ""))
        if ok:
            if mode == "gif":
                if length is None:
                    self._hint(f"Set a time range for the GIF (max {GIF_MAX} s).", "warn")
                elif length > GIF_MAX:
                    self._hint(f"GIFs can be at most {GIF_MAX} s – shorten the range (e.g. with the 10 s button).",
                               "error")
                elif length > GIF_RECOMMENDED:
                    self._hint(f"Works, but GIFs get big quickly – {GIF_RECOMMENDED} s or less is ideal.", "warn")
                else:
                    self._hint("Drag the handles or type times to pick the GIF part.", "")
            else:
                self._hint("Leave empty for the whole video, or drag the handles / type times "
                           "(10 = minute 10, 1:30, 90s).", "")
        self._update_name(s, e)

    def _hint(self, text, state):
        self.clip_hint.setText(text)
        set_state(self.clip_hint, state)

    def _default_name(self, s=None, e=None):
        title = self.info.get("title") if self.info_url == self.url.text().strip() else ""
        if not title:
            return ""
        if self._multi():
            return safe_name(f"{title}_{len(self.clips)} clips" if len(self.clips) != 1 else title + _suffix(*self.clips[0]))
        if s == 0 and e is None:
            s = None
        return safe_name(title + _suffix(s, e))

    def _update_name(self, s, e):
        d = self._default_name(s, e)
        self.name.setPlaceholderText(d or "File name (default: video title)")

    # ------------------------------------------------------------------ video preview (player)
    def _make_audio(self):
        try:
            a = QAudioOutput(self)
            a.setVolume(self.vol.value() / 100)
            self._out_vol = None          # next _apply_gain sets every output again
            return a
        except Exception:  # noqa: BLE001
            return None

    def _ensure_player(self):
        if self.player is None and PLAYER_OK and self.vview.video is not None:
            try:
                self.player = QMediaPlayer(self)
                self.audio_out = self._make_audio()
                if self.audio_out is not None:
                    self.player.setAudioOutput(self.audio_out)
                self.player.setVideoOutput(self.vview.video.sink)
                self.player.positionChanged.connect(self._on_ppos)
                self.player.durationChanged.connect(self._on_pdur)
                self.player.playbackStateChanged.connect(self._on_pstate)
                self.player.mediaStatusChanged.connect(self._on_mstatus)
                self.player.seekableChanged.connect(lambda ok: ok and self._seek_target is not None
                                                    and self._seek_timer.start())
                self.player.errorOccurred.connect(self._on_perror)
            except Exception as ex:  # noqa: BLE001
                self.player = None
                self._on_log(f"Video preview not available: {ex}")
        return self.player

    def _ensure_aplayer(self):
        if self.aplayer is None and PLAYER_OK:
            try:
                self.aplayer = QMediaPlayer(self)
                self.a_out2 = self._make_audio()
                if self.a_out2 is not None:
                    self.aplayer.setAudioOutput(self.a_out2)
                self.aplayer.errorOccurred.connect(self._on_aerror)
            except Exception:  # noqa: BLE001
                self.aplayer = None
        return self.aplayer

    def _audio_follows(self):
        return self.aplayer is not None and not self.aplayer.source().isEmpty()

    def _has_media(self):
        return self.player is not None and self._pv_state == "ready" and not self.player.source().isEmpty()

    def _reset_player(self):
        self._stop_playback()
        self._resetting = True          # setSource() sends position updates – don't react to them
        try:
            if self.player is not None:
                self.player.setSource(QtCore.QUrl())
            if self.aplayer is not None:
                self.aplayer.setSource(QtCore.QUrl())
        finally:
            self._resetting = False
        self._pv_state = ""
        self._pv_kind = ""
        self.thumb.set_overlay("")
        self.vview.show_video(False)
        if self.canvas is not None:
            self.canvas.clear()
        self.transport.hide()
        self.slider.set_playhead(None)
        self.seek.setRange(0, 0)
        self.ed_tc.setText("0:00.00")
        self.lbl_ptime.setText("/ 0:00")

    def _stop_playback(self):
        self._clip_stop = None
        if self.player is not None and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()

    def _pv_mode(self):
        return self.cfg.get("preview_mode", "download")

    def _head_account(self, acc):
        """Signed in: only the profile is in the header (a click opens the Settings); else the Settings button."""
        self.chip_account.set_account(acc)
        self.btn_settings.setVisible(not acc)

    def _stream_q(self):
        q = self.cfg.get("stream_q", "auto")
        return q if q == "auto" else int(q)

    def _cur_stream(self):
        sts = self.info.get("streams") or {}
        return sts.get(self._stream_q()) or sts.get("auto") or self.info.get("stream")

    def _pv_src_menu(self):
        """Click on 'streaming from YouTube' / 'preview copy': switch the preview right here."""
        if self._pv_kind not in ("stream", "copy") or not self._is_info_current() or self.info.get("local"):
            return
        m = QtWidgets.QMenu(self)
        sts = self.info.get("streams") or {}
        h = m.addAction("Stream from YouTube")
        h.setEnabled(False)
        grp = QtGui.QActionGroup(m)
        can = self._can_stream()
        auto_h = ((sts.get("auto") or {}).get("video") or {}).get("height")
        for q in ["auto", *[k for k in sts if k != "auto"]]:
            a = m.addAction("Auto" + (f" ({auto_h}p)" if auto_h else "") if q == "auto" else f"{q}p")
            a.setCheckable(True)
            a.setChecked(self._pv_kind == "stream" and q == self._stream_q())
            a.setEnabled(can)
            a.setActionGroup(grp)
            a.triggered.connect(lambda _=False, q=q: self._switch_preview("stream", q))
        m.addSeparator()
        a = m.addAction(f"Download small copy ({preview_height(self.info.get('duration'))}p)")
        a.setCheckable(True)
        a.setChecked(self._pv_kind == "copy")
        a.setActionGroup(grp)
        a.triggered.connect(lambda: self._switch_preview("download"))
        m.exec(self.lbl_pv_src.mapToGlobal(QtCore.QPoint(0, self.lbl_pv_src.height() + 2)))

    def _switch_preview(self, mode, q=None):
        """Changes the preview source and quality, stays at the same spot."""
        pos = self._player_pos() or 0.0
        self.cfg["preview_mode"] = mode
        if q is not None:
            self.cfg["stream_q"] = q
        save_cfg(self.cfg)
        if getattr(self, "settings_dlg", None) is not None:
            try:
                self.settings_dlg.seg_pv.set_value(mode)
            except Exception:  # noqa: BLE001 - dialog closed / no such control
                pass
        self._resume_play = self.player is not None and \
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._stop_playback()
        self._resume_at = pos
        url = self.info_url
        if mode == "stream" and self._can_stream(url):
            self._start_stream()
        elif url in self._pv_cache and Path(self._pv_cache[url]).exists():
            self._load_player(self._pv_cache[url], True, kind="copy")
        else:
            kept = find_preview(self.info)
            if kept is not None:
                self._pv_cache[url] = str(kept)
                self._load_player(str(kept), True, kind="copy")
            else:
                self._load_preview()

    def _can_stream(self, url=None):
        url = url or self.info_url
        return bool(self.info.get("stream")) and url not in self._stream_failed

    def _setup_preview(self, info, url):
        """After the video info: own files play directly; YouTube videos are streamed through the app
        (or a small copy is downloaded, depending on Settings)."""
        if not PLAYER_OK or self.vview.video is None:
            return
        if info.get("local"):
            self._load_player(info["local"], bool(info.get("has_video")), kind="file")
            return
        if url in self._pv_cache and Path(self._pv_cache[url]).exists():
            self._load_player(self._pv_cache[url], True, kind="copy")
            return
        kept = find_preview(info)
        if kept is not None:              # copy from an earlier time (Settings → keep the small copies)
            self._pv_cache[url] = str(kept)
            self._load_player(str(kept), True, kind="copy")
            return
        auto = self.cfg.get("auto_preview", True)
        dur = info.get("duration") or 0
        if self._pv_mode() == "stream" and self._can_stream(url):
            if auto:
                self._start_stream()
            else:
                self._pv_state = "offer"
                self.thumb.set_overlay("▶  Play preview  (streamed, no download)")
            return
        if auto and dur and dur <= PREVIEW_AUTO_MAX:
            self._load_preview()
        else:
            self._pv_state = "offer"
            mb = f"  (≈ {preview_mb(dur)} MB)" if dur else ""
            self.thumb.set_overlay(f"▶  Load video preview{mb}")

    def _thumb_clicked(self):
        if self._pv_state in ("offer", "error") and self._is_info_current() and not self.info.get("local"):
            if self._pv_mode() == "stream" and self._can_stream():
                self._start_stream()
            else:
                self._load_preview()
        elif self._has_media():
            self._toggle_play()

    def _start_stream(self):
        st = self._cur_stream()
        if not st:
            return self._load_preview()
        try:
            if self._proxy is None:
                self._proxy = StreamProxy()
            v = self._proxy.add(st["video"])
            a = self._proxy.add(st["audio"]) if st.get("audio") else None
        except Exception as ex:  # noqa: BLE001
            self._on_log(f"Streaming not possible ({ex}) – downloading a small copy instead.")
            self._stream_failed.add(self.info_url)
            return self._load_preview()
        self._load_player(v, True, audio_url=a, kind="stream")

    def _load_preview(self):
        url, req = self.info_url, self._req
        if not url or not self.ffmpeg:
            return
        self._pv_state = "loading"
        self.thumb.set_overlay("Loading video preview …", 0.0)
        self.vview.show_video(False)
        self.transport.hide()
        root = preview_dir()
        outdir = root / f".dl_{req}"
        ffmpeg = self.ffmpeg
        dur = self.info.get("duration") if self._is_info_current() else None
        name = preview_name({**self.info, "duration": dur}) if self._is_info_current() else f"video [p{req}] preview 360p"

        def em(kind, val=None):
            if kind == "progress" and val is not None:
                self.emit("pv_progress", (req, float(val)))

        def work():
            try:
                self.update_done.wait()
                tmp = preview_video(url, outdir, ffmpeg=ffmpeg, emit=em, duration=dur)
                path = root / (name + tmp.suffix)
                try:
                    os.replace(tmp, path)
                except OSError:          # an older copy with this name is still open -> use the new one as it is
                    path = tmp
                else:
                    shutil.rmtree(outdir, ignore_errors=True)
                self.emit("pv_ready", (req, url, str(path)))
            except Exception as ex:  # noqa: BLE001
                shutil.rmtree(outdir, ignore_errors=True)
                self.emit("pv_err", (req, clean_error(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _on_pv_progress(self, val):
        req, pct = val
        if req == self._req and self._pv_state == "loading":
            self.thumb.set_overlay(f"Loading video preview … {pct:.0f} %", pct / 100)

    def _on_pv_ready(self, val):
        req, url, path = val
        self._pv_cache[url] = path
        if req == self._req:
            self._load_player(path, True, kind="copy")

    def _on_pv_err(self, val):
        req, msg = val
        if req != self._req:
            return
        self._pv_state = "error"
        self.thumb.set_overlay("▶  Preview failed – click to try again")
        self._on_log("Preview: " + msg)
        if not self.busy:
            self.status.setText("✕  Preview: " + (msg.splitlines()[0][:180] if msg else "failed") + login_hint(msg))
            set_state(self.status, "error")

    def _load_player(self, src, has_video, audio_url=None, kind="copy"):
        if self._ensure_player() is None:
            return
        self._pv_state = "ready"
        self._pv_kind = kind
        self.thumb.set_overlay("")
        url = QtCore.QUrl(src) if str(src).startswith("http") else QtCore.QUrl.fromLocalFile(str(src))
        self.player.setSource(url)
        if audio_url and self._ensure_aplayer() is not None:
            self.aplayer.setSource(QtCore.QUrl(audio_url))
        elif self.aplayer is not None:
            self.aplayer.setSource(QtCore.QUrl())
        self.player.pause()      # shows the first frame
        self._speed_changed()
        self.transport.show()
        self.vview.show_video(has_video)
        site = "YouTube"
        sh = ((self._cur_stream() or {}).get("video") or {}).get("height") if kind == "stream" else None
        ch = preview_height(self.info.get("duration")) if kind == "copy" else None
        self.lbl_pv_src.setText({"stream": f"streaming from {site}" + (f" · {sh}p" if sh else "") + "  ▾",
                                 "copy": f"preview copy ({ch}p)  ▾", "file": "your file"}.get(kind, ""))
        self.lbl_pv_src.setEnabled(kind != "file")
        tip(self.lbl_pv_src, "Preview source", {
            "stream": f"Played straight from {site} through the app – nothing is downloaded for the preview. "
                      "Click to pick the quality or switch to a downloaded copy.",
            "copy": "A small copy, only for the preview – your download uses the quality you pick. Click to "
                    "stream from YouTube instead.",
            "file": "Your own file is played directly."}.get(kind, ""))
        resume = getattr(self, "_resume_at", None)
        self._resume_at = None
        rng = self._cur_range()
        if resume:
            self._resume_check = (max(0.0, resume), 0)
            self._seek_to(resume)
            if getattr(self, "_resume_play", False):
                self._resume_play = False
                QtCore.QTimer.singleShot(700, lambda: self._has_media() and self.player.play())
        elif rng and rng[0] > 0:
            self._seek_to(rng[0])

    def _on_mstatus(self, st):
        if st in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) \
                and self._seek_target is not None:
            self._seek_timer.start()

    def _on_perror(self, *_):
        if self.player is None or not self.player.errorString():
            return
        msg = self.player.errorString()
        if self._pv_kind == "stream" and self._is_info_current():
            yt = self._proxy.last_error if self._proxy is not None else ""
            self._on_log(f"Streaming the preview failed ({msg}{'; YouTube: ' + yt if yt else ''}) – downloading a "
                         "small copy instead.")
            self._stream_failed.add(self.info_url)
            self.player.setSource(QtCore.QUrl())
            if self.aplayer is not None:
                self.aplayer.setSource(QtCore.QUrl())
            self._load_preview()
        else:
            self._on_log(f"Preview player: {msg}")

    def _on_aerror(self, *_):
        if self.aplayer is not None and self.aplayer.errorString():
            self._on_log(f"Preview sound not available: {self.aplayer.errorString()}")
            self.aplayer.setSource(QtCore.QUrl())

    def _fps(self):
        f = self.info.get("fps") if self._is_info_current() else None
        if self._pv_kind == "stream":
            f = (self.info.get("stream") or {}).get("fps") or f
        return float(f) if f and 1 <= float(f) <= 240 else 30.0

    def _on_pdur(self, ms):
        self.seek.setRange(0, max(0, ms))
        self.lbl_ptime.setText(f"/ {fmt_ts(ms / 1000)}")

    def _on_ppos(self, ms):
        if self._resetting:
            return
        t = ms / 1000
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        if not self.ed_tc.hasFocus():
            self.ed_tc.setText(fmt_tc(t))
            set_state(self.ed_tc, "")
        self.slider.set_playhead(t)
        self.lane.set_playhead(t)
        self._update_sub_overlay(t)
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if self.vol_pts and playing:
            self._apply_gain(t)
        if playing and self._audio_follows() and abs(self.aplayer.position() - ms) > 250:
            self.aplayer.setPosition(ms)
        if self._clip_stop is not None and t >= self._clip_stop - 0.02:
            self._clip_stop = None
            self.player.pause()

    def _on_pstate(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("❚❚" if playing else "▶")
        if playing and self.vol_pts:
            self._apply_gain(force=True)
        if self._audio_follows():
            if playing:
                self.aplayer.setPosition(self.player.position())
                self.aplayer.play()
            else:
                self.aplayer.pause()

    def _on_volume(self, v):
        self.btn_mute.set_level(v)
        self._vol_settle.start()            # remember the level once it stays put (not the steps on the way to 0)
        self._apply_gain(force=True)

    def _remember_vol(self):
        if self.vol.value() > 0 and not self.vol.isSliderDown():
            self._vol_restore = self.vol.value()

    def _toggle_mute(self):
        v = self.vol.value()
        if v > 0:
            self._vol_settle.stop()
            self._vol_restore = v
            self.vol.setValue(0)
        else:
            self.vol.setValue(self._vol_restore if self._vol_restore > 0 else 80)
            self._vol_settle.stop()

    def _toggle_play(self):
        if not self._has_media():
            if self._pv_state in ("offer", "error") and self._is_info_current():
                self._thumb_clicked()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self._clip_stop = None
            self.player.play()

    def _cur_range(self):
        """Start/end of the clip being edited (empty fields -> 0 / end of the video)."""
        try:
            s, e = self._range()
        except ValueError:
            return None
        dur = self._duration() or 0
        s = s or 0.0
        e = dur if e is None else e
        return (s, e) if e > s else None

    def _set_pos(self, t):
        ms = int(round(max(0.0, t) * 1000))
        self.player.setPosition(ms)
        if self._audio_follows():
            self.aplayer.setPosition(ms)
        self._pos_hint = (t, time.monotonic())
        self.slider.set_playhead(t)
        if not self.ed_tc.hasFocus():
            self.ed_tc.setText(fmt_tc(t))
            set_state(self.ed_tc, "")

    def _play_clip(self, rng=None):
        rng = rng or self._cur_range()
        if not self._has_media() or not rng:
            return
        self._set_pos(rng[0])
        self._clip_stop = rng[1]
        self.player.play()

    def _seek_to(self, t):
        self._seek_target = max(0.0, t)
        self._pos_hint = (self._seek_target, time.monotonic())
        if not self._seek_timer.isActive():
            self._seek_timer.start()

    def _do_seek(self):
        if self._seek_target is None or not self._has_media():
            return
        st = self.player.mediaStatus()
        ready = st in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
                       QMediaPlayer.MediaStatus.BufferingMedia, QMediaPlayer.MediaStatus.EndOfMedia)
        if not ready or not self.player.isSeekable():
            return          # mediaStatusChanged / seekableChanged try again
        t = self._seek_target
        self._set_pos(t)
        if self._resume_check is not None and self._resume_check[0] == t:
            QtCore.QTimer.singleShot(450, self._check_resume)
        else:
            self._seek_target = None

    def _check_resume(self):
        """After switching the preview: did the jump really happen? (Streams sometimes ignore the first one.)"""
        chk = self._resume_check
        if chk is None or not self._has_media():
            self._seek_target = None
            return
        t, tries = chk
        if abs(self.player.position() / 1000 - t) < 1.0 or tries >= 6:
            self._resume_check, self._seek_target = None, None
            return
        self._resume_check = (t, tries + 1)
        self._seek_target = t
        self._seek_timer.start()

    def _on_handle_dragged(self, _which, t):
        if self._has_media() and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._seek_to(t)

    def _player_pos(self):
        if not self._has_media():
            return None
        t, when = self._pos_hint
        if t is not None and time.monotonic() - when < 0.6:   # a jump that the player hasn't reported yet
            return t
        return self.player.position() / 1000

    def _step(self, frames):
        """Move by whole frames (pauses first)."""
        if not self._has_media():
            return
        self._stop_playback()
        fd = 1.0 / self._fps()
        t = self._player_pos() or 0.0
        n = round(t / fd) + frames
        dur = self.player.duration() / 1000 if self.player.duration() > 0 else None
        target = max(0.0, n * fd)
        if dur:
            target = min(target, max(0.0, dur - fd))
        self._seek_to(target)

    def _nudge(self, d):
        if self._has_media():
            self._stop_playback()
            self._seek_to((self._player_pos() or 0.0) + d)

    def _tc_entered(self):
        try:
            t = parse_time(self.ed_tc.text())
        except ValueError:
            set_state(self.ed_tc, "error")
            return
        if t is None or not self._has_media():
            return
        set_state(self.ed_tc, "")
        dur = self.player.duration() / 1000 if self.player.duration() > 0 else None
        if dur:
            t = min(t, dur)
        self._stop_playback()
        self._seek_to(t)
        self.ed_tc.clearFocus()

    def _set_in(self):
        t = self._player_pos()
        if t is None or not self.slider.isVisible() or self.busy:
            return
        lo, hi = self.slider.values()
        if t >= hi - 0.1:
            hi = min(self.slider.duration(), t + max(1.0, hi - lo))
        self.slider.set_range(t, hi)
        self._slider_changed(*self.slider.values())

    def _set_out(self):
        t = self._player_pos()
        if t is None or not self.slider.isVisible() or self.busy:
            return
        lo, hi = self.slider.values()
        if t <= lo + 0.1:
            lo = max(0.0, t - max(1.0, hi - lo))
        self.slider.set_range(lo, t)
        self._slider_changed(*self.slider.values())

    def keyPressEvent(self, e):   # arrows only arrive here when no field / list / slider uses them
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self._has_media():
            d = 1 if e.key() == Qt.Key.Key_Right else -1
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._nudge(d * 1.0)
            else:
                self._step(d)
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------ several clips
    def _multi(self):
        return self.seg_clips.value() == "multi"

    def _clip_mode_changed(self, mode):
        multi = mode == "multi"
        self.multi_box.setVisible(multi)
        if multi:
            self._init_clips()
        else:
            self.slider.set_others([])
            if self.clips:
                self._load_range(*self.clips[self.cur])
        self._update_clip_info()
        self._set_button_text()

    def _init_clips(self):
        if self.clips or not self._duration():
            self._refresh_clip_list()
            return
        dur = self._duration()
        rng = self._cur_range()
        if not rng or (rng[0] == 0 and rng[1] >= dur - 0.05):
            rng = (0.0, min(dur, 10.0))
        self.clips = [Clip(*rng, box=self.box)]
        self.cur = 0
        self._refresh_clip_list()
        self._load_range(*rng)

    def _refresh_clip_list(self):
        self.clip_list.blockSignals(True)
        self.clip_list.clear()
        n = len(self.clips)
        for i, c in enumerate(self.clips):
            it = QtWidgets.QListWidgetItem()
            row = ClipRow(i, c[0], c[1], n, name=getattr(c, "label", ""))
            row.action.connect(self._clip_action)
            it.setSizeHint(QtCore.QSize(0, 34))
            self.clip_list.addItem(it)
            self.clip_list.setItemWidget(it, row)
        if n:
            self.cur = min(self.cur, n - 1)
            self.clip_list.setCurrentRow(self.cur)
        self.clip_list.blockSignals(False)
        self._update_others()
        total = sum(e - s for s, e in self.clips)
        self.lbl_clips.setText(f"{n} · {fmt_ts(total)}" if n else "")

    def _update_others(self):
        self.slider.set_others([(s, e, i + 1) for i, (s, e) in enumerate(self.clips) if i != self.cur]
                               if self._multi() else [])

    def _load_range(self, s, e):
        """Shows a clip in the timeline and the time fields."""
        self._loading_clip = True
        dur = self._duration() or e
        self.t_from.setText("" if s < 0.005 else fmt_tf(s))
        self.t_to.setText("" if e > dur - 0.005 else fmt_tf(e))
        if self.slider.isVisible():
            self.slider.set_range(s, e)
        self._loading_clip = False

    def _select_clip(self, row):
        if row < 0 or row >= len(self.clips):
            return
        self.cur = row
        s, e = self.clips[row]
        self._load_range(s, e)
        self._update_others()
        self._update_clip_info()
        if self._aspect():
            self.box = self.clips[row].box
            if self.canvas is not None:
                self.canvas.set_box(self.box)
                self.box = self.canvas.box
                self.clips[row].box = self.box
            self._frame_info()
        if self._has_media():
            self._stop_playback()
            self._seek_to(s)

    def _store_current(self):
        if self._loading_clip or not self.clips or self.cur >= len(self.clips):
            return
        rng = self._cur_range()
        if not rng or [round(x, 3) for x in rng] == [round(x, 3) for x in self.clips[self.cur]]:
            return
        self.clips[self.cur][:] = list(rng)
        it = self.clip_list.item(self.cur)
        row = self.clip_list.itemWidget(it) if it is not None else None
        if row is not None:
            row.set_clip(self.cur, rng[0], rng[1], len(self.clips))
        self.lbl_clips.setText(f"{len(self.clips)} · {fmt_ts(sum(e - s for s, e in self.clips))}")

    def _add_clip(self):
        dur = self._duration()
        if not dur:
            return
        start = None
        t = self._player_pos()
        if t is not None and not any(s <= t < e for s, e in self.clips):
            start = t
        if start is None:
            start = max((e for _s, e in self.clips), default=0.0)
        if start >= dur - 0.5:
            start = max(0.0, dur - 5.0)
        self.clips.append(Clip(start, min(dur, start + 5.0), box=self.box))
        self.cur = len(self.clips) - 1
        self._refresh_clip_list()
        self._select_clip(self.cur)
        self._set_button_text()

    def _clip_action(self, what, i):
        if i >= len(self.clips) or self.busy:
            return
        if what == "play":
            self._select_clip(i)
            self._play_clip(tuple(self.clips[i]))
            return
        if what == "del":
            self.clips.pop(i)
            if self.cur >= i and self.cur > 0:
                self.cur -= 1
        elif what in ("up", "down"):
            j = i - 1 if what == "up" else i + 1
            if 0 <= j < len(self.clips):
                self.clips[i], self.clips[j] = self.clips[j], self.clips[i]
                self.cur = j
        self._refresh_clip_list()
        if self.clips:
            self._select_clip(self.cur)
        else:
            self._update_clip_info()
        self._set_button_text()

    def _update_multi_info(self):
        self._store_current()
        n = len(self.clips)
        total = sum(e - s for s, e in self.clips)
        self.lbl_len.setText(f"{n} clip{'s' if n != 1 else ''} · {fmt_ts(total)}" if n else "")
        mode, join = self.seg.value(), self.seg_join.value() == "join"
        try:
            s, e = self._range()
            bad = s is not None and e is not None and e <= s
        except ValueError:
            bad = True
        if bad:
            self._hint("Time not recognized or 'to' before 'from' – this clip keeps its last valid times.", "error")
        elif not n:
            self._hint("Add a clip with “+ Add clip”.", "warn")
        elif mode == "gif" and join and total > GIF_MAX:
            self._hint(f"Joined GIFs can be at most {GIF_MAX} s – now {total:.1f} s.", "error")
        elif mode == "gif" and not join and any(b - a > GIF_MAX for a, b in self.clips):
            self._hint(f"Each GIF can be at most {GIF_MAX} s.", "error")
        else:
            self._hint(f"Editing clip {self.cur + 1}: drag the handles, type times, or press ⇤ Start / End ⇥ "
                       "while the preview plays. Pick another clip in the list on the right.", "")
        title = self.info.get("title") if self._is_info_current() else ""
        if join:
            self.name.setPlaceholderText(self._default_name() or "File name (default: video title)")
        else:
            self.name.setPlaceholderText((safe_name(title) + "_01, _02 …") if title
                                         else "File name (default: video title)")
        self._set_button_text()

    # ------------------------------------------------------------------ events from worker threads
    def emit(self, kind, val=None):
        self.bridge.sig.emit(kind, val)

    def _dispatch(self, kind, val):
        getattr(self, f"_on_{kind}")(val)
        if LOGIN_NOTE and not self._login_noted:
            self._login_noted = True
            self._on_log("WARNING: " + LOGIN_NOTE[0])
            if not self.busy:
                self.status.setText("⚠  " + LOGIN_NOTE[0])
                set_state(self.status, "error")

    def _on_log(self, msg):
        self.log.appendPlainText(str(msg).rstrip())
        if logged_in() and re.search(r"no longer valid|likely been rotated", str(msg), re.I) \
                and not getattr(self, "_login_warned", False):
            self._login_warned = True
            self.status.setText("⚠  Your YouTube login has expired – Settings → YouTube login → Sign out, then sign in "
                                "again.")
            set_state(self.status, "error")

    def _on_status(self, text):
        set_state(self.status, "")
        self.status.setText(text)

    def _on_progress(self, pct):
        if pct is None:
            self._pb_anim.stop()
            self.pb.setRange(0, 0)
            return
        if self.pb.maximum() == 0:
            self.pb.setRange(0, 1000)
            self.pb.setValue(0)
        self._pb_anim.stop()
        self._pb_anim.setStartValue(self.pb.value())
        self._pb_anim.setEndValue(int(pct * 10))
        self._pb_anim.start()

    def _on_done(self, files):
        self._set_busy(False)
        self._on_progress(100)
        self.last_files = files

        def mb(f):
            try:
                return f" ({Path(f).stat().st_size / 1048576:.1f} MB)"
            except OSError:
                return ""
        names = ", ".join(Path(f).name + mb(f) for f in files)
        self.btn_show.setEnabled(True)
        self.status.setText(f"✓  Done: {names}")
        set_state(self.status, "ok")
        self._on_log(f"✓ {names}")
        QtWidgets.QApplication.alert(self)
        self.name.clear()

    def _on_error(self, msg):
        self._set_busy(False)
        self._on_progress(0)
        msg = (msg or "Unknown error").strip()
        self.status.setText("✕  " + msg.splitlines()[0][:200])
        set_state(self.status, "error")
        self._on_log("✕ " + msg)
        if len(msg.splitlines()) > 1 and not self.log.isVisible():
            self._toggle_log()

    def _on_updated(self, ok):
        self.update_done.set()
        self.btn_upd.setEnabled(True)
        self._check_ytdlp()
        if ok:
            self.cfg["last_update"] = time.time()
            save_cfg(self.cfg)
            if "yt_dlp" in sys.modules:
                self._on_log("The new yt-dlp version takes effect after restarting the app.")
        if not self.busy:
            self._on_status("Ready.")

    def _set_busy(self, busy):
        self.busy = busy
        for w in (self.url, self.btn_paste, self.btn_file, self.t_from, self.t_to, self.slider, self.seg, self.tabstack,
                  self.name, self.outdir, self.btn_browse, self.btn_upd, self.cb_thumb, self.btn_thumb, *self.chips,
                  self.seg_clips, self.multi_box, self.btn_set_in, self.btn_set_out, self.btn_hist, self.btn_still,
                  self.btn_chapters, self.btn_app_upd):
            w.setEnabled(not busy)
        self.btn.setEnabled(not busy)
        if busy:
            self.btn.setText("Working …")
        else:
            self._set_button_text()

    # ------------------------------------------------------------------ actions
    def start(self):
        if self.busy:
            return
        url = self.url.text().strip()
        if not url:
            return self._on_error("Paste a link first.")
        if ANY_URL.match(url) and not YT_URL.match(url):
            return self._on_error("Only YouTube links (and your own files) are supported.")
        if self._multi():
            return self._start_multi(url)
        try:
            s, e = self._range()
        except ValueError:
            return self._on_error("Time not recognized – e.g. 10, 1:30, 1:02:30 or 90s")
        if s is not None and e is not None and e <= s:
            return self._on_error("'to' must be after 'from'.")
        if s == 0 and e is None:
            s = None
        if not self.ffmpeg:
            return self._on_error("FFmpeg not found – please run the setup again.")
        mode = self.seg.value()
        dur = self._duration()
        if mode == "gif":
            end = e if e is not None else dur
            if end is None:
                return self._on_error(f"Set a time range for the GIF (max {GIF_MAX} s).")
            if end - (s or 0) > GIF_MAX + 0.01:
                return self._on_error(f"GIFs can be at most {GIF_MAX} s – shorten the time range.")
        outdir = Path(self.outdir.text().strip() or Path.home() / "Downloads")
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            return self._on_error(f"Invalid folder: {ex}")
        name = self.name.text().strip() or self._default_name(s, e)
        ext = self._ext(mode)
        name = unique_name(outdir, name, ext) if name else None
        fx = self._fx(mode)
        if fx_needed(mode, fx):
            if not self._is_info_current() or not dur:
                return self._on_error("Wait until the video info is loaded (needed for crop, volume and subtitles).")
            return self._start_multi(url, single=((s or 0.0), e if e is not None else dur), name=name)
        lp = local_path(url)
        if lp and self._is_local():
            has_video = self.info.get("has_video", True)
            if mode in ("mp4", "gif") and not has_video:
                return self._on_error("This file has no video – choose Audio.")
        src = lp if lp else url
        thumb = None
        if self.cb_thumb.isChecked() and (not lp or self.info.get("has_video", True)):
            dur_ = self._duration() or 0
            at = s if s else min(dur_ * 0.1, 5.0)
            thumb = (url, None if lp or not self._is_info_current() else self.info, at, self._ai())

        kw = {}
        if mode == "mp4":
            size = self.cb_size.currentText()
            codec, profile = self._codec()
            kw = {"codec": codec, "profile": profile}
            target_mb = None
            if SIZES.get(size) == "mb" and codec != "prores":
                try:
                    target_mb = float(self.target_mb.text().replace(",", ".").lower().replace("mb", "").strip())
                    if target_mb <= 0:
                        raise ValueError
                except ValueError:
                    return self._on_error("Target size not recognized – e.g. 50")
            args = (src, s, e, QUALITIES.get(self.cb_quality.currentText()), self.cb_encoder.currentText(),
                    size, target_mb, outdir)
            desc = f"{self.cb_codec.currentText()} · {self.cb_quality.currentText()}"
            if codec != "prores":
                desc += f" · {f'{target_mb:g} MB' if target_mb else size}"
        elif mode == "mp3":
            afmt = self._afmt()
            kw = {"afmt": afmt}
            args = (src, s, e, MP3_QUALITIES.get(self.cb_mp3.currentText(), 320), outdir)
            desc = afmt.upper() + ("" if afmt == "wav" else f" · {self.cb_mp3.currentText()}")
        else:
            args = (src, s, e, GIF_WIDTHS[self.cb_gif_w.currentText()], GIF_FPS[self.cb_gif_fps.currentText()],
                    GIF_COLORS[self.cb_gif_col.currentText()], outdir)
            desc = f"GIF · {self.cb_gif_w.currentText()} · {self.cb_gif_fps.currentText()}"
        self._save_settings()

        rng = "whole video" if s is None and e is None else f"{fmt_ts(s or 0)} – {fmt_ts(e) if e is not None else 'end'}"
        self._on_log(f"\n— {url}\n  {rng} · {desc}" + (f" · {name}{ext}" if name else ""))
        self._set_busy(True)
        self.btn_show.setEnabled(False)
        self._on_status("Starting …")
        self._on_progress(None)
        fn = ({"mp4": local_mp4, "mp3": local_mp3, "gif": local_gif} if lp else
              {"mp4": download, "mp3": download_mp3, "gif": make_gif})[mode]
        srt = self._srt_job()
        if srt:
            kw["_srt"] = ([((s or 0.0), e if e is not None else (dur or 1e9))], srt, True)
        threading.Thread(target=self._worker, args=(fn, args, name, thumb, bool(lp), kw), daemon=True).start()

    def _is_info_current(self):
        return bool(self.info) and self.info_url == self.url.text().strip()

    def _format_params(self):
        """-> (params for export_multi, description) or raises ValueError with a message."""
        mode = self.seg.value()
        if mode == "mp4":
            size = self.cb_size.currentText()
            codec, profile = self._codec()
            target_mb = None
            if SIZES.get(size) == "mb" and codec != "prores":
                try:
                    target_mb = float(self.target_mb.text().replace(",", ".").lower().replace("mb", "").strip())
                    if target_mb <= 0:
                        raise ValueError
                except ValueError:
                    raise ValueError("Target size not recognized – e.g. 50") from None
            p = {"height": QUALITIES.get(self.cb_quality.currentText()), "encoder": self.cb_encoder.currentText(),
                 "size": size, "target_mb": target_mb, "codec": codec, "profile": profile}
            desc = f"{self.cb_codec.currentText()} · {self.cb_quality.currentText()}"
            if codec != "prores":
                desc += f" · {f'{target_mb:g} MB' if target_mb else size}"
            return p, desc
        if mode == "mp3":
            afmt = self._afmt()
            return ({"kbps": MP3_QUALITIES.get(self.cb_mp3.currentText(), 320), "afmt": afmt},
                    afmt.upper() + ("" if afmt == "wav" else f" · {self.cb_mp3.currentText()}"))
        return ({"width": GIF_WIDTHS[self.cb_gif_w.currentText()], "fps": GIF_FPS[self.cb_gif_fps.currentText()],
                 "colors": GIF_COLORS[self.cb_gif_col.currentText()]},
                f"GIF · {self.cb_gif_w.currentText()} · {self.cb_gif_fps.currentText()}")

    def _start_multi(self, url, single=None, name=None):
        clips = [single] if single else [(c[0], c[1], getattr(c, "label", "")) for c in self.clips]
        if not clips:
            return self._on_error("Add at least one clip.")
        if not self._is_info_current() or not self._duration():
            return self._on_error("Wait until the video info is loaded.")
        if any(c[1] <= c[0] for c in clips):
            return self._on_error("A clip ends before it starts – check the clip list.")
        if not self.ffmpeg:
            return self._on_error("FFmpeg not found – please run the setup again.")
        mode = self.seg.value()
        join = self.seg_join.value() == "join" or bool(single)
        if mode == "gif":
            if join and sum(c[1] - c[0] for c in clips) > GIF_MAX + 0.01:
                return self._on_error(f"Joined GIFs can be at most {GIF_MAX} s – shorten or remove clips.")
            if not join and any(c[1] - c[0] > GIF_MAX + 0.01 for c in clips):
                return self._on_error(f"GIFs can be at most {GIF_MAX} s each – shorten the long clips.")
        lp = local_path(url)
        if lp and mode in ("mp4", "gif") and not self.info.get("has_video", True):
            return self._on_error("This file has no video – choose Audio.")
        try:
            params, desc = self._format_params()
        except ValueError as ex:
            return self._on_error(str(ex))
        outdir = Path(self.outdir.text().strip() or Path.home() / "Downloads")
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            return self._on_error(f"Invalid folder: {ex}")
        ext = self._ext(mode)
        fx = self._fx(mode)
        if single:
            name = name or unique_name(outdir, self._default_name(*single) or "clip", ext)
        else:
            name = self.name.text().strip()
            if join:
                name = unique_name(outdir, name or self._default_name(), ext)
            elif name:
                name = safe_name(name)
            elif any(len(c) > 2 and c[2] for c in clips):     # chapter names -> "Title_01 Intro" …
                name = safe_name(self.info.get("title") or "clip")
            else:
                name = None
        thumb = None
        if self.cb_thumb.isChecked() and (not lp or self.info.get("has_video", True)):
            thumb = (url, None if lp else self.info, clips[0][0], self._ai())
        self._save_settings()
        span = ", ".join(f"{fmt_ts(c[0])}–{fmt_ts(c[1])}" for c in clips)
        self._on_log(f"\n— {url}\n  {len(clips)} clips ({span}) · {'joined' if join else 'separate files'} · {desc}"
                     + (f" · {name}{ext if join else ''}" if name else ""))
        self._stop_playback()
        self._set_busy(True)
        self.btn_show.setEnabled(False)
        self._on_status("Starting …")
        self._on_progress(None)
        kw = {"local": bool(lp), "join": join, "params": params, "info": None if lp else self.info, "fx": fx}
        srt = self._srt_job()
        if srt:
            kw["_srt"] = ([(c[0], c[1]) for c in clips], srt, join)
        threading.Thread(target=self._worker, args=(export_multi, (mode, lp or url, clips, outdir), name, thumb,
                                                    bool(lp), kw), daemon=True).start()

    def _worker(self, fn, args, name, thumb, local, kw=None):
        kw = dict(kw or {})
        srt = kw.pop("_srt", None)
        try:
            if not local and not self.update_done.is_set():
                self.emit("status", "Waiting for yt-dlp update …")
                self.update_done.wait()
            self.emit("status", "Reading file …" if local else "Fetching video info …")
            files = [str(f) for f in fn(*args, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, emit=self.emit, name=name,
                                        **kw)]
            if srt and files:
                try:
                    files += [str(f) for f in save_srts(files, *srt)]
                except Exception as ex:  # noqa: BLE001
                    self.emit("log", f"WARNING: .srt not saved: {clean_error(ex)}")
            if thumb and files:
                try:
                    self.emit("status", "Saving thumbnail …")
                    base = Path(files[0])
                    dst = base.parent / (unique_name(base.parent, base.stem, ".jpg") + ".jpg")
                    save_thumbnail(thumb[0], dst, ffmpeg=self.ffmpeg, info=thumb[1], at=thumb[2])
                    if len(thumb) > 3 and thumb[3]:
                        ai_upscale_image(dst, dst, thumb[3], ffmpeg=self.ffmpeg,
                                         emit=self.emit)
                    files.append(str(dst))
                except Exception as ex:  # noqa: BLE001
                    self.emit("log", f"WARNING: thumbnail not saved: {clean_error(ex)}")
            self.emit("done", files)
        except ImportError:
            self.emit("error", "yt-dlp is not installed – please run the setup again.")
        except Exception as ex:  # noqa: BLE001
            msg = clean_error(ex)
            self.emit("error", msg + login_hint(msg))

    def _save_thumb_now(self):
        url = self.url.text().strip()
        if not self._is_info_current() or self.busy:
            return
        outdir = Path(self.outdir.text().strip() or Path.home() / "Downloads")
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            return self._on_error(f"Invalid folder: {ex}")
        try:
            s, _e = self._range()
        except ValueError:
            s = None
        lp = local_path(url)
        base = self.name.text().strip() or safe_name(self.info.get("title") or "thumbnail")
        if lp and s:
            base += f"_{fmt_t(s)}"
        dst = outdir / (unique_name(outdir, base, ".jpg") + ".jpg")
        at = s if s else min((self.info.get("duration") or 0) * 0.1, 5.0)
        info = None if lp else self.info
        self.btn_thumb.setEnabled(False)
        self._on_status("Saving thumbnail …")

        ai = self._ai()

        def work():
            try:
                save_thumbnail(url, dst, ffmpeg=self.ffmpeg, info=info, at=at)
                if ai:
                    ai_upscale_image(dst, dst, ai, ffmpeg=self.ffmpeg, emit=self.emit)
                self.emit("thumb_saved", str(dst))
            except Exception as ex:  # noqa: BLE001
                self.emit("thumb_err", clean_error(ex))
        threading.Thread(target=work, daemon=True).start()

    def _on_thumb_saved(self, path):
        self.btn_thumb.setEnabled(True)
        self.last_files = [path]
        self.btn_show.setEnabled(True)
        try:
            size = f" ({Path(path).stat().st_size / 1024:.0f} KB)"
        except OSError:
            size = ""
        self.status.setText(f"✓  Thumbnail saved: {Path(path).name}{size}")
        set_state(self.status, "ok")
        self._on_log(f"✓ {Path(path).name}")

    def _on_thumb_err(self, msg):
        self.btn_thumb.setEnabled(True)
        self.status.setText("✕  " + msg.splitlines()[0][:200])
        set_state(self.status, "error")
        self._on_log("✕ " + msg)

    def _open_file(self):
        start = self.cfg.get("last_in") or str(Path.home())
        exts = " ".join(f"*{x}" for x in sorted(LOCAL_EXTS))
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open a video or audio file", start,
                                                        f"Media ({exts});;All files (*.*)")
        if path:
            self.cfg["last_in"] = str(Path(path).parent)
            self.url.setText(str(Path(path)))
            self.name.clear()

    def _grab_clipboard(self):
        if self.busy:
            return
        clip = QtWidgets.QApplication.clipboard().text().strip()
        if clip and clip != self.last_clip and YT_URL.fullmatch(clip):
            self.last_clip = clip
            if self.url.text().strip() != clip:
                self.url.setText(clip)
                self.name.clear()
                self._on_status("Link taken from the clipboard.")

    def _paste(self):
        clip = QtWidgets.QApplication.clipboard().text().strip()
        if clip:
            self.url.setText(clip)
            self.name.clear()

    def _pick_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder",
                                                       self.outdir.text() or str(Path.home()))
        if d:
            self.outdir.setText(str(Path(d)))

    def _open_dir(self):
        d = Path(self.outdir.text().strip() or Path.home() / "Downloads")
        if d.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(d)))

    def _reveal(self):
        if self.last_files and Path(self.last_files[-1]).exists():
            if WIN:
                subprocess.Popen(f'explorer /select,"{self.last_files[-1]}"')
            else:
                self._open_dir()

    def _toggle_log(self):
        show = not self.log.isVisible()
        self.log.setVisible(show)
        self.btn_details.setText(("▾" if show else "▸") + "  Details")

    def _check_tools(self):
        missing = [n for n, p in (("FFmpeg", self.ffmpeg), ("FFprobe", self.ffprobe), ("Deno", self.deno)) if not p]
        if missing:
            self._on_log("Missing: " + ", ".join(missing) + " – please run the setup again.")

    def _maybe_update(self):
        if time.time() - float(self.cfg.get("last_update", 0)) < UPDATE_INTERVAL:
            self.update_done.set()
        else:
            self._run_update()

    # ------------------------------------------------------------------ app update (GitHub repo)
    def _check_app_update(self, manual=True):
        if manual:
            self.btn_app_upd.setEnabled(False)
            self._on_status("Checking for a new app version …")

        def work():
            try:
                self.emit("appupd", ("checked", (manual, check_app_update())))
            except Exception as ex:  # noqa: BLE001
                self.emit("appupd", ("check_err", (manual, clean_error(ex))))
        threading.Thread(target=work, daemon=True).start()

    def _app_update_clicked(self):
        if self.busy:
            return
        self._check_app_update(manual=True)

    def _on_appupd(self, val):
        kind, v = val
        if kind == "checked":
            manual, info = v
            self.cfg["last_app_check"] = time.time()
            save_cfg(self.cfg)
            self.btn_app_upd.setEnabled(not self.busy)
            if info.get("newer"):
                first = (self._app_update or {}).get("version") != info.get("version")
                self._app_update = info
                self._show_app_update(info)
                if first:
                    self._on_log(f"New app version {info.get('version')} available (you have {APP_VERSION}) – "
                                 "click “Update app” at the bottom.")
                if not manual:
                    return
                notes = str(info.get("notes") or "").strip()
                q = QtWidgets.QMessageBox.question(
                    self, "Update app", f"Version {info.get('version')} is available (you have {APP_VERSION})."
                    + (f"\n\n{notes[:600]}" if notes else "") + "\n\nUpdate now? The app restarts afterwards.")
                if q == QtWidgets.QMessageBox.StandardButton.Yes:
                    self._install_app_update(info)
                else:
                    self._on_status("Ready.")
            elif manual:
                self._on_status(f"✓  You have the newest version ({APP_VERSION}).")
                set_state(self.status, "ok")
        elif kind == "check_err":
            manual, msg = v
            self.btn_app_upd.setEnabled(not self.busy)
            if manual:
                self._on_error("Update check failed: " + msg)
            else:
                self._on_log("App update check: " + msg)
        elif kind == "installed":
            self._on_log(f"✓ App updated to {v} – restarting …")
            self._restart()
        elif kind == "install_err":
            self._on_error("App update failed: " + v)

    def _show_app_update(self, info):
        """Update button lit up in the accent color with a dot and the new version number."""
        notes = str(info.get("notes") or "").strip()
        self.btn_app_upd.setText(f"●  Update to {info.get('version')}")
        set_state(self.btn_app_upd, "new")
        self.btn_app_upd.updateGeometry()
        tip(self.btn_app_upd, f"Version {info.get('version')} is ready",
            f"You have {APP_VERSION}. Click to update – the app restarts afterwards."
            + (f"\n\nNew: {notes[:400]}" if notes else ""))

    def _install_app_update(self, info):
        if self.busy:
            return
        self._set_busy(True)
        self._on_progress(None)
        script = Path(__file__).resolve()

        def work():
            try:
                install_app_update(info, script, self.emit)
                self.emit("appupd", ("installed", info.get("version")))
            except Exception as ex:  # noqa: BLE001
                self.emit("appupd", ("install_err", clean_error(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _restart(self):
        self.busy = False
        self._save_settings()
        self.login_bridge.close()
        for pl in (self.player, self.aplayer):
            if pl is not None:
                pl.stop()
        if self._proxy is not None:
            self._proxy.close()
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())], cwd=str(Path(__file__).resolve().parent),
                             close_fds=True)
        except OSError as ex:
            self._set_busy(False)
            return self._on_error(f"Please start the app again ({ex}).")
        QtCore.QTimer.singleShot(150, lambda: os._exit(0))

    def _check_ytdlp(self):
        """Is there a newer yt-dlp (or one waiting for a restart)? -> the button lights up."""
        threading.Thread(target=lambda: self.emit("ytdlp_ver", ytdlp_versions()), daemon=True).start()

    def _on_ytdlp_ver(self, v):
        self._ytdlp_v = v
        inst, loaded, latest = v.get("installed"), v.get("loaded"), v.get("latest")
        if latest and inst and _ver(latest) > _ver(inst):
            self.btn_upd.setText(f"●  Update yt-dlp to {latest}")
            set_state(self.btn_upd, "new")
            tip(self.btn_upd, f"yt-dlp {latest} is out", f"You have {inst}. Click to update – takes a few seconds.")
        elif inst and loaded and _ver(inst) > _ver(loaded):
            self.btn_upd.setText(f"●  Restart for yt-dlp {inst}")
            set_state(self.btn_upd, "new")
            tip(self.btn_upd, "Restart", f"yt-dlp {inst} is installed – it works after restarting the app "
                                         "(click to restart now).")
        else:
            self.btn_upd.setText("Update yt-dlp")
            set_state(self.btn_upd, "")
            tip(self.btn_upd, "Update yt-dlp", f"yt-dlp {inst or ''} is up to date. It does the YouTube part – if "
                                               "downloads suddenly fail, an update usually helps.")
        self.btn_upd.updateGeometry()

    def _run_update(self, manual=False):
        if manual and self.busy:
            return
        v = getattr(self, "_ytdlp_v", None) or {}
        if manual and v.get("installed") and v.get("loaded") and _ver(v["installed"]) > _ver(v["loaded"]) \
                and not (v.get("latest") and _ver(v["latest"]) > _ver(v["installed"])):
            return self._restart()
        self.update_done.clear()
        self.btn_upd.setEnabled(False)
        self._on_status("Checking for yt-dlp update …")
        threading.Thread(target=lambda: self.emit("updated", update_ytdlp(self.emit)), daemon=True).start()

    # drag & drop a link onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            u = md.urls()[0]
            text = u.toLocalFile() if u.isLocalFile() else u.toString()
        else:
            text = md.text()
        if text.strip():
            self.url.setText(text.strip())
            self.name.clear()

    def closeEvent(self, e):
        if self.busy and QtWidgets.QMessageBox.question(
                self, APP, "A download is still running. Quit anyway?") != QtWidgets.QMessageBox.StandardButton.Yes:
            e.ignore()
            return
        self._save_settings()
        self.login_bridge.close()
        si, self._signin = self._signin, None
        if si is not None and si.proc is not None and si.proc.poll() is None:
            try:
                si.proc.kill()           # the sign-in window of an unfinished sign-in
            except OSError:
                pass
        for pl in (self.player, self.aplayer):
            if pl is not None:
                pl.stop()
                pl.setSource(QtCore.QUrl())
        if self._proxy is not None:
            self._proxy.close()
        preview_cleanup(self._keep_pv())
        e.accept()
        QtCore.QTimer.singleShot(0, lambda: os._exit(0))


def main():
    if sys.stdout is None or sys.stderr is None:  # pythonw has no console -> write to a log file
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            sink = open(APP_DIR / "last_run.log", "w", encoding="utf-8", buffering=1)
        except OSError:
            sink = open(os.devnull, "w")
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink
    if WIN:
        try:  # own taskbar entry instead of being grouped with other pythonw apps
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setOrganizationName("tfrog")
    app.setStyle("Fusion")
    font = QtGui.QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    font.setPointSize(10)
    app.setFont(font)
    icon = Path(__file__).with_name("icon.ico")
    if icon.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon)))
    win = MainWindow()
    if not win.cfg.get("geometry"):
        win.resize(1220, 900)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
