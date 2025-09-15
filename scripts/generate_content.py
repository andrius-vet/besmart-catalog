#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import time
import urllib.request
import urllib.error
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
PLAYLIST_ITEMS_DIR = CATALOG / "playlist_items"

# ---------- Tuning ----------
TIMEOUT_SEC = 20          # default per-command timeout
MAX_ITEMS_PER_LIST = 80   # max items pulled from channel pages
MAX_ITEMS_PER_PLAYLIST = 500  # max videos per playlist when dumping items

# ---------- Small helpers ----------

def _run_json(cmd: List[str], timeout_sec: int = TIMEOUT_SEC) -> Dict:
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_sec)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return json.loads(p.stdout)

def _pick_thumb_from_list(thumbs) -> Optional[str]:
    if not isinstance(thumbs, list) or not thumbs:
        return None
    # imame paskutinę/„geriausią“ jei sąrašas didėjančios kokybės
    for t in reversed(thumbs):
        u = (t or {}).get("url")
        if u:
            return u
    return None

def _pick_thumb_any(obj: Dict, keys: List[str]) -> Optional[str]:
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
    PLAYLIST_ITEMS_DIR.mkdir(parents=True, exist_ok=True)

def write_json(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

# ---------- Collectors (NO official API) ----------

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

# ---------- Playlist meta (oEmbed first, yt-dlp fallback) ----------

def _oembed_playlist(pl_id: str, timeout_sec: int = 12) -> Optional[Dict]:
    """Fetch title + thumbnail via YouTube's oEmbed (no cookies needed)."""
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/playlist?list={pl_id}&format=json"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            data = json.loads(r.read().decode("utf-8"))
        title = (data.get("title") or "").strip()
        thumb = data.get("thumbnail_url")
        if thumb:
            return {
                "playlistId": pl_id,
                "title": title,
                "thumbnail": thumb,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
                "source": "oembed",
            }
        return None
    except urllib.error.HTTPError as e:
        print(f"[OEMBED] {pl_id} HTTP {e.code}")
        return None
    except Exception as ex:
        print(f"[OEMBED] {pl_id} failed: {ex}")
        return None

def fetch_playlist_meta(pl_id: str, retries: int = 1, timeout_sec: int = 40) -> Optional[Dict]:
    """
    Try oEmbed first (works headlessly). If that fails, *then* try yt-dlp -J.
    """
    meta = _oembed_playlist(pl_id)
    if meta:
        print(f"[META] {pl_id} via oEmbed")
        return meta

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
                "source": "yt-dlp",
            }
        except Exception as ex:
            print(f"[WARN] fetch_playlist_meta {pl_id} (attempt {attempt}) failed: {ex}")
            if attempt < retries:
                time.sleep(3)
    return None

# ---------- NEW: dump playlist_items for each playlist ----------

def collect_playlist_items(pl_id: str, max_items: int = MAX_ITEMS_PER_PLAYLIST) -> List[Dict]:
    """
    Dump all videos in PL… playlist as a flat list (no official API).
    """
    url = f"https://www.youtube.com/playlist?list={pl_id}"
    print(f"[ITEMS] playlist {pl_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(max_items),
            url
        ])
        out: List[Dict] = []
        for e in (j.get("entries") or []):
            vid = (e or {}).get("id") or ""
            if not vid:
                continue
            title = (e or {}).get("title") or ""
            thumb = _pick_thumb_from_list((e or {}).get("thumbnails"))
            out.append({
                "id": vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumb,
                "type": "youtube_video",
                "categories": [],
                "lang": None
            })
        print(f"[ITEMS] playlist {pl_id}: {len(out)} items", flush=True)
        return out
    except Exception as ex:
        print(f"[WARN] items fail {pl_id}: {ex}", flush=True)
        return []

# ---------- Main ----------

def main() -> None:
    ensure_dirs()
    items = load_videos()

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

    # --- Channels → playlists + playlist_items
    for ch in ch_for_playlists:
        avatar = fetch_channel_avatar(ch)
        playlists = collect_playlists(ch)

        # 1) channel playlists JSON
        path = PLAYLISTS_DIR / f"{ch}.json"
        write_json(path, {
            "channelId": ch,
            "channelAvatar": avatar,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": playlists
        })
        print(f"[OK] wrote {path} ({len(playlists)} items)", flush=True)
        written += 1

        # 2) playlist_items for every playlist in that channel
        for p in playlists:
            pl_id = (p or {}).get("id") or ""
            if not pl_id:
                continue
            items_list = collect_playlist_items(pl_id)
            pi_path = PLAYLIST_ITEMS_DIR / f"{pl_id}.json"
            write_json(pi_path, {
                "playlistId": pl_id,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
                "items": items_list
            })
            print(f"[OK] wrote {pi_path} ({len(items_list)} items)", flush=True)
            written += 1

    # --- Channels → shorts (video candidates)
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

    # --- Playlists declared directly in videos.json
    pl_ids = [it["id"] for it in items if it.get("type") == "youtube_playlist" and it.get("id")]
    if pl_ids:
        print(f"[INFO] Playlists declared in videos.json: {pl_ids}")

    for pl in pl_ids:
        # meta
        meta = fetch_playlist_meta(pl)
        if meta:
            path = PLAYLIST_META_DIR / f"{pl}.json"
            write_json(path, meta)
            print(f"[OK] wrote {path}", flush=True)
            written += 1
        else:
            print(f"[WARN] no meta for {pl}", flush=True)

        # items
        items_list = collect_playlist_items(pl)
        pi_path = PLAYLIST_ITEMS_DIR / f"{pl}.json"
        write_json(pi_path, {
            "playlistId": pl,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "items": items_list
        })
        print(f"[OK] wrote {pi_path} ({len(items_list)} items)", flush=True)
        written += 1

    if written == 0:
        print("[ERROR] Nothing written. Check videos.json channelId/type fields.", file=sys.stderr)
        sys.exit(2)

    print(f"[DONE] Generated/updated {written} file(s).")

if __name__ == "__main__":
    main()