from __future__ import annotations

from datetime import date
import sqlite3

import pytest

from attendanceConfig import MonthWindow, RuntimeConfig, resolveScanCutoff
from whatsapp.models import PollRecord
from whatsapp.parsing import PollTextParser
from whatsapp.selectors import DEFAULT_SELECTORS
from whatsapp.store import AttendanceStore, SCHEMA_VERSION
from whatsapp.scraper import WhatsAppPollScraper


def record(
    name="Alice", option="Yes", title="Monday Training", session="20260504 19:00"
):
    return PollRecord(title, "20260501", session, option, name, title)


@pytest.fixture
def store(tmp_path):
    with AttendanceStore(tmp_path / "attendance.sqlite3") as value:
        yield value


def test_schema_creation_enables_foreign_keys_and_versions(store):
    assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert (
        store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    )
    assert store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(RuntimeError, match="newer"):
        AttendanceStore(path).open()


def test_reconcile_is_idempotent_and_changes_response(store):
    first = store.pollReconcile("Group A", "message-1", [record()])
    second = store.pollReconcile("Group A", "message-1", [record()])
    assert first == second
    assert store.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 1
    assert (
        store.connection.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 1
    )
    store.pollReconcile("Group A", "message-1", [record(option="No")])
    assert (
        store.connection.execute("SELECT response FROM attendance").fetchone()[0]
        == "no"
    )
    assert store.summary.attendanceUpdated == 1


def test_incomplete_poll_does_not_remove_unseen_observations(store):
    store.pollReconcile("Group A", "message-1", [record(), record("Bob")])
    store.pollReconcile("Group A", "message-1", [record()], complete=False)
    assert (
        store.connection.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 2
    )
    store.pollReconcile("Group A", "message-1", [record()], complete=True)
    assert (
        store.connection.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 1
    )


def test_multiple_sources_share_session_and_conflict_is_explicit(store):
    session = store.pollReconcile("Group A", "message-a", [record(option="No")])
    other = store.pollReconcile(
        "Group B", "message-b", [record(option="Yes", title="Monday Football")]
    )
    assert other == session
    attendance = store.connection.execute(
        "SELECT response, conflicted FROM attendance"
    ).fetchone()
    assert tuple(attendance) == ("yes", 1)
    observations = store.observationsForAttendance(session, 1)
    assert len(observations) == 2


def test_removing_one_source_keeps_other_source_support(store):
    store.pollReconcile("Group A", "message-a", [record(), record("Bob")])
    store.pollReconcile("Group B", "message-b", [record("Bob")])
    store.pollReconcile("Group A", "message-a", [record()], complete=True)
    assert [row["display_name"] for row in store.membersForSession(1)] == [
        "Alice",
        "Bob",
    ]


def test_alias_matching_and_ambiguous_alias_rejected(store):
    store.pollReconcile("Group A", "message-a", [record("Alice Smith")])
    store.memberAliasAdd(1, "Ali")
    store.pollReconcile(
        "Group A", "message-b", [record("Ali", session="20260511 19:00")]
    )
    assert store.connection.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 1
    store.pollReconcile(
        "Group A", "message-c", [record("Bob", session="20260518 19:00")]
    )
    with pytest.raises(ValueError, match="another member"):
        store.memberAliasAdd(2, "Ali")


def test_date_range_and_filtered_queries(store):
    store.pollReconcile("Group A", "may", [record(session="20260504 19:00")])
    store.pollReconcile("Group A", "june", [record(session="20260604 19:00")])
    store.pollReconcile("Group A", "july", [record(session="20260704 19:00")])
    sessions = store.sessionsForMember(1, date(2026, 5, 1), date(2026, 7, 31))
    assert len(sessions) == 3
    assert len(store.sessionsInRange(date(2026, 6, 4), date(2026, 6, 4))) == 1
    assert (
        len(
            store.attendanceQuery(
                date(2026, 5, 1), date(2026, 7, 31), response="yes", group="Group A"
            )
        )
        == 3
    )


def test_attendance_records_preserve_original_poll_title(store):
    store.pollReconcile(
        "Group A",
        "message-1",
        [
            record(
                title="Wednesday 11am Football Factory",
                session="20260610 11:00",
            )
        ],
    )

    records = store.attendanceRecords(date(2026, 6, 1), date(2026, 6, 30))

    assert records[0].pollTitle == "Wednesday 11am Football Factory"


def test_transaction_rolls_back_incomplete_unit(store):
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO members(display_name, normalised_name, created_at, updated_at) VALUES('A','a','x','x')"
            )
            connection.execute(
                "INSERT INTO members(display_name, normalised_name, created_at, updated_at) VALUES('B','a','x','x')"
            )
    assert store.connection.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0


def test_scan_lifecycle_and_stable_boundary_identity(store):
    source = store.sourceEnsure("whatsapp", "group-a", "Group A")
    store.connection.commit()
    scan = store.scanStart(source, date(2026, 5, 1), date(2026, 5, 31))
    store.scanFinish(scan, "completed", "captured_poll")
    assert store.connection.execute(
        "SELECT status, boundary_reason FROM scans"
    ).fetchone()[:] == ("completed", "captured_poll")
    store.pollReconcile("Group A", "stable-id", [record()])
    assert store.sourcePollCaptured("whatsapp", "group a", "stable-id")
    assert not store.sourcePollCaptured("whatsapp", "group a", "Monday Training")


def test_captured_boundary_is_independent_per_group_and_override_disables_it(
    store, tmp_path
):
    config = RuntimeConfig(
        "Group A",
        MonthWindow("2026-05", date(2026, 5, 1), date(2026, 5, 31)),
        tmp_path,
        tmp_path,
        True,
        False,
        1,
        20,
        None,
        None,
        False,
        False,
        None,
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config,
        DEFAULT_SELECTORS,
        parser,
        store,
    )
    store.pollReconcile("Group A", "stable-id", [record()])

    assert scraper.capturedPollIsBoundary("Group A", "stable-id")
    assert not scraper.capturedPollIsBoundary("Group B", "stable-id")
    assert not scraper.capturedPollIsBoundary("Group A", "")

    overrideConfig = RuntimeConfig(**{**config.__dict__, "override": True})
    overrideParser = PollTextParser(overrideConfig, DEFAULT_SELECTORS)
    overrideScraper = WhatsAppPollScraper(
        overrideConfig,
        DEFAULT_SELECTORS,
        overrideParser,
        store,
    )
    assert not overrideScraper.capturedPollIsBoundary("Group A", "stable-id")


def test_scan_cutoff_standard_custom_and_year_boundary():
    assert resolveScanCutoff(True, None, date(2026, 8, 15)) == date(2026, 6, 1)
    assert resolveScanCutoff(True, None, date(2026, 1, 10)) == date(2025, 11, 1)
    assert resolveScanCutoff(True, date(2026, 2, 15), date(2026, 8, 1)) == date(
        2026, 2, 15
    )
    with pytest.raises(ValueError, match="requires"):
        resolveScanCutoff(False, date(2026, 2, 15), date(2026, 8, 1))
    with pytest.raises(ValueError, match="future"):
        resolveScanCutoff(True, date(2026, 8, 2), date(2026, 8, 1))
