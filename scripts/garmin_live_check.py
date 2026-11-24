"""Call every garmin_* tool once against the real Garmin Personal API.

Run locally before deploying, with the key in the environment and never on
the command line:

    GARMIN_PERSONAL_API_KEY="$(gcloud secrets versions access latest \\
        --secret garmin-personal-api-key --project "$PROJECT")" \\
        uv run python scripts/garmin_live_check.py 2026-11-24

Prints one line per tool: OK with the top-level fields returned, NO DATA, or the
error. It prints no values, so the output is safe to share.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from intervals_icu_mcp.auth import ICUConfig
from intervals_icu_mcp.tools import garmin as g


def _args(tool: Any, day: str, week_start: str, activity_id: int | None) -> dict[str, Any] | None:
    params = tool.__code__.co_varnames[: tool.__code__.co_argcount]
    args: dict[str, Any] = {}
    if "date" in params:
        args["date"] = day
    if "start_date" in params and tool is not g.garmin_search_activities:
        args["start_date"], args["end_date"] = week_start, day
    if "activity_id" in params:
        if activity_id is None:
            return None
        args["activity_id"] = activity_id
    return args


async def main() -> int:
    if not os.environ.get("GARMIN_PERSONAL_API_KEY"):
        print("Set GARMIN_PERSONAL_API_KEY first (see the docstring).", file=sys.stderr)
        return 2
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    week_start = (date.fromisoformat(day) - timedelta(days=6)).isoformat()

    config = ICUConfig(intervals_icu_api_key="unused", intervals_icu_athlete_id="unused")
    ctx = MagicMock()
    ctx.get_state = AsyncMock(return_value=config)

    # Find a recent activity ID so the per-activity tools can be checked too.
    found = json.loads(await g.garmin_search_activities(limit=1, ctx=ctx))
    items = found.get("data", {}).get("items") or []
    activity_id = items[0].get("activityId") if items else None

    failures = 0
    for tool in g.GARMIN_TOOLS:
        args = _args(tool, day, week_start, activity_id)
        if args is None:
            print(f"SKIP     {tool.__name__}: no activity found")
            continue
        result = json.loads(await tool(**args, ctx=ctx))
        if "error" in result:
            failures += 1
            print(f"ERROR    {tool.__name__}: {result['error']['message']}")
        elif result["data"] == {"found": False}:
            print(f"NO DATA  {tool.__name__}")
        else:
            data = result["data"]
            fields = (
                ", ".join(sorted(data)[:12]) if "items" not in data else f"{data['count']} items"
            )
            print(f"OK       {tool.__name__}: {fields}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
