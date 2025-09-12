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

# Greičio/limito nustatymai
TIMEOUT_SEC = 20                 # max trukmė vienam yt-dlp kvietimui (s)
MAX_ITEMS_PER_LIST = 80          # kiek daugiausia elementų imam iš sąrašo

def _run_json(cmd: list[str], timeout_sec: int = TIMEOUT_SEC) -> dict:
    """Paleidžia komandą, grąžina JSON. Timeout'ina, jei užtrunka per ilgai."""
    out = subprocess.run(
        cmd, text=True, capture_output=True, timeout=timeout_sec
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or out.stdout.strip())
    return json.loads(out.stdout)

def _pick_thumb_any(obj: dict, keys: list[str]) -> str | None:
    """Iš kelių galimų laukų parenka geriausią thumbnail (paskutinį/„didžiausią“)."""
    for k in keys:
        thumbs = obj.get(k)
        if isinstance(thumbs, list) and thumbs:
            for t in reversed(thumbs):
                url = (t or {}).get("url")
                if url:
                    return url
    return None

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

def fetch_channel_avatar(channel_id: str) -> str | None:
     """
     Pabandome kelis šaltinius be YouTube API:
     1) /about → turi channel_thumbnails
     2) /videos pirmas įrašas → turi uploader_thumbnails
     3) /videos JSON šaknies thumbnails (rečiau)
     """
     print(f"[AVATAR] {channel_id} …", flush=True)
     # 1) /about
     try:
         j = _run_json(["yt-dlp", "-J", f"https://www.youtube.com/channel/{channel_id}/about"])
         avatar = _pick_thumb_any(j, ["channel_thumbnails", "thumbnails"])
         if avatar:
             print(f"[AVATAR] ok via /about", flush=True)
             return avatar
     except Exception as ex:   # <-- čia buvo klaida
         print(f"[AVATAR] /about failed: {ex}", flush=True)

     # 2) /videos, tik pirmas item (kad gautume uploader_thumbnails)
     try:
         j = _run_json([
             "yt-dlp", "-J",
             "--playlist-items", "1",
             f"https://www.youtube.com/channel/{channel_id}/videos"
         ])
         # iš šaknies arba iš pirmo įrašo
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

def collect_playlists(channel_id: str) -> list[dict]:
    """Grąžina kanalo PLAYLIST'US (PL...). Naudojam flat režimą ir ribą."""
    url = f"https://www.youtube.com/channel/{channel_id}/playlists"
    print(f"[LIST] playlists {channel_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(MAX_ITEMS_PER_LIST),
            url
        ])
        out = []
        for e in (j.get("entries") or []):
            eid = (e or {}).get("id") or ""
            if not eid.startswith("PL"):
                continue
            title = (e or {}).get("title") or ""
            thumbs = (e or {}).get("thumbnails") or []
            thumb = thumbs[-1]["url"] if (isinstance(thumbs, list) and thumbs) else None
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

def collect_channel_videos(channel_id: str) -> list[dict]:
    """Grąžina kanalo VIDEO (kandidatų į shorts) sąrašą, flat + LIMIT."""
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    print(f"[LIST] shorts(candidates) {channel_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(MAX_ITEMS_PER_LIST),
            url
        ])
        out = []
        for e in (j.get("entries") or []):
            eid = (e or {}).get("id") or ""
            if not eid:
                continue
            title = (e or {}).get("title") or ""
            thumbs = (e or {}).get("thumbnails") or []
            thumb = thumbs[-1]["url"] if (isinstance(thumbs, list) and thumbs) else None
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

def main():
    ensure_dirs()
    items = load_videos()

    # Atskirai kanalai, kurie turi būti „playlists“, ir kurie „shorts“
    ch_for_playlists = sorted({it.get("channelId") for it in items
                               if it.get("type") == "youtube_channel_playlists" and it.get("channelId")})
    ch_for_shorts = sorted({it.get("channelId") for it in items
                            if it.get("type") == "youtube_channel_shorts" and it.get("channelId")})

    print(f"[INFO] Channels for playlists: {ch_for_playlists}")
    print(f"[INFO] Channels for shorts   : {ch_for_shorts}")

    written = 0

    # PLAYLISTS
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

    # SHORTS (kandidatų sąrašas iš /videos; app’as gali filtruoti <60s jei reikės)
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

    if written == 0:
        print("[ERROR] Nothing written. Check videos.json channelId/type fields.", file=sys.stderr)
        sys.exit(2)
    print(f"[DONE] Generated/updated {written} file(s).")

if __name__ == "__main__":
    main()
