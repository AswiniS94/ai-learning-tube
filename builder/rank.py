"""Quality score for every tagged video (0–100, higher is better)."""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from statistics import median

from .config import Config
from .sync import parse_iso
from .textutil import has_chapters

COMPONENTS = ("approval", "popularity", "engagement", "freshness", "completeness", "structure")


def percentiles(values: dict[str, float]) -> dict[str, float]:
    """Rank-based percentile in [0, 1]; ties share their average rank."""
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {k: 0.5 for k in values}
    items = sorted(values.items(), key=lambda kv: kv[1])
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        p = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[items[k][0]] = p
        i = j + 1
    return out


def age_days(published: str, now: dt.datetime) -> float:
    t = parse_iso(published)
    if not t:
        return 365.0
    return max(1.0, (now - t).total_seconds() / 86400)


def score_videos(cfg: Config, state: dict, tagged: dict[str, dict], series_members: set[str], now: dt.datetime) -> None:
    """Adds 'q' (score) and 'qb' (component breakdown, 0–100) to each tagged result."""
    weights = cfg.ranking
    chan_w = {c.key: c.weight for c in cfg.channels}
    half_life = {t.id: t.half_life_years for t in cfg.topics}
    boosts = cfg.overrides.get("boost", {})

    by_ch = defaultdict(list)
    for vid in tagged:
        by_ch[state["videos"][vid]["ch"]].append(vid)

    approval, engagement, pop = {}, {}, {}
    for ch, vids in by_ch.items():
        like_rates = []
        comment_rates = []
        for vid in vids:
            d = state["videos"][vid]["details"]
            if d.get("views"):
                if d.get("likes") is not None:
                    like_rates.append(d["likes"] / d["views"])
                if d.get("comments") is not None:
                    comment_rates.append(d["comments"] / d["views"])
        prior_like = median(like_rates) if like_rates else 0.02
        prior_comment = median(comment_rates) if comment_rates else 0.001

        lr, cr, total, rate = {}, {}, {}, {}
        for vid in vids:
            v = state["videos"][vid]
            d = v["details"]
            views = d.get("views") or 0
            if d.get("likes") is not None:
                lr[vid] = (d["likes"] + 500 * prior_like) / (views + 500)
            if d.get("comments") is not None:
                cr[vid] = (d["comments"] + 2000 * prior_comment) / (views + 2000)
            total[vid] = math.log1p(views)
            rate[vid] = math.log1p(views / max(7.0, age_days(v.get("published", ""), now)))
        p_lr, p_cr, p_tot, p_rate = percentiles(lr), percentiles(cr), percentiles(total), percentiles(rate)
        for vid in vids:
            approval[vid] = p_lr.get(vid, 0.5)
            engagement[vid] = p_cr.get(vid, 0.5)
            pop[vid] = 0.5 * p_tot[vid] + 0.5 * p_rate[vid]

    for vid, res in tagged.items():
        v = state["videos"][vid]
        d = v["details"]
        primary = res["topics"][0]
        years = age_days(v.get("published", ""), now) / 365.25
        fresh = 0.5 ** (years / max(0.5, half_life.get(primary, 5)))
        desc = v.get("desc", "")
        complete = 0.4 * bool(d.get("caption")) + 0.3 * has_chapters(desc) + 0.3 * (len(desc) >= 300)
        structure = 1.0 if vid in series_members else (0.5 if res.get("playlists") else 0.3)
        comp = {
            "approval": approval[vid],
            "popularity": pop[vid],
            "engagement": engagement[vid],
            "freshness": fresh,
            "completeness": complete,
            "structure": structure,
        }
        raw = sum(weights[k] * comp[k] for k in COMPONENTS)
        q = 100 * raw * chan_w.get(v["ch"], 1.0) + float(boosts.get(vid, 0))
        res["q"] = round(min(100.0, max(0.0, q)), 1)
        res["qb"] = [round(100 * comp[k]) for k in COMPONENTS]
