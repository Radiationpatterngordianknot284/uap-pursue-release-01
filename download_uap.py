#!/usr/bin/env python3
"""Download all UAP PURSUE Release 01 files from war.gov verbatim."""

import json
import time
import urllib.request
from pathlib import Path

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    raise SystemExit("Run: pip install curl_cffi")

OUT = Path(__file__).parent / "uap-release-01-files"
OUT.mkdir(exist_ok=True)
(OUT / "pdfs").mkdir(exist_ok=True)
(OUT / "images").mkdir(exist_ok=True)
(OUT / "videos").mkdir(exist_ok=True)

HEADERS = {"Referer": "https://www.war.gov/UFO/"}
SESSION = curl_requests.Session()

MANIFEST_URL = "https://raw.githubusercontent.com/Pump-OS/alien-files/main/data/json/index.json"
VIDEO_MANIFEST_URL = "https://raw.githubusercontent.com/KarmCraft/dept-of-war-ufo-dump/main/war-ufo-video-download-manifest.json"


def fetch_json(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())


def download_war_gov(url, dest, label, retries=3):
    if dest.exists():
        print(f"  SKIP (exists): {label}")
        return True
    tmp = dest.with_suffix(".part")
    tmp.unlink(missing_ok=True)  # no partial resume — stream from scratch each attempt

    for attempt in range(1, retries + 1):
        s = curl_requests.Session()
        total = 0
        try:
            print(f"  Downloading: {label} attempt {attempt} ...", flush=True)
            with s.stream("GET", url, impersonate="chrome", headers=HEADERS, timeout=600) as r:
                if r.status_code != 200:
                    print(f"  FAIL HTTP {r.status_code}: {label}")
                    return False
                total = int(r.headers.get("content-length", 0))
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
        except Exception as e:
            # Akamai closes connection abruptly after last byte — check if file is complete
            on_disk = tmp.stat().st_size if tmp.exists() else 0
            if total and on_disk >= total:
                tmp.rename(dest)
                print(f"  OK {on_disk//1024} KB (conn closed by server, file complete): {label}")
                return True
            tmp.unlink(missing_ok=True)
            print(f"  ERROR (attempt {attempt}): {label} — {e}")
            if attempt < retries:
                time.sleep(10 * attempt)
            continue

        tmp.rename(dest)
        print(f"  OK {dest.stat().st_size//1024} KB: {label}")
        return True
    return False


def download_plain(url, dest, label, retries=3):
    if dest.exists():
        print(f"  SKIP (exists): {label}")
        return True
    for attempt in range(1, retries + 1):
        print(f"  Downloading: {label} (attempt {attempt}) ...", flush=True)
        tmp = dest.with_suffix(".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
            tmp.write_bytes(data)
            tmp.rename(dest)
            print(f"  OK {len(data)//1024} KB: {label}")
            return True
        except Exception as e:
            tmp.unlink(missing_ok=True)
            print(f"  ERROR (attempt {attempt}): {label} — {e}")
            if attempt < retries:
                time.sleep(5 * attempt)
    return False


def warm_session():
    """Hit the war.gov portal page to get Akamai session cookies before downloading."""
    try:
        r = SESSION.get("https://www.war.gov/UFO/", impersonate="chrome", timeout=20)
        print(f"Session warm-up: HTTP {r.status_code} ({len(SESSION.cookies)} cookies)")
    except Exception as e:
        print(f"Session warm-up failed (continuing anyway): {e}")


def main():
    print("Fetching manifests...")
    warm_session()
    records = fetch_json(MANIFEST_URL)
    video_manifest = fetch_json(VIDEO_MANIFEST_URL)
    video_results = video_manifest.get("results", [])

    print(f"\n=== PDFs & Images ({len([r for r in records if r.get('document_url')])} files) ===")
    ok = fail = skip = 0
    for r in records:
        url = r.get("document_url", "")
        if not url:
            continue
        ext = r.get("ext", "") or Path(url).suffix
        title = r.get("title", r.get("slug", "unknown"))
        slug = r.get("slug", title.replace(" ", "_").replace("/", "-"))
        fname = slug + ext if ext else slug + ".bin"

        if ext in (".png", ".jpg", ".jpeg"):
            dest = OUT / "images" / fname
        else:
            dest = OUT / "pdfs" / fname

        success = download_war_gov(url, dest, title[:60])
        if success:
            ok += 1
        else:
            fail += 1
        time.sleep(8)

    print(f"\n=== Videos ({len(video_results)} files) ===")
    vok = vfail = 0
    for v in video_results:
        video_url = v.get("selectedVideoUrl", "")
        fname = v.get("fileName", f"video_{v.get('dvidsVideoId','?')}.mp4")
        title = v.get("title", fname)
        dest = OUT / "videos" / fname

        if not video_url:
            print(f"  NO URL: {title}")
            vfail += 1
            continue

        success = download_plain(video_url, dest, title[:60])
        if success:
            vok += 1
        else:
            vfail += 1
        time.sleep(0.2)

    print(f"\n=== Done ===")
    print(f"PDFs/Images: {ok} ok, {fail} failed")
    print(f"Videos:      {vok} ok, {vfail} failed")
    print(f"Output:      {OUT}")


if __name__ == "__main__":
    main()
