"""Notice new Garmin activities and start a Claude scheduled task for them.

Garmin's Personal API is pull-only: it never says when a new activity arrives.
So a scheduler (Cloud Scheduler on Cloud Run) calls ``POST /internal/garmin-watch``
every few minutes. Each call asks Garmin for recent activities, compares them with
the ids already seen, and, when something is new, fires a Claude scheduled task
through its API trigger (the task's ``/fire`` URL and bearer token), passing the
new activity ids as the fire text. The Claude task does the real work: ledger,
plan check, morning brief, log, notification.

The check is cheap and safe to repeat: an activity is marked seen only after the
fire succeeds, so a failed fire is retried on the next call. The first call ever
only records what is already there (a baseline) and fires nothing, so turning
the watcher on never replays old activities.

Configuration (all required for the route to exist):

- ``GARMIN_PERSONAL_API_KEY``: the Garmin key the garmin_* tools use.
- ``GARMIN_WATCH_KEY``: a shared secret the scheduler sends as ``X-Watch-Key``.
- ``CLAUDE_FIRE_URL`` and ``CLAUDE_FIRE_TOKEN``: the scheduled task's API trigger.
- ``GARMIN_WATCH_STATE_FILE``: where the seen ids are kept (on Cloud Run, a file on
  the mounted state bucket, so it survives restarts).
"""

from __future__ import annotations

import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from .auth import ICUConfig
from .garmin_client import GarminAPIError, GarminClient

SEARCH_PATH = "/activitylist-service/activities/search/activities"
FIRE_BETA = "experimental-cc-routine-2026-04-01"
FIRE_API_VERSION = "2023-06-01"
LOOKBACK_DAYS = 2
SEARCH_LIMIT = 20
MAX_SEEN = 500
FIRE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class WatchSettings:
    watch_key: str
    fire_url: str
    fire_token: str
    state_file: Path

    @classmethod
    def from_env(cls) -> WatchSettings | None:
        """Return the settings when every required variable is set, else None."""
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "GARMIN_WATCH_KEY",
                "CLAUDE_FIRE_URL",
                "CLAUDE_FIRE_TOKEN",
                "GARMIN_WATCH_STATE_FILE",
            )
        }
        if not all(values.values()):
            return None
        return cls(
            watch_key=values["GARMIN_WATCH_KEY"],
            fire_url=values["CLAUDE_FIRE_URL"],
            fire_token=values["CLAUDE_FIRE_TOKEN"],
            state_file=Path(values["GARMIN_WATCH_STATE_FILE"]),
        )


def key_matches(supplied: str | None, expected: str) -> bool:
    """Constant-time comparison of the scheduler's key."""
    return bool(supplied) and hmac.compare_digest(str(supplied), expected)


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise RuntimeError(f"The watch state file {path} could not be read: {e}") from e
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else None


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".garmin-watch-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _summarize(activity: dict[str, Any]) -> dict[str, Any] | None:
    """The few fields the Claude task needs; never metrics or locations."""
    activity_id = activity.get("activityId", activity.get("id"))
    if activity_id is None:
        return None
    activity_type = activity.get("activityType")
    type_key = (
        cast(dict[str, Any], activity_type).get("typeKey")
        if isinstance(activity_type, dict)
        else activity_type
    )
    return {
        "id": str(activity_id),
        "start_local": activity.get("startTimeLocal"),
        "type": type_key,
        "name": activity.get("activityName"),
    }


async def _recent_activities(config: ICUConfig, now: datetime) -> list[dict[str, Any]]:
    start = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    async with GarminClient(config) as client:
        raw = await client.get(
            SEARCH_PATH, {"startDate": start, "limit": SEARCH_LIMIT, "sortOrder": "desc"}
        )
    items = cast(list[Any], raw) if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            summary = _summarize(cast(dict[str, Any], item))
            if summary:
                out.append(summary)
    return out


async def _fire(settings: WatchSettings, new: list[dict[str, Any]]) -> dict[str, Any]:
    text = json.dumps({"new_garmin_activities": new}, sort_keys=True)
    async with httpx.AsyncClient(timeout=FIRE_TIMEOUT_SECONDS) as http:
        response = await http.post(
            settings.fire_url,
            headers={
                "Authorization": f"Bearer {settings.fire_token}",
                "anthropic-beta": FIRE_BETA,
                "anthropic-version": FIRE_API_VERSION,
                "Content-Type": "application/json",
            },
            json={"text": text},
        )
    if not response.is_success:
        raise RuntimeError(f"Starting the Claude task failed with HTTP {response.status_code}.")
    try:
        body = cast(dict[str, Any], response.json())
    except ValueError:
        body = {}
    return {"session_url": body.get("claude_code_session_url")}


async def check_once(
    config: ICUConfig, settings: WatchSettings, now: datetime | None = None
) -> tuple[int, dict[str, Any]]:
    """Run one check. Returns an HTTP status and a small JSON-safe report."""
    now = now or datetime.now(UTC)
    try:
        activities = await _recent_activities(config, now)
    except GarminAPIError as e:
        return 502, {"status": "garmin_error", "message": e.message}

    state = _load_state(settings.state_file)
    ids = [a["id"] for a in activities]

    if state is None:
        _save_state(
            settings.state_file,
            {"seen": ids, "baseline_at": now.isoformat(), "last_check": now.isoformat()},
        )
        return 200, {"status": "baseline", "recorded": len(ids)}

    seen: list[str] = [str(i) for i in state.get("seen", [])]
    seen_set = set(seen)
    new = [a for a in reversed(activities) if a["id"] not in seen_set]  # oldest first
    state["last_check"] = now.isoformat()

    if not new:
        _save_state(settings.state_file, state)
        return 200, {"status": "nothing_new"}

    try:
        fired = await _fire(settings, new)
    except (httpx.HTTPError, RuntimeError) as e:
        _save_state(settings.state_file, state)
        return 502, {"status": "fire_failed", "message": str(e), "pending": len(new)}

    seen.extend(a["id"] for a in new)
    state["seen"] = seen[-MAX_SEEN:]
    state["last_fire"] = {"at": now.isoformat(), "ids": [a["id"] for a in new], **fired}
    _save_state(settings.state_file, state)
    return 200, {"status": "fired", "ids": [a["id"] for a in new]}
