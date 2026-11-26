---
title: morning-brief
type: guide
description: 'The morning brief: each morning it reads last night''s recovery, yesterday''s
  sessions, today''s planned session, the weather, the calendars and the vault''s dated
  items, then says go, go easy or rest, and what else the day holds. A method plus
  this vault''s settings. Use when the scheduled brief runs, or when the owner asks
  "what''s my morning brief", "how am I recovered", "should I train today".'
---

# morning-brief

**Version:** 1.2.0

**Shape:** a method plus this vault's settings. Everything above *Settings for this vault* is the method: it names no person and works for any owner. Everything personal (who, where, which page, which calendars, which goals) is in that section and in the owner's own notes.

**Reads:** `profile` for who the owner is; Garmin directly (`garmin_*` tools on the owner's connector); yesterday's, today's and the next two days' planned sessions on the intervals.icu calendar (`icu_get_calendar_events`); yesterday's completed sessions (`icu_get_activities_by_date`); the weather for the location in settings; the calendars in settings for today and the next three days; [[now]] and the season note named in settings for dated items and the current phase of the plan.
**Writes:** the page named in settings (only its brief.json) and one line in the vault's daily log through the cascade.
**Never writes to:** the training calendar or activities, Garmin, any calendar or mailbox, or any other vault note. The brief recommends; changing the plan stays a separate step the owner approves.

## What it is for

One short read before the day starts: am I recovered, what did I do yesterday, what is planned, what should I actually do, and what else needs me today. It is a method the coach uses, not a coach on its own.

## The readiness method

Read these from Garmin for today's date (Garmin files a night under the date it ended):

| Signal | Tool | Good | Watch | Back off |
|---|---|---|---|---|
| Sleep score | `garmin_get_sleep` | 80 or more | 60–79 | under 60 |
| Time asleep against Garmin's sleep need | `garmin_get_sleep` | within 30 min of need | 30–90 min short | more than 90 min short |
| Overnight HRV against the balanced range | `garmin_get_hrv` | inside the range, or above it | — | below the range's low end, or status LOW or UNBALANCED |
| Resting heart rate against the 7-day average | `garmin_get_heart_rate` or `garmin_get_daily_summaries` | within 3 bpm | 3–5 bpm higher | more than 5 bpm higher |
| Body Battery peak overnight | `garmin_get_daily_summaries` (today's `maxValue`) | 75 or more | 50–74 | under 50 |

**Verdict:**
- **Go** — no signal in *Back off*, and at most one in *Watch*. Do the session as planned.
- **Go easy** — two or more in *Watch*, or one in *Back off*. Keep the session, drop any intensity, shorten it by about a third.
- **Rest or swap** — two or more in *Back off*. Suggest an easy walk, mobility or a rest day, and offer to move the planned session.

**Safety outranks the plan, always:**
1. Pain the owner has reported (above 3 out of 10), illness, or a fever means rest, whatever the numbers say. Check the last two days of the log for the "how it felt" lines the [[after-session]] app writes, as well as [[now]] and the season note.
2. Within 10 days after a race of half-marathon distance or longer, only easy running, whatever the numbers say.
3. The brief never moves a workout itself. It offers, and the change waits for the owner's yes.

## Missing data

Never work around a gap silently. If last night's sleep or HRV is missing, say so in the first line ("Garmin hasn't sent last night's sleep yet") and give the verdict from what is there, marked as partial. If Garmin cannot be reached at all, fall back to the sleep and HRV fields in intervals.icu (`icu_get_wellness_for_date`) and say which source was used.

**Owners without Garmin tools** (the connector has no `garmin_*` tools, for example because they use another watch): read sleep, HRV and resting heart rate from intervals.icu wellness every day, and judge with the four signals there are. Body Battery is Garmin's, so leave that rail out rather than flag it as missing.

**Notes that may not exist:** if the vault has no [[now]] note, or settings name no season note, leave out what they would have supplied (dated items, plan phase, last race) without comment. Only a source that should have answered and didn't is a gap worth reporting.

## The brief

Phone-first, readable in under a minute, plain words, no product words.

1. **Verdict line:** Go, Go easy or Rest, and the reason in one clause.
2. **Yesterday:** what was planned, what was done, and a status (see *Yesterday's status* below). For each completed session give its stats against the plan, and the "how it felt" line the [[after-session]] app logged, if there is one.
3. **Recovery:** sleep (time, score, deep and REM), HRV against the range, resting heart rate, Body Battery.
4. **Today's session:** what is planned and the recommended version of it. **If settings set a cadence target, add a cadence reminder on any day with a run.** Give the last run's average cadence in steps per minute (Garmin and intervals.icu report one foot, so double it), the target, and the cue: shorter, quicker steps at the same easy pace, landing under the hips. Don't speed up.
5. **Weather:** today's temperature range and rain chance, and anything notable in the next two days that affects a planned session.
6. **Today:** the calendars' events in time order, with a one-line read of the day's load (for example "6 hours of meetings, first at 8:00"), then dated items from [[now]] due in the next three days. A heavy meeting day is a reason to keep the session short or move it earlier, said as a suggestion.
7. **Coming up:** the next planned sessions, two days ahead.
8. **Weight, Mondays only, if settings name a weight goal:** the 7-day average from Garmin (`garmin_get_weight` for the last 14 days) against the week before, and against the goal. Show the trend and its direction, never single daily numbers. If there has been no weigh-in in the last 7 days, give a one-line nudge instead ("No weigh-in this week: step on the scale, or enter it in Garmin Connect"). Never comment on food or suggest cutting calories in the brief.

The push notification carries the verdict line only.

### Yesterday's status

Compare yesterday's planned sessions (`icu_get_calendar_events` with `days_back` 1) with yesterday's completed ones (`icu_get_activities_by_date`, details from `icu_get_activity_details`):

| Status | When |
|---|---|
| **Done** | A planned session was completed at 90% or more of its planned distance or time |
| **Partly done** | Completed, but under 90% of the planned distance or time |
| **Missed** | A session was planned and nothing was done |
| **Unplanned** | A session was done with nothing planned |
| **Rest day** | Nothing planned, nothing done |

Stats by type, each with the planned figure beside it where there is one:
- **Run:** distance, time, pace, average and max heart rate, cadence in steps per minute (doubled), effort (RPE) and load.
- **Ride:** time, average and normalized power, average heart rate, load.
- **Swim:** distance, time, pace per 100.
- **Strength:** what was recorded, and which session was planned.
- **Hike or walk:** distance, elevation gain, time.

End with one plain sentence on how it went against the plan (for example "Completed as planned, a little quicker than the easy range"). A missed session is stated without judgment; the brief never scolds.

## Settings for this vault

This owner's values. The scheduled task that runs this app carries no personal details; it reads them here. Another owner installing this app replaces this section and nothing above it.

- **Owner:** see `profile`.
- **When:** daily at <time> <IANA time zone>, with a phone notification (the scheduled task "Morning brief").
- **Page:** the Claude artifact "Morning Brief", slug `<artifact slug>` (<artifact link>). Its index.html renders `brief.json`; only brief.json changes.
- **Weather location:** <town, region> (latitude <lat>, longitude <lon>). The page's weather heading shows it as "<short name>" (the `place` field in brief.json).
- **Calendars:** <which calendars, and through which connector>. <Whether work meeting titles may be written into the brief and the vault.>
- **Time zone:** <IANA time zone>.
- **Season note:** <[[season note]], or "none">.
- **Cadence target:** <steps per minute, or "none">.
- **Weight goal:** <where the goal is written, or "none">.

## Rules owned elsewhere

- PROTOCOL-OWNED: the write-back cascade. Call `get_vault_guide` and run what it defines after the brief is published. Footer: "cascade complete".
- PROTOCOL-OWNED: where a log entry goes. Run the cascade; do not name the log's path here.
- PROTOCOL-OWNED: never plain `append` on an entity note; use a section-targeted edit.
