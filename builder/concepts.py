"""Core paths: the fewest good videos that cover every key concept of a level.

For each topic and level with a concept checklist (config/concepts.toml):
1. Work out which concepts each candidate (video, or a whole course) covers.
2. Greedily pick the candidate with the best value per cost, where
   value = newly covered concepts x quality, cost = 1 step + half an hour-equivalent of time.
   Short, focused videos therefore win unless a course covers much more at once.
3. Stop when every concept is covered or no candidate adds anything; the rest are gaps.

Steps are ordered by the earliest concept they cover, so the path follows the checklist.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .config import LEVELS, Config, ConfigError
from .textutil import KeywordMatcher, clean_description, normalize

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_concepts(config_dir: str | Path, topic_ids: set[str]) -> dict:
    path = Path(config_dir) / "concepts.toml"
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    out = {}
    for tid, levels in raw.items():
        if tid not in topic_ids:
            raise ConfigError(f"concepts.toml: unknown topic {tid!r}")
        if not isinstance(levels, dict):
            raise ConfigError(f"concepts.toml [{tid}]: expected beginner/intermediate/advanced lists")
        seen = set()
        out[tid] = {}
        for lv, items in levels.items():
            if lv not in LEVELS:
                raise ConfigError(f"concepts.toml [{tid}]: unknown level {lv!r}")
            concepts = []
            for c in items:
                cid, name, kws = c.get("id", ""), c.get("name", ""), c.get("keywords", [])
                if not _ID_RE.match(cid) or not name or not kws:
                    raise ConfigError(f"concepts.toml [{tid}].{lv}: each concept needs id, name and keywords ({c})")
                if cid in seen:
                    raise ConfigError(f"concepts.toml [{tid}]: duplicate concept id {cid!r}")
                seen.add(cid)
                concepts.append({"id": cid, "name": name, "keywords": list(kws), "m": KeywordMatcher(kws)})
            out[tid][lv] = concepts
    return out


def video_text(state: dict, vid: str, boiler: dict) -> str:
    v = state["videos"][vid]
    det = v.get("details") or {}
    return " ".join([
        normalize(v.get("title", "")),
        normalize(" ".join(det.get("tags", []))),
        clean_description(v.get("desc", ""), boiler.get(v.get("ch"), set()), 600),
    ])


def covered(concepts: list[dict], text: str) -> set[str]:
    return {c["id"] for c in concepts if c["m"].any(text)}


def build_core_paths(cfg: Config, state: dict, tagged: dict, series: dict, concepts: dict, boiler: dict,
                     max_steps: int = 6, min_quality: float = 25.0) -> dict:
    """Returns {topic: {level: {"items": [{"k","id","cv":[concept ids]}], "gaps": [concept ids]}}}."""
    texts = {}

    def text_of(vid):
        if vid not in texts:
            texts[vid] = video_text(state, vid, boiler)
        return texts[vid]

    pins = cfg.overrides.get("pin", [])
    out = {}
    for tid, levels in concepts.items():
        out[tid] = {}
        for lv in LEVELS:
            cl = levels.get(lv) or []
            if not cl:
                continue
            cands = []
            for vid, r in tagged.items():
                if tid in r["topics"] and r["level"] == lv and r["format"] != "News & Podcast" and r["q"] >= min_quality:
                    cands.append({"k": "v", "id": vid, "cov": covered(cl, text_of(vid)), "q": r["q"],
                                  "hours": state["videos"][vid]["details"].get("duration", 0) / 3600,
                                  "primary": r["topics"][0] == tid})
            for s in series.values():
                if tid in s["topics"] and s["level"] == lv and s["q"] >= min_quality:
                    cov = covered(cl, normalize(s["title"]))
                    for vid in s["members"]:
                        cov |= covered(cl, text_of(vid))
                    hours = sum(state["videos"][v]["details"].get("duration", 0) for v in s["members"]) / 3600
                    cands.append({"k": "s", "id": s["id"], "cov": cov, "q": s["q"], "hours": hours,
                                  "primary": s["topics"][0] == tid})
            out[tid][lv] = pick(cl, cands, max_steps,
                                [p for p in pins if p["topic"] == tid and p["level"] == lv])
    return out


def pick(concepts: list[dict], cands: list[dict], max_steps: int, pins: list[dict] | None = None) -> dict:
    order = {c["id"]: i for i, c in enumerate(concepts)}
    uncovered = set(order)
    chosen = []
    by_ref = {(c["k"], c["id"]): c for c in cands}
    for p in pins or []:
        ref = ("s", p["playlist"]) if p.get("playlist") else ("v", p["video"])
        c = by_ref.get(ref)
        if c and c not in chosen:
            chosen.append(c)
            c["new"] = c["cov"] & uncovered
            uncovered -= c["cov"]
    pool = [c for c in cands if c["cov"] and c not in chosen]
    while uncovered and len(chosen) < max_steps:
        best, best_val = None, 0.0
        for c in pool:
            new = c["cov"] & uncovered
            if not new:
                continue
            value = len(new) * (0.5 + c["q"] / 100) * (1.15 if c["primary"] else 1.0)
            cost = 1.0 + c["hours"] / 2
            val = value / cost
            # deterministic tie-break: higher quality, then id
            if best is None or val > best_val + 1e-9 or (abs(val - best_val) <= 1e-9 and (c["q"], c["id"]) > (best["q"], best["id"])):
                best, best_val = c, val
        if best is None:
            break
        best["new"] = best["cov"] & uncovered
        uncovered -= best["cov"]
        chosen.append(best)
        pool.remove(best)
    chosen.sort(key=lambda c: min((order[x] for x in c["new"]), default=len(order)))
    return {
        "items": [{"k": c["k"], "id": c["id"], "cv": sorted(c["cov"], key=order.get)} for c in chosen],
        "gaps": sorted(uncovered, key=order.get),
    }


def concepts_for_site(concepts: dict) -> dict:
    """Strip matchers; keep id, name and a search query for gaps."""
    return {tid: {lv: [{"id": c["id"], "n": c["name"], "s": c["keywords"][0]} for c in cl] for lv, cl in levels.items()}
            for tid, levels in concepts.items()}
