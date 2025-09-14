#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
VIDEOS_JSON = CATALOG / "videos.json"
PLAYLISTS_DIR = CATALOG / "playlists"
SHORTS_DIR = CATALOG / "shorts"
PLAYLIST_META_DIR = CATALOG / "playlist_meta"

# ---------- Tuning ----------
TIMEOUT_SEC = 20          # default per-command timeout
MAX_ITEMS_PER_LIST = 80   # max items pulled from channel pages

# ---------- Helpers ----------

def _run_json(cmd: List[str], timeout_sec: int = TIMEOUT_SEC) -> Dict:
    """Run a process and parse stdout as JSON, erroring if non-zero exit."""
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_sec)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return json.loads(p.stdout)

def _pick_thumb_from_list(thumbs) -> Optional[str]:
    """Pick the 'largest' thumbnail (last item in a list of dicts)."""
    if not isinstance(thumbs, list) or not thumbs:
        return None
    for t in reversed(thumbs):
        u = (t or {}).get("url")
        if u:
            return u
    return None

def _pick_thumb_any(obj: Dict, keys: List[str]) -> Optional[str]:
    """Try multiple keys that may hold thumbnail lists."""
    for k in keys:
        u = _pick_thumb_from_list(obj.get(k))
        if u:
            return u
    return None

def load_videos() -> List[Dict]:
    if not VIDEOS_JSON.exists():
        print(f"[ERROR] Missing {VIDEOS_JSON}", file=sys.stderr)
        sys.exit(1)
    with VIDEOS_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    print(f"[INFO] Loaded videos.json with {len(items)} items")
    return items

def ensure_dirs() -> None:
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    PLAYLIST_META_DIR.mkdir(parents=True, exist_ok=True)

def write_json(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

# ---------- Data collectors (no YouTube API) ----------

def fetch_channel_avatar(channel_id: str) -> Optional[str]:
    """
    Get channel avatar without the official API by probing:
      1) /about → channel_thumbnails or thumbnails
      2) /videos (first item) → uploader_thumbnails
    """
    print(f"[AVATAR] {channel_id} …", flush=True)

    # 1) /about
    try:
        j = _run_json(["yt-dlp", "-J", f"https://www.youtube.com/channel/{channel_id}/about"])
        avatar = _pick_thumb_any(j, ["channel_thumbnails", "thumbnails"])
        if avatar:
            print(f"[AVATAR] ok via /about", flush=True)
            return avatar
    except Exception as ex:
        print(f"[AVATAR] /about failed: {ex}", flush=True)

    # 2) /videos first item
    try:
        j = _run_json([
            "yt-dlp", "-J", "--playlist-items", "1",
            f"https://www.youtube.com/channel/{channel_id}/videos"
        ])
        avatar = _pick_thumb_any(j, ["channel_thumbnails", "thumbnails"])
        if not avatar:
            entries = j.get("entries") or []
            if entries:
                avatar = _pick_thumb_any(entries[0] or {}, ["uploader_thumbnails"])
        if avatar:
            print(f"[AVATAR] ok via /videos first entry", flush=True)
            return avatar
    except Exception as ex:
        print(f"[AVATAR] /videos first failed: {ex}", flush=True)

    print(f"[AVATAR] fallback: none", flush=True)
    return None

def collect_playlists(channel_id: str) -> List[Dict]:
    """List channel playlists (flat mode) and keep only PL… IDs."""
    url = f"https://www.youtube.com/channel/{channel_id}/playlists"
    print(f"[LIST] playlists {channel_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(MAX_ITEMS_PER_LIST),
            url
        ])
        out: List[Dict] = []
        for e in (j.get("entries") or []):
            eid = (e or {}).get("id") or ""
            if not eid.startswith("PL"):
                continue
            title = (e or {}).get("title") or ""
            thumb = _pick_thumb_from_list((e or {}).get("thumbnails"))
            out.append({
                "id": eid,
                "title": title,
                "url": f"https://www.youtube.com/playlist?list={eid}",
                "thumbnail": thumb,
                "type": "youtube_playlist",
                "categories": [],
                "lang": None
            })
        print(f"[LIST] playlists {channel_id}: {len(out)} items", flush=True)
        return out
    except Exception as ex:
        print(f"[WARN] playlists fail {channel_id}: {ex}", flush=True)
        return []

def collect_channel_videos(channel_id: str) -> List[Dict]:
    """List channel videos (flat). App can later filter by duration if needed."""
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    print(f"[LIST] shorts(candidates) {channel_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(MAX_ITEMS_PER_LIST),
            url
        ])
        out: List[Dict] = []
        for e in (j.get("entries") or []):
            eid = (e or {}).get("id") or ""
            if not eid:
                continue
            title = (e or {}).get("title") or ""
            thumb = _pick_thumb_from_list((e or {}).get("thumbnails"))
            out.append({
                "id": eid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={eid}",
                "thumbnail": thumb,
                "type": "youtube_video",
                "categories": [],
                "lang": None
            })
        print(f"[LIST] shorts(candidates) {channel_id}: {len(out)} items", flush=True)
        return out
    except Exception as ex:
        print(f"[WARN] shorts fail {channel_id}: {ex}", flush=True)
        return []

def fetch_playlist_meta(pl_id: str, retries: int = 2, timeout_sec: int = 40) -> Optional[Dict]:
    """
    Fetch playlist title & a usable thumbnail from the playlist page,
    retrying to avoid transient rate/anti-bot hiccups.
    """
    url = f"https://www.youtube.com/playlist?list={pl_id}"
    for attempt in range(1, retries + 1):
        try:
            p = subprocess.run(
                ["yt-dlp", "-J", "--no-warnings", "--no-call-home", url],
                text=True, capture_output=True, timeout=timeout_sec
            )
            if p.returncode != 0:
                raise RuntimeError(p.stderr.strip() or p.stdout.strip())
            j = json.loads(p.stdout)

            title = (j.get("title") or "").strip()
            thumb = _pick_thumb_from_list(j.get("thumbnails"))
            if not thumb:
                entries = j.get("entries") or []
                if entries:
                    thumb = _pick_thumb_from_list((entries[0] or {}).get("thumbnails"))
            if not thumb:
                return None

            return {
                "playlistId": pl_id,
                "title": title,
                "thumbnail": thumb,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
            }
        except Exception as ex:
            print(f"[WARN] fetch_playlist_meta {pl_id} (attempt {attempt}) failed: {ex}")
            if attempt < retries:
                time.sleep(3)
    return None

# ---------- Main flow ----------

def main() -> None:
    ensure_dirs()
    items = load_videos()

    # Channels split by type
    ch_for_playlists = sorted({
        it.get("channelId") for it in items
        if it.get("type") == "youtube_channel_playlists" and it.get("channelId")
    })
    ch_for_shorts = sorted({
        it.get("channelId") for it in items
        if it.get("type") == "youtube_channel_shorts" and it.get("channelId")
    })

    print(f"[INFO] Channels for playlists: {ch_for_playlists}")
    print(f"[INFO] Channels for shorts   : {ch_for_shorts}")

    written = 0

    # Generate channel playlists
    for ch in ch_for_playlists:
        avatar = fetch_channel_avatar(ch)
        playlists = collect_playlists(ch)
        path = PLAYLISTS_DIR / f"{ch}.json"
        write_json(path, {
            "channelId": ch,
            "channelAvatar": avatar,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": playlists
        })
        print(f"[OK] wrote {path} ({len(playlists)} items)", flush=True)
        written += 1

    # Generate channel shorts (video candidates)
    for ch in ch_for_shorts:
        avatar = fetch_channel_avatar(ch)
        vids = collect_channel_videos(ch)
        path = SHORTS_DIR / f"{ch}.json"
        write_json(path, {
            "channelId": ch,
            "channelAvatar": avatar,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": vids
        })
        print(f"[OK] wrote {path} ({len(vids)} items)", flush=True)
        written += 1

    # Always generate playlist meta JSON for youtube_playlist entries in videos.json
    pl_ids = [it["id"] for it in items if it.get("type") == "youtube_playlist" and it.get("id")]
    if pl_ids:
        print(f"[INFO] Playlists declared in videos.json: {pl_ids}")
    for pl in pl_ids:
        meta = fetch_playlist_meta(pl)
        if meta:
            path = PLAYLIST_META_DIR / f"{pl}.json"
            write_json(path, meta)
            print(f"[OK] wrote {path}")
            written += 1
        else:
            print(f"[WARN] no meta for {pl}")

    if written == 0:
        print("[ERROR] Nothing written. Check videos.json channelId/type fields.", file=sys.stderr)
        sys.exit(2)

    print(f"[DONE] Generated/updated {written} file(s).")

if __name__ == "__main__":
    main()
