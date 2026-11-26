"""Tests for the Garmin watcher: new activities start a Claude scheduled task."""

import importlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from intervals_icu_mcp import garmin_client
from intervals_icu_mcp.auth import ICUConfig
from intervals_icu_mcp.garmin_client import TOKEN_PATH
from intervals_icu_mcp.garmin_watch import (
    FIRE_BETA,
    SEARCH_PATH,
    WatchSettings,
    check_once,
    key_matches,
)

BASE = "https://personal.connectapi.garmin.com"
FIRE_URL = "https://api.anthropic.com/v1/claude_code/routines/trig_TEST/fire"
NOW = datetime(2026, 11, 25, 19, 30, tzinfo=UTC)


def _jwt() -> str:
    import base64

    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': time.time() + 86400})}.sig"


def _activity(activity_id: int, start: str, type_key: str = "running") -> dict:
    return {
        "activityId": activity_id,
        "activityName": f"Run {activity_id}",
        "startTimeLocal": start,
        "activityType": {"typeKey": type_key},
        "distance": 3218.0,
    }


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    garmin_client.clear_token_cache()
    yield
    garmin_client.clear_token_cache()


@pytest.fixture
def config() -> ICUConfig:
    return ICUConfig(
        intervals_icu_api_key="test_api_key_12345",
        intervals_icu_athlete_id="i123456",
        garmin_personal_api_key="GCDC_test",
    )


@pytest.fixture
def settings(tmp_path: Path) -> WatchSettings:
    return WatchSettings(
        watch_key="watch-secret",
        fire_url=FIRE_URL,
        fire_token="sk-ant-oat01-test",
        state_file=tmp_path / "watch" / "state.json",
    )


@pytest.fixture
def api():
    with respx.mock(assert_all_called=False) as router:
        router.post(BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=_jwt()))
        yield router


def _search(api, activities):
    return api.get(BASE + SEARCH_PATH).mock(return_value=httpx.Response(200, json=activities))


class TestSettings:
    def test_needs_every_variable(self, monkeypatch):
        monkeypatch.setenv("GARMIN_WATCH_KEY", "k")
        monkeypatch.setenv("CLAUDE_FIRE_URL", FIRE_URL)
        monkeypatch.setenv("CLAUDE_FIRE_TOKEN", "t")
        assert WatchSettings.from_env() is None
        monkeypatch.setenv("GARMIN_WATCH_STATE_FILE", "/tmp/x.json")
        assert WatchSettings.from_env() is not None

    def test_key_matches(self):
        assert key_matches("abc", "abc")
        assert not key_matches("abd", "abc")
        assert not key_matches(None, "abc")
        assert not key_matches("", "abc")


class TestCheckOnce:
    async def test_first_check_records_baseline_and_fires_nothing(self, config, settings, api):
        _search(api, [_activity(2, "2026-11-25 14:06:39"), _activity(1, "2026-11-24 07:00:00")])
        fire = api.post(FIRE_URL)
        status, report = await check_once(config, settings, NOW)
        assert (status, report["status"], report["recorded"]) == (200, "baseline", 2)
        assert not fire.called
        assert json.loads(settings.state_file.read_text())["seen"] == ["2", "1"]

    async def test_nothing_new(self, config, settings, api):
        settings.state_file.parent.mkdir(parents=True)
        settings.state_file.write_text(json.dumps({"seen": ["1"]}))
        _search(api, [_activity(1, "2026-11-24 07:00:00")])
        fire = api.post(FIRE_URL)
        status, report = await check_once(config, settings, NOW)
        assert (status, report["status"]) == (200, "nothing_new")
        assert not fire.called

    async def test_new_activity_fires_the_task(self, config, settings, api):
        settings.state_file.parent.mkdir(parents=True)
        settings.state_file.write_text(json.dumps({"seen": ["1"]}))
        search = _search(
            api,
            [
                _activity(3, "2026-11-25 18:00:00"),
                _activity(2, "2026-11-25 14:06:39"),
                _activity(1, "2026-11-24 07:00:00"),
            ],
        )
        fire = api.post(FIRE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "type": "routine_fire",
                    "claude_code_session_url": "https://claude.ai/code/s",
                },
            )
        )
        status, report = await check_once(config, settings, NOW)

        assert (status, report["status"], report["ids"]) == (200, "fired", ["2", "3"])
        request = fire.calls.last.request
        assert request.headers["Authorization"] == "Bearer sk-ant-oat01-test"
        assert request.headers["anthropic-beta"] == FIRE_BETA
        payload = json.loads(json.loads(request.content)["text"])
        assert [a["id"] for a in payload["new_garmin_activities"]] == ["2", "3"]
        assert payload["new_garmin_activities"][0] == {
            "id": "2",
            "start_local": "2026-11-25 14:06:39",
            "type": "running",
            "name": "Run 2",
        }
        assert "distance" not in json.dumps(payload)
        params = search.calls.last.request.url.params
        assert params["startDate"] == "2026-11-23"
        state = json.loads(settings.state_file.read_text())
        assert state["seen"] == ["1", "2", "3"]
        assert state["last_fire"]["session_url"] == "https://claude.ai/code/s"

    async def test_failed_fire_is_retried_next_time(self, config, settings, api):
        settings.state_file.parent.mkdir(parents=True)
        settings.state_file.write_text(json.dumps({"seen": ["1"]}))
        _search(api, [_activity(2, "2026-11-25 14:06:39"), _activity(1, "2026-11-24 07:00:00")])
        fire = api.post(FIRE_URL).mock(
            side_effect=[httpx.Response(500), httpx.Response(200, json={})]
        )
        status, report = await check_once(config, settings, NOW)
        assert (status, report["status"], report["pending"]) == (502, "fire_failed", 1)
        assert json.loads(settings.state_file.read_text())["seen"] == ["1"]

        status, report = await check_once(config, settings, NOW)
        assert (status, report["status"]) == (200, "fired")
        assert fire.call_count == 2

    async def test_garmin_error(self, config, settings, api):
        api.get(BASE + SEARCH_PATH).mock(return_value=httpx.Response(503))
        status, report = await check_once(config, settings, NOW)
        assert (status, report["status"]) == (502, "garmin_error")
        assert not settings.state_file.exists()


def _reload_server():
    sys.modules.pop("intervals_icu_mcp.server", None)
    return importlib.import_module("intervals_icu_mcp.server")


class TestRoute:
    def _env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "GCDC_test")
        monkeypatch.setenv("GARMIN_WATCH_KEY", "watch-secret")
        monkeypatch.setenv("CLAUDE_FIRE_URL", FIRE_URL)
        monkeypatch.setenv("CLAUDE_FIRE_TOKEN", "sk-ant-oat01-test")
        monkeypatch.setenv("GARMIN_WATCH_STATE_FILE", str(tmp_path / "state.json"))

    def _paths(self, server) -> set[str]:
        return {getattr(r, "path", "") for r in server.mcp.http_app().routes}

    def test_absent_without_settings(self, monkeypatch):
        monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "GCDC_test")
        assert "/internal/garmin-watch" not in self._paths(_reload_server())
        monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
        _reload_server()

    def test_rejects_a_wrong_key(self, monkeypatch, tmp_path):
        self._env(monkeypatch, tmp_path)
        server = _reload_server()
        assert "/internal/garmin-watch" in self._paths(server)
        with TestClient(server.mcp.http_app()) as client:
            assert client.post("/internal/garmin-watch").status_code == 403
            response = client.post("/internal/garmin-watch", headers={"X-Watch-Key": "nope"})
            assert response.status_code == 403
        for name in (
            "GARMIN_PERSONAL_API_KEY",
            "GARMIN_WATCH_KEY",
            "CLAUDE_FIRE_URL",
            "CLAUDE_FIRE_TOKEN",
            "GARMIN_WATCH_STATE_FILE",
        ):
            monkeypatch.delenv(name)
        _reload_server()
