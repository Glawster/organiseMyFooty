# organiseMyFooty

Python tool for exporting WhatsApp poll attendance from WhatsApp Web.

The supported runtime is Python 3.12.

Automates collection of footy training/match poll responses from a WhatsApp group,
exporting voter names and attendance counts to CSV files.

## Documentation

- [Project records](project/README.md)
- [Copilot instructions](.github/copilot-instructions.md)
- [Project-specific instructions](.github/additional-instructions.md)
- [Repository layout](documentation/repositoryLayout.md)
- [Requirements management](documentation/requirementsManagement.md)
- [Persistent attendance store](documentation/persistentAttendanceStore/README.md)
- [Cancelled sessions](documentation/cancelledSessions/README.md)

## Source files

- `main.py` — standalone compatibility entry point
- `src/organiseMyFooty/cli.py` — installed CLI entry point
- `src/whatsapp/exporter.py` — collection and report orchestration
- `src/whatsapp/scraper.py` — WhatsApp browser collection workflow
- `src/whatsapp/store.py` — SQLite schema, reconciliation and queries
- `src/attendanceConfig.py` — config helpers and month/date resolution
- `src/whatsapp/selectors.py` — centralised WhatsApp Web selectors

## Install

Conda is the preferred environment manager:

```bash
conda env create -f environment.yml
conda activate organise-my-footy
playwright install chromium
```

This project expects `organiseMyFooty.logUtils` to be available in the same
Python environment for centralized logging.

## Development checks

Run the automated checks from the `py312` Conda environment:

```bash
conda run -n py312 pytest -q
conda run -n py312 black --check main.py src tests
conda run -n py312 ruff check main.py src tests
conda run -n py312 python tests/runLinter.py
git diff --check
```

## First-run login

On the very first run the browser profile is empty, so WhatsApp Web will show
a QR-code login screen inside the Playwright-controlled browser window.

1. Run without `--headless` (the default) so the browser window is visible.
2. Open WhatsApp on your phone → **Linked devices** → **Link a device**.
3. Scan the QR code shown in the browser window.
4. Wait for your chats to load, then the tool will continue automatically.

The session is persisted in `--user-data-dir`, so you only need to do this
once. If the default 120-second window is not enough to scan the code, pass
a longer timeout:

```bash
python main.py --group "My Footy Group" --month 2026-03
```

## Usage

Run from the `src/` directory (or add `src/` to `PYTHONPATH`):

```bash
python main.py \
  --group "My Footy Group" \
  --month 2026-03
```

You can also run it as a module from the repository root:

```bash
python -m organiseMyFooty \
  --group "My Footy Group" \
  --month 2026-03
```

Or run the installed console script:

```bash
organiseMyFooty \
  --group "My Footy Group" \
  --month 2026-03
```

For a safe first run (inspect without writing files — default behaviour):

```bash
python main.py --group "My Footy Group" --month 2026-03
```

Groups used in successful runs accumulate in
`~/.config/organiseMyFooty/state.json`. Run without `--group` to scan every
configured group, or provide `--group` to scan only the named group for that
run. Repeat `--group` to scan a selected set:

```bash
python main.py \
  --group "My Footy Group" \
  --group "My Other Footy Group" \
  --month 2026-03
```

To actually write the CSV exports, add `--confirm`:

```bash
python main.py --group "My Footy Group" --month 2026-03 --confirm
```

## CLI options

| Option | Description |
|---|---|
| `--group` | Exact WhatsApp group name; repeat to select multiple groups; omit to scan all configured groups |
| `--month` | Target month in `YYYY-MM` format (default: previous month) |
| `--output` | Output directory for CSV files |
| `--user-data-dir` | Persistent browser profile directory |
| `--timeout-ms` | Selector/action timeout in ms (default: 15000) |
| `--limit-polls` | Limit number of polls processed (for testing) |
| `--browser-channel` | Playwright browser channel, e.g. `chrome` |
| `--include-no-votes` | Also collect "No" voters |
| `--poll-title-filter` | Only process polls whose text contains this substring |
| `--headless` | Run browser without showing a window |
| `--confirm` | Write CSV exports; omit to run in safe dry-run mode (default) |
| `--override` | Continue past captured polls to the start of the month two calendar months ago |
| `--scan-since YYYY-MM-DD` | Replace the override horizon with an inclusive local date; requires `--override` |
| `--view` | Inspect stored attendance for the selected month without browser scanning |

Polls are always filtered to sessions whose derived session date falls inside the selected month window.
The SQLite attendance store is loaded automatically; no cache opt-in is required.

## Output files

| File | Description |
|---|---|
| `attendanceSummary.csv` | Aggregated summary: `name`, `yesCount`, `noCount`, `totalVotes`, `pollsResponded` |
| `attendanceReport.csv` | Session-by-session matrix used for month attendance reporting |
| `socialMediaSummary.txt` | Paste-ready monthly attendance summary generated from `attendanceReport.csv` |
| `exportPreview.json` | JSON preview of both datasets for quick inspection |

## Development

```bash
pip install -r dev-requirements.txt
pytest
black src/ tests/
```

## Notes

- Uses WhatsApp Web browser automation; CSS selectors in `whatsappSelectors.py` may need
  updating if WhatsApp changes its UI.
- Reuses a persistent browser profile so you only need to log in once.
- Without `--confirm`, the tool runs in dry-run mode and writes no output files.
