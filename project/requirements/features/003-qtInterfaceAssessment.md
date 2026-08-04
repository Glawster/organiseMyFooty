# 003 — Qt interface assessment

## Status

ToDo

## Summary

Assess whether a Qt desktop interface would improve the attendance workflow and
define the smallest useful interface before committing to implementation.

## Context

The application currently exposes its collection, configuration and reporting
workflows through a command-line interface. A desktop interface may make common
operations and attendance queries more accessible, but it would add packaging,
state-management and UI-maintenance costs. The decision must be based on a
defined user workflow rather than the availability of a GUI framework.

## Requirements

1. Document the users and workflows that would benefit from a desktop
   interface.
2. Identify the smallest useful Qt interface, including the minimum screens,
   actions, inputs, progress information and results.
3. Compare the proposed interface with retaining or improving the CLI.
4. Assess supported operating systems, Python and Qt bindings, installation,
   packaging and distribution implications.
5. Assess how Playwright browser interaction and authentication would be
   launched, monitored and cancelled from the interface.
6. Define how long-running scans report progress without blocking the UI event
   loop.
7. Keep domain, persistence, scraping and reporting logic independent of Qt and
   fully usable by the CLI.
8. Limit the UI layer to input collection, workflow orchestration, progress and
   presentation.
9. Identify accessibility, error-reporting, logging and recovery requirements.
10. Consider how users would browse sessions and member attendance history from
    the persistent attendance store.
11. Record the recommendation and material trade-offs in an architecture
    decision record before implementation begins.

## Deliverables

1. A concise workflow and user-needs assessment.
2. A proposed minimum interface scope or a recommendation not to build one.
3. A technical approach covering UI boundaries, background work and packaging.
4. An architecture decision record documenting the outcome.
5. Follow-on implementation requirements if a Qt interface is approved.

## Acceptance criteria

1. The assessment reaches an explicit build, defer or reject recommendation.
2. The recommendation is supported by user workflow and maintenance-cost
   evidence.
3. Any proposed architecture keeps core behaviour testable without Qt.
4. The minimum interface scope is sufficiently defined to estimate and split
   into implementation requirements.
5. No production Qt dependency is introduced solely to complete the assessment.

## Dependencies

The assessment should account for the query and storage capabilities described
by [001 — Persistent attendance store](001-persistentAttendanceStore.md).

## Out of scope

- Implementing the Qt interface.
- Selecting visual branding or producing final UI artwork.
- Replacing the supported CLI.
