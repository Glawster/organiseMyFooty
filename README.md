# organiseMyWhatsApp

Python scaffolding for exporting WhatsApp poll attendance from WhatsApp Web.

## Files

- `exportAttendance.py` — CLI entry point
- `whatsappAttendance.py` — browser automation and export pipeline
- `attendanceConfig.py` — config helpers and month/date resolution
- `selectors.py` — centralised selectors and heuristics
- `__init__.py`

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install playwright
playwright install chromium
```

## Example

```bash
python exportAttendance.py \
  --group "LLC" \
  --month 2026-03 \
  --output ~/attendance/llc_2026_03 \
  --user-data-dir ~/.local/share/organiseMyWhatsApp/profile
```

For a safe first run:

```bash
python exportAttendance.py --group "LLC" --month 2026-03 --dry-run
```

## Notes

This uses WhatsApp Web automation, so selectors may need adjustment if WhatsApp changes its UI.
The default implementation is intentionally semi-automatic and defensive:
- it reuses a persistent browser profile
- it writes raw poll rows plus a summary CSV
- it has optional `--limit-polls`
- it can run headful so you can see what it is doing
