"""Load and validate the TOML configuration files."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

LEVELS = ("beginner", "intermediate", "advanced")
FORMATS = ("Explainer", "Lecture", "Tutorial", "Talk", "Deep dive", "News & Podcast")


class ConfigError(ValueError):
    pass


@dataclass
class Channel:
    key: str
    name: str
    handle: str = ""
    channel_id: str = ""
    weight: float = 1.0
    enabled: bool = True
    scan_playlists: bool = True


@dataclass
class Topic:
    id: str
    name: str
    description: str
    half_life_years: float
    prerequisites: list[str]
    keywords: list[str]
    contextual: list[str]


@dataclass
class Config:
    site: dict
    build: dict
    channels: list[Channel]
    classifier: dict
    topics: list[Topic]
    roadmaps: list[dict]
    level: dict
    ranking: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)

    @property
    def enabled_channels(self) -> list[Channel]:
        return [c for c in self.channels if c.enabled]

    def topic(self, topic_id: str) -> Topic:
        for t in self.topics:
            if t.id == topic_id:
                return t
        raise KeyError(topic_id)


_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

BUILD_DEFAULTS = {
    "min_duration_seconds": 120,
    "quota_budget": 9000,
    "stats_refresh_hours": 20,
    "full_rescan_days": 7,
    "path_items_per_level": 8,
}

RANKING_DEFAULTS = {
    "approval": 0.30,
    "popularity": 0.25,
    "engagement": 0.10,
    "freshness": 0.15,
    "completeness": 0.10,
    "structure": 0.10,
}


def _load(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"missing config file: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def load_config(config_dir: str | Path) -> Config:
    config_dir = Path(config_dir)
    ch = _load(config_dir / "channels.toml")
    tx = _load(config_dir / "taxonomy.toml")
    ov_path = config_dir / "overrides.toml"
    ov = _load(ov_path) if ov_path.exists() else {}

    channels = []
    seen = set()
    for raw in ch.get("channel", []):
        unknown = set(raw) - {"key", "name", "handle", "channel_id", "weight", "enabled", "scan_playlists"}
        if unknown:
            raise ConfigError(f"channel {raw.get('key')!r}: unknown fields {sorted(unknown)}")
        c = Channel(**raw)
        if not _KEY_RE.match(c.key):
            raise ConfigError(f"channel key {c.key!r} must be lowercase letters, digits and dashes")
        if c.key in seen:
            raise ConfigError(f"duplicate channel key {c.key!r}")
        seen.add(c.key)
        if not c.channel_id and not c.handle:
            raise ConfigError(f"channel {c.key!r} needs a handle or a channel_id")
        if c.channel_id and not re.match(r"^UC[\w-]{22}$", c.channel_id):
            raise ConfigError(f"channel {c.key!r}: channel_id {c.channel_id!r} doesn't look like a YouTube channel id")
        if not 0.5 <= float(c.weight) <= 1.5:
            raise ConfigError(f"channel {c.key!r}: weight should be between 0.5 and 1.5")
        c.weight = float(c.weight)
        channels.append(c)
    if not channels:
        raise ConfigError("channels.toml defines no [[channel]] entries")

    build = {**BUILD_DEFAULTS, **ch.get("build", {})}

    topics = []
    tids = set()
    for raw in tx.get("topic", []):
        t = Topic(
            id=raw["id"],
            name=raw["name"],
            description=raw.get("description", ""),
            half_life_years=float(raw.get("half_life_years", 5)),
            prerequisites=list(raw.get("prerequisites", [])),
            keywords=list(raw.get("keywords", [])),
            contextual=list(raw.get("contextual", [])),
        )
        if not _KEY_RE.match(t.id):
            raise ConfigError(f"topic id {t.id!r} must be lowercase letters, digits and dashes")
        if t.id in tids:
            raise ConfigError(f"duplicate topic id {t.id!r}")
        if not t.keywords:
            raise ConfigError(f"topic {t.id!r} has no keywords")
        tids.add(t.id)
        topics.append(t)
    for t in topics:
        for p in t.prerequisites:
            if p not in tids:
                raise ConfigError(f"topic {t.id!r}: unknown prerequisite {p!r}")
    roadmaps = tx.get("roadmap", [])
    for r in roadmaps:
        for tid in r.get("topics", []):
            if tid not in tids:
                raise ConfigError(f"roadmap {r.get('id')!r}: unknown topic {tid!r}")

    level = tx.get("level", {})
    for code, lv in level.get("course_codes", {}).items():
        if lv not in LEVELS:
            raise ConfigError(f"course code {code!r}: level must be one of {LEVELS}")
    for key, prior in level.get("channel_prior", {}).items():
        for lv in prior:
            if lv not in LEVELS:
                raise ConfigError(f"channel_prior {key!r}: unknown level {lv!r}")

    for rt in ov.get("retag", []):
        if "level" in rt and rt["level"] not in LEVELS:
            raise ConfigError(f"retag {rt.get('video')}: bad level {rt['level']!r}")
        if "format" in rt and rt["format"] not in FORMATS:
            raise ConfigError(f"retag {rt.get('video')}: bad format {rt['format']!r}")
        for tid in rt.get("topics", []):
            if tid not in tids:
                raise ConfigError(f"retag {rt.get('video')}: unknown topic {tid!r}")
    for pin in ov.get("pin", []):
        if pin.get("topic") not in tids or pin.get("level") not in LEVELS:
            raise ConfigError(f"pin {pin}: needs a valid topic and level")
        if not (pin.get("video") or pin.get("playlist")):
            raise ConfigError(f"pin {pin}: needs video or playlist")

    ranking = {**RANKING_DEFAULTS, **tx.get("ranking", {})}
    unknown = set(ranking) - set(RANKING_DEFAULTS)
    if unknown:
        raise ConfigError(f"[ranking]: unknown components {sorted(unknown)}")
    if any(float(w) < 0 for w in ranking.values()) or abs(sum(ranking.values()) - 1.0) > 0.01:
        raise ConfigError("[ranking] weights must be non-negative and add up to 1.0")

    return Config(
        site=ch.get("site", {}),
        build=build,
        channels=channels,
        classifier=tx.get("classifier", {}),
        topics=topics,
        roadmaps=roadmaps,
        level=level,
        ranking=ranking,
        overrides=ov,
    )
