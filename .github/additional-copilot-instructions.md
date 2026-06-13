# organiseMyFooty — Project-Specific Copilot Instructions

These instructions extend the master guidelines in `copilot-instructions.md`.

---

## Project Overview

`organiseMyFooty` automates the collection of footy training and match attendance
from WhatsApp group polls. It uses Playwright to drive WhatsApp Web, extracts poll
voter names, and writes CSV summaries.

---

## Source Layout

```
src/
├── __init__.py              # package init
├── attendanceConfig.py      # config dataclasses, month helpers, CSV writer
├── exportAttendance.py      # CLI entry point (argparse → RuntimeConfig → exporter)
├── whatsappSelectors.py     # centralised WhatsApp Web CSS/aria selectors
└── whatsappAttendance.py    # browser automation + export pipeline
tests/
├── conftest.py              # adds src/ to sys.path
├── guiNamingLinter.py       # GUI naming convention linter
├── runLinter.py             # CLI entry for the linter
├── test_AttendanceConfig.py  # unit tests for attendanceConfig
└── test_WhatsappAttendance.py # unit tests for non-browser helpers
```

---

## Running the tool

Source files import each other without the `src.` prefix, so run from `src/`:

```bash
cd src
python exportAttendance.py --group "My Footy Group" --month 2026-03 --dry-run
```

---

## Testing

```bash
pytest            # run all tests
pytest tests/test_AttendanceConfig.py -v
pytest tests/test_WhatsappAttendance.py -v
```

Tests for browser automation are **not** included — Playwright requires a live
browser and WhatsApp login. Restrict unit tests to pure-Python helpers.

---

## Key Conventions

### Selectors

`whatsappSelectors.py` holds all CSS / aria / text selectors for WhatsApp Web. Update
selectors there first when WhatsApp changes its UI — never scatter selector
strings across other modules.

### Confirm / dry-run flag

The CLI uses `--confirm` (safe-by-default pattern). When `--confirm` is **not** passed the
tool runs in dry-run mode — it opens the browser and inspects polls but writes no files.
Pass `--confirm` to execute the export. The `dryRun` boolean (`not args.confirm`) is stored
in `RuntimeConfig` and threaded through to `AttendanceExporter`.

### Logging

Use `organiseMyProjects.logUtils` directly for centralized logging. Do not add
new stdlib logging fallbacks in this repository; tests should stub the
dependency when needed.

### Output files

All writes go through `attendanceConfig.writeCsv()`. Do not open CSV files
directly in `whatsappAttendance.py` or `exportAttendance.py`.

---

## Dependencies

- `playwright` — browser automation (listed in `requirements.txt`)
- `pytest`, `black`, `pre-commit` — dev tools (listed in `dev-requirements.txt`)

Install dev deps:

```bash
pip install -r dev-requirements.txt
playwright install chromium
```
