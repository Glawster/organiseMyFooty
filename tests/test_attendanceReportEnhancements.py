"""Regression tests for enhanced attendance report output."""

from datetime import date
from pathlib import Path

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.exporter import AttendanceExporter
from whatsapp.models import PollRecord, SessionStatus
from whatsapp.parsing import PollTextParser
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.reports import AttendanceReportBuilder
from whatsapp.selectors import DEFAULT_SELECTORS


def _makeConfig() -> RuntimeConfig:
    return RuntimeConfig(
        groupName="Test Group",
        monthWindow=MonthWindow(
            monthKey="2026-08",
            startDate=date(2026, 8, 1),
            endDate=date(2026, 8, 31),
        ),
        outputDir=Path("/tmp/test_output"),
        userDataDir=Path("/tmp/test_profile"),
        headless=True,
        dryRun=True,
        timeoutMs=5000,
        logLevel=20,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=True,
        resume=False,
        pollTitleFilter=None,
        strictMonth=True,
    )


def _record(
    title: str,
    pollDateText: str,
    sessionDateText: str,
    voterName: str,
    option: str = "Yes",
    status: SessionStatus = SessionStatus.SCHEDULED,
) -> PollRecord:
    return PollRecord(
        pollTitle=title,
        pollDateText=pollDateText,
        sessionDateText=sessionDateText,
        option=option,
        voterName=voterName,
        sourceHint=title,
        sessionStatus=status,
    )


def testEnhancedAttendanceReportAddsCancelledRowAndPlayerTotals():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)
    records = [
        _record(
            "Wednesday 11am LLC",
            "20260810",
            "20260812 11:00",
            "Alice",
        ),
        _record(
            "Wednesday 11am LLC",
            "20260810",
            "20260812 11:00",
            "Bob",
            option="No",
        ),
        _record(
            "Friday 8pm Football Factory",
            "20260813",
            "20260814 20:00",
            "",
            option="",
            status=SessionStatus.CANCELLED,
        ),
    ]

    rows = builder.buildAttendanceReportRows(
        records,
        includeAttendanceTotal=True,
        includeCancelled=True,
    )

    assert rows[4][-1] == "Total Attended"
    assert rows[5] == ["Cancelled", "", "cancelled", ""]
    assert rows[6] == ["Alice", "yes", "", "1"]
    assert rows[7] == ["Bob", "no", "", "0"]
    assert rows[-1] == ["Session Total", "1", "", ""]


def testCancelledSessionColumnDoesNotRequireAttendanceRecord():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)
    attendanceRecords = [
        _record(
            "Wednesday 11am LLC",
            "20260810",
            "20260812 11:00",
            "Alice",
        )
    ]
    sessionRecords = [
        _record(
            "Wednesday 11am LLC",
            "20260810",
            "20260812 11:00",
            "",
        ),
        _record(
            "Friday 8pm Football Factory",
            "20260813",
            "20260814 20:00",
            "",
            option="",
            status=SessionStatus.CANCELLED,
        ),
    ]

    rows = builder.buildAttendanceReportRows(
        attendanceRecords,
        includeAttendanceTotal=True,
        includeCancelled=True,
        sessionRecords=sessionRecords,
    )

    assert rows[5] == ["Cancelled", "", "cancelled", ""]
    assert rows[6] == ["Alice", "yes", "", "1"]
    assert rows[-1] == ["Session Total", "1", "", ""]


def testAttendanceMatchesPersistedSessionDateBeforeSourcePollKey():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)
    attendanceRecords = [
        _record(
            "Tuesday 10.30am LLC",
            "20260809",
            "20260804 10:30",
            "Alice",
        )
    ]
    sessionRecords = [
        _record(
            "Tuesday 10.30am LLC",
            "20260802",
            "20260804 10:30",
            "",
        ),
        _record(
            "Tuesday 10.30am LLC",
            "20260809",
            "20260811 10:30",
            "",
        ),
    ]

    rows = builder.buildAttendanceReportRows(
        attendanceRecords,
        includeAttendanceTotal=True,
        sessionRecords=sessionRecords,
    )

    assert rows[5] == ["Alice", "yes", "", "1"]
    assert rows[-1] == ["Session Total", "1", "0", ""]


def testCurrentScanCancellationOverridesStoredSessionStatus():
    exporter = AttendanceExporter(_makeConfig())
    storedRecord = _record(
        "Friday 8pm Football Factory",
        "20260813",
        "20260814 20:00",
        "",
    )
    currentRecord = _record(
        "Friday 8pm Football Factory",
        "20260813",
        "20260814 20:00",
        "",
        option="",
        status=SessionStatus.CANCELLED,
    )

    merged = exporter.mergeReportSessionRecords([storedRecord], [currentRecord])

    assert merged == [currentRecord]


def testPollRecordBuilderRetainsPhoneLookupForCurrentScan():
    config = _makeConfig()
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    discovery = PollDiscovery(config, DEFAULT_SELECTORS, parser)
    builder = PollRecordsBuilder(config, DEFAULT_SELECTORS, parser, discovery)

    builder.buildOptionRecords(
        dialogText="Wednesday 11am LLC\nYes\nTom\n+44 7810 878563\nNo",
        pollTitle="Wednesday 11am LLC",
        pollDateText="20260810",
        sessionDateText="20260812 11:00",
        sourceHint="test",
        sessionStatus=SessionStatus.SCHEDULED,
    )

    assert builder.voterPhones == {"tom": "447810878563"}
