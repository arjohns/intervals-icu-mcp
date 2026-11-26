# Scheduled task: Training ledger sync

A Claude scheduled task (chat). Suggested schedule: every evening, after your usual last session. No notification needed. Connectors it needs: your Commonplace vault and this server.

The prompt, word for word:

```text
Bring the vault owner's training ledger up to date. This is the nightly safety net: the "After-session update" task, if the owner has one, usually adds each session soon after it ends. Nobody is watching this run: do not ask questions.

1. In the owner's Commonplace vault, read the app note app/training-ledger/SKILL.md and follow its "Syncing" section exactly, with the values in its "Settings and history for this vault". Read the newest month's ledger note in app/training-ledger/data/ (Training Ledger — YYYY-MM) for its entry grammar and its last line.
2. Pull every activity from the last three days from intervals.icu (icu_get_activities_by_date). Skip any activity already in the month's ledger: either its id is there, or a line with the same date and a start time within 10 minutes is there (a g… Garmin line added before intervals.icu had it). If a new month has started, create that month's note by copying the previous month's intro and entry-grammar section unchanged.
3. Add each new session as one line in the month's "## Sessions" section, in time order, formatted exactly as the grammar says, with a section-targeted edit, never a plain append.
4. If anything was added, rewrite the affected rows of "Training Ledger — Index" from the ledgers (covers line and session count, the year row, the month row, and the "Last of each kind" and "Long runs" entries the new sessions change), then run validate_note on each ledger touched; the grammar check must come back clean.
5. If nothing new was found, change nothing and stop.
6. If sessions were added, call get_vault_guide and run the write-back it defines for a finished task, so today's log gets one line naming what was added.
7. Never write to intervals.icu, Garmin, or any vault note other than the ledgers, the index and today's log. End with one line: what was added, or "No new sessions."
```
