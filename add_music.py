#!/usr/bin/env python3
"""Add unique cinematic background music to each UAP video.

Workflow:
  1. Scrape Pixabay for dark/thriller/suspense instrumental tracks
  2. Extract direct CDN audio URLs via yt-dlp (Chrome impersonation)
  3. Download MP3s to uap-release-01-files/music/
  4. Mix each video with a unique track (ffmpeg loop + mux)
  5. Output to uap-release-01-files/videos-with-music/
"""

import re
import subprocess
import time
import urllib.request
from pathlib import Path

try:
    from curl_cffi import requests as cr
except ImportError:
    raise SystemExit("Run: pip install curl_cffi")

YTDLP = "/Users/siewbrayden/Library/Application Support/pypoetry/venv/bin/yt-dlp"

VIDEOS_IN  = Path(__file__).parent / "uap-release-01-files/videos"
VIDEOS_OUT = Path(__file__).parent / "uap-release-01-files/videos-with-music"
MUSIC_DIR  = Path(__file__).parent / "uap-release-01-files/music"

MUSIC_VOLUME = 0.78  # comfortable over silent video

# Search terms → Pixabay music search URLs, ordered by popularity
SEARCHES = [
    "https://pixabay.com/music/search/crime+thriller/?order=popular",
    "https://pixabay.com/music/search/spy+thriller/?order=popular",
    "https://pixabay.com/music/search/suspense+thriller/?order=popular",
    "https://pixabay.com/music/search/dark+cinematic/?order=popular",
    "https://pixabay.com/music/search/horror+suspense/?order=popular",
    "https://pixabay.com/music/search/dystopian/?order=popular",
    "https://pixabay.com/music/search/dark+orchestral/?order=popular",
    "https://pixabay.com/music/search/dramatic+thriller/?order=popular",
    "https://pixabay.com/music/search/thriller/?order=popular",
    "https://pixabay.com/music/search/suspense/?order=popular",
]

# Skip tracks that are clearly too upbeat / peaceful for this footage
BLOCKLIST_WORDS = {
    "inspir", "motivat", "uplift", "happy", "joyful", "medit", "spirit",
    "relax", "sleep", "calm", "peaceful", "soft", "ambient softness",
    "romantic", "love", "summer", "christmas", "holiday", "children",
}


def is_intense(url: str) -> bool:
    slug = url.lower()
    return not any(w in slug for w in BLOCKLIST_WORDS)


def scrape_pixabay_urls() -> list[str]:
    """Return de-duplicated list of Pixabay track page URLs, most intense first."""
    all_urls: dict[str, str] = {}
    for search_url in SEARCHES:
        try:
            r = cr.get(search_url, impersonate="chrome", timeout=20)
            matches = re.findall(r'href="(/music/[^"]+?-\d{4,7}/)"', r.text)
            added = 0
            for m in matches:
                tid = re.search(r"-(\d{4,7})/$", m)
                if tid and tid.group(1) not in all_urls:
                    full_url = "https://pixabay.com" + m
                    all_urls[tid.group(1)] = full_url
                    added += 1
            label = search_url.split("/")[-2].replace("+", " ")
            print(f"  [{label}] +{added} tracks  (total: {len(all_urls)})")
        except Exception as e:
            print(f"  fetch failed: {e}")
        time.sleep(1.2)

    # Prioritise intense/dark tracks, then fall back to the rest
    urls = list(all_urls.values())
    intense   = [u for u in urls if is_intense(u)]
    remainder = [u for u in urls if not is_intense(u)]
    return intense + remainder


def get_cdn_url(page_url: str) -> str:
    """Ask yt-dlp to extract the direct CDN MP3 URL from a Pixabay music page."""
    r = subprocess.run(
        [YTDLP, "--no-update", "--get-url",
         "--extractor-args", "generic:impersonate",
         page_url],
        capture_output=True, text=True, timeout=30,
    )
    for line in r.stdout.splitlines():
        if line.startswith("http"):
            return line.strip()
    return ""


def download_mp3(cdn_url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 10_000:
        return True
    tmp = dest.with_suffix(".part")
    try:
        req = urllib.request.Request(cdn_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            tmp.write_bytes(resp.read())
        tmp.rename(dest)
        return True
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"    download failed: {e}")
        return False


def video_duration(path: Path) -> float:
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def has_audio(path: Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def mix(video: Path, music: Path, out: Path) -> bool:
    dur = video_duration(video)

    if has_audio(video):
        fc = (
            f"[1:a]volume={MUSIC_VOLUME}[m];"
            f"[0:a][m]amix=inputs=2:duration=first:weights='1 0.35'[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", fc,
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", str(dur), str(out),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-stream_loop", "-1", "-i", str(music),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-af", f"volume={MUSIC_VOLUME}",
            "-t", str(dur), str(out),
        ]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    ffmpeg error: {r.stderr[-500:]}")
        return False
    return True


def track_label(url: str) -> str:
    """Human-readable track name from Pixabay URL slug."""
    slug = re.search(r"/music/(.+?)-\d+/$", url)
    if slug:
        return slug.group(1).replace("-", " ").title()
    return url


def main():
    VIDEOS_OUT.mkdir(parents=True, exist_ok=True)
    MUSIC_DIR.mkdir(exist_ok=True)

    videos = sorted(VIDEOS_IN.glob("*.mp4"))
    needed = len(videos)
    print(f"Videos to process: {needed}\n")

    # ── 1. Collect enough track URLs ──────────────────────────────────────
    print("Scraping Pixabay for cinematic/thriller tracks...\n")
    track_pages = scrape_pixabay_urls()
    print(f"\n{len(track_pages)} candidate tracks found.\n")

    # ── 2. Extract CDN URL + download (until we have `needed` working tracks)
    print("Extracting audio URLs and downloading...\n")
    music_files: list[tuple[Path, str]] = []  # (path, label)

    for page_url in track_pages:
        if len(music_files) >= needed:
            break

        label = track_label(page_url)
        dest  = MUSIC_DIR / f"track_{len(music_files):02d}.mp3"

        if dest.exists() and dest.stat().st_size > 10_000:
            print(f"  [{len(music_files)+1}] SKIP (cached)  {label}")
            music_files.append((dest, label))
            continue

        print(f"  [{len(music_files)+1}] {label[:55]}")
        cdn = get_cdn_url(page_url)
        if not cdn:
            print("      no CDN URL — skipping")
            continue

        if download_mp3(cdn, dest):
            sz = dest.stat().st_size // 1024
            print(f"      OK  {sz} KB")
            music_files.append((dest, label))
        time.sleep(0.8)

    if not music_files:
        print("No music downloaded. Cannot continue.")
        return

    print(f"\n{len(music_files)} tracks ready.\n")

    # ── 3. Mix each video with its unique track ───────────────────────────
    print(f"Mixing {needed} videos...\n")
    ok = fail = skip = 0

    for i, vid in enumerate(videos):
        mf, mlabel = music_files[i % len(music_files)]
        out = VIDEOS_OUT / vid.name

        print(f"[{i+1:02d}/{needed}] {vid.name[:52]}")
        print(f"         ♪  {mlabel[:55]}")

        if out.exists():
            sz = out.stat().st_size // (1024 * 1024)
            print(f"         SKIP (exists, {sz} MB)")
            skip += 1
            continue

        if mix(vid, mf, out):
            sz = out.stat().st_size // (1024 * 1024)
            print(f"         OK  {sz} MB")
            ok += 1
        else:
            fail += 1
        print()

    print("=" * 60)
    print(f"Done — {ok} new, {skip} skipped, {fail} failed")
    print(f"Output: {VIDEOS_OUT}")


if __name__ == "__main__":
    main()
