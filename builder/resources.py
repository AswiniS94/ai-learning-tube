"""Hands-on resources: links pulled from video descriptions + curated course/topic links.

Only links are stored; nothing is downloaded or re-hosted.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import ConfigError

KINDS = ("code", "notebook", "notes", "course", "paper")

_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)
_ARXIV_TEXT_RE = re.compile(r"\barxiv[:\s]*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.I)
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?", re.I)

# Hosts whose links are never learning resources (social, shops, shorteners we can't see through).
BLOCKED_HOSTS = {
    "youtube.com", "youtu.be", "m.youtube.com", "twitter.com", "x.com", "linkedin.com", "facebook.com",
    "instagram.com", "tiktok.com", "threads.net", "discord.gg", "discord.com", "patreon.com",
    "buymeacoffee.com", "ko-fi.com", "amazon.com", "amzn.to", "ibm.biz", "bit.ly", "tinyurl.com", "goo.gl",
    "spotify.com", "open.spotify.com", "podcasts.apple.com", "apple.co", "t.me", "reddit.com",
    "teespring.com", "spreadshirt.com", "paypal.me", "paypal.com", "gumroad.com", "manning.com",
    "learn.ibm.com", "ibm.com", "stanford.io", "online.stanford.edu", "forms.gle", "eepurl.com",
    "substack.com", "medium.com", "flipboard.com", "join.slack.com",
}
GITHUB_NON_REPO = {"sponsors", "orgs", "features", "about", "pricing", "topics", "collections", "marketplace",
                   "settings", "login", "signup", "explore", "trending", "apps", "enterprise", "security"}
PAPER_HOSTS = {"openreview.net", "aclanthology.org", "proceedings.neurips.cc", "papers.nips.cc",
               "openaccess.thecvf.com", "proceedings.mlr.press", "jmlr.org", "dl.acm.org"}
COURSE_HOST_HINTS = ("stanford.edu", "ocw.mit.edu", "mit.edu", "nptel.ac.in", "github.io", "d2l.ai",
                     "huggingface.co/learn", "fast.ai", "deeplearningbook.org", "incompleteideas.net")
GENERIC_LABELS = {"code", "github", "notebook", "colab", "slides", "notes", "paper", "link", "repo", "source code"}
TRACKING_PARAMS = {"si", "feature", "fbclid", "gclid", "ref", "ref_src", "s"}


def _strip_url(u: str) -> str:
    u = u.rstrip(".,;:!?)]}>*'\"")
    # balanced parentheses inside wiki-style URLs are rare here; drop a dangling "("
    return u


def normalize_url(u: str) -> str | None:
    try:
        parts = urlsplit(_strip_url(u))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower()
    if "@" in host:
        return None
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit(("https", host, path, urlencode(query), ""))


def host_of(url: str) -> str:
    return urlsplit(url).netloc


def _blocked(host: str) -> bool:
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def classify_url(url: str) -> tuple[str, str] | None:
    """Return (kind, key) or None. key identifies the resource (repo name, arXiv id, url)."""
    parts = urlsplit(url)
    host, path = parts.netloc, parts.path
    low = path.lower()
    m = _ARXIV_URL_RE.search(host + path)
    if m:
        return "paper", "arxiv:" + m.group(1)
    if _blocked(host):
        return None
    if host == "github.com":
        segs = [s for s in path.split("/") if s]
        if len(segs) < 2 or segs[0].lower() in GITHUB_NON_REPO:
            return None  # profile pages, sponsors, etc.
        repo = segs[0] + "/" + segs[1].removesuffix(".git")
        if low.endswith(".ipynb"):
            return "notebook", url
        return "code", "gh:" + repo
    if host == "colab.research.google.com" or host == "nbviewer.org" or low.endswith(".ipynb"):
        return "notebook", url
    if host == "kaggle.com" and (low.startswith("/code/") or "/kernels/" in low or "/notebooks" in low):
        return "notebook", url
    if host == "huggingface.co" and low.startswith("/spaces/"):
        return "code", url
    if host == "gitlab.com" and len([s for s in path.split("/") if s]) >= 2:
        return "code", url
    if host in PAPER_HOSTS:
        return "paper", url
    if low.endswith(".pdf"):
        return "notes", url
    if host == "ocw.mit.edu" and low.startswith("/courses/"):
        return "course", url
    if any(h in host + path for h in COURSE_HOST_HINTS):
        return "course", url
    return None


def _label_from_line(line: str, url_text: str) -> str:
    before = line.split(url_text)[0]
    before = re.sub(r"[^\w\s&+/().,'-]", " ", before)  # drop emoji / arrows
    before = re.sub(r"\s+", " ", before).strip(" :-–—|•>.,")
    return before if 3 <= len(before) <= 70 else ""


def auto_label(kind: str, key: str, url: str) -> str:
    if key.startswith("gh:"):
        return key[3:]
    parts = urlsplit(url)
    tail = [s for s in parts.path.split("/") if s]
    if kind == "notebook" and tail:
        return tail[-1][:60]
    return (parts.netloc + ("/" + "/".join(tail[:2]) if tail else ""))[:70]


def extract_links(description: str) -> list[dict]:
    """All classified links in one description, in order, de-duplicated."""
    out, seen = [], set()
    for line in (description or "").splitlines():
        for raw in _URL_RE.findall(line):
            url = normalize_url(raw)
            if not url:
                continue
            c = classify_url(url)
            if not c:
                continue
            kind, key = c
            if key in seen:
                continue
            seen.add(key)
            auto = auto_label(kind, key, url)
            label = _label_from_line(line, raw)
            if label and (len(label) <= 14 or label.lower() in GENERIC_LABELS):
                label = f"{label}: {auto}"  # "Code" alone doesn't say which repo
            out.append({"k": kind, "key": key, "u": url, "l": label or auto})
        for m in _ARXIV_TEXT_RE.finditer(line):
            key = "arxiv:" + m.group(1)
            if key not in seen:
                seen.add(key)
                out.append({"k": "paper", "key": key, "u": "https://arxiv.org/abs/" + m.group(1), "l": ""})
    return out


def channel_link_frequency(items_by_channel: dict[str, list[tuple[str, str]]]) -> dict[str, tuple[Counter, int]]:
    """Per channel: in how many distinct groups each link key appears, and how many groups exist.

    items are (description, group) pairs; a group is a video's course playlist (or the
    video itself). Counting groups instead of videos means a link shared by every
    lecture of one course (its notes or website) is never mistaken for a promo,
    while a link repeated under unrelated videos is.
    """
    out = {}
    for ch, items in items_by_channel.items():
        seen: dict[str, set[str]] = defaultdict(set)
        groups = set()
        for desc, group in items:
            groups.add(group)
            for l in extract_links(desc):
                seen[l["key"]].add(group)
        out[ch] = (Counter({k: len(g) for k, g in seen.items()}), len(groups))
    return out


def is_promo(kind: str, key: str, freq: tuple[Counter, int] | None) -> bool:
    """A link repeated across a channel's videos is a promo, not a per-video resource.

    Papers are never promos. Code repos get a higher bar, because a book's companion
    repo legitimately appears under many videos; other links are promos at 5%.
    """
    if not freq or kind == "paper":
        return False
    counts, n = freq
    c = counts.get(key, 0)
    share = 0.30 if kind in ("code", "notebook") else 0.05
    return c >= max(6, int(share * n))


def video_resources(description: str, freq: tuple[Counter, int] | None, limit: int = 10) -> list[dict]:
    return [l for l in extract_links(description) if not is_promo(l["k"], l["key"], freq)][:limit]


# --------------------------------------------------------------- curated ----

def load_curated(config_dir: str | Path, topic_ids: set[str]) -> dict:
    path = Path(config_dir) / "resources.toml"
    if not path.exists():
        return {"courses": [], "starters": {}}
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None

    def check_links(where, links):
        out = []
        for l in links:
            if l.get("kind") not in KINDS:
                raise ConfigError(f"resources.toml {where}: kind must be one of {KINDS}")
            url = normalize_url(l.get("url", ""))
            if not url:
                raise ConfigError(f"resources.toml {where}: bad url {l.get('url')!r}")
            if not l.get("label"):
                raise ConfigError(f"resources.toml {where}: every link needs a label")
            out.append({"k": l["kind"], "u": l["url"], "l": l["label"], "key": url, "cur": 1})
        return out

    courses = []
    for c in raw.get("course", []):
        codes = [re.sub(r"[^a-z0-9]", "", x.lower()) for x in c.get("codes", [])]
        playlists = list(c.get("playlists", []))
        if not codes and not playlists:
            raise ConfigError(f"resources.toml course {c.get('name')!r}: needs codes or playlists")
        courses.append({"name": c.get("name", ""), "codes": codes, "playlists": playlists,
                        "links": check_links(f"course {c.get('name')!r}", c.get("links", []))})
    starters = {}
    for s in raw.get("starter", []):
        tid = s.get("topic")
        if tid not in topic_ids:
            raise ConfigError(f"resources.toml starter: unknown topic {tid!r}")
        starters[tid] = check_links(f"starter {tid}", s.get("links", []))
    return {"courses": courses, "starters": starters}


def curated_for_series(curated: dict, series: dict) -> list[dict]:
    codes = {re.sub(r"[^a-z0-9]", "", c) for c in series.get("codes", [])}
    out = []
    for c in curated["courses"]:
        if series["id"] in c["playlists"] or codes & set(c["codes"]):
            out.extend(c["links"])
    return out


def series_auto_links(series: dict, video_links: dict[str, list[dict]]) -> list[dict]:
    """Course-level links that several lectures share (e.g. MIT 'complete course' page)."""
    counts = Counter()
    first = {}
    for vid in series["members"]:
        for l in video_links.get(vid, []):
            if l["k"] in ("course", "notes", "code"):
                counts[l["key"]] += 1
                first.setdefault(l["key"], l)
    need = max(2, len(series["members"]) // 3)
    return [first[k] for k, c in counts.most_common() if c >= need][:6]


def dedupe(links: list[dict]) -> list[dict]:
    seen, out = set(), []
    for l in links:
        k = l.get("key") or l["u"]
        if k in seen:
            continue
        seen.add(k)
        out.append(l)
    return out


__all__ = ["extract_links", "video_resources", "channel_link_frequency", "load_curated", "curated_for_series",
           "series_auto_links", "dedupe", "normalize_url", "classify_url", "KINDS", "defaultdict"]
