"""In-memory stand-in for the YouTube API, serving API-shaped responses from a
fixture file. Used by the tests and by `--fixture` demo builds."""

from __future__ import annotations

import json
from pathlib import Path

from .youtube import QuotaExhausted, YouTubeError


class FakeYouTube:
    PAGE = 50

    def __init__(self, fixture: dict | str | Path, budget: int = 10_000, uploads_cap: int | None = None):
        if not isinstance(fixture, dict):
            fixture = json.loads(Path(fixture).read_text(encoding="utf-8"))
        self.data = fixture
        self.budget = budget
        self.cap = budget
        self.used = 0
        self.calls = []
        self.uploads_cap = uploads_cap  # emulate YouTube's ~20k uploads paging limit
        self.channels = {c["id"]: c for c in fixture["channels"]}
        self.videos_by_id = {v["id"]: v for v in fixture["videos"]}

    def _charge(self, name, **kw):
        if self.used + 1 > min(self.cap, self.budget):
            raise QuotaExhausted("fake quota cap reached")
        self.used += 1
        self.calls.append((name, kw))

    # -- API surface used by sync.py --
    def channel(self, channel_id: str = "", handle: str = ""):
        self._charge("channels", id=channel_id, handle=handle)
        for c in self.channels.values():
            if (channel_id and c["id"] == channel_id) or (handle and c["handle"].lower() == handle.lower()):
                return {
                    "id": c["id"],
                    "snippet": {"title": c["title"], "customUrl": c["handle"].lower(),
                                "thumbnails": {"default": {"url": ""}}},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UU" + c["id"][2:]}},
                    "statistics": {"subscriberCount": str(c.get("subs", 1000)), "videoCount": "0"},
                }
        return None

    def _page(self, rows, token):
        start = int(token[1:]) if token else 0
        chunk = rows[start : start + self.PAGE]
        out = {"items": chunk}
        if start + self.PAGE < len(rows):
            out["nextPageToken"] = f"p{start + self.PAGE}"
        return out

    def _item(self, v, playlist_id, pos):
        ch = v["channel"]
        return {
            "snippet": {
                "title": v["title"], "description": v.get("description", ""), "publishedAt": v["published"],
                "playlistId": playlist_id, "position": pos,
                "resourceId": {"kind": "youtube#video", "videoId": v["id"]},
                **({} if v.get("private") else {"videoOwnerChannelId": ch}),
            },
            "contentDetails": {"videoId": v["id"], "videoPublishedAt": v["published"]},
        }

    def playlist_items_page(self, playlist_id: str, page_token=None):
        self._charge("playlistItems", playlistId=playlist_id, pageToken=page_token)
        if playlist_id.startswith("UU"):
            cid = "UC" + playlist_id[2:]
            vids = sorted((v for v in self.data["videos"] if v["channel"] == cid), key=lambda v: v["published"], reverse=True)
            if self.uploads_cap is not None:
                vids = vids[: self.uploads_cap]
            rows = [self._item(v, playlist_id, i) for i, v in enumerate(vids)]
            for r, v in zip(rows, vids):
                if v.get("private"):
                    r["snippet"]["title"] = "Private video"
            return self._page(rows, page_token)
        for p in self.data["playlists"]:
            if p["id"] == playlist_id:
                rows = []
                for i, vid in enumerate(p["items"]):
                    v = self.videos_by_id[vid]
                    r = self._item(v, playlist_id, i)
                    if v.get("private"):
                        r["snippet"]["title"] = "Private video"
                    rows.append(r)
                return self._page(rows, page_token)
        raise YouTubeError(404, "playlistNotFound", playlist_id)

    def playlists_page(self, channel_id: str, page_token=None):
        self._charge("playlists", channelId=channel_id, pageToken=page_token)
        rows = [
            {"id": p["id"], "snippet": {"title": p["title"], "description": p.get("description", ""),
                                        "publishedAt": "2020-01-01T00:00:00Z", "channelId": p["channel"]},
             "contentDetails": {"itemCount": len(p["items"])}}
            for p in self.data["playlists"] if p["channel"] == channel_id
        ]
        return self._page(rows, page_token)

    def videos(self, ids):
        self._charge("videos", n=len(ids))
        out = []
        for vid in ids:
            v = self.videos_by_id.get(vid)
            if not v or v.get("private"):
                continue
            stats = {"viewCount": str(v["views"])}
            if v.get("likes") is not None:
                stats["likeCount"] = str(v["likes"])
            if v.get("comments") is not None:
                stats["commentCount"] = str(v["comments"])
            out.append({
                "id": vid,
                "snippet": {"title": v["title"], "description": v.get("description", ""), "publishedAt": v["published"],
                            "channelId": v["channel"], "tags": v.get("tags", []), "liveBroadcastContent": "none"},
                "contentDetails": {"duration": _iso(v["duration"]), "caption": "true" if v.get("caption") else "false"},
                "statistics": stats,
                "status": {"privacyStatus": "public", "embeddable": v.get("embeddable", True)},
            })
        return out


def _iso(seconds) -> str:
    if isinstance(seconds, str):
        return seconds
    s = int(seconds)
    return f"PT{s // 3600}H{s % 3600 // 60}M{s % 60}S"


def fake_web(fixture):
    """A fake `fetch` for enrich.py: GitHub, arXiv, Semantic Scholar and link checks from fixture['web']."""
    import json as _json
    from urllib.parse import parse_qs, urlsplit
    from xml.sax.saxutils import escape

    if not isinstance(fixture, dict):
        fixture = _json.loads(Path(fixture).read_text(encoding="utf-8"))
    web = fixture.get("web", {})
    calls = []

    def fetch(url, method="GET", headers=None, body=None, timeout=0):
        calls.append((method, url))
        parts = urlsplit(url)
        if parts.netloc == "api.github.com":
            repo = parts.path.removeprefix("/repos/")
            d = web.get("repos", {}).get(repo)
            return (200, _json.dumps(d).encode()) if d else (404, b"{}")
        if parts.netloc == "export.arxiv.org":
            ids = parse_qs(parts.query).get("id_list", [""])[0].split(",")
            entries = []
            for i in ids:
                p = web.get("arxiv", {}).get(i)
                if not p:
                    continue
                authors = "".join(f"<author><name>{escape(a)}</name></author>" for a in p["authors"])
                entries.append(
                    f"<entry><id>http://arxiv.org/abs/{i}v2</id><published>{p['published']}T00:00:00Z</published>"
                    f"<title>{escape(p['title'])}</title><summary>{escape(p['abstract'])}</summary>{authors}"
                    f"<arxiv:primary_category term=\"{p['category']}\"/></entry>")
            xml = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
                   'xmlns:arxiv="http://arxiv.org/schemas/atom">' + "".join(entries) + "</feed>")
            return 200, xml.encode()
        if parts.netloc == "api.semanticscholar.org":
            ids = _json.loads(body)["ids"]
            return 200, _json.dumps([web.get("s2", {}).get(i.removeprefix("ARXIV:")) for i in ids]).encode()
        if url in web.get("dead", []):
            return 404, b""
        return 200, b"ok"

    fetch.calls = calls
    return fetch
