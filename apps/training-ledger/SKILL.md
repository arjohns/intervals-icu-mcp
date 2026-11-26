---
title: training-ledger
type: guide
description: 'The training record in the vault: every run, ride, swim, strength session
  and hike, one line each, with derived totals. A method plus this vault''s settings
  and history. Use when the owner asks about their own training history or wants it
  brought up to date: "what did I run in September", "how many miles have I run this
  year", "when was my last 20-miler", "sync my workouts into the vault", "update the
  training ledger".'
---

# training-ledger

**Version:** 1.1.0

**Shape:** a method plus this vault's settings and history. Everything above *Settings and history for this vault* names no person and works for any owner.

**Reads:** the owner's Intervals.icu account through their connector (tools named `icu_*`); the ledger notes in `app/training-ledger/data/`; the season note named in settings, for context, if there is one; the ledger works without it.
**Writes:** `app/training-ledger/data/` only: the monthly session ledgers and the derived index.
**Never writes to:** the system project; the owner's Intervals.icu calendar or activities; the Garmin account; any other vault note on this app's behalf (the season note belongs to the weekly digest and to the cascade).

## What this is

The vault's own record of every training session, so the vault can answer questions about the owner's training without any outside service. The vault, not the training platform, is the source of truth. Three layers, each with one job:

| Layer | Holds | Role |
|---|---|---|
| Garmin (device and Garmin Connect, plus the full account export) | The original recordings: every second of every session | The originals |
| **This app's ledger** | One line per session: what, when, how far, how long, heart rate, load | The vault's record |
| The season note (settings) | The plan, results against plan, achievements, lessons | What it means |

Intervals.icu sits beside these as a working tool (analysis, and the path for workouts to reach the watch). Nothing in this app depends on it except the sync.

## Words, because one of them collides

This app keeps **sessions** in **ledgers**. The vault also has a **log**, the daily `log/` notes the cascade writes. They are different things. A session line never goes in the vault's log, and finishing a sync does not count as "logged" until the cascade has run.

## The ledger

- **One note per month:** `Training Ledger — YYYY-MM` in `app/training-ledger/data/`, `type: data`. Its sessions sit under `## Sessions`, in time order.
- **The line format, what counts as valid, and the corrections rule are declared in each ledger note**, under `## Entry grammar`. Read them there; this file does not restate them. A new month's note copies the previous month's intro and grammar section unchanged. The first month's note comes from `ledger-month-template.md`.
- **The index,** `Training Ledger — Index`, is **derived**: totals by month, the year to date, the last of each kind, and the long runs. Rewrite it from the ledgers after every update. Never hand-edit it.
- **Strength from a dedicated app.** If settings name a strength app, its lines (exercises, working sets, volume) are the record, because watch strength records often have unreliable times. When a sync brings in a platform strength line, keep it; when a later export from the strength app shows the same workout, add the strength app's line and a `correction:` under the platform line saying to count the other one. Match by start time within 3 hours, then by same day. Strength counts are still a floor.
- **Where history starts, and where it came from,** is recorded in settings.

## Syncing

1. Find the newest session already in the ledger (the last line of the newest month).
2. Pull everything after it with `icu_get_activities_by_date` (from that date, inclusive).
3. Skip any activity whose id already appears in that month's ledger; the id at the end of each line is the de-duplication key.
4. Map the Intervals.icu type to a ledger kind: Run → run, TrailRun → trail_run, VirtualRun → virtual_run, Ride → ride, VirtualRide → virtual_ride, Swim → swim, WeightTraining → strength, Workout → workout, Hike → hike, Walk → walk, StairStepper → stairs, anything else → other.
5. Format each session exactly as the ledger's grammar says: miles to two decimals, moving time as h:mm:ss (or m:ss), pace per mile for foot sessions, average heart rate and training load when present.
6. Add the lines to the month's `## Sessions` section, in time order, with a section-targeted edit.
7. Rewrite the index from the ledgers.
8. Run `validate_note` on each ledger touched. The grammar check must run and come back clean.

How often this runs, and what starts it, is in settings.

Add a `note:` item under a session whenever the recording misleads: a race's official time, a watch left running, a test's result.

## Answering questions

Start at the index (totals, last-of-each-kind, long runs), then open the month ledgers it points to. Distances are as the device recorded them. For races, prefer the official result in the session's `note:` item and in the season note.

## Good to know

- intervals.icu sends only the next ~7 days of planned workouts to Garmin and tops them up daily, so workouts further out show only on the intervals.icu calendar.
- Garmin files calendar workouts on the watch under **Scheduled**, not under the sport's workout list. A workout can't be deleted on the watch: remove it from the Garmin Connect calendar, then sync.
- Writing pace bands as a percentage of threshold pace (for example easy at 80–86%) means a new test result moves every future workout without rewriting them.

## Settings and history for this vault

This owner's values and this ledger's history. Another owner installing this app replaces this section and nothing above it.

- **Owner:** see `profile`.
- **Season note:** <[[season note]], or "none">.
- **Source:** Intervals.icu through the owner's own connector.
- **Strength app:** <name and id prefix, or "none: strength comes from the watch">.
- **What starts a sync:** <the After-session task, if there is a Garmin watcher; the scheduled task "Training ledger sync" every evening as the safety net>.
- **History starts:** <date of the first ledger line, and where older history came from, if imported>.

## Rules owned elsewhere

- PROTOCOL-OWNED: the write-back cascade. Call `get_vault_guide` and run what it defines when a sync is done. Footer: "cascade complete".
- PROTOCOL-OWNED: where a log entry goes. Run the cascade; do not name the log's path here.
- PROTOCOL-OWNED: never plain `append` on an entity note; use a section-targeted edit.
- PROTOCOL-OWNED: frontmatter carries tags, not body hashtags.
- PROTOCOL-OWNED: where a ledger's machine-readable grammar is read from, and the shape of the declaration.
