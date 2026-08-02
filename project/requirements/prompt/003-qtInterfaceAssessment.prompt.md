# Agent prompt — 003 Qt interface assessment

Complete [requirement 003 — Qt interface assessment](../features/003-qtInterfaceAssessment.md).

The requirement is authoritative. Read it completely before beginning, and
also follow `AGENTS.md`, `.github/repositoryLayout.md` and all other applicable
repository instructions. Inspect the actual CLI, scraping, persistence,
reporting and packaging code rather than relying on stale source-layout
documentation.

## Working process

1. Read `AGENTS.md` completely before planning or making changes.
2. Read and apply every standards and repository-definition file referenced by
   `AGENTS.md`, including `.github/agent-instructions.md`,
   `.github/additional-instructions.md` when it exists, and
   `.github/repositoryLayout.md`.
3. Inspect `git status` and preserve any existing user changes. Do not overwrite
   or discard unrelated work.
4. Before assessment changes, create and switch to the requirement branch:
   `feature/003-qtInterfaceAssessment`.
5. Confirm the active branch before editing. If that branch already exists,
   switch to it rather than creating a differently named branch.
6. Keep all assessment, ADR, follow-on requirements and documentation for this
   requirement on that branch.
7. Re-read the applicable standards before adding or moving repository content
   or when a decision affects architecture, naming, safety or testing.

## Objective

Determine whether a Qt desktop interface would materially improve the current
attendance workflow, identify the smallest useful interface if appropriate,
and record a supported build, defer or reject decision. This requirement is an
assessment, not authorization to implement a production GUI.

## Required approach

1. Describe the current end-to-end user workflows, including configuration,
   WhatsApp authentication, scanning, progress, failures, report generation and
   attendance-history queries.
2. Identify likely users, their recurring tasks and the specific usability
   problems a desktop interface would address.
3. Compare a Qt interface with focused CLI improvements. Include development,
   testing, packaging, distribution and maintenance costs.
4. Evaluate appropriate supported Qt bindings and operating-system implications
   using current primary documentation where version-sensitive facts matter.
5. Define the smallest useful interface: screens, inputs, actions, progress,
   cancellation, errors and results. Avoid speculative secondary features.
6. Explain how Playwright work would run without blocking the Qt event loop and
   how progress, cancellation, errors and cleanup would cross the worker/UI
   boundary.
7. Define an architecture in which domain, persistence, scraping and reporting
   remain independent of Qt and reusable from the CLI.
8. Account for the session/member queries and persistent store described by
   requirement 001, without assuming unfinished functionality already exists.
9. Assess accessibility, logging, recovery, authentication/profile handling and
   safe-by-default execution.
10. Record an architecture decision under `project/adr/` with an explicit build,
    defer or reject outcome, alternatives, rationale and consequences.
11. If the decision is to build, create separately numbered follow-on
    requirements for implementation slices. Do not implement those slices as
    part of this assessment.

## Deliverables

- A maintained assessment document in the repository's appropriate project or
  documentation location.
- A concise minimum-interface definition or a recommendation not to build it.
- A technical boundary and background-work proposal.
- An architecture decision record.
- Separately scoped implementation requirements only if the decision is to
  proceed.

## Constraints

- Do not add a production Qt dependency or GUI code for this assessment.
- Do not weaken or replace the supported CLI.
- Keep factual claims evidence-based and cite primary sources for current Qt,
  packaging or platform details.
- Clearly distinguish facts observed in the repository, external facts and
  design recommendations.
- Avoid unrelated repository changes.

## Verification

Check every deliverable and acceptance criterion in requirement 003. Validate
all internal links and requirement numbering. If repository code is unchanged,
code tests are not required; run relevant documentation or formatting checks if
available and report what was checked.

## Completion report

State the decision first, then summarize user needs, minimum scope, architecture,
background execution, packaging implications, alternatives, ADR location,
follow-on requirements and unresolved risks.
