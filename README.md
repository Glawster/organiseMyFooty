# organiseMyFooty

Python tool for exporting WhatsApp poll attendance from WhatsApp Web.

Automates collection of footy training/match poll responses from a WhatsApp group,
exporting voter names and attendance counts to CSV files.

## Source files

- `src/exportAttendance.py` — CLI entry point
- `src/whatsappAttendance.py` — browser automation and export pipeline
- `src/attendanceConfig.py` — config helpers and month/date resolution
- `src/whatsappSelectors.py` — centralised WhatsApp Web CSS/aria selectors
- `src/__init__.py` — package initialisation

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

This project expects `organiseMyProjects.logUtils` to be available in the same
Python environment for centralized logging.

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
python main.py --group "My Footy Group" --month 2026-03 --timeout-ms 300000
```

## Usage

Run from the `src/` directory (or add `src/` to `PYTHONPATH`):

```bash
cd src
python exportAttendance.py \
  --group "My Footy Group" \
  --month 2026-03 \
  --output ~/attendance/footy_2026_03 \
  --user-data-dir ~/.local/share/organiseMyFooty/profile
```

For a safe first run (inspect without writing files — default behaviour):

```bash
cd src
python exportAttendance.py --group "My Footy Group" --month 2026-03
```

To actually write the CSV exports, add `--confirm`:

```bash
cd src
python exportAttendance.py --group "My Footy Group" --month 2026-03 --confirm
```

## CLI options

| Option | Description |
|---|---|
| `--group` | Exact WhatsApp group name (required) |
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

## Output files

| File | Description |
|---|---|
| `polls.csv` | Raw poll rows: `pollTitle`, `pollDateText`, `option`, `voterName`, `sourceHint` |
| `attendanceSummary.csv` | Aggregated summary: `name`, `yesCount`, `noCount`, `totalVotes`, `pollsResponded` |
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
