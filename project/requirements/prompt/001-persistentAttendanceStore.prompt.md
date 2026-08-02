# Agent prompt — 001 persistent attendance store

Implement [requirement 001 — Persistent attendance store](../features/001-persistentAttendanceStore.md).

The requirement is authoritative. Read it completely before changing code, and
also follow `AGENTS.md` and all repository instructions it references. Inspect
the current implementation and tests rather than relying on filenames or source
layout described in older documentation.

## Working process

1. Read `AGENTS.md` completely before planning or making changes.
2. Read and apply every standards and repository-definition file referenced by
   `AGENTS.md`, including `.github/agent-instructions.md`,
   `.github/additional-instructions.md` when it exists, and
   `.github/repositoryLayout.md`.
3. Inspect `git status` and preserve any existing user changes. Do not overwrite
   or discard unrelated work.
4. Before development changes, create and switch to the requirement branch:
   `feature/001-persistentAttendanceStore`.
5. Confirm the active branch before editing. If that branch already exists,
   switch to it rather than creating a differently named branch.
6. Keep all implementation, tests and documentation for this requirement on
   that branch.
7. Re-read the applicable standards before adding or moving repository content
   or when an implementation decision affects architecture, naming, safety or
   testing.

## Objective

Replace the poll-oriented JSON cache with a durable SQLite attendance store
which models logical sessions, members, effective attendance, source-specific
observations and scan completion. Make the store the source for attendance
queries and report generation.

## Required approach

1. Trace the existing CLI, scraper, poll identity, cache, reporting and logging
   workflows before designing changes.
2. Define a normalized SQLite schema for sessions, members, aliases, sources,
   session/source associations, effective attendance, raw observations and
   scans.
3. Use Python's standard-library `sqlite3`, enable foreign keys, apply suitable
   uniqueness constraints and indexes, and manage migrations with
   `PRAGMA user_version`.
4. Keep persistence behind a focused domain storage API. Browser/UI code must
   not issue SQL or own reconciliation rules.
5. Load the store by default. Remove the old cache opt-in semantics and update
   CLI help, runtime configuration and documentation accordingly.
6. Reconcile scanned observations transactionally. Preserve prior data after a
   failed poll read or incomplete scan, and only infer removals after a complete
   scan of the relevant source and scope.
7. Implement the scan boundaries exactly as specified:
   - normally stop each source/group at the first reliably matched captured
     poll;
   - `--override` continues through the current month and two preceding calendar
     months;
   - `--override --scan-since YYYY-MM-DD` replaces that horizon with an
     inclusive cutoff;
   - reject `--scan-since` without `--override`, invalid dates and future dates
     before opening the browser.
8. Do not use title-only or ambiguous matches as a captured-poll boundary.
9. Calculate and log semantic changes to sessions, members, attendance and
   observations as they occur, followed by the required run summary.
10. Generate reports through store queries and allow member/session queries
    over arbitrary inclusive date ranges.
11. Provide an idempotent importer for valid legacy JSON cache records. Do not
    alter a legacy cache until its import commits successfully.
12. Document the database location, schema migration policy, backup/recovery
    process, new CLI behaviour and query capabilities.

## Implementation constraints

- Preserve existing user data and supported export behaviour.
- Treat source observations separately from effective attendance so conflicts
  and provenance remain auditable.
- Use stable source identifiers where available and make identity refinement
  idempotent.
- Do not silently merge ambiguous members.
- Do not interpret an early stop caused by failure, filtering or an arbitrary
  limit as a complete historical scan.
- Keep domain and persistence logic testable without Playwright or a live
  WhatsApp session.
- Avoid unrelated refactoring unless it is necessary to complete the
  requirement safely.

## Verification

Add focused automated tests for every acceptance criterion and all test
categories named in the requirement. At minimum, verify schema creation and
migration, transaction rollback, idempotent imports, session identity
refinement, aliases, multi-source conflicts, additions/removals/response
changes, incomplete scans, all scan-boundary modes, year boundaries,
date-range queries and change logs.

Run the relevant focused tests while developing, then the complete test suite
and repository formatting/lint checks. Do not require a live browser for unit or
integration tests. Report the commands run and any checks that could not be
executed.

## Completion report

Summarize the schema and migration path, reconciliation rules, scan-boundary
behaviour, CLI changes, query/report changes, logging, tests, documentation and
any remaining risks. Explicitly confirm how existing JSON cache data is
preserved and migrated.
