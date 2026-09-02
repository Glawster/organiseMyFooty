# organiseMyFooty

Python 3.12 command-line application which collects attendance responses from
WhatsApp Web polls, persists them in SQLite, and writes CSV, JSON and text
reports.

## Documentation

This file is the documentation entry point. Living guides:

- [Repository layout](documentation/repositoryLayout.md)
- [Requirements management](documentation/requirementsManagement.md)
- [Testing process](documentation/testingProcess.md)
- [Release process](documentation/howToRelease.md)
- [Persistent attendance store](documentation/persistentAttendanceStore/README.md)
- [Cancelled sessions](documentation/cancelledSessions/README.md)
- [Project records](project/README.md)
- [Requirements index](project/requirements/README.md)
- [Agent instructions](.github/agent-instructions.md)
- [Project-specific instructions](.github/additional-instructions.md)
- [Copilot instructions](.github/copilot-instructions.md)

## Install

Conda is the preferred environment manager:

```bash
conda env create -f environment.yml
conda activate organise-my-footy
playwright install chromium
```

This project expects `organiseMyFooty.logUtils` to be available in the same
Python environment for centralized logging.

A live collection run needs Playwright's Chromium browser. Unit and integration
tests must not.

## Usage

Run from the repository root. All three entry points must stay behaviourally
aligned:

```bash
python main.py --group "My Footy Group" --month 2026-03
python -m organiseMyFooty --group "My Footy Group" --month 2026-03
organiseMyFooty --group "My Footy Group" --month 2026-03
```

Omit `--confirm` for a dry-run. The browser may open and polls may be inspected,
but reports are not written. Pass `--confirm` to persist attendance and write
exports:

```bash
python main.py --group "My Footy Group" --month 2026-03 --confirm
```

Groups from successful runs accumulate in
`~/.config/organiseMyFooty/state.json`. Run without `--group` to scan every
configured group. Repeat `--group` to scan a selected set:

```bash
python main.py \
  --group "My Footy Group" \
  --group "My Other Footy Group" \
  --month 2026-03
```

Inspect stored attendance for the selected month without scanning:

```bash
python main.py --group "My Footy Group" --month 2026-03 --view
```

Print the resolved runtime configuration and exit:

```bash
python main.py --group "My Footy Group" --month 2026-03 --config
```

Use `--help` at the entry point for the current options.

## CLI options

| Option | Description |
| --- | --- |
| `--group` | Exact WhatsApp group name; repeat to select multiple groups; omit to scan all configured groups |
| `--month` | Target month as `YYYY-MM`, a month name, or a number; defaults to the previous calendar month |
| `--confirm` | Write the attendance store and reports; omit to run in dry-run mode |
| `--override` | Continue past captured polls to the start of the month two calendar months ago |
| `--scan-since YYYY-MM-DD` | Inclusive history cutoff; requires `--override` |
| `--view` | Inspect stored attendance for the selected month without browser scanning |
| `--config` | Print the resolved runtime configuration and exit |
| `--debug` | Enable debug logging |

Polls are filtered to sessions whose derived session date falls inside the
selected month window. The SQLite attendance store is opened by default; there
is no cache opt-in flag.

`--override` continues past previously captured polls but stops at the start of
the month two calendar months before the current local month.
`--override --scan-since YYYY-MM-DD` replaces that horizon with an inclusive
date. A future or invalid date, or `--scan-since` without `--override`, is
rejected before the browser starts.

## Output

Generated files belong under the repository-level `output/` directory.

| Path | Description |
| --- | --- |
| `output/attendance.sqlite3` | Durable attendance store |
| `output/attendanceSummary-YYYY-MM.csv` | Aggregated summary: `name`, `yesCount`, `noCount`, `totalVotes`, `pollsResponded` |
| `output/attendanceReport-YYYY-MM.csv` | Session-by-session matrix for the selected month |
| `output/socialMediaSummary-YYYY-MM.txt` | Paste-ready monthly attendance summary |
| `output/exportPreview-YYYY-MM.json` | JSON preview of the report datasets |

SQLite databases, WAL/SHM files, browser profiles, generated reports, logs and
real attendance data must not be committed. Log files can contain member display
names and should be treated as personal data.

## First-run login

The Playwright browser profile is empty on the first run, so WhatsApp Web shows
a QR-code login screen. The collection browser is shown, not headless.

1. Start a collection run so the browser window is visible.
2. Open WhatsApp on your phone → **Linked devices** → **Link a device**.
3. Scan the QR code shown in the browser window.
4. Wait for chats to load; the tool continues automatically.

The session is stored in
`~/.local/share/organiseMyWhatsApp/profile`. Login is only required again if
that profile is removed.

## Source layout

- `main.py` — standalone compatibility entry point
- `src/organiseMyFooty/cli.py` — installed `organiseMyFooty` console entry point
- `src/attendanceConfig.py` — runtime configuration and date-window logic
- `src/whatsapp/exporter.py` — collection and report orchestration
- `src/whatsapp/scraper.py` — WhatsApp browser collection workflow
- `src/whatsapp/store.py` — SQLite schema, reconciliation and queries
- `src/whatsapp/selectors.py` — centralised WhatsApp Web selectors

`src/whatsapp/store.py` is the only module that may issue attendance-store SQL
or own schema migrations. Core persistence, parsing, reconciliation and
reporting remain testable without Playwright.

## Development checks

Activate the Conda environment, then run focused tests while developing,
followed by:

```bash
pytest -q
black --check main.py src tests
python tests/runLinter.py
git diff --check
```

The naming linter may report legacy diagnostics in existing files even when it
exits successfully. Do not introduce new diagnostics in changed code.

Tests must use `tmp_path` for database, filesystem and migration work and must
not write to the real `output/`, user configuration, browser profile or log
directories. Live-browser checks are manual.

## Notes

- WhatsApp Web selectors live in `src/whatsapp/selectors.py` and may need
  updating if WhatsApp changes its UI.
- Cancelled session polls are recognised from `(cancelled)` in the poll title
  and are excluded from attendance totals; see
  [Cancelled sessions](documentation/cancelledSessions/README.md).
- Attendance backup and scan-boundary behaviour are described in
  [Persistent attendance store](documentation/persistentAttendanceStore/README.md).
