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
    """Pick a good-looking thumbnail URL from yt-dlp list."""
    if not thumbs:
        return None
    for t in reversed(thumbs):
        url = (t or {}).get("url")
        if url:
            return url
    return None

def fetch_channel_avatar(channel_id: str) -> str | None:
    """
    Grab channel avatar without YouTube API:
    ask for the first upload (has 'uploader_thumbnails').
    """
    try:
        j = sh(
            "yt-dlp",
            "-J",
            "--playlist-items", "1",  # only one entry is enough
            f"https://www.youtube.com/channel/{channel_id}/videos",
        )
        entries = j.get("entries") or []
        if not entries:
            return None
        first = entries[0] or {}
        return pick_thumb(first.get("uploader_thumbnails"))
    except Exception as ex:
        print(f"[WARN] fetch_channel_avatar failed for {channel_id}: {ex}")
        return None

def collect_flat_list(url: str, want_playlists: bool) -> list:
    """
    Flat, cheap listing with IDs/titles/thumb candidates.
    - if want_playlists=True, keep only PL... entries (channel playlists)
    - else, return uploads as plain video items (candidates for Shorts)
    """
    try:
        j = sh("yt-dlp", "--flat-playlist", "-J", url)
        entries = j.get("entries") or []
        out = []
        for e in entries:
            e = e or {}
            eid = e.get("id") or ""
            title = e.get("title") or ""
            thumb = None
            thumbs = e.get("thumbnails") or []
            if isinstance(thumbs, list) and thumbs:
                thumb = thumbs[-1].get("url")

            if want_playlists:
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

    # Surenkam UC atskirai pagal tipą
    playlist_channels = set()
    shorts_channels = set()
    for it in items:
        t = (it.get("type") or "").strip()
        ch = (it.get("channelId") or "").strip()
        if not ch:
            continue
        if t == "youtube_channel_playlists":
            playlist_channels.add(ch)
        elif t == "youtube_channel_shorts":
            shorts_channels.add(ch)

    # Jei kanalas yra abiejuose – sugeneruosim abu failus (tai OK), bet avatarą imsime tik kartą
    all_channels = sorted(playlist_channels | shorts_channels)
    print(f"[INFO] Channels for playlists: {sorted(playlist_channels)}")
    print(f"[INFO] Channels for shorts   : {sorted(shorts_channels)}")

    avatar_cache: dict[str, str] = {}
    written = 0

    for ch in all_channels:
        # Avataras – tik jei dar nepaimtas
        if ch not in avatar_cache:
            avatar_cache[ch] = fetch_channel_avatar(ch) or ""

        # PLAYLISTS failas tik jei buvo įrašas youtube_channel_playlists
        if ch in playlist_channels:
            playlists_url = f"https://www.youtube.com/channel/{ch}/playlists"
            playlists = collect_flat_list(playlists_url, want_playlists=True)
            path_pl = PLAYLISTS_DIR / f"{ch}.json"
            write_json(path_pl, {
                "channelId": ch,
                "channelAvatar": avatar_cache[ch] or None,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
                "items": playlists
            })
            print(f"[OK] Wrote {path_pl.name} with {len(playlists)} playlists")
            written += 1

        # SHORTS failas tik jei buvo įrašas youtube_channel_shorts
        if ch in shorts_channels:
            videos_url = f"https://www.youtube.com/channel/{ch}/videos"
            uploads = collect_flat_list(videos_url, want_playlists=False)
            path_sh = SHORTS_DIR / f"{ch}.json"
            write_json(path_sh, {
                "channelId": ch,
                "channelAvatar": avatar_cache[ch] or None,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
                "items": uploads
            })
            print(f"[OK] Wrote {path_sh.name} with {len(uploads)} videos (candidates for shorts)")
            written += 1

    if written == 0:
        print("[ERROR] Nothing to write. Make sure videos.json has youtube_channel_playlists/shorts items with channelId.", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"[DONE] Generated/updated {written} JSON files.")

if __name__ == "__main__":
    main()
