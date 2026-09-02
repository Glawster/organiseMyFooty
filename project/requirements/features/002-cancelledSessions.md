# 002 — Cancelled sessions

## Status

InProgress

## Outcome

As a session organiser, I need a crying-face reaction on an existing WhatsApp
poll to cancel that session without changing or deleting the poll.

## Context

WhatsApp poll subjects cannot be edited and the organiser does not have the
ability to delete the polls. Cancellation is therefore represented by exactly
the `😢` Crying Face reaction on the poll message. The reacting participant is
not significant and no CLI configuration is required.

## Scope

1. Recognise exactly `😢` from accessible WhatsApp reaction metadata on a
   session poll.
2. Ignore other emojis.
3. Preserve the poll title and captured attendance observations unchanged.
4. Record the logical session as cancelled and exclude it from effective
   attendance, reports and totals.
5. Restore the session when the `😢` reaction is removed.
6. Revisit captured polls in the selected month so later reaction changes are
   observable.
7. Log cancellation and restoration with session identity.
8. Preserve the last stored status when reaction metadata cannot be inspected;
   an inspection failure must not imply restoration.
9. Remove the former `--emoji NAME` CLI option and legacy saved `emojiName`
   state value.

## Acceptance criteria

1. A poll reaction metadata value containing `😢` cancels the session.
2. The reacting participant does not affect cancellation.
3. Another emoji does not cancel the session.
4. Adding and removing the reaction updates the same logical session, logs the
   transition and does not duplicate it.
5. Cancelled attendance evidence remains auditable but is excluded from every
   attendance report and total.
6. Reaction recognition is always enabled for session polls.
7. If reaction inspection fails, the poll is not reconciled and its last stored
   session status and observations remain unchanged.
8. `--emoji` is no longer accepted and `emojiName` is removed from saved state.

## Test coverage

Automated tests must cover CLI removal, automatic crying-face recognition,
other-emoji false positives, captured-poll rescans, cancellation, restoration,
report exclusion, logging and multi-source reconciliation.

## Dependencies and decisions

- [001 — Persistent attendance store](001-persistentAttendanceStore.md) owns
  durable status, source reconciliation and audit evidence.
- Live WhatsApp validation is required because reaction accessibility metadata
  is an external DOM contract.
- 2026-09-01 live validation showed WhatsApp exposing cancelled polls with
  values such as `reaction 😢. View reactions` while not exposing the reacting
  participant in the static reaction metadata. The reaction itself is therefore
  the cancellation authority.

## Out of scope

- Inferring cancellation from free-form chat messages.
- Allowing arbitrary cancellation emojis.
- Automatically notifying members that a session was cancelled.

## Verification

- Automated coverage: `tests/test_cancelledSessions.py` and
  `tests/test_mainCli.py`
- Full regression suite and repository formatting/lint checks are required.
- Live validation must confirm the `😢` reaction is exposed on the poll message.

## Traceability

- Implementation: `main.py`, `src/organiseMyFooty/cli.py`,
  `src/attendanceConfig.py`, `src/whatsapp/pollDiscovery.py`,
  `src/whatsapp/pollRecordsBuilder.py`, `src/whatsapp/scraper.py`, and
  `src/whatsapp/store.py`
- Tests: `tests/test_cancelledSessions.py`, `tests/test_mainCli.py`
- Documentation: `documentation/cancelledSessions.md`
- Pull request: pending

## Change history

- 2026-08-03: delivery started on `feature/002-cancelledSessions`.
- 2026-08-31: replaced edited-title cancellation after confirming WhatsApp
  poll subjects cannot be changed.
- 2026-08-31: replaced deletion-based cancellation because the organiser
  cannot delete polls; cancellation moved to `😢` reactions.
- 2026-09-01: live DOM validation confirmed the crying-face reaction but not a
  reliable participant identity; participant configuration and `--emoji` were
  removed and any `😢` reaction now cancels the session.
