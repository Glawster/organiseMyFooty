# Agent prompt — 002 cancelled sessions

Implement [requirement 002 — Cancelled sessions](../features/002-cancelledSessions.md).

The requirement is authoritative. Read it completely before changing code, and
also follow `AGENTS.md` and all repository instructions it references. Inspect
the current parsing, session identity, persistence, reporting and test code
before deciding where changes belong.

## Working process

1. Read `AGENTS.md` completely before planning or making changes.
2. Read and apply every standards and repository-definition file referenced by
   `AGENTS.md`, including `.github/agent-instructions.md`,
   `.github/additional-instructions.md` when it exists, and
   `.github/repositoryLayout.md`.
3. Inspect `git status` and preserve any existing user changes. Do not overwrite
   or discard unrelated work.
4. Before development changes, create and switch to the requirement branch:
   `feature/002-cancelledSessions`.
5. Confirm the active branch before editing. If that branch already exists,
   switch to it rather than creating a differently named branch.
6. Keep all implementation, tests and documentation for this requirement on
   that branch.
7. Re-read the applicable standards before adding or moving repository content
   or when an implementation decision affects architecture, naming, safety or
   testing.

## Objective

Recognise the case-insensitive `(cancelled)` marker in WhatsApp poll titles,
preserve the original source title, retain the logical session as cancelled,
and exclude it from attendance processing and totals.

## Required approach

1. Locate the single domain boundary responsible for interpreting session
   titles and status. Do not scatter cancellation checks through CLI, browser
   and report code.
2. Add an explicit session status representation suitable for both active and
   cancelled sessions.
3. Detect `(cancelled)` case-insensitively with appropriate whitespace and
   placement tolerance while avoiding false positives.
4. Preserve the source title exactly as captured. If a normalized title is
   needed for matching or display, store or derive it separately.
5. Reconcile an active session becoming cancelled as an update to the existing
   logical session, not a new session. Likewise, restore the same session when
   the marker is removed.
6. Exclude cancelled sessions from attendance associations, member attendance
   totals, session totals, attendance report columns and summaries.
7. Keep cancelled sessions queryable and expose their cancelled status wherever
   session metadata is intentionally displayed.
8. Log cancellation and restoration with enough identity information to audit
   the change.
9. Respect multi-source provenance and conflict-resolution behaviour from
   requirement 001. Do not let one source observation silently erase another.
10. Update user and developer documentation describing cancelled-session
    behaviour.

## Implementation constraints

- Keep parsing and status logic independent of Playwright and user interfaces.
- Do not discard a session merely because it is cancelled.
- Do not mutate or lose the original source title.
- Do not count voters from cancelled sessions as attendees.
- Avoid unrelated refactoring unless required for a safe implementation.
- If requirement 001 is not yet implemented, design the change so the current
  model remains functional and the status representation can migrate cleanly to
  its persistent session model. State any temporary compatibility decisions.

## Verification

Add focused automated tests for all acceptance criteria, including marker case,
position and whitespace, false positives, original-title preservation,
active/cancelled transitions, identity stability, logging, report exclusion and
multi-source conflict behaviour where supported.

Run the focused tests, complete test suite and applicable formatting/lint
checks. Tests must not require a live WhatsApp session. Report the commands run
and any checks that could not be executed.

## Completion report

Summarize the domain-model, parsing, reconciliation, reporting, logging,
documentation and test changes. Explicitly show that cancellation does not
duplicate or delete the logical session and does not affect attendance totals.
