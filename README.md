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

**Without warnings (recommended):** press Start, type `PowerShell`, press Enter, paste this line and press Enter:

```powershell
irm https://raw.githubusercontent.com/TFrogVFX/youtube-downloader/main/installer/web-install.ps1 | iex
```

It loads the newest version from this repository, checks it and installs Python, FFmpeg, Deno and the app (1–3 minutes). Shortcuts go on the desktop and into the Start menu.

**Or with the setup file:** download [`setup/YouTube-Downloader.exe`](setup/YouTube-Downloader.exe) and start it. The file isn't signed, so the browser asks whether to keep it (*Keep*) and Windows shows "Windows protected your PC" – click *More info* → *Run anyway*. After the first start the same exe just starts the app.

## YouTube login (optional)

Only needed for age-restricted, members-only or Premium videos. Two ways in **Settings → YouTube login**:

- **Sign in with Chrome** – opens a tab in your own Chrome (or Edge, Brave …) with your Google accounts. A small extension of the app hands the YouTube login to the app on this PC and keeps it up to date. It only answers the real app (both share a key made on your PC), only after you clicked *Sign in*, only YouTube cookies, only to `127.0.0.1`. Added once per PC – Chrome doesn't let programs add extensions themselves, so the app opens Chrome in the right profile, copies everything you need and you drag the folder onto the extensions page (developer mode).
- **Without extension** – an own, empty browser window; sign in with e-mail and password. Nothing to install, but the login isn't kept up to date. The window's profile is deleted right after the sign-in.

The login is stored encrypted with Windows' own protection (readable only by your Windows user on this PC) and handed to yt-dlp in memory. Tip: a second Google account is the safest choice.

## Repair

**Settings → Repair …** checks the app file (loads it again from GitHub if it's damaged), puts yt-dlp in again, checks FFmpeg, restores the sign-in extension, the login and the settings file, and removes leftovers. Settings, history and login stay.

## Updates

**Update app** (bottom right in the app) loads the newest version from this repository and restarts. yt-dlp updates itself once a day (**Update yt-dlp** for a manual update).

## Development

The app is one file, `tfrog_ytclip.pyw`, built from the parts in `src/`:

```
python tools/build.py "What changed"
```

This writes `tfrog_ytclip.pyw` and `version.json`. Raise `APP_VERSION` in `src/header.py.part` (and `$AppVersion` in `installer/install.ps1` for a new setup exe) before you push – the apps only update to a higher version number.
