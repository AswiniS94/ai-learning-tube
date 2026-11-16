"""Course (series) detection and beginner → intermediate → advanced learning paths."""

from __future__ import annotations

import math
from collections import Counter

from .config import LEVELS, Config
from .textutil import course_codes, normalize


def build_series(cfg: Config, state: dict, tagged: dict[str, dict], pls: dict[str, dict], course_levels: dict) -> dict[str, dict]:
    """Relevant playlists with >= 3 catalog videos become series; each video gets one primary series."""
    series = {}
    for pid, res in pls.items():
        p = state["playlists"][pid]
        members = [vid for vid in (p.get("items") or []) if vid in tagged]
        news = sum(tagged[v]["format"] == "News & Podcast" for v in members)
        if len(members) < 3 or res.get("news") or news >= 0.5 * len(members):
            continue
        series[pid] = {
            "id": pid,
            "title": p.get("title", ""),
            "ch": p.get("ch"),
            "topics": res["topics"],
            "course": bool(res.get("course")),
            "codes": res.get("codes", []),
            "members": members,
        }

    # Drop near-duplicate playlists (same lectures re-published as another list).
    ordered = sorted(series.values(), key=lambda s: (-s["course"], -len(s["members"]), s["id"]))
    kept: list[dict] = []
    for s in ordered:
        ms = set(s["members"])
        if any(len(ms & set(k["members"])) >= 0.8 * len(ms) for k in kept):
            continue
        kept.append(s)
    series = {s["id"]: s for s in kept}

    # Primary series per video: a course beats a loose playlist, then the most specific (smallest).
    for vid, res in tagged.items():
        cands = [series[pid] for pid in res.get("playlists", []) if pid in series]
        if not cands:
            continue
        best = sorted(cands, key=lambda s: (not s["course"], len(s["members"]), s["id"]))[0]
        res["series"] = best["id"]
        res["sx"] = best["members"].index(vid)

    for s in series.values():
        lv = None
        for code in s["codes"]:
            lv = course_levels.get(code)
            if lv:
                break
        if not lv:
            votes = Counter(tagged[v]["level"] for v in s["members"])
            lv = max(LEVELS, key=lambda l: (votes.get(l, 0), l == "intermediate"))
        s["level"] = lv
    return series


def score_series(series: dict[str, dict], tagged: dict[str, dict]) -> None:
    for s in series.values():
        qs = [tagged[v]["q"] for v in s["members"]]
        base = sum(qs) / len(qs)
        s["q"] = round(min(100.0, base + min(6.0, len(qs) / 3)), 1)


def build_paths(cfg: Config, tagged: dict[str, dict], series: dict[str, dict], channels_of: dict) -> dict:
    k = int(cfg.build.get("path_items_per_level", 8))
    max_series = max(1, math.ceil(k / 2))
    pins = cfg.overrides.get("pin", [])
    paths = {}
    for topic in cfg.topics:
        tid = topic.id
        s_cands = [s for s in series.values() if tid in s["topics"]]
        # A lecture from the middle of a course is never a standalone step: courses are taken whole.
        covered = {v for s in series.values() if s["course"] for v in s["members"]}
        v_cands = [
            (vid, r) for vid, r in tagged.items()
            if tid in r["topics"] and r["format"] != "News & Podcast" and vid not in covered
        ]
        topic_path = {}
        for lv in LEVELS:
            pool = []
            for s in s_cands:
                if s["level"] == lv:
                    pool.append(("s", s["id"], s["q"] + (5 if s["topics"][0] == tid else 0), s["ch"]))
            for vid, r in v_cands:
                if r["level"] == lv:
                    pool.append(("v", vid, r["q"] + (5 if r["topics"][0] == tid else 0), channels_of[vid]))
            picked = _pick(pool, k, max_series)
            # Beginners start with short standalone videos; later levels lead with full courses.
            picked.sort(key=(lambda x: x[0] == "s") if lv == "beginner" else (lambda x: x[0] == "v"))
            for pin in pins:
                if pin["topic"] == tid and pin["level"] == lv:
                    ref = ("s", pin["playlist"]) if pin.get("playlist") else ("v", pin["video"])
                    exists = ref[1] in series if ref[0] == "s" else ref[1] in tagged
                    if exists:
                        picked = [ref] + [p for p in picked if p != ref]
            picked = picked[:k]
            topic_path[lv] = [{"k": kind, "id": i} for kind, i in picked]
        paths[tid] = topic_path
    return paths


def _pick(pool, k, max_series):
    """Greedy pick by score with light channel diversity; videos and courses interleaved by score."""
    chosen = []
    per_channel = Counter()
    n_series = 0
    remaining = sorted(pool, key=lambda x: (-x[2], x[1]))
    while remaining and len(chosen) < k:
        best_i, best_val = None, None
        for i, (kind, _id, sc, ch) in enumerate(remaining):
            if kind == "s" and n_series >= max_series:
                continue
            val = sc - 4.0 * max(0, per_channel[ch] - 1)
            if best_val is None or val > best_val:
                best_i, best_val = i, val
        if best_i is None:
            break
        kind, _id, sc, ch = remaining.pop(best_i)
        chosen.append((kind, _id, sc))
        per_channel[ch] += 1
        n_series += kind == "s"
    return [(kind, _id) for kind, _id, _ in chosen]


def course_level_map(cfg: Config) -> dict:
    return {normalize(k).replace(" ", ""): v for k, v in cfg.level.get("course_codes", {}).items()}


__all__ = ["build_series", "score_series", "build_paths", "course_level_map", "course_codes"]
