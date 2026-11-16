"""Network enrichment for resources and papers, cached in the state file.

- GitHub repo details (stars, last push, archived, license) via the GitHub REST API.
- Link health checks for other links (dead links are hidden after two failures).
- arXiv metadata (title, authors, date, abstract) via the arXiv API.
- Citation counts and one-line summaries via the Semantic Scholar API.

Every step is best-effort: failures are logged and never fail the build.
`fetch` is injectable so tests can run without network.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable

from .sync import Log, iso, now_utc, parse_iso

UA = "ai-learning-tube/1.1 (+https://github.com)"
Fetch = Callable[..., tuple[int, bytes]]


def http_fetch(url: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None,
               timeout: float = 20.0) -> tuple[int, bytes]:
    """Returns (status, body). status 0 = network error."""
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read(200_000)
        except Exception:
            data = b""
        return exc.code, data
    except Exception:
        return 0, b""


def _age_days(ts: str | None) -> float:
    t = parse_iso(ts)
    return 1e9 if t is None else (now_utc() - t).total_seconds() / 86400


# ------------------------------------------------------------------ GitHub --

def enrich_repos(state: dict, repos: list[str], log: Log, fetch: Fetch = http_fetch, token: str = "",
                 max_calls: int = 600, refresh_days: float = 7) -> None:
    cache = state.setdefault("repos", {})
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    else:
        max_calls = min(max_calls, 50)  # unauthenticated limit is 60/hour
    todo = sorted(repos, key=lambda r: _age_days(cache.get(r, {}).get("checked")), reverse=True)
    todo = [r for r in todo if _age_days(cache.get(r, {}).get("checked")) > refresh_days]
    calls = 0
    for repo in todo:
        if calls >= max_calls:
            break
        calls += 1
        status, body = fetch("https://api.github.com/repos/" + repo, headers=headers)
        if status == 200:
            try:
                d = json.loads(body)
            except ValueError:
                continue
            cache[repo] = {
                "ok": d.get("size", 1) > 0 and not d.get("disabled", False),
                "name": d.get("full_name", repo),
                "stars": int(d.get("stargazers_count", 0)),
                "pushed": (d.get("pushed_at") or "")[:10],
                "archived": bool(d.get("archived")),
                "license": ((d.get("license") or {}).get("spdx_id") or ""),
                "desc": (d.get("description") or "")[:160],
                "checked": iso(now_utc()),
            }
        elif status in (404, 451):
            cache[repo] = {"ok": False, "checked": iso(now_utc())}
        elif status in (403, 429):
            log.warn(f"GitHub API rate limit reached after {calls} calls; the rest will be checked next run")
            break
        # other statuses (0/5xx): leave as-is and retry next run
    if calls:
        log.info(f"github: checked {calls} repos")


# --------------------------------------------------------------- link check --

DEAD = {404, 410}


def check_links(state: dict, urls: list[str], log: Log, fetch: Fetch = http_fetch, max_checks: int = 300,
                refresh_days: float = 30) -> None:
    cache = state.setdefault("links", {})
    # Links that failed last time are rechecked on the very next run (confirm or clear quickly).
    todo = [u for u in urls if cache.get(u, {}).get("fails", 0) > 0
            or _age_days(cache.get(u, {}).get("checked")) > refresh_days]
    todo.sort(key=lambda u: _age_days(cache.get(u, {}).get("checked")), reverse=True)
    n = 0
    for url in todo[:max_checks]:
        n += 1
        status, _ = fetch(url, method="HEAD", timeout=12)
        if status in (405, 403, 400, 501) or status == 0:
            status, _ = fetch(url, headers={"Range": "bytes=0-1023"}, timeout=12)
        e = cache.get(url, {"fails": 0})
        if status in DEAD or status == 0:
            e["fails"] = e.get("fails", 0) + 1
        else:  # 2xx/3xx, and 401/403/429 (bot-blocking sites) count as alive
            e["fails"] = 0
        e["status"] = status
        e["checked"] = iso(now_utc())
        cache[url] = e
    if n:
        log.info(f"links: checked {n} urls")


def link_alive(state: dict, url: str) -> bool:
    return state.get("links", {}).get(url, {}).get("fails", 0) < 2


# ------------------------------------------------------------------- arXiv --

ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def parse_arxiv_feed(xml_bytes: bytes) -> dict[str, dict]:
    out = {}
    root = ET.fromstring(xml_bytes)
    for entry in root.findall("a:entry", ATOM):
        raw_id = (entry.findtext("a:id", "", ATOM) or "").strip()
        if "/abs/" not in raw_id:
            continue  # error entries
        aid = raw_id.split("/abs/")[1]
        base = aid.split("v")[0] if "v" in aid.split(".")[-1] else aid
        title = " ".join((entry.findtext("a:title", "", ATOM) or "").split())
        if not title or title.lower() == "error":
            continue
        authors = [" ".join((a.findtext("a:name", "", ATOM) or "").split()) for a in entry.findall("a:author", ATOM)]
        summary = " ".join((entry.findtext("a:summary", "", ATOM) or "").split())
        prim = entry.find("arxiv:primary_category", ATOM)
        out[base] = {
            "title": title,
            "authors": authors[:8],
            "n_authors": len(authors),
            "published": (entry.findtext("a:published", "", ATOM) or "")[:10],
            "abstract": summary[:600],
            "category": prim.get("term") if prim is not None else "",
        }
    return out


def enrich_arxiv(state: dict, ids: list[str], log: Log, fetch: Fetch = http_fetch, batch: int = 50,
                 max_batches: int = 20, pause: float = 3.0) -> None:
    papers = state.setdefault("papers", {})
    todo = [i for i in ids if not papers.get(i, {}).get("title") and papers.get(i, {}).get("missing", 0) < 3]
    done = 0
    for b in range(0, min(len(todo), batch * max_batches), batch):
        chunk = todo[b : b + batch]
        url = "https://export.arxiv.org/api/query?max_results=%d&id_list=%s" % (len(chunk), ",".join(chunk))
        status, body = fetch(url, timeout=30)
        if status != 200:
            log.warn(f"arXiv API returned {status}; remaining papers will be fetched next run")
            break
        try:
            got = parse_arxiv_feed(body)
        except ET.ParseError:
            log.warn("arXiv API returned unreadable XML")
            break
        for i in chunk:
            p = papers.setdefault(i, {})
            if i in got:
                p.update(got[i])
                p.pop("missing", None)
                done += 1
            else:
                p["missing"] = p.get("missing", 0) + 1
        if pause and b + batch < len(todo):
            time.sleep(pause)  # arXiv asks for one request every 3 seconds
    if todo:
        log.info(f"arxiv: fetched metadata for {done}/{len(todo)} papers")


# --------------------------------------------------------- Semantic Scholar --

def enrich_citations(state: dict, ids: list[str], log: Log, fetch: Fetch = http_fetch, api_key: str = "",
                     refresh_days: float = 7, batch: int = 400, pause: float = 1.1) -> None:
    papers = state.setdefault("papers", {})
    todo = [i for i in ids if papers.get(i, {}).get("title") and _age_days(papers[i].get("cited_at")) > refresh_days]
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    fields = "citationCount,influentialCitationCount,venue,year,tldr"
    updated = 0
    for b in range(0, len(todo), batch):
        chunk = todo[b : b + batch]
        body = json.dumps({"ids": ["ARXIV:" + i for i in chunk]}).encode()
        status, data = 0, b""
        for attempt in range(3):
            status, data = fetch("https://api.semanticscholar.org/graph/v1/paper/batch?fields=" + fields,
                                 method="POST", headers=headers, body=body, timeout=40)
            if status != 429:
                break
            time.sleep(5 * (attempt + 1) if pause else 0)
        if status != 200:
            log.warn(f"Semantic Scholar returned {status}; citation counts will refresh next run")
            break
        try:
            rows = json.loads(data)
        except ValueError:
            break
        for i, row in zip(chunk, rows):
            p = papers[i]
            p["cited_at"] = iso(now_utc())
            if not row:
                continue
            p["citations"] = int(row.get("citationCount") or 0)
            p["influential"] = int(row.get("influentialCitationCount") or 0)
            p["venue"] = (row.get("venue") or "")[:80]
            tl = row.get("tldr") or {}
            if tl.get("text"):
                p["tldr"] = tl["text"][:300]
            updated += 1
        if pause:
            time.sleep(pause)
    if todo:
        log.info(f"semantic scholar: updated {updated}/{len(todo)} papers")
