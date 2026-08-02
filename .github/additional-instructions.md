# Additional instructions for organiseMyFooty

## Project overview

`organiseMyFooty` is a Python 3.12 command-line application which collects
attendance responses from WhatsApp Web polls, persists attendance in SQLite,
and generates CSV, JSON and text reports.

The universal rules in `agent-instructions.md` take precedence. Requirements
work must also follow `requirementsManagement.md`, and repository placement
must follow `repositoryLayout.md`.

## Architecture

- `main.py` is the standalone compatibility entry point.
- `src/organiseMyFooty/cli.py` provides the installed `organiseMyFooty` console
  entry point declared in `pyproject.toml`.
- `src/attendanceConfig.py` owns runtime configuration and date-window logic.
- `src/whatsapp/` contains WhatsApp navigation, discovery, parsing, scraping,
  persistence and reporting modules.
- `src/whatsapp/store.py` is the only module which may issue attendance-store
  SQL or own SQLite schema migrations and reconciliation rules.
- `src/whatsapp/exporter.py` orchestrates collection and report generation.
- Core persistence, parsing, reconciliation and reporting behavior must remain
  testable without Playwright or a live WhatsApp session.

Keep the two CLI entry points behaviorally aligned while both remain supported.
Do not add new application behavior to only one entry point.

## Persistent state and generated output

- Durable attendance state lives at `output/attendance.sqlite3` by default.
- Generated reports and previews belong under the repository-level `output/`
  directory.
- SQLite databases, WAL/SHM files, browser profiles, generated reports and real
  attendance data must not be committed.
- The retired JSON poll-cache layer and raw `polls-YYYY-MM.csv` export must not
  be reintroduced; SQLite is the only durable attendance store.
- Browser profile data belongs in the configured user-data directory outside
  version control.

## Logging

The root entry point must call `setApplication()` before importing helper
modules which call `getLogger()`. Helper modules import `getLogger` from
`organiseMyProjects.logUtils` and must not initialize or replace logging.

Attendance logs can contain member display names. Treat log files as personal
data: do not commit them, include them in fixtures, or expose them in examples.

## Environment and installation

Conda is the preferred environment manager:

```bash
conda env create -f environment.yml
conda activate organise-my-footy
playwright install chromium
```

The project is packaged from `src/` using `pyproject.toml`. Runtime dependencies
belong in `pyproject.toml`; development-only dependencies belong in
`dev-requirements.txt` and the Conda environment definition.

Do not install dependencies automatically at runtime. A live collection run
requires Playwright's Chromium browser, but unit and integration tests must not.

## Development checks

Run focused tests while developing, followed by:

```bash
pytest -q
black --check main.py src tests
python tests/runLinter.py
git diff --check
```

The naming linter currently reports legacy diagnostics in existing files even
when it exits successfully. Do not introduce new diagnostics in changed code;
record any pre-existing diagnostics separately from the result of the tests and
formatter.

Use `tmp_path` for database, filesystem and migration tests. Tests must not
write to the real `output/`, user configuration, browser profile or log
directories.

Live-browser checks are manual and must be reported explicitly; never describe
them as passing when only mocked or unit-level behavior was exercised.

## Requirements workflow

Requirements live at stable paths under `project/requirements/features/`, with
durable prompts under `project/requirements/prompt/`. Update the requirement
record and the traceability matrix together whenever status changes.

Do not mark a requirement `Completed` until every acceptance criterion has
recorded evidence, maintained documentation is current, required architecture
decisions are linked, and any necessary live-browser validation is complete.
Requirement-owned living documentation belongs under
`documentation/<requirementName>/`.

## Documentation

The root `README.md` is the documentation entry point and must link to every
living guide. Requirement delivery records remain in `project/`; maintained
explanations of application behavior belong in `documentation/`.

Examples and fixtures must use fictional group names, member names and
attendance data.
