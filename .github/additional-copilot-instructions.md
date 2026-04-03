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
├── testAttendanceConfig.py  # unit tests for attendanceConfig
└── testWhatsappAttendance.py # unit tests for non-browser helpers
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
pytest tests/testAttendanceConfig.py -v
```

Tests for browser automation are **not** included — Playwright requires a live
browser and WhatsApp login. Restrict unit tests to pure-Python helpers.

---

## Key Conventions

### Selectors

`whatsappSelectors.py` holds all CSS / aria / text selectors for WhatsApp Web. Update
selectors there first when WhatsApp changes its UI — never scatter selector
strings across other modules.

### Dry-run flag

The CLI exposes `--dry-run` (not `--confirm`) because it aligns with the
WhatsApp export context where "inspect without writing" is the expected safe
default phrasing. The `dryRun` boolean is passed through `RuntimeConfig`.

### Logging

The module falls back to `stdlib logging` when `organiseMyProjects.logUtils` is
not installed. New code should follow the same `try / except` pattern used in
`whatsappAttendance.py` so the tool works stand-alone.

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
