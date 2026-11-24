"""Tests for the Garmin Connect Personal API client and garmin_* tools."""

import asyncio
import base64
import importlib
import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from intervals_icu_mcp import garmin_client
from intervals_icu_mcp.auth import ICUConfig
from intervals_icu_mcp.garmin_client import TOKEN_PATH
from intervals_icu_mcp.tools import garmin as g

BASE = "https://personal.connectapi.garmin.com"
API_KEY = "GCDC_test-key"


def _jwt(exp: float) -> str:
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


TOKEN = _jwt(time.time() + 24 * 3600)


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    garmin_client.clear_token_cache()
    yield
    garmin_client.clear_token_cache()


@pytest.fixture
def garmin_config():
    return ICUConfig(
        intervals_icu_api_key="test_api_key_12345",
        intervals_icu_athlete_id="i123456",
        garmin_personal_api_key=API_KEY,
    )


@pytest.fixture
def ctx(garmin_config):
    mock_ctx = MagicMock()
    mock_ctx.get_state = AsyncMock(return_value=garmin_config)
    return mock_ctx


@pytest.fixture
def garmin():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.post(TOKEN_PATH).mock(return_value=httpx.Response(200, text=TOKEN))
        yield router


SLEEP = {
    "userProfilePK": 42,
    "calendarDate": "2026-11-24",
    "sleepTimeSeconds": 24660,
    "deepSleepSeconds": 4932,
    "lightSleepSeconds": 13563,
    "remSleepSeconds": 6165,
    "awakeSleepSeconds": 780,
    "sleepScores": {"overall": {"value": 75, "qualifierKey": "FAIR"}},
    "avgHeartRate": 47.0,
    "sleepFromDevice": True,
    "userNote": None,
    "dailyNapDTOS": [],
    "sleepNeed": {"actual": 480},
    "heartRateValues": [[1, 50], [2, 49]],
}


class TestTokenHandling:
    async def test_key_exchanged_once_and_token_reused(self, ctx, garmin):
        route = garmin.get("/sleep-service/sleep/dailySleep").mock(
            return_value=httpx.Response(200, json=SLEEP)
        )
        await g.garmin_get_sleep(date="2026-11-24", ctx=ctx)
        await g.garmin_get_sleep(date="2026-11-24", ctx=ctx)

        token_calls = [c for c in garmin.calls if c.request.url.path == TOKEN_PATH]
        assert len(token_calls) == 1
        assert token_calls[0].request.headers["Authorization"] == f"ApiKey {API_KEY}"
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert route.calls.last.request.url.params["date"] == "2026-11-24"

    async def test_token_near_expiry_is_refreshed(self, ctx, garmin):
        garmin.post(TOKEN_PATH).mock(
            side_effect=[
                httpx.Response(200, text=_jwt(time.time() + 600)),  # inside refresh window
                httpx.Response(200, text=TOKEN),
            ]
        )
        garmin.get("/sleep-service/sleep/dailySleep").mock(
            return_value=httpx.Response(200, json=SLEEP)
        )
        await g.garmin_get_sleep(date="2026-11-24", ctx=ctx)
        await g.garmin_get_sleep(date="2026-11-24", ctx=ctx)
        assert len([c for c in garmin.calls if c.request.url.path == TOKEN_PATH]) == 2

    async def test_stale_token_retried_once_on_401(self, ctx, garmin):
        route = garmin.get("/sleep-service/sleep/dailySleep").mock(
            side_effect=[httpx.Response(401), httpx.Response(200, json=SLEEP)]
        )
        result = json.loads(await g.garmin_get_sleep(date="2026-11-24", ctx=ctx))
        assert result["data"]["sleepTimeSeconds"] == 24660
        assert route.call_count == 2

    async def test_rejected_key_explains_fix(self, ctx, garmin):
        garmin.post(TOKEN_PATH).mock(return_value=httpx.Response(401))
        result = json.loads(await g.garmin_get_sleep(date="2026-11-24", ctx=ctx))
        assert result["error"]["type"] == "api_error"
        assert "GARMIN_PERSONAL_API_KEY" in result["error"]["message"]
        assert API_KEY not in result["error"]["message"]

    async def test_unreadable_expiry_falls_back(self, ctx, garmin):
        garmin.post(TOKEN_PATH).mock(return_value=httpx.Response(200, text="opaque-token"))
        garmin.get("/sleep-service/sleep/dailySleep").mock(
            return_value=httpx.Response(200, json=SLEEP)
        )
        result = json.loads(await g.garmin_get_sleep(date="2026-11-24", ctx=ctx))
        assert "data" in result

    async def test_not_configured(self, mock_config):
        mock_ctx = MagicMock()
        mock_ctx.get_state = AsyncMock(return_value=mock_config)
        result = json.loads(await g.garmin_get_sleep(date="2026-11-24", ctx=mock_ctx))
        assert "GARMIN_PERSONAL_API_KEY" in result["error"]["message"]


class TestResponses:
    async def test_sleep_summary_and_compaction(self, ctx, garmin):
        garmin.get("/sleep-service/sleep/dailySleep").mock(
            return_value=httpx.Response(200, json=SLEEP)
        )
        result = json.loads(await g.garmin_get_sleep(date="2026-11-24", ctx=ctx))

        data, analysis, meta = result["data"], result["analysis"], result["metadata"]
        assert "userProfilePK" not in data
        assert "userNote" not in data and "dailyNapDTOS" not in data
        assert "heartRateValues" not in data
        assert meta["omitted_samples"] == ["heartRateValues"]
        assert meta["source"] == "garmin_personal_api"
        assert analysis["asleep"] == "6h 51m"
        assert analysis["score"] == 75 and analysis["score_rating"] == "FAIR"
        assert analysis["stages"]["deep"]["percent_of_sleep"] == 20
        assert "percent_of_sleep" not in analysis["stages"]["awake"]
        assert analysis["sleep_need_minutes"] == 480

    async def test_include_samples(self, ctx, garmin):
        garmin.get("/sleep-service/sleep/dailySleep").mock(
            return_value=httpx.Response(200, json=SLEEP)
        )
        result = json.loads(
            await g.garmin_get_sleep(date="2026-11-24", include_samples=True, ctx=ctx)
        )
        assert result["data"]["heartRateValues"] == [[1, 50], [2, 49]]
        assert "omitted_samples" not in result["metadata"]

    async def test_empty_body_means_no_data(self, ctx, garmin):
        garmin.get("/sleep-service/sleep/dailySleep").mock(return_value=httpx.Response(200))
        result = json.loads(await g.garmin_get_sleep(date="2026-11-24", ctx=ctx))
        assert result["data"] == {"found": False}

    async def test_list_response_wrapped(self, ctx, garmin):
        garmin.get("/usersummary-service/stats/steps/daily/2026-11-01/2026-11-02").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"calendarDate": "2026-11-01", "totalSteps": 8000},
                    {"calendarDate": "2026-11-02", "totalSteps": 9000},
                ],
            )
        )
        result = json.loads(
            await g.garmin_get_steps(start_date="2026-11-01", end_date="2026-11-02", ctx=ctx)
        )
        assert result["data"]["count"] == 2

    async def test_hrv_summary(self, ctx, garmin):
        garmin.get("/hrv-service/hrv/2026-11-24").mock(
            return_value=httpx.Response(
                200,
                json={
                    "hrvSummary": {
                        "lastNightAvg": 61,
                        "weeklyAvg": 52,
                        "status": "BALANCED",
                        "baseline": {"balancedLow": 45, "balancedUpper": 60},
                    },
                    "hrvReadings": [{"hrvValue": 60}],
                },
            )
        )
        result = json.loads(await g.garmin_get_hrv(date="2026-11-24", ctx=ctx))
        assert result["analysis"]["last_night_avg_ms"] == 61
        assert result["analysis"]["balanced_range_ms"] == [45, 60]
        assert result["metadata"]["omitted_samples"] == ["hrvReadings"]

    async def test_404_is_not_found(self, ctx, garmin):
        garmin.get("/fitnessage-service/fitnessage/v2/2026-11-24").mock(
            return_value=httpx.Response(404)
        )
        result = json.loads(await g.garmin_get_fitness_age(date="2026-11-24", ctx=ctx))
        assert result["error"]["type"] == "not_found"

    async def test_download_returns_base64(self, ctx, garmin):
        garmin.get("/download-service/files/activity/123").mock(
            return_value=httpx.Response(200, content=b"PK\x03\x04zip")
        )
        result = json.loads(await g.garmin_download_activity_file(activity_id=123, ctx=ctx))
        assert base64.b64decode(result["data"]["content_base64"]) == b"PK\x03\x04zip"


class TestValidation:
    @pytest.mark.parametrize(
        ("start", "end", "fragment"),
        [
            ("2026-11-24", "2026-11-01", "on or after"),
            ("2025-01-01", "2026-11-24", "limited to"),
            ("11/24/2026", "2026-11-24", "YYYY-MM-DD"),
        ],
    )
    async def test_range_errors(self, ctx, start, end, fragment):
        result = json.loads(await g.garmin_get_stress(start_date=start, end_date=end, ctx=ctx))
        assert result["error"]["type"] == "validation_error"
        assert fragment in result["error"]["message"]

    async def test_bad_date(self, ctx):
        result = json.loads(await g.garmin_get_sleep(date="yesterday", ctx=ctx))
        assert result["error"]["type"] == "validation_error"

    async def test_search_params(self, ctx, garmin):
        route = garmin.get("/activitylist-service/activities/search/activities").mock(
            return_value=httpx.Response(200, json=[{"activityId": 1}])
        )
        await g.garmin_search_activities(
            start_date="2026-11-01", activity_type="running", limit=500, ctx=ctx
        )
        params = route.calls.last.request.url.params
        assert params["limit"] == "100"
        assert params["activityType"] == "running"
        assert params["startDate"] == "2026-11-01"
        assert "endDate" not in params


# Every tool, the arguments to call it with, and the path it must hit.
CASES = [
    (g.garmin_get_sleep, {"date": "2026-11-24"}, "/sleep-service/sleep/dailySleep"),
    (
        g.garmin_get_sleep_range,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/sleep-service/sleep/dailySleepSummariesByDate",
    ),
    (g.garmin_get_hrv, {"date": "2026-11-24"}, "/hrv-service/hrv/2026-11-24"),
    (
        g.garmin_get_hrv_range,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/hrv-service/hrv/daily/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_body_battery,
        {"start_date": "2026-11-24", "end_date": "2026-11-24"},
        "/wellness-service/wellness/bodyBattery/reports/daily",
    ),
    (
        g.garmin_get_stress,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/usersummary-service/stats/stress/daily/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_daily_summaries,
        {"start_date": "2026-11-24", "end_date": "2026-11-24"},
        "/usersummary-service/v2/dailysummaries",
    ),
    (g.garmin_get_user_summary, {"date": "2026-11-24"}, "/usersummary-service/usersummary/daily"),
    (g.garmin_get_heart_rate, {"date": "2026-11-24"}, "/wellness-service/wellness/dailyHeartRate"),
    (
        g.garmin_get_spo2,
        {"date": "2026-11-24"},
        "/wellness-service/wellness/daily/spo2acclimation/2026-11-24",
    ),
    (
        g.garmin_get_steps,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/usersummary-service/stats/steps/daily/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_hydration,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/usersummary-service/stats/hydration/daily/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_wellness_activities,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/wellnessactivity-service/activity/summary/range/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_vo2max,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/metrics-service/metrics/maxmet/daily/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_fitness_age,
        {"date": "2026-11-24"},
        "/fitnessage-service/fitnessage/v2/2026-11-24",
    ),
    (g.garmin_get_heart_rate_zones, {}, "/biometric-service/heartRateZones/v2"),
    (
        g.garmin_get_weight,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/weight-service/weight/range/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_weight_entries,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/weight-service/weight/all/2026-11-01/2026-11-07",
    ),
    (
        g.garmin_get_weight_goals,
        {"start_date": "2026-11-01", "end_date": "2026-11-07"},
        "/goal-service/goal/user/effective/weightgoal/2026-11-01/2026-11-07",
    ),
    (g.garmin_get_food_log, {"date": "2026-11-24"}, "/nutrition-service/food/logs/2026-11-24"),
    (g.garmin_search_activities, {}, "/activitylist-service/activities/search/activities"),
    (g.garmin_get_activity, {"activity_id": 99}, "/activity-service/activity/99"),
    (g.garmin_get_activity_workouts, {"activity_id": 99}, "/activity-service/activity/99/workouts"),
    (g.garmin_get_activity_types, {}, "/activity-service/activity/activityTypes/simple"),
    (g.garmin_download_activity_file, {"activity_id": 99}, "/download-service/files/activity/99"),
    (
        g.garmin_get_menstrual_cycle_summary,
        {"date": "2026-11-24"},
        "/periodichealth-service/menstrualcycle/summary/2026-11-24",
    ),
    (
        g.garmin_get_menstrual_cycle_day,
        {"date": "2026-11-24"},
        "/periodichealth-service/menstrualcycle/dayview/2026-11-24",
    ),
    (g.garmin_get_profile_settings, {}, "/userprofile-service/userprofile/settings"),
]


def test_cases_cover_every_tool():
    assert {c[0] for c in CASES} == set(g.GARMIN_TOOLS)
    assert len(g.GARMIN_TOOLS) == 28


@pytest.mark.parametrize(("tool", "kwargs", "path"), CASES, ids=[c[0].__name__ for c in CASES])
async def test_each_tool_hits_its_endpoint(tool, kwargs, path, ctx, garmin):
    route = garmin.get(path).mock(return_value=httpx.Response(200, content=b'{"ok": 1}'))
    result = json.loads(await tool(**kwargs, ctx=ctx))
    assert route.called, f"{tool.__name__} did not call {path}"
    assert "error" not in result


def _reload_server() -> object:
    sys.modules.pop("intervals_icu_mcp.server", None)
    return importlib.import_module("intervals_icu_mcp.server")


def _tool_names(server_module: object) -> set[str]:
    tools = asyncio.run(server_module.mcp.list_tools())  # type: ignore[attr-defined]
    return {t.name for t in tools}


class TestRegistration:
    def test_off_without_key(self, monkeypatch):
        monkeypatch.delenv("GARMIN_PERSONAL_API_KEY", raising=False)
        names = _tool_names(_reload_server())
        assert not any(n.startswith("garmin_") for n in names)

    def test_on_with_key(self, monkeypatch):
        monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", API_KEY)
        names = _tool_names(_reload_server())
        assert {t.__name__ for t in g.GARMIN_TOOLS} <= names
        monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
        _reload_server()
