# Persistent attendance store

The application keeps durable attendance state in `output/attendance.sqlite3`.
SQLite foreign keys are enabled on every connection and schema changes are
applied explicitly using `PRAGMA user_version`. The current schema models
logical sessions, members and aliases, external sources, source/session links,
effective attendance, raw observations, and source scans.

## Reconciliation

Each successfully read poll is reconciled in its own transaction, allowing a
completed WhatsApp group to remain committed if a later browser operation
fails. Incomplete reads preserve earlier observations. Missing observations
are deactivated only for a successfully and completely read poll. Effective
attendance is then recalculated from all active source observations.

When sources disagree, the attendance row is marked conflicted and the
deterministic precedence rule is `yes`, `maybe`, `no`, then `unknown`. The raw
observations remain available for auditing. Removing evidence from one source
does not remove attendance supported by another source.

## Scan boundaries

A normal newest-to-oldest scan stops independently per WhatsApp group when it
encounters a captured poll with a stable message identifier. Titles alone
never establish this boundary. `--override` continues past captured polls but
stops at the beginning of the month two calendar months before the current
local month. `--override --scan-since YYYY-MM-DD` replaces that horizon with an
inclusive date. A future or invalid date, or `--scan-since` without
`--override`, is rejected before browser startup.

## Queries and reports

The storage API supports inclusive session ranges, members for a session,
sessions for a member across arbitrary date ranges, filtered attendance, and
the observations behind an effective result. CSV, text, and JSON exports are
built from stored attendance for the selected report month after collection.
Use `--view` to inspect that month without scanning.

## Backup and recovery

Stop collection before copying the database. Back up `attendance.sqlite3`
together with any adjacent `-wal` and `-shm` files, or use SQLite's online
backup command/API while the application is running. Recovery is performed by
moving the unusable database aside and restoring the backup at the same path.
Never replace a live database while a collection process has it open.
