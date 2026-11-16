"""Rule-based tagging: relevance, topics, level and format.

Everything is deterministic and explainable: each tag carries the signals that
produced it, and those are shown on the site ("why this level?").
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .config import LEVELS, Config
from . import textutil
from .textutil import KeywordMatcher, boilerplate_lines, clean_description, course_codes, display_code, normalize

TALK_WORDS = [
    "seminar", "talk", "talks", "keynote", "webinar", "panel", "panel discussion",
    "fireside chat", "guest lecture", "interview", "in conversation", "symposium",
    "conference", "summit", "colloquium", "q a", "ama", "distinguished lecture",
]
TUTORIAL_WORDS = [
    "tutorial", "tutorials", "hands on", "demo", "walkthrough", "coding", "code along",
    "step by step", "how to build", "build a", "build an", "building a", "building an",
    "implement", "implementing", "lab", "colab", "notebook", "live coding", "from scratch",
    "with python", "in python", "guide to building",
]
COURSE_WORDS = [
    "course", "lectures", "lecture series", "nptel", "noc", "full course", "autumn",
    "spring", "winter", "summer", "fall", "semester", "syllabus",
]
_LECTURE_RE = re.compile(
    r"\b(lecture|lectures|lec|mod\d+\s?lec\d+|week \d+|module \d+|session \d+|class \d+|unit \d+|part \d+ of \d+)\b"
)


@dataclass
class TopicResult:
    scores: dict = field(default_factory=dict)
    hits: dict = field(default_factory=dict)  # topic -> sorted keywords
    strong: set = field(default_factory=set)  # topics with a strong (non-contextual) hit


class Classifier:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        c = cfg.classifier
        self.w_title = float(c.get("title_weight", 3.0))
        self.w_tag = float(c.get("tag_weight", 2.0))
        self.w_desc = float(c.get("description_weight", 1.0))
        self.ctx_factor = float(c.get("contextual_factor", 0.5))
        self.threshold = float(c.get("threshold", 3.0))
        self.secondary_ratio = float(c.get("secondary_ratio", 0.5))
        self.max_topics = int(c.get("max_topics", 3))
        self.inherit = float(c.get("playlist_inherit_factor", 0.75))

        self.kw_map: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        for t in cfg.topics:
            for k in t.keywords:
                self.kw_map[normalize(k)].append((t.id, False))
            for k in t.contextual:
                self.kw_map[normalize(k)].append((t.id, True))
        self.kw = KeywordMatcher(self.kw_map.keys())
        self.ctx = KeywordMatcher(c.get("ai_context", []))
        self.exclude = KeywordMatcher(c.get("exclude_title", []))
        self.news = KeywordMatcher(c.get("news_patterns", []))
        self.news_desc = KeywordMatcher(["podcast", "this episode", "in this episode", "today s episode"])
        lv = cfg.level
        self.level_kw = {name: KeywordMatcher(lv.get(name, [])) for name in LEVELS}
        self.course_levels = {normalize(k).replace(" ", ""): v for k, v in lv.get("course_codes", {}).items()}
        textutil.KNOWN_NUMERIC_CODES.clear()
        textutil.KNOWN_NUMERIC_CODES.update(k for k in self.course_levels if k[:1].isdigit())
        self.channel_prior = lv.get("channel_prior", {})
        self.talk = KeywordMatcher(TALK_WORDS)
        self.tutorial = KeywordMatcher(TUTORIAL_WORDS)
        self.course_words = KeywordMatcher(COURSE_WORDS)

    # ---------------------------------------------------------------- topics
    def topic_scores(self, fields: list[tuple[str, float]]) -> TopicResult:
        alltext = " ".join(t for t, _ in fields)
        found_per_field = [(self.kw.find(text), w) for text, w in fields]
        any_strong = any(not ctx for found, _ in found_per_field for k in found for _, ctx in self.kw_map[k])
        has_ctx = any_strong or self.ctx.any(alltext)
        res = TopicResult()
        hits = defaultdict(set)
        for found, w in found_per_field:
            for k in found:
                for tid, contextual in self.kw_map[k]:
                    if contextual and not has_ctx:
                        continue
                    res.scores[tid] = res.scores.get(tid, 0.0) + w * (self.ctx_factor if contextual else 1.0)
                    hits[tid].add(k)
                    if not contextual:
                        res.strong.add(tid)
        res.hits = {t: sorted(v) for t, v in hits.items()}
        return res

    def pick_topics(self, scores: dict, strong: set) -> list[str]:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if not ranked:
            return []
        best_t, best = ranked[0]
        if best < self.threshold or best_t not in strong:
            return []
        out = [best_t]
        floor = max(self.threshold, self.secondary_ratio * best)
        for t, s in ranked[1:]:
            if len(out) >= self.max_topics:
                break
            if s >= floor:
                out.append(t)
        return out

    # ------------------------------------------------------------- playlists
    def classify_playlist(self, p: dict, boilerplate: set[str]) -> dict:
        title = normalize(p.get("title", ""))
        desc = clean_description(p.get("desc", ""), boilerplate, 800)
        if self.exclude.any(title):
            return {"topics": [], "scores": {}, "excluded": True}
        r = self.topic_scores([(title, self.w_title), (desc, self.w_desc)])
        return {
            "topics": self.pick_topics(r.scores, r.strong),
            "scores": r.scores,
            "strong": sorted(r.strong),
            "news": self.news.any(title),
            "codes": course_codes(title),
            "course_words": self.course_words.any(title),
            "title_norm": title,
        }

    # ---------------------------------------------------------------- videos
    def classify_video(self, v: dict, boilerplate: set[str], playlists: list[dict]) -> dict:
        """playlists: classified relevant playlists containing this video (with 'title_norm')."""
        title = normalize(v.get("title", ""))
        det = v.get("details") or {}
        tags = normalize(" ".join(det.get("tags", [])))
        desc = clean_description(v.get("desc", ""), boilerplate)
        out = {"relevant": False, "topics": [], "why": {}}
        if self.exclude.any(title):
            out["why"]["excluded"] = sorted(self.exclude.find(title))
            return out
        r = self.topic_scores([(title, self.w_title), (tags, self.w_tag), (desc, self.w_desc)])
        scores = dict(r.scores)
        strong = set(r.strong)
        inherited = {}
        for p in playlists:
            # Lectures in a course inherit its topic fully (NPTEL titles are often just
            # "Lecture 1: Introduction"); loose playlists pass on part of their score.
            factor = 1.0 if p.get("course") else self.inherit
            for tid, s in p["scores"].items():
                if tid in p.get("strong", []):
                    inherited[tid] = max(inherited.get(tid, 0.0), factor * s)
        for tid, s in inherited.items():
            scores[tid] = scores.get(tid, 0.0) + s
            strong.add(tid)
        topics = self.pick_topics(scores, strong)
        out["topics"] = topics
        out["scores"] = {t: round(scores[t], 2) for t in topics}
        out["why"]["keywords"] = {t: r.hits.get(t, []) for t in topics}
        if inherited:
            out["why"]["from_playlist"] = sorted(t for t in topics if t in inherited)
        out["relevant"] = bool(topics)
        if not topics:
            return out

        pl_titles = [p["title_norm"] for p in playlists]
        out["level"], out["why"]["level"] = self.level(v, title, desc, pl_titles)
        out["format"], out["why"]["format"] = self.fmt(v, title, pl_titles, playlists)
        return out

    def level(self, v: dict, title: str, desc: str, pl_titles: list[str]) -> tuple[str, list[str]]:
        score = {lv: 0.0 for lv in LEVELS}
        signals = []
        for text in [title] + pl_titles:
            for code in course_codes(text):
                lv = self.course_levels.get(code)
                if lv:
                    score[lv] += 4.0
                    signals.append((lv, f"{display_code(code)} is a{'n' if lv[0] in 'aei' else ''} {lv}-level course"))
                    break
        for lv, m in self.level_kw.items():
            for k in m.find(title):
                score[lv] += 2.0
                signals.append((lv, f"title says “{k}”"))
            for pt in pl_titles:
                for k in m.find(pt):
                    score[lv] += 1.5
                    signals.append((lv, f"course/playlist says “{k}”"))
            for k in m.find(desc[:400]):
                score[lv] += 0.5
        prior = self.channel_prior.get(v.get("ch", ""), {})
        for lv, s in prior.items():
            score[lv] += float(s)
        dur = (v.get("details") or {}).get("duration", 0)
        if dur:
            if dur < 600:
                score["beginner"] += 1.0
                signals.append(("beginner", "short (under 10 min)"))
            elif dur > 2400:
                score["intermediate"] += 0.75
        order = {"intermediate": 2, "beginner": 1, "advanced": 0}
        best = max(LEVELS, key=lambda lv: (score[lv], order[lv]))
        # keep the signals that point at the chosen level first, de-duplicated
        if prior.get(best):
            signals.append((best, "typical level for this channel"))
        seen, ordered = set(), []
        for lv, s in sorted(signals, key=lambda x: x[0] != best):
            if lv == best and s not in seen:
                seen.add(s)
                ordered.append(s)
        return best, ordered[:4] or ["default for long-form content"]

    def fmt(self, v: dict, title: str, pl_titles: list[str], playlists: list[dict]) -> tuple[str, str]:
        dur = (v.get("details") or {}).get("duration", 0)
        raw_desc = normalize((v.get("desc") or "")[:600])
        if self.news.any(title) or any(self.news.any(t) for t in pl_titles) or self.news_desc.any(raw_desc):
            return "News & Podcast", "news show / podcast"
        if self.talk.any(title):
            return "Talk", "title mentions " + ", ".join(sorted(self.talk.find(title)))
        if _LECTURE_RE.search(title) or course_codes(title):
            return "Lecture", "numbered course lecture"
        in_course = any(p.get("course") for p in playlists)
        if in_course and dur >= 1500:
            return "Lecture", "part of a course playlist"
        if self.tutorial.any(title):
            return "Tutorial", "hands-on: " + ", ".join(sorted(self.tutorial.find(title)))
        if dur and dur <= 1200:
            return "Explainer", "short focused explainer"
        if any(self.talk.any(t) for t in pl_titles):
            return "Talk", "from a seminar/talk series"
        return "Deep dive", "long-form single video"


def channel_boilerplate(state: dict) -> dict[str, set[str]]:
    by_ch = defaultdict(list)
    for v in state["videos"].values():
        by_ch[v.get("ch", "")].append(v.get("desc", ""))
    return {ch: boilerplate_lines(descs) for ch, descs in by_ch.items()}


def classify_playlists(clf: Classifier, cfg: Config, state: dict, boiler: dict) -> dict[str, dict]:
    excluded = set(cfg.overrides.get("exclude_playlists", []))
    enabled = {c.key for c in cfg.enabled_channels}
    out = {}
    for pid, p in state["playlists"].items():
        if pid in excluded or p.get("ch") not in enabled:
            continue
        res = clf.classify_playlist(p, boiler.get(p.get("ch"), set()))
        if res.get("topics"):
            out[pid] = res
    return out


def finalize_playlist_course_flags(clf: Classifier, state: dict, pls: dict[str, dict]) -> None:
    """A playlist is a 'course' if its title says so or most items are lectures."""
    for pid, res in pls.items():
        items = state["playlists"][pid].get("items") or []
        lecture_like = 0
        for vid in items:
            t = normalize(state["videos"].get(vid, {}).get("title", ""))
            if _LECTURE_RE.search(t) or course_codes(t):
                lecture_like += 1
        res["course"] = len(items) >= 3 and (
            bool(res["codes"]) or res["course_words"] or lecture_like >= 0.5 * len(items)
        ) and not res.get("news")


def video_playlist_index(state: dict, pls: dict[str, dict]) -> dict[str, list[str]]:
    idx = defaultdict(list)
    for pid in pls:
        for vid in state["playlists"][pid].get("items") or []:
            idx[vid].append(pid)
    return idx


def classify_videos(clf: Classifier, cfg: Config, state: dict, boiler: dict, pls: dict, vp_index: dict) -> dict[str, dict]:
    excluded = set(cfg.overrides.get("exclude_videos", []))
    forced = set(cfg.overrides.get("include_videos", []))
    enabled = {c.key for c in cfg.enabled_channels}
    out = {}
    for vid, v in state["videos"].items():
        if vid in excluded or v.get("gone") or v.get("ch") not in enabled:
            continue
        playlists = [pls[pid] for pid in vp_index.get(vid, [])]
        res = clf.classify_video(v, boiler.get(v.get("ch"), set()), playlists)
        if not res["relevant"] and vid in forced:
            res = _forced(clf, v, playlists)
        if res["relevant"]:
            res["playlists"] = vp_index.get(vid, [])
            out[vid] = res
    return out


def _forced(clf: Classifier, v: dict, playlists: list[dict]) -> dict:
    title = normalize(v.get("title", ""))
    r = clf.topic_scores([(title, clf.w_title), (normalize(v.get("desc", "")), clf.w_desc)])
    ranked = sorted(r.scores.items(), key=lambda kv: -kv[1])
    topics = [ranked[0][0]] if ranked else [clf.cfg.topics[0].id]
    pl = [p["title_norm"] for p in playlists]
    lv, lsig = clf.level(v, title, "", pl)
    fm, fsig = clf.fmt(v, title, pl, playlists)
    return {"relevant": True, "topics": topics, "scores": {topics[0]: 0}, "level": lv, "format": fm,
            "why": {"keywords": {}, "level": lsig, "format": fsig, "forced": True}}
