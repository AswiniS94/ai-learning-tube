"""Write the static site: copy front-end assets and emit data/catalog.json."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .config import FORMATS, LEVELS, Config
from .textutil import normalize

_URL = re.compile(r"https?://|www\.", re.I)


def short_description(desc: str, boilerplate: set[str], limit: int = 320) -> str:
    out = []
    size = 0
    for line in (desc or "").splitlines():
        line = line.strip()
        if not line or _URL.search(line) or normalize(line) in boilerplate or line.startswith("#"):
            continue
        out.append(line)
        size += len(line) + 1
        if size >= limit:
            break
    text = " ".join(out)
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def channel_url(info: dict, ch) -> str:
    handle = info.get("handle") or ch.handle
    if handle:
        return "https://www.youtube.com/" + (handle if handle.startswith("@") else "@" + handle)
    return "https://www.youtube.com/channel/" + (info.get("channel_id") or ch.channel_id)


def build_catalog(cfg: Config, state: dict, tagged: dict, series: dict, paths: dict, boiler: dict, meta: dict) -> dict:
    videos = []
    for vid, r in sorted(tagged.items(), key=lambda kv: -kv[1]["q"]):
        v = state["videos"][vid]
        d = v["details"]
        rec = {
            "id": vid,
            "t": v.get("title", ""),
            "c": v["ch"],
            "p": (v.get("published") or "")[:10],
            "d": d.get("duration", 0),
            "v": d.get("views") or 0,
            "tp": r["topics"],
            "lv": r["level"],
            "f": r["format"],
            "q": r["q"],
            "qb": r["qb"],
            "ds": short_description(v.get("desc", ""), boiler.get(v["ch"], set())),
            "why": {
                "lv": r["why"].get("level", []),
                "f": r["why"].get("format", ""),
                "kw": (r["why"].get("keywords", {}).get(r["topics"][0]) or [])[:6],
                "pl": bool(r["why"].get("from_playlist")),
            },
        }
        if d.get("likes") is not None:
            rec["l"] = d["likes"]
        if r.get("series"):
            rec["s"] = r["series"]
            rec["x"] = r["sx"]
        if not d.get("embeddable", True):
            rec["ne"] = 1
        if d.get("caption"):
            rec["cc"] = 1
        videos.append(rec)

    counts = {t.id: 0 for t in cfg.topics}
    per_channel = {}
    for r in tagged.values():
        for t in r["topics"]:
            counts[t] += 1
    for vid in tagged:
        ch = state["videos"][vid]["ch"]
        per_channel[ch] = per_channel.get(ch, 0) + 1

    channels = []
    for ch in cfg.enabled_channels:
        info = state["channels"].get(ch.key, {})
        channels.append(
            {
                "key": ch.key,
                "name": ch.name,
                "url": channel_url(info, ch),
                "thumb": info.get("thumb", ""),
                "subs": info.get("subscribers", 0),
                "n": per_channel.get(ch.key, 0),
            }
        )

    return {
        "meta": meta,
        "site": {"title": cfg.site.get("title", "AI Learning Tube"), "tagline": cfg.site.get("tagline", "")},
        "levels": list(LEVELS),
        "formats": list(FORMATS),
        "channels": channels,
        "topics": [
            {"id": t.id, "name": t.name, "desc": t.description, "pre": t.prerequisites, "n": counts[t.id]}
            for t in cfg.topics
        ],
        "roadmaps": cfg.roadmaps,
        "series": [
            {"id": s["id"], "t": s["title"], "c": s["ch"], "tp": s["topics"], "lv": s["level"], "q": s["q"],
             "course": s["course"], "v": s["members"]}
            for s in sorted(series.values(), key=lambda s: -s["q"])
        ],
        "paths": paths,
        "videos": videos,
    }


def write_site(catalog: dict, site_src: str | Path, out_dir: str | Path, base_url: str = "") -> Path:
    site_src, out_dir = Path(site_src), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(site_src, out_dir)
    (out_dir / "data").mkdir(exist_ok=True)
    with open(out_dir / "data" / "catalog.json", "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, separators=(",", ":"))
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    index = out_dir / "index.html"
    html = index.read_text(encoding="utf-8")
    title = catalog["site"]["title"]
    html = html.replace("{{TITLE}}", _esc(title)).replace("{{TAGLINE}}", _esc(catalog["site"]["tagline"]))
    canonical = f'<link rel="canonical" href="{_esc(base_url)}">' if base_url else ""
    html = html.replace("{{CANONICAL}}", canonical)
    html = html.replace("{{VERSION}}", _esc(catalog["meta"].get("generated", "")))
    index.write_text(html, encoding="utf-8")
    return out_dir


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
