# Setup prompt

Paste this into a new Claude chat once your server is deployed and both connectors work: your Commonplace vault and this server. Claude asks a few questions, then installs everything. It takes about ten minutes.

```text
Set up the training apps from this repository in my Commonplace vault. The files are in the apps/ folder of https://github.com/arjohns/intervals-icu-mcp, and each can be fetched raw from https://raw.githubusercontent.com/arjohns/intervals-icu-mcp/main/<path>: apps/morning-brief/SKILL.md, apps/after-session/SKILL.md, apps/training-ledger/SKILL.md, apps/training-ledger/ledger-month-template.md, apps/training-ledger/ledger-index-template.md, apps/morning-brief/page/index.html and apps/morning-brief/page/brief.json, and the three prompts in apps/tasks/. Read them before you start.

First check what is already there: read my vault's profile and its guide (get_vault_guide), list app/ to see whether any of these apps is installed, and check that the training connector answers (icu_get_athlete_profile) and whether it has garmin_* tools. Tell me in two lines what you found.

Then ask me, one question at a time, multiple choice where it fits, only what you could not find:
1. Where I live, for the weather (town and region).
2. Which calendars the brief should read, and whether work meeting titles may be written into the brief and the vault.
3. What time I want the brief, in my time zone.
4. Whether I have a season or race plan note in the vault, or want a short one created (goal race and date, current phase).
5. Injuries or body areas worth asking about after a session.
6. FTP if I ride; pool units if I swim; where I log strength.
7. A cadence target and a weight goal, each optional.
8. Whether the brief's check-in may record my answers in the vault (drinks, illness, injury, mood), and any habit I want to change.

Then install, in this order, telling me one line per step:
a. Write the three app notes to app/morning-brief/SKILL.md, app/after-session/SKILL.md and app/training-ledger/SKILL.md exactly as in the repository, with only their settings sections filled in from my answers. Leave out anything I said no to.
b. Create the current month's ledger from the month template and the index from the index template in app/training-ledger/data/. Then fill this month and the last three months from intervals.icu (icu_get_activities_by_date), one ledger per month, validate each, and rewrite the index. Ask before going back further.
c. If I asked for one, create the season note where the vault guide says project notes go.
d. Create a Claude artifact called "Morning Brief" from index.html and brief.json, put its slug and link in the morning-brief settings, and set brief.json's "place".
e. Create the scheduled tasks "Morning brief" (at my time, with a phone notification) and "Training ledger sync" (every evening, no notification) from the prompts in apps/tasks/, word for word.
f. Run the Morning brief task once so I can see it, and give me the page link.
g. If I have Garmin tools, tell me the one remaining manual step: create the "After-session update" Code task from apps/tasks/after-session.md and give its API trigger to the server, as docs/cloud-run.md describes. Once I've done that, put its id in the after-session settings.

Finally run the vault's write-back for a finished task. Never write my keys or tokens anywhere, never change my intervals.icu calendar, and ask before anything you can't undo.
```
