---
title: Training Ledger — YYYY-MM
type: data
---

# Training Ledger — YYYY-MM

Append-only. Every training session recorded in <Month YYYY>, one line each, kept by the [[training-ledger]] app. The vault's own copy of the record: the original files are in Garmin, and Intervals.icu is a working mirror. Totals and "when did I last…" answers are in [[Training Ledger — Index]].

## Entry grammar — v1

One line per recorded session, in time order: date and start time, the kind, the session's name as recorded, then what was measured (distance, moving time, pace per mile for foot sessions or per 100 yd for swims, average heart rate, training load), then the activity id: `i…` for Intervals.icu, `g…` for Garmin Connect, `f…` for a strength app's export. Kinds: run, trail_run, virtual_run, ride, virtual_ride, swim, strength, workout, hike, walk, stairs, other. "load" is Intervals.icu's training load; "Garmin load" is Garmin's, on a different scale. A strength-app line gives the number of exercises, working sets (warm-ups left out) and volume (reps × weight, in lb) instead of time.

    - 2026-11-22 07:31: run — City Marathon — 26.40 mi · 3:58:03 · 9:01/mi · HR 152 · load 360 · i100000001

A line records what the device recorded, not what was meant. A `note:` item under an entry explains it (official race time, a watch left running). **Corrections:** never edit a past line. Add a `correction:` item under it saying what was wrong and what is right.

```ledger-grammar
{"name": "training-ledger sessions v1",
 "entry_heading": "## Sessions",
 "line_shapes": {
   "entry": "^(?P<date>\\d{4}-\\d{2}-\\d{2}) (?P<time>\\d{2}:\\d{2}): (?P<kind>[a-z_]+) — (?P<name>.+?) — (?P<metrics>.+) · (?P<id>[igf]\\d+)$"
 },
 "token_sets": {"kind": ["run", "trail_run", "virtual_run", "ride", "virtual_ride", "swim", "strength", "workout", "hike", "walk", "stairs", "other"]},
 "sidecar_prefixes": ["note:", "correction:"]}
```

## Sessions

