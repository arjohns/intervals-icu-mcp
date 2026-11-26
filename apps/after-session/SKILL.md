---
title: after-session
type: guide
description: 'What happens after a session: the owner''s server sees it in Garmin
  and starts a task that records it, checks it against the plan, then talks briefly
  about how it felt, with questions chosen for the kind of session and the owner''s
  injury history, until there is nothing left to ask. A method plus this vault''s
  settings.'
---

# after-session

**Version:** 1.1.0

**Shape:** a method plus this vault's settings. Everything above *Settings for this vault* names no person and works for any owner; the owner's history, zones and habits are in that section and in their season note.

**Started by:** the owner's server, when Garmin shows a new activity. It fires the Code task named in settings with the new activity ids. An owner without a Garmin key has no watcher: the nightly ledger sync records the session, and this app runs when the owner asks about a session ("how did that run go?"), reading it from intervals.icu.
**Reads:** `profile` for who the owner is; the session from Garmin (`garmin_get_activity`, `garmin_get_activity_workouts` for strength) and intervals.icu; today's planned workout; the season note named in settings for zones, pace ranges and injury history; the [[training-ledger]] and [[morning-brief]] apps.
**Writes:** the ledger and its index (by the training-ledger app's rules), the Morning Brief page's session block, and today's log.
**Never writes to:** intervals.icu, Garmin, any calendar, or other vault notes.

## First, see what it was

Read the activity type before saying anything. Everything after that depends on the type.

| Type | Report | Plan check | Areas the session loads |
|---|---|---|---|
| Run, trail run, treadmill | Distance, pace, average heart rate, cadence in steps/min (double Garmin's one-foot figure) | Distance and pace against the planned workout's range | Calves, Achilles, shins, knees, hips, ankles |
| Ride, indoor ride | Time, average and normalized power if present, average heart rate | Time in the planned power zones (the owner's FTP is in settings) | Hips and hip flexors, knees, lower back |
| Pool swim | Distance, pace per 100, rest | Distance and pace against the plan | Shoulders, neck. Breathing and how the stroke felt matter more than pain |
| Open-water swim | Distance or time only | Distance or time against the plan | Same as pool |
| Strength | What Garmin recorded (sets, exercises) | Which strength session was planned, if any | Whatever the session worked; general soreness |
| Hike or walk | Distance, elevation gain, time | No plan check unless one was planned | Ankles and knees, especially on uneven ground or descents |
| Anything else | What was recorded | Planned or not | Ask one open question only |

**Which area to ask about first:** an area this session loads that also appears in the owner's injury history (settings). If none does, or settings list no history, ask how the session felt overall. If settings name no season note, the plan check uses only the planned workout on the calendar; if nothing was planned, skip the plan check.

**Where strength is recorded** is a setting. If the owner logs strength in another app, don't add a Garmin strength line to the ledger; ask whether the session was logged there.

## The conversation

The phone message is the first turn: what the session was, the plan check, then one question. Then the owner replies, or doesn't.

1. **One question per message**, multiple choice where it fits ("Calf: fine / a bit tight / sore, out of 10?").
2. **Ask first about what this session most likely affected**, from the table. Never ask about a body part the session didn't load unless the owner brings it up. No calf questions after a swim.
3. **Stop as soon as it's conclusive.** Conclusive means one of these:
   - The owner says it all felt fine, or anything like "all good". Stop: no follow-up.
   - The area asked about is 3 out of 10 or less and nothing else came up. Note it and stop.
   - Something is above 3 out of 10, sharp, or worse than before. Ask at most one follow-up (where, and whether it hurt during the session or only after). Then give the safety call (easy or rest tomorrow, and the physical therapist if it lasts more than a few days) and stop.
4. **Never more than three questions in total.** If no answer comes, nothing more is asked.
5. **Close by saying what was recorded**, in one line: "Logged: calf 2/10, nothing else."

## What gets written

When the conversation ends, add one line to today's log in the owner's words: "how it felt" for that session, including any number they gave. The morning brief reads the last two days of the log for these lines. Anything above 3 out of 10 there counts as reported pain under the brief's safety rule.

This is not medical advice and never diagnoses anything. Pain that is sharp, gets worse, or changes how the owner moves means stopping and getting it seen.

## Settings for this vault

This owner's values. Another owner installing this app replaces this section and nothing above it.

- **Owner:** see `profile`.
- **Started by:** <the Code task "After-session update" and its id, fired by the Garmin watcher; or "none: no Garmin key, run on request">.
- **Season note:** <[[season note]], or "none">.
- **Injury history worth asking about first:** <body areas, most recent first, or "none">.
- **Bike:** <FTP in watts and zone edges, or "no bike">.
- **Swim:** <pool distances in yards or meters, or "no swimming">.
- **Strength:** <logged in Garmin, or in another app (which), and the usual strength days>.

## Rules owned elsewhere

- PROTOCOL-OWNED: the write-back cascade. Call `get_vault_guide` and run what it defines. Footer: "cascade complete".
- PROTOCOL-OWNED: never plain `append` on an entity note; use a section-targeted edit.
