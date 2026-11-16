"""CLI: python -m builder build [--offline] [--full] [--fixture FILE]"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .classify import (Classifier, channel_boilerplate, classify_playlists, classify_videos,
                       finalize_playlist_course_flags, video_playlist_index)
from .config import ConfigError, load_config
from .paths import build_paths, build_series, course_level_map, score_series
from .rank import score_videos
from . import enrich, resources
from .site import build_catalog, write_site
from .state import load_state, save_state
from .sync import (Log, iso, now_utc, sync_channels, sync_details, sync_playlist_index, sync_playlist_items,
                   sync_uploads)
from .youtube import FatalAPIError, QuotaExhausted, YouTubeClient

ROOT = Path(__file__).resolve().parent.parent


def tag_catalog(cfg, state, clf):
    boiler = channel_boilerplate(state)
    pls = classify_playlists(clf, cfg, state, boiler)
    finalize_playlist_course_flags(clf, state, pls)
    vp = video_playlist_index(state, pls)
    tagged = classify_videos(clf, cfg, state, boiler, pls, vp)
    return boiler, pls, tagged


def run_sync(client, cfg, state, clf, log, full: bool) -> None:
    budget = client.budget
    try:
        client.cap = int(budget * 0.6)  # discovery may use 60%; the rest is reserved for details
        sync_channels(client, cfg, state, log)
        sync_uploads(client, cfg, state, log, force_full=full)
        sync_playlist_index(client, cfg, state, log)
        boiler = channel_boilerplate(state)
        pls = classify_playlists(clf, cfg, state, boiler)
        order = sorted(pls, key=lambda pid: -max(pls[pid]["scores"].values()))
        sync_playlist_items(client, cfg, state, log, order, force=full)
    except QuotaExhausted as exc:
        log.warn(f"discovery stopped early: {exc}. Continuing with cached data; the next run resumes.")
    try:
        client.cap = budget
        _, _, tagged = tag_catalog(cfg, state, clf)
        wanted = list(tagged) + [v for v in cfg.overrides.get("include_videos", []) if v in state["videos"]]
        sync_details(client, state, log, wanted, float(cfg.build["stats_refresh_hours"]))
    except QuotaExhausted as exc:
        log.warn(f"detail refresh stopped early: {exc}. Some statistics are from an earlier run.")


def collect_resources(cfg, state, final, series, curated, log, fetch):
    """Links per video/course/topic plus papers, enriched (when online) and filtered for dead links."""
    group_of = {}
    for pid, p in sorted(state["playlists"].items()):
        for vid in p.get("items") or []:
            group_of.setdefault(vid, pid)
    items = {}
    for vid, v in state["videos"].items():
        items.setdefault(v.get("ch", ""), []).append((v.get("desc", ""), group_of.get(vid, vid)))
    promo = resources.channel_link_frequency(items)
    video_links = {vid: resources.video_resources(state["videos"][vid].get("desc", ""), promo.get(state["videos"][vid]["ch"]))
                   for vid in final}
    series_links = {}
    for sid, s in series.items():
        series_links[sid] = resources.dedupe(resources.curated_for_series(curated, s) + resources.series_auto_links(s, video_links))
    starters = curated["starters"]

    all_links = [l for ls in video_links.values() for l in ls] + [l for ls in series_links.values() for l in ls] + \
                [l for ls in starters.values() for l in ls]
    repos = sorted({l["key"][3:] for l in all_links if l["key"].startswith("gh:")})
    urls = sorted({l["u"] for l in all_links if not l["key"].startswith(("gh:", "arxiv:"))})
    arxiv_ids = sorted({l["key"][6:] for l in all_links if l["key"].startswith("arxiv:")})
    if fetch:
        try:
            enrich.enrich_repos(state, repos, log, fetch, token=os.environ.get("GITHUB_TOKEN", ""))
            enrich.check_links(state, urls, log, fetch)
            real = fetch is enrich.http_fetch
            enrich.enrich_arxiv(state, arxiv_ids, log, fetch, pause=3.0 if real else 0)
            enrich.enrich_citations(state, arxiv_ids, log, fetch, api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
                                    pause=1.1 if real else 0)
        except Exception as exc:  # enrichment must never break the build
            log.warn(f"resource enrichment stopped: {exc!r}")

    repo_cache, papers_cache = state.get("repos", {}), state.get("papers", {})

    def render(l):
        if l["key"].startswith("gh:"):
            info = repo_cache.get(l["key"][3:])
            if info is not None and not info.get("ok", True):
                return None  # deleted or empty repo
            out = {"k": l["k"], "u": l["u"], "l": l["l"]}
            if info and info.get("ok"):
                out.update({"st": info["stars"], "pu": info["pushed"]})
                if info.get("archived"):
                    out["ar"] = 1
            if l.get("cur"):
                out["cur"] = 1
            return out
        if l["key"].startswith("arxiv:"):
            return None  # shown in the papers box instead
        if not enrich.link_alive(state, l["u"]):
            return None
        out = {"k": l["k"], "u": l["u"], "l": l["l"]}
        if l.get("cur"):
            out["cur"] = 1
        return out

    def render_all(ls):
        return [r for r in (render(l) for l in ls) if r]

    papers = {}
    video_papers = {}
    for vid, ls in video_links.items():
        ids = [l["key"][6:] for l in ls if l["key"].startswith("arxiv:") and papers_cache.get(l["key"][6:], {}).get("title")]
        if ids:
            video_papers[vid] = ids
            for pid in ids:
                papers.setdefault(pid, set()).add(vid)
    return {
        "videos": {vid: render_all(ls) for vid, ls in video_links.items()},
        "video_papers": video_papers,
        "series": {sid: render_all(ls) for sid, ls in series_links.items()},
        "starters": {tid: render_all(ls) for tid, ls in starters.items()},
        "papers": {pid: {"cache": papers_cache[pid], "videos": sorted(vs)} for pid, vs in papers.items()},
    }


def apply_retags(cfg, tagged):
    for rt in cfg.overrides.get("retag", []):
        r = tagged.get(rt.get("video"))
        if not r:
            continue
        if rt.get("topics"):
            r["topics"] = list(rt["topics"])
        if rt.get("level"):
            r["level"] = rt["level"]
            r["why"]["level"] = ["set by curator"]
        if rt.get("format"):
            r["format"] = rt["format"]
            r["why"]["format"] = "set by curator"


def build(args) -> int:
    log = Log(verbose=not args.quiet)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"::error::config: {exc}")
        return 2
    state = load_state(args.state)
    clf = Classifier(cfg)
    used = 0
    if not args.offline:
        if args.fixture:
            from .fake import FakeYouTube
            client = FakeYouTube(args.fixture, budget=int(cfg.build["quota_budget"]))
        else:
            key = os.environ.get("YOUTUBE_API_KEY", "").strip()
            if not key:
                print("::error::YOUTUBE_API_KEY is not set. Add it as a repository secret, or use --offline.")
                return 2
            client = YouTubeClient(key, budget=int(cfg.build["quota_budget"]))
        try:
            run_sync(client, cfg, state, clf, log, args.full)
        except FatalAPIError as exc:
            print(f"::error::YouTube API: {exc}")
            save_state(state, args.state)
            return 2
        finally:
            used = client.used
        save_state(state, args.state)
        log.info(f"quota used this run: {used} units")

    # Final tagging with fresh details, then filter what's displayable.
    boiler, pls, tagged = tag_catalog(cfg, state, clf)
    min_dur = int(cfg.build["min_duration_seconds"])
    allowed_ids = {state["channels"].get(c.key, {}).get("channel_id") or c.channel_id for c in cfg.enabled_channels}
    final = {}
    for vid, r in tagged.items():
        d = state["videos"][vid].get("details")
        if not d or d.get("live", "none") != "none":
            continue
        if d.get("channel_id") and d["channel_id"] not in allowed_ids:
            continue
        if d.get("duration", 0) < min_dur:
            continue
        final[vid] = r
    apply_retags(cfg, final)

    levels = course_level_map(cfg)
    series = build_series(cfg, state, final, pls, levels)
    members = {v for s in series.values() if s["course"] for v in s["members"]}
    now = now_utc()
    score_videos(cfg, state, final, members, now)
    score_series(series, final)
    channels_of = {vid: state["videos"][vid]["ch"] for vid in final}
    paths = build_paths(cfg, final, series, channels_of)

    try:
        curated = resources.load_curated(args.config, {t.id for t in cfg.topics})
    except ConfigError as exc:
        print(f"::error::config: {exc}")
        return 2
    online = not args.offline and not args.fixture
    fetch = None
    if args.fixture:
        from .fake import fake_web
        fetch = fake_web(args.fixture)
    elif online:
        fetch = enrich.http_fetch
    res = collect_resources(cfg, state, final, series, curated, log, fetch)
    if fetch:
        save_state(state, args.state)

    meta = {
        "generated": iso(now),
        "builder": __version__,
        "videos_scanned": len(state["videos"]),
        "videos_listed": len(final),
        "courses": len(series),
        "quota_used": used,
        "warnings": len(log.warnings),
        "sample_data": bool(args.fixture),
    }
    meta["papers"] = len(res["papers"])
    catalog = build_catalog(cfg, state, final, series, paths, boiler, meta, res)
    write_site(catalog, ROOT / "site", args.out, cfg.site.get("base_url", ""))
    log.info(f"site written to {args.out}: {len(final)} videos, {len(series)} courses "
             f"(scanned {len(state['videos'])} videos)")
    if not final and not args.allow_empty:
        print("::error::catalog is empty; refusing to deploy an empty site (use --allow-empty to override)")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m builder", description="Build the AI learning video site.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="sync from YouTube (unless --offline) and write the static site")
    b.add_argument("--config", default=str(ROOT / "config"))
    b.add_argument("--state", default=str(ROOT / ".state"))
    b.add_argument("--out", default=str(ROOT / "dist"))
    b.add_argument("--offline", action="store_true", help="don't call the API; rebuild from cached state")
    b.add_argument("--full", action="store_true", help="rescan every uploads list and playlist")
    b.add_argument("--fixture", help="use a fixture JSON instead of the real API (demo/tests)")
    b.add_argument("--allow-empty", action="store_true")
    b.add_argument("--quiet", action="store_true")
    c = sub.add_parser("check", help="validate the config files")
    c.add_argument("--config", default=str(ROOT / "config"))
    args = ap.parse_args(argv)
    if args.cmd == "check":
        try:
            cfg = load_config(args.config)
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 2
        try:
            cur = resources.load_curated(args.config, {t.id for t in cfg.topics})
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 2
        print(f"ok: {len(cfg.enabled_channels)} channels, {len(cfg.topics)} topics, {len(cfg.roadmaps)} roadmaps, "
              f"{len(cur['courses'])} curated courses, {len(cur['starters'])} starter kits")
        return 0
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
