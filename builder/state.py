"""Persistent cache of everything fetched from YouTube (gzip JSON).

Keeping this between runs (GitHub Actions cache) makes nightly builds cheap:
only new uploads and stale statistics are fetched again.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

STATE_VERSION = 1


def empty_state() -> dict:
    return {"version": STATE_VERSION, "channels": {}, "videos": {}, "playlists": {}}


def load_state(state_dir: str | Path) -> dict:
    path = Path(state_dir) / "state.json.gz"
    if not path.exists():
        return empty_state()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, EOFError) as exc:
        print(f"::warning::state cache unreadable ({exc}); starting fresh")
        return empty_state()
    if data.get("version") != STATE_VERSION:
        print("::warning::state cache has an old format; starting fresh")
        return empty_state()
    for k in ("channels", "videos", "playlists"):
        data.setdefault(k, {})
    return data


def save_state(state: dict, state_dir: str | Path) -> Path:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "state.json.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
        json.dump(state, fh, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)
    return path
