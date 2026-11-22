"""Builds tfrog_ytclip.pyw from src/ and writes version.json (used by the app's "Update app" button).

    python tools/build.py "What changed in this version"

Change APP_VERSION in src/header.py.part (and $AppVersion in installer/install.ps1) before a release.
After pushing to main, every installed app can update itself with "Update app".
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = ["header", "core", "multi", "stream", "fx", "gui"]


def main():
    src = "".join((ROOT / "src" / f"{p}.py.part").read_text(encoding="utf-8") for p in PARTS)
    compile(src, "tfrog_ytclip.pyw", "exec")
    version = re.search(r'^APP_VERSION = "([\d.]+)"', src, re.M).group(1)
    out = ROOT / "tfrog_ytclip.pyw"
    out.write_bytes(src.encode("utf-8"))
    vfile = ROOT / "version.json"
    old = json.loads(vfile.read_text(encoding="utf-8")) if vfile.exists() else {}
    notes = sys.argv[1] if len(sys.argv) > 1 else (old.get("notes", "") if old.get("version") == version else "")
    info = {
        "version": version,
        "file": "tfrog_ytclip.pyw",
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "notes": notes,
        "pip": ["yt-dlp[default]", "PySide6-Essentials", "PySide6-Addons"],
        "extra": ["icon.ico"],
    }
    vfile.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ps1 = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8-sig")
    m = re.search(r"\$AppVersion = '([\d.]+)'", ps1)
    if m and m.group(1) != version:
        print(f"Note: installer/install.ps1 still says {m.group(1)} – the setup exe uses that number.")
    print(f"Built tfrog_ytclip.pyw {version} ({out.stat().st_size // 1024} KB) + version.json")


if __name__ == "__main__":
    main()
