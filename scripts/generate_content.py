#!/usr/bin/env python3
import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]  # repo root
CATALOG = ROOT / "catalog"
VIDEOS_JSON = CATALOG / "videos.json"
PLAYLISTS_DIR = CATALOG / "playlists"
SHORTS_DIR = CATALOG / "shorts"


def sh(*args) -> dict:
    """Run a command and parse JSON output."""
    out = subprocess.check_output(args, text=True)
    return json.loads(out)


def load_videos():
    if not VIDEOS_JSON.exists():
        print(f"[ERROR] Missing {VIDEOS_JSON}", file=sys.stderr)
        sys.exit(1)
    with VIDEOS_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    print(f"[INFO] Loaded videos.json with {len(items)} items")
    return items


def ensure_dirs():
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def pick_thumb(thumbs: list | None) -> str | None:
    """Pick the largest-looking thumbnail url from yt-dlp list."""
    if not thumbs:
        return None
    # yt-dlp returns ascending-ish sizes; take the last
    for t in reversed(thumbs):
        url = (t or {}).get("url")
        if url:
            return url
    return None


def fetch_channel_avatar(channel_id: str) -> str | None:
    """
    Grab channel avatar without YouTube API:
    - request the /videos tab, but fetch only the FIRST entry with full metadata
      to get 'uploader_thumbnails'
    """
    try:
        j = sh(
            "yt-dlp",
            "-J",
            "--playlist-items", "1",            # tik 1 įrašas
            "https://www.youtube.com/channel/{}/videos".format(channel_id),
        )
        entries = j.get("entries") or []
        if not entries:
            return None
        first = entries[0] or {}
        return pick_thumb(first.get("uploader_thumbnails"))
    except Exception as ex:
        print(f"[WARN] fetch_channel_avatar failed for {channel_id}: {ex}")
        return None


def collect_flat_list(url: str) -> list:
    """Flat, cheap listing with IDs/titles/thumb candidates."""
    try:
        j = sh("yt-dlp", "--flat-playlist", "-J", url)
        entries = j.get("entries") or []
        out = []
        for e in entries:
            eid = (e or {}).get("id") or ""
            title = (e or {}).get("title") or ""
            thumb = None
            thumbs = (e or {}).get("thumbnails") or []
            if isinstance(thumbs, list) and thumbs:
                thumb = thumbs[-1].get("url")

            if "playlist?list=" in url or "/playlists" in url:
                # Kanalų PLAYLISTAI: filtruojam tik PL...
                if eid.startswith("PL"):
                    out.append({
                        "id": eid,
                        "title": title,
                        "url": f"https://www.youtube.com/playlist?list={eid}",
                        "thumbnail": thumb,
                        "type": "youtube_playlist",
                        "categories": [],
                        "lang": None
                    })
            else:
                # Kanalų VIDEO (kandidatai į shorts – filtruos app, jei reikia)
                if eid:
                    out.append({
                        "id": eid,
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={eid}",
                        "thumbnail": thumb,
                        "type": "youtube_video",
                        "categories": [],
                        "lang": None
                    })
        return out
    except Exception as ex:
        print(f"[WARN] yt-dlp flat list failed for {url}: {ex}")
        return []


def main():
    ensure_dirs()
    items = load_videos()

    # Surenkam visus channelId iš videos.json (youtube_channel_playlists / _shorts)
    channels = []
    for it in items:
        ch = it.get("channelId")
        if ch:
            channels.append(ch)
    channels = sorted(set(channels))
    print(f"[INFO] Found {len(channels)} channelId(s): {channels}")

    written = 0
    for ch in channels:
        print(f"[INFO] Processing channel {ch}")

        # 1) Avatar
        avatar = fetch_channel_avatar(ch)

        # 2) PLAYLISTS
        playlists_url = f"https://www.youtube.com/channel/{ch}/playlists"
        playlists = collect_flat_list(playlists_url)
        path_pl = PLAYLISTS_DIR / f"{ch}.json"
        write_json(path_pl, {
            "channelId": ch,
            "channelAvatar": avatar,                 # <--- nauja
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": playlists
        })
        print(f"[OK] Wrote {path_pl.name} with {len(playlists)} items")

        # 3) SHORTS kandidatai (iš /videos)
        videos_url = f"https://www.youtube.com/channel/{ch}/videos"
        shorts = collect_flat_list(videos_url)
        path_sh = SHORTS_DIR / f"{ch}.json"
        write_json(path_sh, {
            "channelId": ch,
            "channelAvatar": avatar,                 # <--- nauja
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": shorts
        })
        print(f"[OK] Wrote {path_sh.name} with {len(shorts)} items")

        written += 2

    if written == 0:
        print("[ERROR] No files were generated. Check your videos.json (need channelId fields).", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"[DONE] Generated/updated {written} JSON files.")


if __name__ == "__main__":
    main()