"""Requirement 002 tests for cancelled WhatsApp sessions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import re

import pytest

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.models import PollRecord, SessionStatus
from whatsapp.parsing import PollTextParser
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.reports import AttendanceReportBuilder
from whatsapp.selectors import DEFAULT_SELECTORS
from whatsapp.store import AttendanceStore


class StubDiscovery:
    def extractPollDateText(self, locator, sourceText: str) -> str:
        return "01/03/2026"


class ReactionLocator:
    def __init__(self, values: list[str]):
        self.values = values

    def evaluate(self, _script, participantName: str):
        namePattern = re.compile(
            rf"(?<!\w){re.escape(participantName.casefold())}(?!\w)"
        )
        return any(
            "😢" in value and namePattern.search(value.casefold())
            for value in self.values
        )


class UnavailableReactionLocator:
    def evaluate(self, _script, _participantName: str):
        raise RuntimeError("reaction metadata unavailable")


def _record(
    title: str = "Monday 7pm Riverside",
    status: SessionStatus = SessionStatus.SCHEDULED,
    voterName: str = "Alex Example",
) -> PollRecord:
    return PollRecord(
        pollTitle=title,
        pollDateText="20260301",
        sessionDateText="20260302 19:00",
        option="Yes",
        voterName=voterName,
        sourceHint=f"source: {title}",
        sessionStatus=status,
    )


@pytest.fixture
def parser():
    config = RuntimeConfig(
        groupName="Riverside Football",
        monthWindow=MonthWindow(
            monthKey="2026-03",
            startDate=date(2026, 3, 1),
            endDate=date(2026, 3, 31),
        ),
        outputDir=Path("/tmp/test_cancelled_output"),
        userDataDir=Path("/tmp/test_cancelled_profile"),
        headless=True,
        dryRun=True,
        timeoutMs=5000,
        logLevel=20,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=True,
        resume=False,
        pollTitleFilter=None,
        cancellationEmojiName="Alex Example",
    )
    return PollTextParser(config, DEFAULT_SELECTORS)


@pytest.fixture
def store(tmp_path, parser):
    with AttendanceStore(tmp_path / "attendance.sqlite3", parser) as value:
        value.logger.messages.clear()
        yield value


@pytest.mark.parametrize(
    "metadata, expected",
    [
        (["😢 by Another Person"], False),
        (["😢 Alex Example"], True),
        (["😢 Alexandra Example"], False),
        (["😢 Alex Example", "😢 by Another Person"], True),
    ],
)
def testOnlySadFaceFromConfiguredParticipantCancels(parser, metadata, expected):
    discovery = PollDiscovery(parser.config, DEFAULT_SELECTORS, parser)

    assert discovery.pollHasCancellationReaction(ReactionLocator(metadata)) is expected


def testOtherEmojiFromConfiguredParticipantDoesNotCancel(parser):
    discovery = PollDiscovery(parser.config, DEFAULT_SELECTORS, parser)

    assert not discovery.pollHasCancellationReaction(
        ReactionLocator(["😡 Alex Example", "❤️ Alex Example"])
    )


def testReactionInspectionFailureIsUnknownRatherThanScheduled(parser):
    discovery = PollDiscovery(parser.config, DEFAULT_SELECTORS, parser)

    assert discovery.pollHasCancellationReaction(UnavailableReactionLocator()) is None


def testCancelledPollPreservesTitleAndCapturedVoters(parser):
    builder = PollRecordsBuilder(
        config=parser.config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscovery(),
    )
    title = "Monday 7pm Riverside"
    sourceText = f"{title}\nSelect one or more\n2 votes\n01/03/2026"

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText=f"{title}\nYes\nAlex Example\nBlair Example",
        sourceText=sourceText,
        cancelledByReaction=True,
    )

    assert {record.voterName for record in records} == {
        "Alex Example",
        "Blair Example",
    }
    assert all(record.option == "Yes" for record in records)
    assert all(record.pollTitle == title for record in records)
    assert all(record.sessionStatus is SessionStatus.CANCELLED for record in records)
    assert builder.logger.hasCall(
        "info",
        "cancellation indicator found: emoji=%s participant=%s poll=%s",
        "😢",
        "Alex Example",
        title,
    )


def testCancelAndRestorePreserveIdentityTitleAttendanceAndLogs(store):
    scheduled = _record()
    cancelledTitle = "Monday 7pm Riverside"
    cancelled = _record(cancelledTitle, SessionStatus.CANCELLED)

    sessionId = store.pollReconcile("Riverside A", "message-1", [scheduled])
    cancelledId = store.pollReconcile("Riverside A", "message-1", [cancelled])

    assert cancelledId == sessionId
    assert store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    session = store.sessionsInRange(date(2026, 3, 1), date(2026, 3, 31))[0]
    source = store.connection.execute(
        "SELECT source_title, session_status FROM session_sources"
    ).fetchone()
    assert session["status"] == "cancelled"
    assert tuple(source) == (cancelledTitle, "cancelled")
    assert store.attendanceRecords(date(2026, 3, 1), date(2026, 3, 31)) == []
    assert store.attendanceQuery(date(2026, 3, 1), date(2026, 3, 31)) == []
    assert store.membersForSession(sessionId) == []
    assert store.sessionsForMember(1, date(2026, 3, 1), date(2026, 3, 31)) == []
    observation = store.observationsForAttendance(sessionId, 1)[0]
    assert observation["raw_member_name"] == "Alex Example"
    assert observation["active"] == 1
    assert store.logger.hasCall("value", "session cancelled", sessionId)

    restoredId = store.pollReconcile("Riverside A", "message-1", [scheduled])

    assert restoredId == sessionId
    assert store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert len(store.attendanceRecords(date(2026, 3, 1), date(2026, 3, 31))) == 1
    assert store.logger.hasCall("value", "session restored", sessionId)


def testCancelledSessionWithoutVotersRemainsQueryable(store):
    cancelled = _record(
        "Monday 7pm Riverside",
        SessionStatus.CANCELLED,
        voterName="",
    )

    sessionId = store.pollReconcile("Riverside A", "message-1", [cancelled])

    assert (
        store.sessionsInRange(date(2026, 3, 1), date(2026, 3, 31))[0]["status"]
        == "cancelled"
    )
    assert store.connection.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0
    assert (
        store.connection.execute(
            "SELECT COUNT(*) FROM attendance_observations"
        ).fetchone()[0]
        == 0
    )
    assert sessionId == 1


def testMultiSourceCancellationRequiresEverySourceToRestore(store):
    scheduled = _record()
    cancelled = _record("Monday 7pm Riverside", SessionStatus.CANCELLED)
    sessionId = store.pollReconcile("Riverside A", "message-a", [scheduled])
    otherId = store.pollReconcile("Riverside B", "message-b", [cancelled])

    assert otherId == sessionId
    assert (
        store.connection.execute("SELECT COUNT(*) FROM session_sources").fetchone()[0]
        == 2
    )
    assert (
        store.connection.execute(
            "SELECT status FROM sessions WHERE id=?", (sessionId,)
        ).fetchone()[0]
        == "cancelled"
    )

    store.pollReconcile("Riverside A", "message-a", [scheduled])
    assert (
        store.connection.execute(
            "SELECT status FROM sessions WHERE id=?", (sessionId,)
        ).fetchone()[0]
        == "cancelled"
    )

    store.pollReconcile("Riverside B", "message-b", [scheduled])
    assert (
        store.connection.execute(
            "SELECT status FROM sessions WHERE id=?", (sessionId,)
        ).fetchone()[0]
        == "scheduled"
    )


def testReportsExcludeCancelledRecordsDefensively(parser):
    builder = AttendanceReportBuilder(parser)
    cancelled = _record("Monday 7pm Riverside", SessionStatus.CANCELLED)

    assert builder.buildSummaryRows([cancelled]) == []
    assert builder.buildAttendanceReportRows([cancelled]) == [
        ["Week"],
        ["Date"],
        ["Venue"],
        ["Day"],
        ["Name"],
    ]


def testSchemaVersionOneMigratesSourceStatus(tmp_path):
    path = tmp_path / "version-one.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE session_sources (id INTEGER PRIMARY KEY);
        CREATE TABLE scans (
            status TEXT,
            completed_at TEXT,
            boundary_reason TEXT
        );
        PRAGMA user_version = 1;
        """
    )
    connection.close()

    with AttendanceStore(path) as migrated:
        columns = {
            row["name"]
            for row in migrated.connection.execute("PRAGMA table_info(session_sources)")
        }

        assert "session_status" in columns
        assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 2
