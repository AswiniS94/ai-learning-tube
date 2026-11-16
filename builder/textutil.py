"""Text normalisation, keyword matching and description clean-up."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_COURSE_GAP = re.compile(r"\b(x?cs|cme|stats|ee|msande)\s(\d{2,3}[a-z]?)\b")
_URL = re.compile(r"https?://|www\.|\.(?:com|org|net|io|biz|ly|in|edu)/", re.I)
_CHAPTER = re.compile(r"(?m)^\s*[\(\[]?\d{1,2}:\d{2}(?::\d{2})?[\)\]]?\s")
_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")
COURSE_CODE = re.compile(r"\b(x?cs|cme|stats|ee|msande)(\d{2,3}[a-z]?)\b")


def normalize(text: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumerics to single spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_ALNUM.sub(" ", text.lower()).strip()
    return _COURSE_GAP.sub(r"\1\2", text)


class KeywordMatcher:
    """Whole-word phrase matcher on normalized text.

    Scans tokens left to right and takes the longest keyword starting at each
    position (so "reinforcement learning from human feedback" wins over
    "reinforcement learning"). Matches don't overlap. Runs in O(tokens).
    """

    def __init__(self, keywords):
        self.keywords = {normalize(k) for k in keywords} - {""}
        self.max_len = max((k.count(" ") + 1 for k in self.keywords), default=0)

    def find(self, normalized_text: str) -> set[str]:
        found: set[str] = set()
        if not self.keywords or not normalized_text:
            return found
        toks = normalized_text.split()
        n, i, kws, max_len = len(toks), 0, self.keywords, self.max_len
        while i < n:
            for size in range(min(max_len, n - i), 0, -1):
                g = " ".join(toks[i : i + size])
                if g in kws:
                    found.add(g)
                    i += size
                    break
            else:
                i += 1
        return found

    def any(self, normalized_text: str) -> bool:
        return bool(self.find(normalized_text))


def parse_duration(iso: str | None) -> int:
    """ISO-8601 duration (PT1H2M3S, P1DT2H, P0D) -> seconds; 0 if unknown."""
    if not iso:
        return 0
    m = _DURATION.match(iso)
    if not m:
        return 0
    d, h, mi, s = m.groups()
    return int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi or 0) * 60 + int(float(s or 0))


def has_chapters(description: str) -> bool:
    return len(_CHAPTER.findall(description or "")) >= 3


def boilerplate_lines(descriptions: list[str]) -> set[str]:
    """Normalized lines that repeat across many descriptions of one channel."""
    counts: Counter[str] = Counter()
    for desc in descriptions:
        lines = {normalize(line) for line in (desc or "").splitlines()}
        lines.discard("")
        counts.update(lines)
    n = len(descriptions)
    limit = max(4, int(0.02 * n))
    return {line for line, c in counts.items() if c >= limit}


def clean_description(description: str, boilerplate: set[str], limit: int = 1500) -> str:
    """Drop link lines and channel boilerplate; return normalized text."""
    out = []
    size = 0
    for line in (description or "").splitlines():
        if _URL.search(line):
            continue
        n = normalize(line)
        if not n or n in boilerplate:
            continue
        out.append(n)
        size += len(n) + 1
        if size >= limit:
            break
    return " ".join(out)[:limit]


def course_codes(normalized_text: str) -> list[str]:
    return [a + b for a, b in COURSE_CODE.findall(normalized_text)]
