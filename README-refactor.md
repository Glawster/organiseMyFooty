# WhatsApp attendance refactor

## File layout

- `whatsappAttendance.py` — compatibility wrapper for existing imports.
- `whatsappAttendanceExporter.py` — top-level export orchestration and file writing.
- `whatsappAttendanceBrowser.py` — WhatsApp Web / Playwright scraping routines.
- `whatsappAttendanceCache.py` — poll cache load/save and cache merge helpers.
- `whatsappAttendanceReports.py` — summary and attendance report builders.
- `whatsappAttendanceParsing.py` — poll title, date, key, and voter text parsing.
- `whatsappAttendanceModels.py` — `PollRecord` and `PollSession` dataclasses.
- `whatsappAttendanceRecords.py` — record-level helpers such as deduplication.
- `whatsappAttendanceConstants.py` — cache and recheck constants.

## Pattern used

Each file groups functions under comment headings such as:

```python
# ## export orchestration
# ## csv write utilities
# ## preview utilities
```

Function names remain camelCase and related routines are kept alphabetically/grouped within their section where practical.

## Migration

Replace the original `whatsappAttendance.py` with all files in this folder. Existing code that imports `AttendanceExporter` from `whatsappAttendance` should continue to work.
