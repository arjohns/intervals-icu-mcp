"""Garmin Connect Personal API tools (read-only).

These tools read the athlete's own data straight from Garmin with a Personal API
key, alongside what arrives through Intervals.icu. They fill the gaps that
Intervals.icu's wellness sync leaves (sleep stages, Body Battery, stress,
respiration, SpO2) and keep activities and health data readable if Intervals.icu
is unavailable. The Personal API is pull-only: nothing here writes to Garmin,
and workouts still reach the watch through Intervals.icu.

Each tool maps to one endpoint of Garmin's Personal API (OpenAPI 1.0.0). Garmin's
responses are passed through with empty fields removed. Dense per-minute time
series are left out unless ``include_samples`` is true, so a day's record stays
small enough to read; the metadata lists what was left out.

Dates are the athlete's local calendar dates (YYYY-MM-DD). For sleep, Garmin files
a night under the date it ended: the night of Mar 3 into Mar 4 is ``2026-03-04``.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from datetime import date as date_cls
from typing import Annotated, Any, cast

from fastmcp import Context

from ..auth import ICUConfig
from ..garmin_client import GarminAPIError, GarminClient
from ..response_builder import ResponseBuilder

SOURCE = "garmin_personal_api"

# Per-minute or per-reading arrays, and the descriptor lists that label their
# columns. Omitted by default; include_samples=true returns them.
SAMPLE_KEYS: frozenset[str] = frozenset(
    {
        "bodyBatteryValuesArray",
        "bodyBatteryValueDescriptorDTOList",
        "heartRateValues",
        "heartRateValueDescriptors",
        "abnormalHRValuesArray",
        "spO2SingleValues",
        "spO2SingleValuesDescriptorList",
        "spO2HourlyAverages",
        "spO2HourlyAveragesDescriptorList",
        "monitoringEnvironmentValues",
        "monitoringEnvironmentValuesDescriptorList",
        "hrvReadings",
    }
)

# Internal identifiers that carry no meaning for the athlete.
NOISE_KEYS: frozenset[str] = frozenset({"userProfilePK", "userProfilePk"})

MAX_RANGE_DAYS = 366
MAX_ACTIVITY_PAGE = 100


# --------------------------------------------------------------------------- helpers


def _obj(value: Any) -> dict[str, Any] | None:
    """Return value as a JSON object, or None if it is not one."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _compact(value: Any, include_samples: bool, omitted: set[str]) -> Any:
    """Drop empty values and noise keys; drop sample arrays unless asked for."""
    obj = _obj(value)
    if obj is not None:
        out: dict[str, Any] = {}
        for key, item in obj.items():
            if key in NOISE_KEYS:
                continue
            if key in SAMPLE_KEYS and not include_samples:
                if item:
                    omitted.add(key)
                continue
            cleaned = _compact(item, include_samples, omitted)
            if cleaned is None or cleaned == "" or cleaned == [] or cleaned == {}:
                continue
            out[key] = cleaned
        return out
    if isinstance(value, list):
        items = cast(list[Any], value)
        return [_compact(item, include_samples, omitted) for item in items]
    return value


def _parse_date(value: str, name: str) -> date_cls:
    try:
        return date_cls.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name} must be a date in YYYY-MM-DD format; got {value!r}.") from e


def _check_date(value: str, name: str = "date") -> str:
    return _parse_date(value, name).isoformat()


def _check_range(start_date: str, end_date: str) -> tuple[str, str]:
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise ValueError("end_date must be on or after start_date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"Date ranges are limited to {MAX_RANGE_DAYS} days per call.")
    return start.isoformat(), end.isoformat()


async def _config(ctx: Context | None) -> ICUConfig:
    assert ctx is not None
    return await ctx.get_state("config")


async def _fetch(
    ctx: Context | None,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    query_type: str,
    include_samples: bool = False,
    analysis: Callable[[Any], dict[str, Any] | None] | None = None,
) -> str:
    """Call one Garmin endpoint and build the standard response."""
    config = await _config(ctx)
    try:
        async with GarminClient(config) as client:
            raw = await client.get(path, params)
    except GarminAPIError as e:
        error_type = "not_found" if e.status_code == 404 else "api_error"
        return ResponseBuilder.build_error_response(e.message, error_type=error_type)
    except Exception as e:
        return ResponseBuilder.build_error_response(
            f"Unexpected error: {e}", error_type="internal_error"
        )

    if raw is None or raw == [] or raw == {}:
        return ResponseBuilder.build_response(
            data={"found": False},
            metadata={
                "source": SOURCE,
                "message": "Garmin returned no data for this request. The device may "
                "not have synced yet, or did not record this metric.",
            },
            query_type=query_type,
        )

    omitted: set[str] = set()
    cleaned = _compact(raw, include_samples, omitted)
    cleaned_obj = _obj(cleaned)
    if cleaned_obj is not None:
        data = cleaned_obj
    else:
        items = cast(list[Any], cleaned) if isinstance(cleaned, list) else [cleaned]
        data = {"items": items, "count": len(items)}
    metadata: dict[str, Any] = {"source": SOURCE}
    if omitted:
        metadata["omitted_samples"] = sorted(omitted)
        metadata["hint"] = "Pass include_samples=true to include these time series."
    summary = None
    if analysis:
        try:
            summary = analysis(raw)
        except Exception:  # a summary must never break the underlying data
            summary = None
    return ResponseBuilder.build_response(
        data=data, analysis=summary or None, metadata=metadata, query_type=query_type
    )


def _validation_error(e: ValueError) -> str:
    return ResponseBuilder.build_error_response(str(e), error_type="validation_error")


def _hours(seconds: Any) -> str | None:
    if not isinstance(seconds, int | float) or seconds <= 0:
        return None
    minutes = round(seconds / 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _sleep_summary(record: Any) -> dict[str, Any] | None:
    """Plain-language summary of one DailySleepDTO."""
    record = _obj(record)
    if record is None:
        return None
    total = record.get("sleepTimeSeconds")
    summary: dict[str, Any] = {}
    if _hours(total):
        summary["asleep"] = _hours(total)
    stages = {
        "deep": record.get("deepSleepSeconds"),
        "light": record.get("lightSleepSeconds"),
        "rem": record.get("remSleepSeconds"),
        "awake": record.get("awakeSleepSeconds"),
    }
    stage_out: dict[str, Any] = {}
    for name, secs in stages.items():
        if isinstance(secs, int | float) and secs > 0:
            entry: dict[str, Any] = {"duration": _hours(secs)}
            if name != "awake" and isinstance(total, int | float) and total > 0:
                entry["percent_of_sleep"] = round(100 * secs / total)
            stage_out[name] = entry
    if stage_out:
        summary["stages"] = stage_out
    scores = _obj(record.get("sleepScores"))
    if scores is not None:
        overall = _obj(scores.get("overall"))
        if overall is not None and overall.get("value") is not None:
            summary["score"] = overall.get("value")
            if overall.get("qualifierKey"):
                summary["score_rating"] = overall["qualifierKey"]
    for key, label in (
        ("avgHeartRate", "avg_heart_rate"),
        ("avgSleepStress", "avg_sleep_stress"),
        ("averageRespirationValue", "avg_respiration"),
        ("averageSpO2Value", "avg_spo2"),
        ("awakeCount", "awakenings"),
        ("sleepScoreFeedback", "feedback"),
    ):
        if record.get(key) is not None:
            summary[label] = record[key]
    need = _obj(record.get("sleepNeed"))
    if need is not None and need.get("actual") is not None:
        summary["sleep_need_minutes"] = need["actual"]
    if record.get("sleepFromDevice") is False:
        summary["note"] = "This night was not recorded by a device (entered or estimated)."
    return summary or None


def _hrv_summary(record: Any) -> dict[str, Any] | None:
    record = _obj(record)
    hrv = _obj(record.get("hrvSummary")) if record is not None else None
    if hrv is None:
        return None
    summary: dict[str, Any] = {}
    for key, label in (
        ("lastNightAvg", "last_night_avg_ms"),
        ("lastNight5MinHigh", "last_night_5min_high_ms"),
        ("weeklyAvg", "weekly_avg_ms"),
        ("status", "status"),
        ("feedbackPhrase", "feedback"),
    ):
        if hrv.get(key) is not None:
            summary[label] = hrv[key]
    baseline = _obj(hrv.get("baseline"))
    if baseline is not None and baseline.get("balancedLow") is not None:
        summary["balanced_range_ms"] = [baseline.get("balancedLow"), baseline.get("balancedUpper")]
    return summary or None


# --------------------------------------------------------------------------- sleep


async def garmin_get_sleep(
    date: Annotated[str, "Date the night ended, YYYY-MM-DD (the night of Mar 3 is 2026-03-04)"],
    include_samples: Annotated[bool, "Include per-minute time series"] = False,
    ctx: Context | None = None,
) -> str:
    """Get one night's sleep from Garmin: stages (deep, light, REM, awake), sleep score
    and its components, sleep need, average heart rate, stress, respiration and SpO2.

    Use for "how did I sleep last night" or when Intervals.icu shows no sleep for a
    night. Garmin files a night under the date it ended. For several nights use
    garmin_get_sleep_range.
    """
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        "/sleep-service/sleep/dailySleep",
        {"date": day},
        query_type="garmin_sleep",
        include_samples=include_samples,
        analysis=_sleep_summary,
    )


async def garmin_get_sleep_range(
    start_date: Annotated[str, "First night (end date), YYYY-MM-DD"],
    end_date: Annotated[str, "Last night (end date), YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin sleep summaries for a range of nights (stages, score, timing).

    Use for sleep trends across a week or a training block. For one night with its
    full detail use garmin_get_sleep.
    """
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        "/sleep-service/sleep/dailySleepSummariesByDate",
        {"startDate": start, "endDate": end},
        query_type="garmin_sleep_range",
    )


# --------------------------------------------------------------------------- HRV


async def garmin_get_hrv(
    date: Annotated[str, "Date YYYY-MM-DD (the morning after the night measured)"],
    include_samples: Annotated[bool, "Include the individual overnight HRV readings"] = False,
    ctx: Context | None = None,
) -> str:
    """Get Garmin's overnight HRV for one night: last-night average, 5-minute high,
    7-day average, your balanced baseline range and HRV status (e.g. BALANCED).

    Garmin's status and baseline are not available through Intervals.icu.
    """
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/hrv-service/hrv/{day}",
        query_type="garmin_hrv",
        include_samples=include_samples,
        analysis=_hrv_summary,
    )


async def garmin_get_hrv_range(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's daily HRV summaries (average, baseline range, status) for a range."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(ctx, f"/hrv-service/hrv/daily/{start}/{end}", query_type="garmin_hrv_range")


# --------------------------------------------------------------------------- daily wellness


async def garmin_get_body_battery(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    chunks: Annotated[int | None, "Split each day into this many intervals (optional)"] = None,
    include_samples: Annotated[bool, "Include the Body Battery time series"] = False,
    ctx: Context | None = None,
) -> str:
    """Get Garmin Body Battery per day: charged and drained totals, Garmin's feedback
    events (e.g. overnight recharge), and activity drains.

    For a quick morning read, use the day's date as both start and end.
    """
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        "/wellness-service/wellness/bodyBattery/reports/daily",
        {"startDate": start, "endDate": end, "chunks": chunks},
        query_type="garmin_body_battery",
        include_samples=include_samples,
    )


async def garmin_get_stress(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's daily stress statistics (average and maximum stress level) for a
    range. For time spent in each stress band use garmin_get_daily_summaries."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx, f"/usersummary-service/stats/stress/daily/{start}/{end}", query_type="garmin_stress"
    )


async def garmin_get_daily_summaries(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's all-day summary per day: heart rate (min, max, resting), stress
    (average, time in each band), Body Battery (min, max, charged, drained, end of
    day), respiration, pulse ox (SpO2), steps and distance, calories, intensity
    minutes, hydration and jet lag.

    The broadest single read of a day; a good first call for a morning brief.
    """
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        "/usersummary-service/v2/dailysummaries",
        {"startDate": start, "endDate": end},
        query_type="garmin_daily_summaries",
    )


async def garmin_get_user_summary(
    date: Annotated[str, "Date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's classic one-day user summary (steps, calories, heart rate, stress,
    Body Battery, floors, intensity minutes) in Garmin Connect's original format.
    garmin_get_daily_summaries returns the same day in the newer, structured format."""
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        "/usersummary-service/usersummary/daily",
        {"calendarDate": day},
        query_type="garmin_user_summary",
    )


async def garmin_get_heart_rate(
    date: Annotated[str, "Date YYYY-MM-DD"],
    include_samples: Annotated[bool, "Include the all-day heart rate time series"] = False,
    ctx: Context | None = None,
) -> str:
    """Get one day's heart rate from Garmin: resting, minimum, maximum, 7-day average
    resting heart rate, and any abnormal-heart-rate alerts."""
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        "/wellness-service/wellness/dailyHeartRate",
        {"date": day},
        query_type="garmin_heart_rate",
        include_samples=include_samples,
    )


async def garmin_get_spo2(
    date: Annotated[str, "Date YYYY-MM-DD"],
    include_samples: Annotated[bool, "Include individual and hourly SpO2 readings"] = False,
    ctx: Context | None = None,
) -> str:
    """Get one day's pulse ox (SpO2) from Garmin: average, lowest, latest, sleep
    average and 7-day average, with altitude acclimation where recorded."""
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/wellness-service/wellness/daily/spo2acclimation/{day}",
        query_type="garmin_spo2",
        include_samples=include_samples,
    )


async def garmin_get_steps(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin daily steps, distance (meters) and step goal for a range."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx, f"/usersummary-service/stats/steps/daily/{start}/{end}", query_type="garmin_steps"
    )


async def garmin_get_hydration(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin daily hydration (logged intake and goal) for a range."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/usersummary-service/stats/hydration/daily/{start}/{end}",
        query_type="garmin_hydration",
    )


async def garmin_get_wellness_activities(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's wellness activity summaries for a range, with time in heart-rate
    zones."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/wellnessactivity-service/activity/summary/range/{start}/{end}",
        query_type="garmin_wellness_activities",
    )


# --------------------------------------------------------------------------- fitness


async def garmin_get_vo2max(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    sport: Annotated[list[str] | None, "Optional sport filter, e.g. ['RUNNING']"] = None,
    ctx: Context | None = None,
) -> str:
    """Get Garmin's daily VO2 max estimates (running, cycling, rowing) for a range."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/metrics-service/metrics/maxmet/daily/{start}/{end}",
        {"sport": sport} if sport else None,
        query_type="garmin_vo2max",
    )


async def garmin_get_fitness_age(
    date: Annotated[str, "Date YYYY-MM-DD; returns the latest fitness age as of this date"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's fitness age, and the components Garmin bases it on, as of a date."""
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx, f"/fitnessage-service/fitnessage/v2/{day}", query_type="garmin_fitness_age"
    )


async def garmin_get_heart_rate_zones(ctx: Context | None = None) -> str:
    """Get the heart rate zones configured in Garmin Connect, per sport (the zones the
    watch uses), including the zone method and max/resting/threshold heart rate."""
    return await _fetch(
        ctx,
        "/biometric-service/heartRateZones/v2",
        {"generateDefaults": "true"},
        query_type="garmin_heart_rate_zones",
    )


# --------------------------------------------------------------------------- body and nutrition


async def garmin_get_weight(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    include_all: Annotated[
        bool, "Include every weigh-in per day, not just the daily summary"
    ] = False,
    ctx: Context | None = None,
) -> str:
    """Get Garmin weight data for a range: daily summaries and averages, with body
    composition (body fat, muscle mass, BMI) where a smart scale recorded it."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/weight-service/weight/range/{start}/{end}",
        {"includeAll": "true" if include_all else "false"},
        query_type="garmin_weight",
    )


async def garmin_get_weight_entries(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get every individual Garmin weigh-in for a range, as a flat list by date."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx, f"/weight-service/weight/all/{start}/{end}", query_type="garmin_weight_entries"
    )


async def garmin_get_weight_goals(
    start_date: Annotated[str, "Start date YYYY-MM-DD"],
    end_date: Annotated[str, "End date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get the weight goals in effect in Garmin Connect over a range."""
    try:
        start, end = _check_range(start_date, end_date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/goal-service/goal/user/effective/weightgoal/{start}/{end}",
        query_type="garmin_weight_goals",
    )


async def garmin_get_food_log(
    date: Annotated[str, "Date YYYY-MM-DD"],
    meal_id: Annotated[int | None, "Optional meal ID to return one meal only"] = None,
    ctx: Context | None = None,
) -> str:
    """Get the day's food log from Garmin Connect's nutrition feature: meals, foods,
    calories and macronutrients, and nutrition goals."""
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/nutrition-service/food/logs/{day}",
        {"mealId": meal_id, "includeMedia": "false"},
        query_type="garmin_food_log",
    )


# --------------------------------------------------------------------------- activities


async def garmin_search_activities(
    start_date: Annotated[str | None, "Earliest start date YYYY-MM-DD (local time)"] = None,
    end_date: Annotated[str | None, "Latest start date YYYY-MM-DD (local time)"] = None,
    activity_type: Annotated[
        str | None, "Parent type key, e.g. running, cycling, swimming, strength_training"
    ] = None,
    activity_sub_type: Annotated[str | None, "Subtype key, e.g. treadmill_running"] = None,
    search: Annotated[str | None, "Text to match in activity names and descriptions"] = None,
    event_type: Annotated[str | None, "Event type key: race, training, recreation, ..."] = None,
    min_distance_m: Annotated[int | None, "Minimum distance in meters"] = None,
    max_distance_m: Annotated[int | None, "Maximum distance in meters"] = None,
    min_duration_s: Annotated[int | None, "Minimum moving duration in seconds"] = None,
    max_duration_s: Annotated[int | None, "Maximum moving duration in seconds"] = None,
    sort_by: Annotated[str | None, "Field to sort by (default: start time)"] = None,
    sort_order: Annotated[str, "asc or desc"] = "desc",
    start: Annotated[int, "Zero-based offset, for paging"] = 0,
    limit: Annotated[int, "Number of activities to return (1-100)"] = 20,
    ctx: Context | None = None,
) -> str:
    """Search activities directly in Garmin Connect, with filters.

    Returns summaries (ID, name, type, start time, distance, duration, heart rate,
    training effect). Use garmin_get_activity_types for valid type keys, then
    garmin_get_activity for one activity's full detail.
    """
    try:
        start_day = _check_date(start_date, "start_date") if start_date else None
        end_day = _check_date(end_date, "end_date") if end_date else None
        if start_day and end_day and end_day < start_day:
            raise ValueError("end_date must be on or after start_date.")
        if sort_order.lower() not in ("asc", "desc"):
            raise ValueError("sort_order must be asc or desc.")
    except ValueError as e:
        return _validation_error(e)
    params = {
        "start": max(start, 0),
        "limit": min(max(limit, 1), MAX_ACTIVITY_PAGE),
        "startDate": start_day,
        "endDate": end_day,
        "activityType": activity_type,
        "activitySubType": activity_sub_type,
        "search": search,
        "eventType": event_type,
        "minDistance": min_distance_m,
        "maxDistance": max_distance_m,
        "minDuration": min_duration_s,
        "maxDuration": max_duration_s,
        "sortBy": sort_by,
        "sortOrder": sort_order.lower(),
    }
    return await _fetch(
        ctx,
        "/activitylist-service/activities/search/activities",
        params,
        query_type="garmin_search_activities",
    )


async def garmin_get_activity(
    activity_id: Annotated[int, "Garmin activity ID"],
    ctx: Context | None = None,
) -> str:
    """Get one Garmin activity's full summary: measurements, splits, laps, device and
    sensor info. Use garmin_search_activities to find the ID."""
    return await _fetch(
        ctx, f"/activity-service/activity/{int(activity_id)}", query_type="garmin_activity"
    )


async def garmin_get_activity_workouts(
    activity_id: Annotated[int, "Garmin activity ID"],
    ctx: Context | None = None,
) -> str:
    """Get the workouts performed during a Garmin activity: the structured workout's
    steps and, for strength activities, the exercise sets recorded."""
    return await _fetch(
        ctx,
        f"/activity-service/activity/{int(activity_id)}/workouts",
        query_type="garmin_activity_workouts",
    )


async def garmin_get_activity_types(ctx: Context | None = None) -> str:
    """List Garmin's activity types and subtypes (the keys garmin_search_activities
    accepts as activity_type and activity_sub_type)."""
    return await _fetch(
        ctx, "/activity-service/activity/activityTypes/simple", query_type="garmin_activity_types"
    )


async def garmin_download_activity_file(
    activity_id: Annotated[int, "Garmin activity ID"],
    output_path: Annotated[str | None, "Path to save the ZIP file (optional)"] = None,
    ctx: Context | None = None,
) -> str:
    """Download an activity's original file from Garmin, as recorded by the device
    (a ZIP containing the .FIT file). Saved to output_path if given, otherwise
    returned base64-encoded."""
    if int(activity_id) <= 0:
        return ResponseBuilder.build_error_response(
            "activity_id must be a positive integer.", error_type="validation_error"
        )
    config = await _config(ctx)
    try:
        async with GarminClient(config) as client:
            content = await client.get_bytes(f"/download-service/files/activity/{int(activity_id)}")
    except GarminAPIError as e:
        return ResponseBuilder.build_error_response(e.message, error_type="api_error")
    except Exception as e:
        return ResponseBuilder.build_error_response(
            f"Unexpected error: {e}", error_type="internal_error"
        )
    data: dict[str, Any] = {"activity_id": str(activity_id), "size_bytes": len(content)}
    if output_path:
        directory = os.path.dirname(output_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(content)
        data["saved_to"] = output_path
    else:
        data["content_base64"] = base64.b64encode(content).decode("ascii")
        data["note"] = "Base64 of a ZIP file containing the original activity file (.FIT)."
    return ResponseBuilder.build_response(
        data=data, metadata={"source": SOURCE}, query_type="garmin_download_activity_file"
    )


# --------------------------------------------------------------------------- women's health


async def garmin_get_menstrual_cycle_summary(
    date: Annotated[str, "Date YYYY-MM-DD"],
    ctx: Context | None = None,
) -> str:
    """Get Garmin's menstrual cycle summary for the cycle containing a date (cycle
    day, phase, predicted dates). Returns nothing for accounts without cycle tracking."""
    try:
        day = _check_date(date)
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/periodichealth-service/menstrualcycle/summary/{day}",
        query_type="garmin_menstrual_cycle_summary",
    )


async def garmin_get_menstrual_cycle_day(
    date: Annotated[str, "Date YYYY-MM-DD"],
    today: Annotated[str | None, "Today's date YYYY-MM-DD, used for predictions"] = None,
    include_analysis: Annotated[bool, "Include cycle analysis"] = False,
    ctx: Context | None = None,
) -> str:
    """Get Garmin's detailed menstrual cycle day view for a date (logged symptoms,
    phase, and, with include_analysis, cycle analysis)."""
    try:
        day = _check_date(date)
        today_day = _check_date(today, "today") if today else None
    except ValueError as e:
        return _validation_error(e)
    return await _fetch(
        ctx,
        f"/periodichealth-service/menstrualcycle/dayview/{day}",
        {"todayDate": today_day, "includeAnalysis": "true" if include_analysis else None},
        query_type="garmin_menstrual_cycle_day",
    )


# --------------------------------------------------------------------------- profile


async def garmin_get_profile_settings(ctx: Context | None = None) -> str:
    """Get Garmin Connect profile settings: units, time zone, and the personal details
    Garmin uses in its calculations (such as height and weight)."""
    return await _fetch(
        ctx, "/userprofile-service/userprofile/settings", query_type="garmin_profile_settings"
    )


# Every Garmin tool, in registration order. server.py registers these only when a
# Personal API key is configured.
GARMIN_TOOLS: tuple[Callable[..., Any], ...] = (
    garmin_get_sleep,
    garmin_get_sleep_range,
    garmin_get_hrv,
    garmin_get_hrv_range,
    garmin_get_body_battery,
    garmin_get_stress,
    garmin_get_daily_summaries,
    garmin_get_user_summary,
    garmin_get_heart_rate,
    garmin_get_spo2,
    garmin_get_steps,
    garmin_get_hydration,
    garmin_get_wellness_activities,
    garmin_get_vo2max,
    garmin_get_fitness_age,
    garmin_get_heart_rate_zones,
    garmin_get_weight,
    garmin_get_weight_entries,
    garmin_get_weight_goals,
    garmin_get_food_log,
    garmin_search_activities,
    garmin_get_activity,
    garmin_get_activity_workouts,
    garmin_get_activity_types,
    garmin_download_activity_file,
    garmin_get_menstrual_cycle_summary,
    garmin_get_menstrual_cycle_day,
    garmin_get_profile_settings,
)
