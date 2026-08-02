<!-- deployed from Glawster/organiseMyProjects release 0.3 -- do not edit directly -->
# Requirements management

This guide defines the shared process for capturing, agreeing, delivering and
maintaining requirements. It incorporates the practices established while
developing fmparser: small outcome-focused records, permanent identifiers and
paths, an explicit status index, requirement-owned documentation, and evidence
that connects each requirement to its implementation and tests.

The process is deliberately lightweight. A requirement should contain enough
information to make the intended outcome and proof of completion unambiguous,
without becoming a second implementation plan.

## Principles

- Describe the user or system outcome before proposing an implementation.
- Give every requirement a permanent identifier and stable file path.
- Keep one authoritative requirement record; link to it instead of copying it.
- Make scope, acceptance criteria and exclusions explicit before development.
- Keep requirements small enough to implement and verify independently.
- Trace implementation, tests, documentation and decisions back to the
  requirement.
- Treat a changed requirement as a controlled change, not an informal edit.
- Complete a requirement only when objective evidence demonstrates every
  acceptance criterion.

## Authoritative locations

Requirements are project-management records and follow
[`repositoryLayout.md`](repositoryLayout.md):

```text
project/requirements/
├── README.md
├── prompt/
│   ├── adapters/
│   │   ├── codex.md
│   │   └── copilot.md
│   ├── 003a-viewManagement.prompt.md
│   └── 003b-viewManagement.prompt.md
├── templates/
│   └── requirement.md
└── features/
    └── 003-viewManagement.md
```

- `project/requirements/README.md` is the requirements index and records the
  next available number, workflow state and project-specific conventions.
- `project/requirements/features/` contains every requirement at every
  lifecycle stage. Files are not moved when their status changes.
- `project/requirements/prompt/` contains one or more durable prompts per
  requirement in a flat layout, plus reusable agent adapters.
- `project/requirements/templates/` contains the project's approved templates.
- `documentation/<requirementName>/` contains living documentation owned by a
  single requirement. Cross-cutting documentation remains directly under
  `documentation/`.
- Significant architectural or project-shaping decisions belong in
  `project/adr/` and are linked from the affected requirements.

## Identification and naming

Allocate the next number from `project/requirements/README.md` when a
requirement record is created:

```text
ddd-conciseCamelCaseName.md
```

The three-digit number is sequential, permanent and never reused, including
when a requirement is rejected or retired. The filename and identifier do not
change after allocation. Update the next available number in the same change
that creates the record so concurrent work cannot allocate it twice.
The identifier must also appear inside the requirement record.

Use the numeric identifier in the record heading and in relevant issue, branch,
commit, pull-request, test and documentation references. Repository-specific
prefixes may be used in external tools when necessary, but they are not part of
the requirement filename.

When a requirement has one prompt, its filename matches the requirement with
`.prompt` inserted before the Markdown extension. When it has multiple prompts,
append sequential lowercase letters to the requirement number and give each
prompt the same requirement name:

```text
project/requirements/features/003-viewManagement.md
project/requirements/prompt/003-viewManagement.prompt.md
project/requirements/prompt/003a-viewManagement.prompt.md
project/requirements/prompt/003b-viewManagement.prompt.md
```

Use the unsuffixed form only while there is a single prompt. For multiple
prompts, `a` identifies the primary prompt and subsequent prompts use `b`, `c`
and so on. Never reuse a suffix. If a second prompt is added later, rename the
existing unsuffixed prompt to the `a` form while preserving its version-control
history, create the `b` prompt, and update all references in the same change.
The suffixed identities are stable after allocation.

Living documentation owned by one requirement belongs in a directory named
after the requirement without its number or extension, for example
`documentation/viewManagement/`. General documentation spanning multiple
requirements remains directly under the owning `documentation/` directory.

## Requirement record

Each requirement should use this minimum structure:

```markdown
# 003: View management

## Status

ToDo

## Outcome

As a <user or system>, I need <capability> so that <measurable benefit>.

## Context

Why this is needed, including the current problem and relevant constraints.

## Scope

- Behaviour included in this requirement.

## Out of scope

- Closely related behaviour deliberately excluded.

## Acceptance criteria

1. Given <starting condition>, when <action>, then <observable result>.
2. Failure and boundary behaviour is explicitly defined.

## Dependencies and decisions

- Related requirements, ADRs, external dependencies or `None`.

## Verification

- Planned and completed tests, review steps or other evidence.

## Traceability

- Implementation: pending
- Tests: pending
- Documentation: pending
- Pull request: pending
- Agent runs: pending or `None`

## Change history

- YYYY-MM-DD: created — reason or source.
```

Add non-functional constraints such as performance, security, privacy,
compatibility, accessibility or data migration only when they apply. State
measurable thresholds rather than words such as "fast", "secure" or "easy".

## Writing good requirements

The outcome states the need and value, not the chosen code structure. Acceptance
criteria define externally observable behaviour and form the basis of tests.
Each criterion should be necessary, unambiguous and independently verifiable.

During refinement, check that the requirement:

- has one clear outcome and an identified user, stakeholder or system;
- defines normal, boundary and relevant failure behaviour;
- separates included work from tempting adjacent work;
- identifies dependencies, risks and assumptions;
- does not conflict with an approved requirement or ADR;
- can be demonstrated by tests or another named verification method; and
- is small enough to review without hiding unrelated outcomes.

Split a record when its parts have different stakeholders, priorities,
dependencies or completion evidence. Link the resulting requirements rather
than creating a parent record whose completion is ambiguous.

## Workflow

The index in `project/requirements/README.md` contains a traceability matrix.
Each requirement has one row whose `Status` is `ToDo`, `InProgress` or
`Completed`. These states mean, respectively: captured or ready but not yet
started; accepted and actively being delivered; or verified as delivered (or
closed with a visible disposition such as rejected, superseded or retired).

Use this operating process:

### 1. Capture

Search the index and existing records for duplicates. Allocate the next number,
create the record and its primary prompt from the approved templates, add the
matrix row with status `ToDo`, and record the requirement's origin and purpose.
Early uncertainty should be written as an assumption or open question, not
silently resolved.

### 2. Refine and agree

Review the outcome, scope, exclusions, acceptance criteria, dependencies and
verification approach with the relevant stakeholder. Resolve contradictions or
record a decision in an ADR. A requirement is ready for implementation when its
criteria can be tested and no material product decision is left implicit.

Record who or what approved the requirement and the approval date when formal
approval is needed. For small projects, review acceptance in the pull request
may be sufficient if the decision remains traceable.

### 3. Start delivery

Set the index entry to `InProgress` and update the record's status in the same
change. Before coding, map each acceptance criterion to planned test
coverage or another verification method. Link any implementation plan, issue or
ADR; do not turn the requirement itself into a task-by-task coding diary.

### 4. Implement and maintain traceability

Keep the change focused on the agreed scope. Reference the requirement from the
implementation and tests through meaningful names, comments only where useful,
commit or pull-request metadata, and links in the Traceability section. Update
the owned living documentation as behaviour becomes stable.

If delivery exposes a material ambiguity or changes an agreed outcome, stop and
apply the change-control process below before continuing. Implementation detail
that preserves the agreed outcome does not require a requirement revision.

### 5. Verify and complete

Verify every acceptance criterion and record the evidence. Evidence normally
includes automated test paths and results, plus manual or stakeholder validation
where automated tests cannot prove the outcome. Confirm that relevant living
documentation and ADRs are current and that no temporary assumption remains.

Set the index entry to `Completed` and update the record only after all criteria
pass. The completion change should include the final implementation, test,
documentation and pull-request links. Keep the requirement file in
`features/`; its stable path remains valid for future references.

## Requirements and architecture decisions

A requirement defines the outcome and the evidence needed to accept it. An
architecture decision record (ADR) explains a consequential implementation or
project-shaping choice, the alternatives considered and the consequences of the
selected approach. Keep these responsibilities separate so a later technical
decision can change without rewriting the underlying need.

Create or update an ADR when satisfying a requirement introduces a decision
that is difficult or costly to reverse, affects several requirements or
components, changes a public interface or data model, selects a significant
dependency, or materially affects security, privacy, performance or operations.
Routine local implementation choices do not need ADRs.

Handle the relationship as follows:

1. identify the decision during refinement or implementation and link a
   proposed ADR from `Dependencies and decisions`;
2. record the context, viable options, decision, rationale, consequences and
   status in `project/adr/` according to `project/adr/README.md`;
3. accept the ADR before work that depends on the decision becomes difficult to
   unwind;
4. link the requirement from the ADR and the accepted ADR from every affected
   requirement; and
5. verify both the requirement's observable acceptance criteria and any
   constraints introduced by the ADR.

One ADR may support several requirements and one requirement may depend on
several ADRs. Do not duplicate the ADR rationale in each requirement. Do not
hide a user-visible outcome or acceptance criterion only in an ADR. If an ADR
changes agreed scope or observable behaviour, apply requirement change control
and obtain the necessary agreement rather than treating it as a purely
technical update. Supersede an obsolete ADR through the ADR process while
retaining its stable link and history.

## Prompts and agent-assisted delivery

The requirement is the source of truth for every agent. A prompt assigns work;
it does not redefine the requirement. This distinction allows Codex, GitHub
Copilot and other coding or review agents to work from the same agreed outcome
without maintaining separate versions of the scope.

### Canonical prompt and agent adapters

Write each task brief from the authoritative requirement, then add only the
minimum agent-specific wrapper needed for the selected tool. Multiple prompts
must partition roles or scope clearly and must not redefine the requirement or
allow their acceptance criteria to drift apart.

Store a single prompt at:

```text
project/requirements/prompt/<ddd-requirementName>.prompt.md
```

If separate prompts are needed, store them as:

```text
project/requirements/prompt/<ddd>a-<requirementName>.prompt.md
project/requirements/prompt/<ddd>b-<requirementName>.prompt.md
```

For example, separate implementation and verification prompts for
`003-viewManagement.md` are `003a-viewManagement.prompt.md` and
`003b-viewManagement.prompt.md`. Keep reusable tool-specific instructions in
`project/requirements/prompt/adapters/<agent>.md` and combine the applicable
adapter with the relevant prompt when starting a run. Do not create an
additional prompt merely to change the agent name.

Prompt paths are durable delivery records. Apart from converting a single
unsuffixed prompt to the required multi-prompt naming, do not move them when the
requirement is completed or another prompt is added. Update a prompt in place
before it is issued. After it has been used, preserve its issued meaning in
version control; a material revision must be recorded in the requirement's
change history and Agent runs traceability.

The canonical brief contains:

- the requirement identifier and repository-relative path;
- the requested role, such as refine, implement, test, review or document;
- the exact acceptance criteria assigned to the run;
- relevant scope, exclusions, constraints, dependencies and ADR links;
- the files or component boundaries the agent may change;
- required verification commands and expected evidence; and
- the required handoff format, including changed files, checks run, results,
  assumptions and unresolved items.

An agent adapter may add tool syntax, available capabilities, response format or
an instruction to inspect a particular repository entry point. It must not
weaken acceptance criteria, expand authority or silently make product decisions.
For example, repository agents should be told to follow the nearest `AGENTS.md`
and its linked instructions; GitHub Copilot should follow
`.github/copilot-instructions.md`; and agents operating outside the repository
must receive the applicable instruction text or a stable link to it.

Use this prompt pattern:

```text
Requirement: 003 — project/requirements/features/003-viewManagement.md
Role: implement

Read the requirement and applicable repository instructions before changing
anything. Deliver acceptance criteria 1–3 only. Preserve the stated exclusions
and follow ADR-002. Limit changes to <paths/components>.

Verify with:
- <automated command>
- <manual or review check>

If the requirement is ambiguous or the outcome must change, stop and report the
decision needed. Do not infer new scope.

Handoff with:
- files changed and why;
- acceptance criterion-to-evidence mapping;
- commands run and results;
- assumptions, risks and unresolved items.
```

### Choosing and separating agent roles

Assign agents according to the work they can independently verify:

- a refinement agent may identify ambiguity, duplicates, risks and proposed
  acceptance criteria, but a stakeholder still agrees the outcome;
- an implementation agent changes only the assigned scope and supplies test
  evidence;
- a test or verification agent checks criteria against observable behaviour and
  should not merely repeat the implementation agent's conclusions;
- a review agent looks for regressions, missing criteria, unsafe assumptions and
  conflicts with repository guidance; and
- a documentation agent updates maintained explanations from the delivered
  behaviour, without inventing behaviour that was not verified.

Where multiple agents work concurrently, give them non-overlapping ownership or
isolated branches/worktrees and name one coordinating run. The coordinator
reconciles results against the requirement. Agents must not overwrite another
run's changes, claim shared files implicitly or treat a partial handoff as proof
that the complete requirement is delivered.

### Context, handoff and traceability

Prefer directing a repository-aware agent to the stable requirement path over
pasting a copy that may become stale. If an agent cannot access the repository,
provide a controlled snapshot and identify its commit or date. Regenerate the
prompt after a material requirement change and tell active agents that their
previous brief is superseded.

Record material agent use under `Agent runs` in the requirement's Traceability
section. For each run, capture the date, agent or tool, role, assigned criteria,
and a durable result reference such as a pull request, issue, commit or saved
handoff. Record the prompt itself when it contains important constraints not
already visible in the requirement. Do not commit secrets, credentials,
sensitive user data, transient chat transcripts or vendor-specific internal
reasoning.

Agent output is proposed work and evidence, not automatic approval. A human or
designated coordinating process reviews the diff, runs the relevant checks and
maps the final evidence to every acceptance criterion before completion.

## Change control

Requirements may evolve, but their history and delivered meaning must remain
clear.

- Before implementation, refine the existing record and add a dated reason to
  its Change history.
- During implementation, reassess scope, acceptance criteria, tests, estimates,
  dependencies and documentation before accepting a material change.
- After completion, do not rewrite history to make new behaviour appear part of
  the original delivery. Create a new linked requirement for a new outcome.
- Correcting a typo or clarifying wording that does not alter meaning may be
  made in place and noted when the distinction could matter later.
- When superseding, rejecting or retiring a requirement, keep its file and
  identifier, record the reason and related replacement, and place it in the
  index's `Completed` section with its disposition visible.

Never recycle a cancelled identifier, rename a requirement to reflect its
replacement, or move completed records to an archive directory.

## Review checklist

Before moving a requirement to `InProgress`, confirm:

- the outcome, value, scope and exclusions are clear;
- acceptance criteria are observable and testable;
- dependencies, assumptions, risks and decisions are linked;
- a verification approach exists for every criterion; and
- the record and index agree.

Before moving it to `Completed`, confirm:

- every acceptance criterion has recorded evidence;
- tests cover normal, boundary and relevant failure behaviour;
- implementation, test, documentation, ADR and pull-request links are current;
- maintained documentation describes the delivered behaviour;
- no unresolved item is being hidden by completion; and
- the record and index are updated together.

## Requirements index

The traceability matrix must use these columns in this order:

| Column | Purpose |
| --- | --- |
| `Req ID` | Permanent zero-padded requirement identifier. |
| `Requirement` | Link to the authoritative requirement record. |
| `Description` | Concise statement of what the requirement is about. |
| `Status` | Current lifecycle state: `ToDo`, `InProgress` or `Completed`. |
| `Agent Prompt` | Links to the requirement's durable prompt or prompts. |
| `Architecture Decisions` | Links to supporting ADRs, `Pending`, or `Not required`. |

Keep descriptions short enough for the matrix to remain scannable; detailed
scope belongs in the linked requirement. Every requirement links to at least
one prompt; when there are several, list them in suffix order. A requirement
may link to zero or more ADRs. ADRs link back to the requirements they support.
The requirement record remains authoritative for scope and status.

Example:

```markdown
# Requirements

Next available number: 006

| Req ID | Requirement | Description | Status | Agent Prompt | Architecture Decisions |
| --- | --- | --- | --- | --- | --- |
| 003 | [Manage views](features/003-viewManagement.md) | Create and manage saved views. | Completed | [Implement](prompt/003a-viewManagement.prompt.md), [verify](prompt/003b-viewManagement.prompt.md) | [ADR-002](../adr/002-viewStorage.md) |
| 004 | [Export parsed messages](features/004-exportParsedMessages.md) | Export parsed messages in supported formats. | ToDo | [Prompt](prompt/004-exportParsedMessages.prompt.md) | Pending |
| 005 | [Report malformed input](features/005-reportMalformedInput.md) | Explain malformed input without losing valid results. | InProgress | [Prompt](prompt/005-reportMalformedInput.prompt.md) | Not required |
```

The index is a navigation and status view, not a substitute for the individual
records. Keep detailed scope, evidence and history in the requirement file.
