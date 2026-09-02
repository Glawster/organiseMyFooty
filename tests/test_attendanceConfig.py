"""Tests for attendanceConfig module."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from attendanceConfig import (
    defaultOutputDir,
    defaultUserDataDir,
    ensureOutputDir,
    resolveMonthWindow,
    writeCsv,
)

# ---------------------------------------------------------------------------
# resolveMonthWindow
# ---------------------------------------------------------------------------


class TestResolveMonthWindow:
    def testExplicitMonthReturnsCorrectWindow(self):
        # Arrange / Act
        window = resolveMonthWindow("2026-03")

        # Assert
        assert window.monthKey == "2026-03"
        assert window.startDate == date(2026, 3, 1)
        assert window.endDate == date(2026, 3, 31)

    def testExplicitMonthFebruaryLeapYear(self):
        window = resolveMonthWindow("2024-02")

        assert window.startDate == date(2024, 2, 1)
        assert window.endDate == date(2024, 2, 29)

    def testExplicitMonthFebruaryNonLeapYear(self):
        window = resolveMonthWindow("2023-02")

        assert window.endDate == date(2023, 2, 28)

    def testNoArgReturnsPreviousCalendarMonth(self):
        today = date.today()
        firstThisMonth = today.replace(day=1)
        from datetime import timedelta

        lastPrevious = firstThisMonth - timedelta(days=1)
        expectedStart = lastPrevious.replace(day=1)
        expectedEnd = lastPrevious

        window = resolveMonthWindow()

        assert window.startDate == expectedStart
        assert window.endDate == expectedEnd

    def testNoneArgBehavesSameAsNoArg(self):
        assert resolveMonthWindow(None) == resolveMonthWindow()

    def testInvalidFormatRaisesValueError(self):
        with pytest.raises(ValueError, match="invalid month format"):
            resolveMonthWindow("March 2026")

    def testInvalidFormatShowsBadValueInMessage(self):
        with pytest.raises(ValueError, match="bad-input"):
            resolveMonthWindow("bad-input")

    def testDisplayNameIsHumanReadable(self):
        window = resolveMonthWindow("2026-01")
        assert window.displayName == "January 2026"


# ---------------------------------------------------------------------------
# ensureOutputDir
# ---------------------------------------------------------------------------


class TestEnsureOutputDir:
    def testCreatesNewDirectory(self, tmp_path):
        target = tmp_path / "new" / "nested" / "dir"
        assert not target.exists()

        result = ensureOutputDir(target)

        assert target.is_dir()
        assert result == target

    def testExistingDirectoryIsNotAnError(self, tmp_path):
        target = tmp_path / "existing"
        target.mkdir()

        result = ensureOutputDir(target)

        assert result == target


# ---------------------------------------------------------------------------
# defaultOutputDir
# ---------------------------------------------------------------------------


class TestDefaultOutputDir:
    def testSanitisesSpecialCharactersInGroupName(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir("My Group!", window)

        assert result == Path.cwd() / "output"

    def testIncludesMonthKeyInPath(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir("Team", window)

        assert result == Path.cwd() / "output"

    def testIncludesMultipleGroupNamesInPath(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir(["Team One", "Team Two"], window)

        assert result == Path.cwd() / "output"

    def testResultIsInsideOutputSubdirectory(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir("Team", window)

        assert result == Path.cwd() / "output"


# ---------------------------------------------------------------------------
# defaultUserDataDir
# ---------------------------------------------------------------------------


class TestDefaultUserDataDir:
    def testReturnsPath(self):
        result = defaultUserDataDir()
        assert isinstance(result, Path)

    def testPathContainsProfileSegment(self):
        result = defaultUserDataDir()
        assert "profile" in result.parts


# ---------------------------------------------------------------------------
# writeCsv
# ---------------------------------------------------------------------------


class TestWriteCsv:
    def testWritesHeaderAndRows(self, tmp_path):
        output = tmp_path / "out.csv"
        rows = [{"name": "Alice", "count": 3}, {"name": "Bob", "count": 1}]
        fields = ["name", "count"]

        writeCsv(output, rows, fields)

        lines = output.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "name,count"
        assert lines[1] == "Alice,3"
        assert lines[2] == "Bob,1"

    def testCreatesParentDirectories(self, tmp_path):
        output = tmp_path / "nested" / "dir" / "out.csv"
        writeCsv(output, [], ["col"])
        assert output.exists()

    def testEmptyRowsWritesOnlyHeader(self, tmp_path):
        output = tmp_path / "empty.csv"
        writeCsv(output, [], ["a", "b"])
        with output.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == ["a", "b"]
            assert list(reader) == []

    def testUnicodeContentIsPreserved(self, tmp_path):
        output = tmp_path / "unicode.csv"
        rows = [{"name": "Ångström", "count": 1}]
        writeCsv(output, rows, ["name", "count"])
        content = output.read_text(encoding="utf-8")
        assert "Ångström" in content
