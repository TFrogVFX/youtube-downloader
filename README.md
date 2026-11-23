# YouTube Downloader (by tfrog)

Windows app for YouTube: download a clip (time range, frame-accurate), the audio (MP3 / WAV / M4A) or a GIF – or do the same with your own video files.

- Preview player with timecode, frame steps (← / →) and start / end keys (I / O) – a small copy, or streamed from YouTube
- Several clips: join them or save one file per clip, YouTube chapters → clips
- Codecs: H.264, H.265, ProRes 422 / HQ, target size in MB, NVIDIA encoder
- Frame: crop to 16:9, 9:16, 1:1, 4:3 or any shape (Custom) with a box you can drag (Shorts, Reels)
- Volume curve (fades, ducking, muting), save the frame you see as PNG
- Subtitles: load (YouTube, your file, .srt / .vtt / .ass), edit, own font, colors, place anywhere, burn in or add as track
- History of all links, own folders for the history and the small preview copies, themes and accent colors, hover help

## Install

Download [`setup/YouTube-Downloader.exe`](setup/YouTube-Downloader.exe) and start it. The first start installs Python, FFmpeg, Deno and the app (takes 1–3 minutes); after that the same exe just starts the app.

## YouTube login (optional)

Only needed for age-restricted, members-only or Premium videos. **Settings → Sign in with Chrome** opens a tab in your own Chrome (or Edge, Brave …) with your Google accounts. A small extension of the app hands the YouTube login to the app on this PC – only YouTube cookies, only to `127.0.0.1`, only after you clicked *Sign in* – and keeps it up to date. The first time, the app shows how to add it (developer mode → *Load unpacked*, once per PC). Your account name and picture appear top right.

## Updates

**Update app** (bottom right in the app) loads the newest version from this repository and restarts. yt-dlp updates itself once a day (**Update yt-dlp** for a manual update).

## Development

The app is one file, `tfrog_ytclip.pyw`, built from the parts in `src/`:

```
python tools/build.py "What changed"
```

This writes `tfrog_ytclip.pyw` and `version.json`. Raise `APP_VERSION` in `src/header.py.part` (and `$AppVersion` in `installer/install.ps1` for a new setup exe) before you push – the apps only update to a higher version number.
