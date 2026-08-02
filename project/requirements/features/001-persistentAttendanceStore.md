# 001 — Persistent attendance store

## Status

InProgress

## Outcome

As the attendance-reporting application, I need durable attendance state with
auditable source evidence so that collection can resume safely and attendance
can be queried across arbitrary date ranges.

## Summary

Replace the poll-oriented JSON cache with a durable SQLite attendance store.
The store must represent logical sessions and members independently, associate
members with the sessions they attended, and retain the source observations
used to establish attendance.

The stored data must support queries in both directions:

- list the members who attended a given session;
- list the sessions attended by a given member over an arbitrary date range,
  including ranges spanning several months.

## Context

The existing cache is a month-specific JSON snapshot keyed by derived poll
keys. It is loaded only when explicitly requested, contains repeated poll vote
rows rather than first-class sessions and members, and is saved only after a
successful scrape. It cannot reliably combine observations from multiple
sources, explain how attendance changed, or answer attendance-history queries
without reconstructing the domain model on every run.

The desired store is durable application state and not merely a performance
cache. WhatsApp polls are the first input source, but the data model must allow
additional sources to contribute observations to the same logical session.

## Requirements

### Storage lifecycle

1. The application must open and read the attendance store by default at the
   start of a collection run.
2. A collection run must record each source scan, including its start time,
   completion time, scope and completion status.
3. Successfully scanned observations must be reconciled with existing state as
   pages are scanned.
4. A failed poll read must preserve the last successfully stored observations
   for that poll or source.
5. Absence from a partial or failed scan must not remove a session, member or
   attendance observation.
6. Removal of observations which are no longer present may occur only after a
   complete scan of the relevant source and scope.
7. A completed run must commit its changes transactionally. Completed groups
   may be checkpointed independently so that a later browser failure does not
   discard earlier completed work.
8. The store must use schema versioning and explicit migrations.

### Scan boundary

1. When scanning a source from newest to oldest, the application must normally
   stop scanning that source after it encounters a poll which has already been
   captured successfully in the attendance store.
2. A poll may act as this boundary only when it can be matched reliably using a
   stable source identity. A title-only or otherwise ambiguous match must not
   stop the scan.
3. The boundary applies independently to each source or WhatsApp group; finding
   a captured poll in one group must not prevent other requested groups from
   being scanned.
4. Stopping at a previously captured poll is an expected successful completion
   of the older-history portion of that source scan and must be recorded as
   such, rather than as a partial or failed scan.
5. The application must log the poll and source which caused scanning to stop.
6. The `--override` CLI flag must force scanning to continue past previously
   captured polls. Its behaviour must be documented in CLI help and user
   documentation.
7. When the override is active, scanning must continue no further back than the
   start of the month two calendar months before the current calendar month.
   For example, a run during August may scan June, July and August records but
   must stop before 1 June.
8. The override horizon must be calculated from the application's current local
   date and must behave correctly across year boundaries. For example, a
   January run may scan records from 1 November onwards.
9. Reaching the override horizon must be logged with the calculated cutoff date
   and recorded as a successful scan boundary.
10. The CLI must provide `--scan-since YYYY-MM-DD` for explicitly replacing the
    two-month override horizon.
11. A custom `--scan-since` date must take effect only when both `--override`
    and `--scan-since YYYY-MM-DD` are supplied. `--scan-since` without
    `--override` must be rejected with a clear error explaining that both
    options are required.
12. `--override` without `--scan-since` must use the standard two-month horizon.
13. `--scan-since` must reject invalid or future dates with a clear error and
    must treat the supplied local calendar date as an inclusive cutoff.
14. The resolved scan mode and cutoff date must be logged before browser
    scanning begins.
15. Scan limits, title filters, failures and ambiguous matches must remain
    distinguishable from the normal previously-captured boundary in scan status
    and logs.

### Sessions

1. A session must be stored as a first-class record with a stable internal
   identifier.
2. Session data must include, where known, its date, start time, name or type,
   venue, status, and creation and update timestamps.
3. Session identity must not depend only on a mutable poll title.
4. Stable source identifiers, such as a WhatsApp group and message identifier,
   must be retained when available.
5. Normalised date, time, venue and title information may be used to match a
   source observation to an existing logical session when no stable external
   identifier is available.
6. Multiple source records must be able to refer to the same logical session.
7. Refining a provisional session identity after reading a poll must not create
   a duplicate session.

### Members

1. A member must be stored as a first-class record with a stable internal
   identifier.
2. Member data must include a canonical display name, a normalised name, and
   creation and update timestamps.
3. The model must support aliases so spelling or display-name changes do not
   automatically create separate members.
4. Ambiguous member matches must not be silently merged.

### Attendance and source observations

1. Attendance must associate one logical member with one logical session.
2. Attendance must support at least `yes`, `no`, `maybe` and `unknown` states.
3. The effective attendance record must include first-seen and last-seen
   timestamps.
4. Raw source observations must be retained separately from effective
   attendance so the origin of a decision remains auditable.
5. Each observation must identify its source, session, member, observed
   response and observation time.
6. Removing a member from one source must not erase attendance still supported
   by another source.
7. Conflicting observations from different sources must be detectable and
   resolved using an explicit, documented rule.

### Change logging

The application must log material changes as they are reconciled, including:

- a session being created, updated, cancelled or removed;
- a member being created or matched through an alias;
- a member being added to or removed from a session;
- an attendance response changing;
- conflicting source observations;
- a failed reconciliation which preserves earlier state.

At the end of a run, the application must log totals for sessions, members and
attendance associations added, updated, removed, unchanged or conflicted.

### Queries and reporting

The storage API must support at least:

1. sessions within an inclusive date range;
2. members associated with a session;
3. sessions attended by a member within an inclusive date range;
4. attendance filtered by response status, group, venue or source;
5. the source observations supporting an effective attendance record.

Existing CSV and text reports must be generated from the persistent attendance
store rather than from a flattened in-memory poll cache. Query date ranges must
not be restricted to a single calendar month.

### SQLite implementation

1. SQLite must be used through Python's standard-library `sqlite3` module.
2. Foreign-key enforcement must be enabled for every connection.
3. Appropriate uniqueness constraints and indexes must protect session,
   member, source and attendance identity.
4. Mutating workflows must use transactions and roll back incomplete units of
   work.
5. The implementation must use SQLite's `PRAGMA user_version` or an equivalent
   explicit mechanism for schema migrations.
6. The database must live beneath the application output or data location and
   must not be committed to version control.
7. The application must provide a documented backup and recovery approach.

## Suggested logical model

The implementation is expected to provide equivalents of these entities; the
exact table and column names may be refined during design:

- `sessions` — logical session details and status;
- `members` — canonical member identities;
- `member_aliases` — alternate source names for members;
- `sources` — external source identity and type;
- `session_sources` — association between a logical session and its sources;
- `attendance` — effective member-to-session attendance;
- `attendance_observations` — source-specific evidence;
- `scans` — source scan scope, timing and completion state.

## Cache retirement

The superseded JSON poll-cache layer, its migration command, and the raw poll
CSV export are removed. SQLite is the only durable attendance store.

## Acceptance criteria

1. A normal collection run reads existing attendance state without requiring a
   cache opt-in flag.
2. Re-scanning unchanged polls produces no duplicate sessions, members or
   attendance associations and logs them as unchanged.
3. Adding, removing or changing a poll response updates the appropriate source
   observation and produces a detailed log message.
4. A failed or incomplete scan does not interpret unseen data as removed.
5. Two sources can contribute observations to one session without duplicating
   the logical session.
6. A user can query everyone who attended a selected session.
7. A user can query all sessions attended by a selected member across May,
   June and July, or any other inclusive date range.
8. Reports are produced from stored session and attendance data.
9. An interrupted write or failed transaction leaves the last committed
   database state usable.
10. A normal newest-to-oldest scan stops when it reaches a reliably matched,
    previously captured poll and logs that boundary.
11. With the override flag set, the same scan continues past previously
    captured polls and processes history back to, but not before, the start of
    the month two calendar months before the current month.
12. With `--override --scan-since 2026-02-15`, scanning continues past captured
    polls and includes records dated 15 February 2026 or later, regardless of
    the normal two-month horizon.
13. Supplying `--scan-since 2026-02-15` without `--override` is rejected before
    browser scanning begins.

## Test coverage

Automated tests must cover schema creation and migration, default loading,
session identity refinement, member alias matching, multi-source
reconciliation, additions, removals, response changes, incomplete scans,
transaction rollback, idempotent JSON migration, date-range queries and change
summary logging. Tests must also cover the default captured-poll boundary, the
override path, ambiguous identities, and independent boundaries for multiple
groups. Override-horizon tests must include ordinary month changes and a year
boundary. Tests for `--scan-since` must cover its inclusive cutoff, invalid
input and future dates. Tests must verify that `--scan-since`
without `--override` is rejected and that `--override` without `--scan-since`
uses the standard two-month horizon.

## Out of scope

- A graphical interface for browsing or editing attendance.
- Automatic merging of ambiguous member identities.
- Networked or multi-user database hosting.
- Replacing WhatsApp browser automation as part of this requirement.

## Dependencies and decisions

- A pending architecture decision must record the durable schema,
  reconciliation boundaries and conflict precedence before completion.
- Live WhatsApp browser validation remains required for the scan-boundary and
  interrupted-browser acceptance criteria.

## Verification

- Automated storage and reconciliation coverage:
  `tests/test_AttendanceStore.py`.
- Automated CLI cutoff validation: `tests/test_main_cli.py`.
- Existing report and scraper regression coverage:
  `tests/test_WhatsappAttendance.py`.
- Latest automated result on 2026-08-02: `103 passed` using `pytest -q`.
- Formatting result on 2026-08-02: Black checks passed for every changed
  Python file.
- Repository validation on 2026-08-02: Python compilation and
  `git diff --check` passed.
- Pending: live WhatsApp validation of default boundaries, override horizons,
  failed poll reads and browser interruption recovery.
- Pending: focused automated evidence for session identity refinement, failed
  reconciliation logging, end-of-run summary logging and report generation
  through the store boundary.

## Traceability

- Implementation: `src/whatsapp/store.py`, `src/whatsapp/scraper.py`,
  `src/whatsapp/exporter.py`, `src/attendanceConfig.py`, `main.py`, and
  `src/organiseMyFooty/cli.py`.
- Tests: `tests/test_AttendanceStore.py`, `tests/test_main_cli.py`, and
  `tests/test_WhatsappAttendance.py`.
- Documentation: `documentation/persistentAttendanceStore/README.md` and
  `README.md`.
- Pull request: pending.
- Agent runs: 2026-08-01 to 2026-08-02 — Codex implementation run using
  `project/requirements/prompt/001-persistentAttendanceStore.prompt.md`;
  result is the current requirement branch and working tree.

## Change history

- 2026-08-01: created from the persistent attendance-store request.
- 2026-08-01: implementation started on
  `feature/001-persistentAttendanceStore`.
- 2026-08-02: status corrected to `InProgress` under the latest requirements
  workflow because manual browser evidence, focused verification and an
  architecture decision remain pending.
