# YouTube Downloader (by tfrog)

Windows app for YouTube: download a clip (time range, frame-accurate), the audio (MP3 / WAV / M4A) or a GIF – or do the same with your own video files.

- Preview player with timecode, frame steps (← / →) and start / end keys (I / O), streamed straight from YouTube
- Several clips: join them or save one file per clip, YouTube chapters → clips
- Codecs: H.264, H.265, ProRes 422 / HQ, target size in MB, NVIDIA encoder
- Frame: crop to 9:16, 1:1, 3:4 or 16:9 with a box you can drag (Shorts, Reels)
- Upscale to 1080p / 1440p / 4K or 2× – 4×, normal or with AI (Real-ESRGAN, own ncnn models possible)
- Volume curve (fades, ducking, muting), save the frame you see as PNG
- Subtitles: load (YouTube, your file, .srt / .vtt / .ass), edit, own font, colors, place anywhere, burn in or add as track
- History of all links, themes and accent colors, hover help

## Install

Download [`setup/YouTube-Downloader.exe`](setup/YouTube-Downloader.exe) and start it. The first start installs Python, FFmpeg, Deno and the app (takes 1–3 minutes); after that the same exe just starts the app.

## Updates

**Update app** (bottom right in the app) loads the newest version from this repository and restarts. yt-dlp updates itself once a day (**Update yt-dlp** for a manual update).

## Development

The app is one file, `tfrog_ytclip.pyw`, built from the parts in `src/`:

```
python tools/build.py "What changed"
```

This writes `tfrog_ytclip.pyw` and `version.json`. Raise `APP_VERSION` in `src/header.py.part` (and `$AppVersion` in `installer/install.ps1` for a new setup exe) before you push – the apps only update to a higher version number.
