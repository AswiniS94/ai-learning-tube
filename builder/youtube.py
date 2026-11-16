"""Minimal YouTube Data API v3 client (standard library only) with quota tracking.

Every list call used here costs 1 quota unit. The default project quota is
10,000 units per day, which this builder stays well inside on nightly runs.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://www.googleapis.com/youtube/v3/"


class YouTubeError(RuntimeError):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(f"YouTube API {status} {reason}: {message}")
        self.status = status
        self.reason = reason


class QuotaExhausted(RuntimeError):
    """Raised when our own budget or Google's daily quota is used up."""


class FatalAPIError(RuntimeError):
    """Bad key, API not enabled, etc. Retrying won't help."""


FATAL_REASONS = {"keyInvalid", "accessNotConfigured", "keyExpired", "ipRefererBlocked", "forbidden"}
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


class YouTubeClient:
    def __init__(self, api_key: str, budget: int = 9000, timeout: float = 30.0, max_retries: int = 4):
        if not api_key:
            raise FatalAPIError("YOUTUBE_API_KEY is empty")
        self.api_key = api_key
        self.budget = budget
        self.cap = budget  # current phase cap (<= budget)
        self.used = 0
        self.calls = 0
        self.timeout = timeout
        self.max_retries = max_retries

    # -- low level -----------------------------------------------------------
    def _get(self, endpoint: str, params: dict) -> dict:
        if self.used + 1 > min(self.cap, self.budget):
            raise QuotaExhausted(f"quota cap reached ({self.used} units used)")
        q = {k: v for k, v in params.items() if v is not None and v != ""}
        q["key"] = self.api_key
        url = API_ROOT + endpoint + "?" + urllib.parse.urlencode(q)
        attempt = 0
        while True:
            attempt += 1
            self.used += 1  # Google charges failed calls too
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ai-learning-tube/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                status = exc.code
                reason, message = _parse_error(exc)
                if reason in QUOTA_REASONS and reason != "rateLimitExceeded":
                    raise QuotaExhausted(f"YouTube quota exhausted ({reason})") from None
                if status == 400 and reason in ("keyInvalid", "badRequest") and "key" in message.lower():
                    raise FatalAPIError(f"API key rejected: {message}") from None
                if status in (401,) or reason in FATAL_REASONS - {"forbidden"}:
                    raise FatalAPIError(f"{status} {reason}: {message}") from None
                retryable = status in (429, 500, 502, 503, 504) or reason == "rateLimitExceeded"
                if retryable and attempt <= self.max_retries:
                    time.sleep(min(30, 2 ** attempt))
                    continue
                raise YouTubeError(status, reason, message) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt <= self.max_retries:
                    time.sleep(min(30, 2 ** attempt))
                    continue
                raise YouTubeError(0, "network", str(exc)) from None

    # -- endpoints -----------------------------------------------------------
    def channel(self, channel_id: str = "", handle: str = "") -> dict | None:
        params = {"part": "snippet,contentDetails,statistics", "maxResults": 1}
        if channel_id:
            params["id"] = channel_id
        else:
            params["forHandle"] = handle if handle.startswith("@") else "@" + handle
        items = self._get("channels", params).get("items") or []
        return items[0] if items else None

    def playlist_items_page(self, playlist_id: str, page_token: str | None = None) -> dict:
        return self._get(
            "playlistItems",
            {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50, "pageToken": page_token},
        )

    def playlists_page(self, channel_id: str, page_token: str | None = None) -> dict:
        return self._get(
            "playlists",
            {"part": "snippet,contentDetails", "channelId": channel_id, "maxResults": 50, "pageToken": page_token},
        )

    def videos(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        if len(ids) > 50:
            raise ValueError("videos.list accepts at most 50 ids")
        data = self._get(
            "videos",
            {"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids), "maxResults": 50},
        )
        return data.get("items") or []


def _parse_error(exc: urllib.error.HTTPError) -> tuple[str, str]:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        err = body.get("error", {})
        errors = err.get("errors") or [{}]
        reason = errors[0].get("reason") or err.get("status") or ""
        return reason, err.get("message", "")
    except Exception:
        return "", str(exc)
