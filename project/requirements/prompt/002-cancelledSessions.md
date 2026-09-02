# Agent prompt — 002 cancelled sessions

Implement [requirement 002 — Cancelled sessions](../features/002-cancelledSessions.md).

The requirement is authoritative. Follow `AGENTS.md` and all referenced
repository instructions, preserve existing user changes, and work on
`feature/002-cancelledSessions`.

## Objective

Treat exactly the configured WhatsApp participant's `😢` reaction on a poll as
session cancellation. Configure and persist the participant with
`--emoji NAME` in both CLI entry points.

## Required approach

1. Keep reaction DOM inspection in WhatsApp discovery code and pass only a
   domain cancellation status into parsing/persistence.
2. Require exact emoji and participant-name matches; avoid partial names,
   unrelated message text, other participants and other emojis.
3. Preserve titles, votes and source evidence while excluding cancelled
   sessions from effective attendance and reports.
4. Reconcile reaction removal as restoration of the same logical session.
5. Revisit captured polls in the selected month when recognition is enabled;
   the captured-poll shortcut must not hide reaction changes.
6. Persist the name safely in existing user state and expose it through
   resolved configuration without storing it in the attendance database.
7. Log relevant state changes without exposing attendance data in tests.
8. Treat reaction inspection failure as unknown and preserve the last stored
   state; never interpret an inspection error as reaction removal.

## Verification

Test CLI parsing and state persistence, exact reaction matching, false
positives, captured-poll rescans, cancellation/restoration, report exclusion
and multi-source behavior. Run focused tests, the full suite, formatter, naming
linter and `git diff --check`.

Live WhatsApp validation is required to prove the participant and emoji are
available together in accessible reaction metadata. Report it separately from
automated tests.
