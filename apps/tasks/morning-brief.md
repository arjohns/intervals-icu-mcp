# Scheduled task: Morning brief

A Claude scheduled task (chat). Suggested schedule: daily, about 15 minutes before you wake, in your time zone. Turn on the phone notification. Connectors it needs: your Commonplace vault, this server, your calendars, and Claude's artifacts.

The prompt, word for word:

```text
Run the vault owner's morning brief for today, in the time zone the app's settings give. Nobody is watching while it is built: do not wait for answers. Decide, publish, and say in the brief what you could not get. The check-in's question goes in the final message, and the conversation continues only if the owner replies.

1. In the owner's Commonplace vault, read profile for who they are, then the app note app/morning-brief/SKILL.md, and follow it exactly. That covers what to read, the readiness bands, the verdict rules, the safety rules (safety outranks the numbers), the missing-data rule, the brief's sections, how to decide yesterday's status, and the check-in. Its "Settings for this vault" section gives the page, weather location, calendars, time zone, season note, cadence target, weight goal, habits the owner wants to change, and whether check-in answers may be logged. Also read now and the season note if they exist, and the last two days of the log for "how it felt" and check-in lines.

2. Gather today's data as the method says (Garmin files a night under the date it ended): Garmin through the training connector (garmin_get_sleep, garmin_get_hrv, garmin_get_heart_rate, garmin_get_daily_summaries; on Mondays garmin_get_weight), the planned sessions for yesterday through two days ahead (icu_get_calendar_events, days_back 1, days_ahead 2), yesterday's completed sessions (icu_get_activities_by_date, then icu_get_activity_details for each), the weather for the settings location, and today's events on each calendar in settings. If Garmin fails or has no tools, use icu_get_wellness_for_date as the method says. If a calendar cannot be reached, say so in "missing".

3. Decide the verdict by the method. level is "go", "easy" or "rest"; label is "Go", "Go easy" or "Rest"; reason is one plain sentence. Any missing signal goes in "missing" as a plain sentence, and the verdict is marked partial in its reason. Then pick today's check-in questions by the method's "When it asks" (none if nothing applies).

4. Publish to the page in settings. Its index.html renders brief.json and must not be changed. Read the current brief.json with the artifacts read_file tool and use it as the template: same keys and shapes (date, weekday, made, place, verdict, missing, yesterday, signals with min/max/x/zones/status, sleep with stages in minutes, session or null, weather for three days, today, due, coming, sources). "place" is the short name settings give for the weather heading. "yesterday" is {date, weekday, status: done|partial|missed|extra|rest, label: "Done"|"Partly done"|"Missed"|"Unplanned"|"Rest day", planned (text, or null), done: [{what, stats: [[label, value, plan-or-note]], felt (or null)}], note}. Put each of today's calendar events in "today" as {"time": "9:00 AM", "what": "..."} in time order, with the day's meeting load as the first item. The page stays on the day: check-in answers never go on it. Write today's brief.json to a file in the working folder, check it parses as JSON, then get the artifact's current version with get_artifact and republish only brief.json with publish_files (slug, base_version, mode patch, label "brief YYYY-MM-DD"). Plain words only, no product words.

5. Log it: call get_vault_guide and run the write-back it defines for a finished task: one line in today's log saying the brief ran, its verdict and yesterday's status.

6. End with a final message, which reaches the owner's phone: the verdict line, the page's link, then the check-in's first question if there is one.

7. If the owner replies in this conversation, continue the check-in exactly as the method says: one question at a time, three at most, stop once an answer settles it. If settings say check-in answers may be logged, write one check-in line to today's log in the method's format, in the owner's words with its cause tags. If an answer changes the day (illness, or pain above 3 out of 10), republish brief.json with the new verdict and offer to move sessions, waiting for the owner's yes.

Apart from those log lines and brief.json, nothing in the vault changes. Never change the training calendar, Garmin, any calendar, or any other vault note. Changes to the app itself are made in a separate conversation, not here.
```
