"""Incrementally mirror channel uploads, playlists and video details into the state."""

from __future__ import annotations

import datetime as dt
from typing import Callable

from .config import Config
from .textutil import parse_duration
from .youtube import QuotaExhausted, YouTubeError

SKIP_TITLES = {"Private video", "Deleted video"}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class Log:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.warnings: list[str] = []

    def info(self, msg: str):
        if self.verbose:
            print(msg, flush=True)

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"::warning::{msg}", flush=True)


# ----------------------------------------------------------------- channels --

def sync_channels(client, cfg: Config, state: dict, log: Log) -> None:
    for ch in cfg.enabled_channels:
        known = state["channels"].get(ch.key, {})
        # Re-resolve daily-ish: cheap (1 unit) and keeps subscriber counts fresh.
        try:
            item = client.channel(channel_id=ch.channel_id or "", handle="" if ch.channel_id else ch.handle)
        except YouTubeError as exc:
            log.warn(f"channel {ch.key}: lookup failed ({exc}); using cached info")
            continue
        if not item:
            log.warn(f"channel {ch.key}: not found on YouTube (handle={ch.handle!r} id={ch.channel_id!r})")
            continue
        sn = item.get("snippet", {})
        st = item.get("statistics", {})
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        if known.get("channel_id") and known["channel_id"] != item["id"]:
            log.warn(f"channel {ch.key}: channel id changed {known['channel_id']} -> {item['id']}; resetting its cache")
            known = {}
        known.update(
            {
                "channel_id": item["id"],
                "title": sn.get("title", ch.name),
                "handle": sn.get("customUrl", ch.handle),
                "thumb": thumb,
                "subscribers": int(st.get("subscriberCount", 0) or 0),
                "video_count": int(st.get("videoCount", 0) or 0),
                "uploads": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
            }
        )
        state["channels"][ch.key] = known
        log.info(f"channel {ch.key}: {known['title']} ({known['channel_id']}), ~{known['video_count']} videos")


def channel_id_map(cfg: Config, state: dict) -> dict[str, str]:
    """YouTube channel id -> config key, for enabled channels only."""
    out = {}
    for ch in cfg.enabled_channels:
        cid = state["channels"].get(ch.key, {}).get("channel_id") or ch.channel_id
        if cid:
            out[cid] = ch.key
    return out


# ------------------------------------------------------------------ helpers --

def _record_basic(state: dict, vid: str, key: str, snippet: dict, published: str | None) -> bool:
    """Insert/refresh a video's basic text. Returns True if it was new."""
    videos = state["videos"]
    title = snippet.get("title", "")
    desc = (snippet.get("description") or "")[:5000]
    v = videos.get(vid)
    if v is None:
        videos[vid] = {"ch": key, "title": title, "desc": desc, "published": published or ""}
        return True
    if v.get("ch") != key:
        v["ch"] = key
    if not v.get("details"):  # details (fresher) override basic text once fetched
        v["title"] = title or v.get("title", "")
        v["desc"] = desc or v.get("desc", "")
    if published and not v.get("published"):
        v["published"] = published
    return False


def _walk_playlist(client, playlist_id: str, start_token: str | None, on_page: Callable[[list[dict]], bool],
                   on_token: Callable[[str], None] | None = None):
    """Page through a playlist. on_page returns False to stop early.

    on_token(token) is called with the next page token before it is fetched, so
    an interrupted walk (quota) can be resumed later. Returns the next token when
    stopped early, None when the playlist was read to the end.
    """
    token = start_token
    while True:
        page = client.playlist_items_page(playlist_id, token)
        keep_going = on_page(page.get("items") or [])
        token = page.get("nextPageToken")
        if not token:
            return None
        if not keep_going:
            return token
        if on_token:
            on_token(token)


# ------------------------------------------------------------------ uploads --

def sync_uploads(client, cfg: Config, state: dict, log: Log, force_full: bool = False) -> None:
    full_days = int(cfg.build["full_rescan_days"])
    for ch in cfg.enabled_channels:
        info = state["channels"].get(ch.key)
        if not info or not info.get("uploads"):
            continue
        uploads = info["uploads"]
        last_full = parse_iso(info.get("last_full_scan"))
        resume = info.get("uploads_resume_token")
        full = force_full or last_full is None or (now_utc() - last_full).days >= full_days

        def make_handler(stop_on_known: bool):
            stats = {"new": 0, "pages": 0}

            def handler(items):
                stats["pages"] += 1
                new_here = 0
                for it in items:
                    sn = it.get("snippet", {})
                    vid = it.get("contentDetails", {}).get("videoId") or sn.get("resourceId", {}).get("videoId")
                    if not vid or sn.get("title") in SKIP_TITLES:
                        continue
                    published = it.get("contentDetails", {}).get("videoPublishedAt") or sn.get("publishedAt")
                    if _record_basic(state, vid, ch.key, sn, published):
                        new_here += 1
                stats["new"] += new_here
                return not (stop_on_known and new_here == 0)

            return handler, stats

        try:
            def save_token(t, info=info):
                info["uploads_resume_token"] = t

            if full and not resume:
                handler, stats = make_handler(stop_on_known=False)
                _walk_playlist(client, uploads, None, handler, save_token)
                info["last_full_scan"] = iso(now_utc())
                info.pop("uploads_resume_token", None)
                log.info(f"uploads {ch.key}: full scan, {stats['pages']} pages, {stats['new']} new")
            else:
                handler, stats = make_handler(stop_on_known=True)
                _walk_playlist(client, uploads, None, handler)
                log.info(f"uploads {ch.key}: incremental, {stats['pages']} pages, {stats['new']} new")
                if resume:
                    handler2, stats2 = make_handler(stop_on_known=False)
                    _walk_playlist(client, uploads, resume, handler2, save_token)
                    info["last_full_scan"] = iso(now_utc())
                    info.pop("uploads_resume_token", None)
                    log.info(f"uploads {ch.key}: resumed full scan, {stats2['pages']} pages, {stats2['new']} new")
        except QuotaExhausted:
            raise
        except YouTubeError as exc:
            # A stale page token must not block future runs: restart the full scan next time.
            info.pop("uploads_resume_token", None)
            if exc.status == 404:
                log.warn(f"uploads {ch.key}: uploads playlist not found")
            else:
                log.warn(f"uploads {ch.key}: {exc}")


# ---------------------------------------------------------------- playlists --

def sync_playlist_index(client, cfg: Config, state: dict, log: Log) -> None:
    """Refresh the list of each channel's playlists (titles + item counts)."""
    for ch in cfg.enabled_channels:
        if not ch.scan_playlists:
            continue
        cid = state["channels"].get(ch.key, {}).get("channel_id")
        if not cid:
            continue
        seen = set()
        token = None
        complete = False
        try:
            while True:
                page = client.playlists_page(cid, token)
                for it in page.get("items") or []:
                    pid = it["id"]
                    sn = it.get("snippet", {})
                    seen.add(pid)
                    p = state["playlists"].setdefault(pid, {"ch": ch.key, "items": None, "fetched_count": -1})
                    p.update(
                        {
                            "ch": ch.key,
                            "title": sn.get("title", ""),
                            "desc": (sn.get("description") or "")[:1500],
                            "count": int(it.get("contentDetails", {}).get("itemCount", 0) or 0),
                            "published": sn.get("publishedAt", ""),
                        }
                    )
                token = page.get("nextPageToken")
                if not token:
                    complete = True
                    break
        except YouTubeError as exc:
            log.warn(f"playlists {ch.key}: {exc}")
        if complete:
            gone = [pid for pid, p in state["playlists"].items() if p.get("ch") == ch.key and pid not in seen]
            for pid in gone:
                del state["playlists"][pid]
            log.info(f"playlists {ch.key}: {len(seen)} playlists ({len(gone)} removed)")


def sync_playlist_items(client, cfg: Config, state: dict, log: Log, playlist_ids: list[str], force: bool = False) -> None:
    """Fetch ordered items for the given (relevant) playlists when their size changed."""
    owners = channel_id_map(cfg, state)
    fetched = 0
    for pid in playlist_ids:
        p = state["playlists"].get(pid)
        if not p:
            continue
        if not force and p.get("items") is not None and p.get("fetched_count") == p.get("count"):
            continue
        items: list[str] = []
        new = 0

        def handler(page_items):
            nonlocal new
            for it in page_items:
                sn = it.get("snippet", {})
                vid = it.get("contentDetails", {}).get("videoId") or sn.get("resourceId", {}).get("videoId")
                if not vid or sn.get("title") in SKIP_TITLES:
                    continue
                owner = sn.get("videoOwnerChannelId")
                key = owners.get(owner or "")
                if not key:  # video uploaded by a channel we don't allow
                    continue
                published = it.get("contentDetails", {}).get("videoPublishedAt")
                if _record_basic(state, vid, key, sn, published):
                    new += 1
                if vid not in items:
                    items.append(vid)
            return True

        try:
            _walk_playlist(client, pid, None, handler)
        except QuotaExhausted:
            raise
        except YouTubeError as exc:
            log.warn(f"playlist {pid}: {exc}")
            continue
        p["items"] = items
        p["fetched_count"] = p.get("count")
        fetched += 1
    log.info(f"playlist items: refreshed {fetched} playlists")


# ------------------------------------------------------------------ details --

def sync_details(client, state: dict, log: Log, video_ids: list[str], refresh_hours: float) -> None:
    """videos.list for relevant videos: duration, stats, tags, status."""
    now = now_utc()
    missing, stale = [], []
    for vid in video_ids:
        v = state["videos"].get(vid)
        if not v or v.get("gone"):
            continue
        at = parse_iso(v.get("details_at"))
        if not v.get("details"):
            missing.append(vid)
        elif at is None or (now - at).total_seconds() > refresh_hours * 3600:
            stale.append((at or now, vid))
    stale.sort()
    queue = missing + [vid for _, vid in stale]
    done = 0
    for i in range(0, len(queue), 50):
        batch = queue[i : i + 50]
        try:
            items = client.videos(batch)
        except YouTubeError as exc:
            log.warn(f"videos.list failed for a batch: {exc}")
            continue
        got = set()
        for it in items:
            vid = it["id"]
            got.add(vid)
            v = state["videos"].get(vid)
            if v is None:
                continue
            sn, cd, stt, status = it.get("snippet", {}), it.get("contentDetails", {}), it.get("statistics", {}), it.get("status", {})
            v["title"] = sn.get("title", v.get("title", ""))
            v["desc"] = (sn.get("description") or "")[:5000]
            v["published"] = sn.get("publishedAt", v.get("published", ""))
            v["details"] = {
                "duration": parse_duration(cd.get("duration")),
                "views": _int(stt.get("viewCount")),
                "likes": _int(stt.get("likeCount")),  # None when hidden
                "comments": _int(stt.get("commentCount")),  # None when disabled
                "tags": (sn.get("tags") or [])[:30],
                "caption": cd.get("caption") == "true",
                "embeddable": bool(status.get("embeddable", True)),
                "privacy": status.get("privacyStatus", "public"),
                "live": sn.get("liveBroadcastContent", "none"),
                "lang": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "",
                "channel_id": sn.get("channelId", ""),
            }
            v["details_at"] = iso(now)
            v.pop("gone", None)
            if v["details"]["privacy"] != "public":
                v["gone"] = True
        for vid in batch:
            if vid not in got and vid in state["videos"]:
                state["videos"][vid]["gone"] = True  # deleted or made private
        done += len(batch)
    log.info(f"details: {len(missing)} new, {len(stale)} stale, {done} fetched")


def _int(x):
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None
