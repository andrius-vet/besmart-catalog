#!/usr/bin/env python3
import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# -------- Paths --------
ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
VIDEOS_JSON = CATALOG / "videos.json"
PLAYLISTS_DIR = CATALOG / "playlists"
SHORTS_DIR = CATALOG / "shorts"
PLAYLIST_META_DIR = CATALOG / "playlist_meta"

# -------- Limits / timeouts --------
TIMEOUT_SEC = 20                 # max trukmė vienam yt-dlp kvietimui (s)
MAX_ITEMS_PER_LIST = 80          # max elementų iš kanalų sąrašų

# -------- Helpers --------
def _run_json(cmd: list[str], timeout_sec: int = TIMEOUT_SEC) -> dict:
    """Paleidžia komandą, grąžina JSON (arba išmeta klaidą)."""
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_sec)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip())
    return json.loads(cp.stdout)

def _pick_thumb_list(thumbs) -> str | None:
    """Ima paskutinį (dažniausiai didžiausią) URL iš yt-dlp thumbnails sąrašo."""
    if not isinstance(thumbs, list) or not thumbs:
        return None
    for t in reversed(thumbs):
        url = (t or {}).get("url")
        if url:
            return url
    return None

def _pick_thumb_any(obj: dict, keys: list[str]) -> str | None:
    """Iš kelių laukų ('channel_thumbnails', 'thumbnails', ...) parenka geriausią."""
    for k in keys:
        url = _pick_thumb_list(obj.get(k))
        if url:
            return url
    return None

def ensure_dirs():
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    PLAYLIST_META_DIR.mkdir(parents=True, exist_ok=True)

def load_videos() -> list[dict]:
    if not VIDEOS_JSON.exists():
        print(f"[ERROR] Missing {VIDEOS_JSON}", file=sys.stderr)
        sys.exit(1)
    with VIDEOS_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    print(f"[INFO] Loaded videos.json with {len(items)} items")
    return items

def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

# -------- Avatars / metadata --------
def fetch_channel_avatar(channel_id: str) -> str | None:
    """
    Be YouTube API:
      1) /about -> channel_thumbnails
      2) /videos (tik 1 įrašas) -> uploader_thumbnails
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

    # 2) /videos (pirmas įrašas)
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

def collect_playlists(channel_id: str) -> list[dict]:
    """Kanalų PLAYLIST'ai (PL...)."""
    url = f"https://www.youtube.com/channel/{channel_id}/playlists"
    print(f"[LIST] playlists {channel_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(MAX_ITEMS_PER_LIST),
            url
        ])
        out: list[dict] = []
        for e in (j.get("entries") or []):
            eid = (e or {}).get("id") or ""
            if not eid.startswith("PL"):
                continue
            title = (e or {}).get("title") or ""
            thumb = _pick_thumb_list((e or {}).get("thumbnails"))
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
    """Kanalų VIDEO (kandidatų į shorts) sąrašas."""
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    print(f"[LIST] shorts(candidates) {channel_id} …", flush=True)
    try:
        j = _run_json([
            "yt-dlp", "--flat-playlist", "-J",
            "--playlist-end", str(MAX_ITEMS_PER_LIST),
            url
        ])
        out: list[dict] = []
        for e in (j.get("entries") or []):
            eid = (e or {}).get("id") or ""
            if not eid:
                continue
            title = (e or {}).get("title") or ""
            thumb = _pick_thumb_list((e or {}).get("thumbnails"))
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

def _extract_pl_id(it: dict) -> str | None:
    """Iš videos.json įrašo ištraukia playlistId (iš id arba url)."""
    idv = str(it.get("id") or "")
    if idv.startswith("PL"):
        return idv
    url = str(it.get("url") or "")
    if "playlist?list=" in url:
        return url.split("playlist?list=")[-1].split("&")[0]
    return None

def fetch_playlist_meta(pl_id: str, retries: int = 3) -> dict | None:
    """
    Greitas ir patikimas būdas gauti playlist'o pavadinimą + thumbnail:
    - naudoti --flat-playlist ir --playlist-items 1 (tik pirmas įrašas)
    - paimti pavadinimą iš šaknies, miniatiūrą iš pirmo įrašo (arba iš šaknies, jei yra)
    Su retry + ilgesniu timeout, nes YouTube kartais lėtas.
    """
    url = f"https://www.youtube.com/playlist?list={pl_id}"
    for attempt in range(1, retries + 1):
        try:
            j = _run_json([
                "yt-dlp", "-J",
                "--flat-playlist",
                "--playlist-items", "1",
                "--socket-timeout", "15",
                url
            ], timeout_sec=max(TIMEOUT_SEC, 60))  # šitam kvietimui duodam daugiau laiko

            title = (j.get("title") or "").strip()
            # thumb: pirmo entry thumbnails -> jei nėra, imame iš šaknies
            entries = j.get("entries") or []
            thumb = None
            if entries:
                thumb = _pick_thumb_any(entries[0] or {}, ["thumbnails"])
            if not thumb:
                thumb = _pick_thumb_any(j, ["thumbnails"])

            if not title and not thumb:
                return None

            return {
                "playlistId": pl_id,
                "title": title,
                "thumbnail": thumb,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
            }

        except Exception as ex:
            if attempt >= retries:
                print(f"[WARN] fetch_playlist_meta failed for {pl_id} (attempt {attempt}/{retries}): {ex}", flush=True)
                return None
            else:
                print(f"[INFO] retry fetch_playlist_meta {pl_id} (attempt {attempt}/{retries}) …", flush=True)

# -------- Main --------
def main():
    ensure_dirs()
    items = load_videos()

    # Kanalai: kurie rodomi kaip "playlists" ir kurie kaip "shorts"
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

    # 1) PLAYLISTS JSON
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

    # 2) SHORTS JSON (iš /videos; app’as jei norės – filtruos <60s)
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

    # 3) Atskirų playlistų miniatiūrų meta (videos.json įrašams su tuščiu thumbnail)
    to_fill: list[str] = []
    for it in items:
        if it.get("type") == "youtube_playlist":
            thumb = str(it.get("thumbnail") or "").strip()
            if not thumb:
                pl = _extract_pl_id(it)
                if pl:
                    to_fill.append(pl)
    to_fill = sorted(set(to_fill))
    print(f"[INFO] Playlists needing thumbnails: {to_fill}")

    for pl in to_fill:
        meta_path = PLAYLIST_META_DIR / f"{pl}.json"
        # Jei nori visada atnaujinti – nuimk šį if
        if meta_path.exists():
            print(f"[SKIP] {meta_path.name} exists")
            continue
        meta = fetch_playlist_meta(pl)
        if meta:
            write_json(meta_path, meta)
            print(f"[OK] wrote {meta_path}", flush=True)
            written += 1

    if written == 0:
        print("[ERROR] Nothing written. Check videos.json channelId/type fields.", file=sys.stderr)
        sys.exit(2)

    print(f"[DONE] Generated/updated {written} file(s).")

if __name__ == "__main__":
    main()