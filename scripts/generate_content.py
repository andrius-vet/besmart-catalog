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

def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def collect_with_ytdlp(channel_id: str, what: str) -> list:
    """
    what == 'playlists' => list channel playlists
    what == 'shorts'    => recent short videos (duration <= 60s)
    Uses yt-dlp. If yt-dlp is not available or fails, returns empty.
    """
    try:
        # base args
        base = ["yt-dlp", "--flat-playlist", "-J"]
        if what == "playlists":
            url = f"https://www.youtube.com/channel/{channel_id}/playlists"
        else:
            # we’ll list uploads and filter by duration later
            url = f"https://www.youtube.com/channel/{channel_id}/videos"

        print(f"[INFO] yt-dlp {what} for {channel_id}")
        out = subprocess.check_output(base + [url], text=True)
        data = json.loads(out)

        entries = data.get("entries", []) or []
        # normalize minimal schema we need in app
        results = []
        for e in entries:
            # playlists have 'id' = PL..., videos have 'id' = videoId
            eid = e.get("id") or ""
            title = e.get("title") or ""
            # thumbnails may be list
            thumb = None
            thumbs = e.get("thumbnails") or []
            if isinstance(thumbs, list) and thumbs:
                # pick last (usually largest)
                thumb = thumbs[-1].get("url")

            if what == "playlists":
                if eid.startswith("PL"):
                    results.append({
                        "id": eid,
                        "title": title,
                        "url": f"https://www.youtube.com/playlist?list={eid}",
                        "thumbnail": thumb,
                        "type": "youtube_playlist",
                        "categories": [],
                        "lang": None
                    })
            else:
                # we don’t have duration in flat mode; keep as “candidate shorts”
                # (If you want strict shorts, run another yt-dlp per video, but that costs time.)
                if eid:
                    results.append({
                        "id": eid,
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={eid}",
                        "thumbnail": thumb,
                        "type": "youtube_video",
                        "categories": [],
                        "lang": None
                    })
        return results
    except Exception as ex:
        print(f"[WARN] yt-dlp failed for {channel_id} ({what}): {ex}")
        return []

def main():
    ensure_dirs()
    items = load_videos()

    channels = []
    for it in items:
        ch = it.get("channelId")
        if ch:
            channels.append(ch)

    channels = sorted(set(channels))
    print(f"[INFO] Found {len(channels)} channelId(s): {channels}")

    written = 0
    for ch in channels:
        # PLAYLISTS
        playlists = collect_with_ytdlp(ch, "playlists")
        path_pl = PLAYLISTS_DIR / f"{ch}.json"
        write_json(path_pl, {
            "channelId": ch,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": playlists
        })
        print(f"[OK] Wrote {path_pl} with {len(playlists)} items")
        written += 1

        # SHORTS (candidate list from uploads)
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
        print("[ERROR] No files were generated. Check your videos.json (need channelId fields).", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"[DONE] Generated {written} JSON files.")

if __name__ == "__main__":
    main()