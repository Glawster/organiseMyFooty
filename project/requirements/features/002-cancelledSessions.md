# 002 — Cancelled sessions

## Status

ToDo

## Summary

Recognise WhatsApp session polls whose titles mark the session as cancelled,
preserve their original source details, and prevent them from contributing to
attendance calculations.

## Context

A session organiser may mark an existing poll as cancelled by adding
`(cancelled)` to its title. Treating that poll as an ordinary active session
would incorrectly add it to attendance reports and distort attendance totals.
The cancellation must remain visible and auditable rather than causing the
session record to disappear.

## Requirements

1. Session-title parsing must recognise `(cancelled)` case-insensitively.
2. Recognition must tolerate surrounding whitespace without requiring an exact
   title suffix.
3. The original poll title must be preserved unchanged as source data.
4. The logical session must be recorded with a cancelled status.
5. A cancelled session must not contribute to attendance processing, member
   attendance totals, session totals or attendance summaries.
6. Re-scanning a previously active session after its source title is marked
   cancelled must update the existing logical session rather than create a
   duplicate.
7. Re-scanning a cancelled session whose cancellation marker has been removed
   must restore it to the appropriate active status, subject to normal source
   reconciliation rules.
8. Session cancellation and restoration must produce clear change log messages.
9. Reports which expose session metadata may identify the session as cancelled,
   but must not present it as an attended session.
10. Cancellation observations from multiple sources must be retained and
    resolved using the persistent attendance store's documented source-conflict
    rules.

## Acceptance criteria

1. Titles containing `(cancelled)` in any letter case are recognised as
   cancelled.
2. The source title is retained exactly as captured.
3. Cancelled sessions remain queryable but are excluded from attendance counts
   and attendance report columns.
4. Cancelling an existing session updates that session and logs the change.
5. Removing the marker restores the session without duplicating it and logs the
   change.
6. Similar words which are not the `(cancelled)` marker do not cancel a session.

## Test coverage

Automated tests must cover case variations, marker position and whitespace,
false-positive titles, preservation of the original title, exclusion from each
report type, active-to-cancelled transitions, cancelled-to-active transitions,
logging and multi-source reconciliation.

## Dependencies

The durable status and source-reconciliation behaviour should align with
[001 — Persistent attendance store](001-persistentAttendanceStore.md).

## Out of scope

- Detecting cancellation from free-form chat messages outside a poll title.
- Automatically notifying members that a session was cancelled.
