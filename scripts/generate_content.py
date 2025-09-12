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

def clean_dir(dir_path: Path):
    for p in dir_path.glob("*.json"):
        try:
            p.unlink()
        except Exception as ex:
            print(f"[WARN] Cannot remove {p}: {ex}")

def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def collect_with_ytdlp(channel_id: str, what: str) -> list:
    """
    what == 'playlists' -> channel playlists
    what == 'shorts'    -> channel shorts feed
    """
    try:
        base = ["yt-dlp", "--flat-playlist", "-J"]
        if what == "playlists":
            url = f"https://www.youtube.com/channel/{channel_id}/playlists"
        else:  # shorts
            url = f"https://www.youtube.com/channel/{channel_id}/shorts"

        print(f"[INFO] yt-dlp {what} for {channel_id}")
        out = subprocess.check_output(base + [url], text=True)
        data = json.loads(out)
        entries = data.get("entries", []) or []

        results = []
        for e in entries:
            eid = e.get("id") or ""
            title = (e.get("title") or "").strip()
            thumb = None
            thumbs = e.get("thumbnails") or []
            if isinstance(thumbs, list) and thumbs:
                thumb = thumbs[-1].get("url")

            if what == "playlists":
                if eid.startswith("PL"):
                    results.append({
                        "id": eid,
                        "title": title or f"Playlist {eid}",
                        "url": f"https://www.youtube.com/playlist?list={eid}",
                        "thumbnail": thumb,
                        "type": "youtube_playlist",
                        "categories": [],
                        "lang": None
                    })
            else:  # shorts -> video ids
                if eid:
                    results.append({
                        "id": eid,
                        "title": title or f"Video {eid}",
                        "url": f"https://www.youtube.com/watch?v={eid}",
                        "thumbnail": thumb,
                        "type": "youtube_video",
                        "categories": [],
                        "lang": None
                    })
        return results
    except subprocess.CalledProcessError as ex:
        print(f"[WARN] yt-dlp failed for {channel_id} ({what}): {ex}", file=sys.stderr)
        return []
    except Exception as ex:
        print(f"[WARN] Unexpected error for {channel_id} ({what}): {ex}", file=sys.stderr)
        return []

def main():
    ensure_dirs()

    items = load_videos()

    # Filtruojame kanalus pagal tipą
    playlist_channels = sorted({
        it.get("channelId") for it in items
        if (it.get("type") == "youtube_channel_playlists" and it.get("channelId"))
    })
    shorts_channels = sorted({
        it.get("channelId") for it in items
        if (it.get("type") == "youtube_channel_shorts" and it.get("channelId"))
    })

    print(f"[INFO] playlist channels: {playlist_channels}")
    print(f"[INFO] shorts channels:   {shorts_channels}")

    # Išvalome senus failus, kad neliktų nebereikalingų
    clean_dir(PLAYLISTS_DIR)
    clean_dir(SHORTS_DIR)

    written = 0

    # PLAYLISTS
    for ch in playlist_channels:
        playlists = collect_with_ytdlp(ch, "playlists")
        path_pl = PLAYLISTS_DIR / f"{ch}.json"
        write_json(path_pl, {
            "channelId": ch,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": playlists
        })
        print(f"[OK] Wrote {path_pl} with {len(playlists)} items")
        written += 1

    # SHORTS
    for ch in shorts_channels:
        shorts = collect_with_ytdlp(ch, "shorts")
        path_sh = SHORTS_DIR / f"{ch}.json"
        write_json(path_sh, {
            "channelId": ch,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": shorts
        })
        print(f"[OK] Wrote {path_sh} with {len(shorts)} items")
        written += 1

    if written == 0:
        print("[ERROR] No files were generated. Ensure videos.json has items with "
              "'type': 'youtube_channel_playlists' or 'youtube_channel_shorts' and valid 'channelId'.",
              file=sys.stderr)
        sys.exit(2)
    else:
        print(f"[DONE] Generated {written} JSON files.")

if __name__ == "__main__":
    main()