"""Tests for attendanceConfig module."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from attendanceConfig import (
    MonthWindow,
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
    def test_explicit_month_returns_correct_window(self):
        # Arrange / Act
        window = resolveMonthWindow("2026-03")

        # Assert
        assert window.monthKey == "2026-03"
        assert window.startDate == date(2026, 3, 1)
        assert window.endDate == date(2026, 3, 31)

    def test_explicit_month_february_leap_year(self):
        window = resolveMonthWindow("2024-02")

        assert window.startDate == date(2024, 2, 1)
        assert window.endDate == date(2024, 2, 29)

    def test_explicit_month_february_non_leap_year(self):
        window = resolveMonthWindow("2023-02")

        assert window.endDate == date(2023, 2, 28)

    def test_no_arg_returns_previous_calendar_month(self):
        today = date.today()
        first_this_month = today.replace(day=1)
        from datetime import timedelta

        last_prev = first_this_month - timedelta(days=1)
        expected_start = last_prev.replace(day=1)
        expected_end = last_prev

        window = resolveMonthWindow()

        assert window.startDate == expected_start
        assert window.endDate == expected_end

    def test_none_arg_behaves_same_as_no_arg(self):
        assert resolveMonthWindow(None) == resolveMonthWindow()

    def test_invalid_format_raises_value_error(self):
        with pytest.raises(ValueError, match="invalid month format"):
            resolveMonthWindow("March 2026")

    def test_invalid_format_shows_bad_value_in_message(self):
        with pytest.raises(ValueError, match="bad-input"):
            resolveMonthWindow("bad-input")

    def test_display_name_is_human_readable(self):
        window = resolveMonthWindow("2026-01")
        assert window.displayName == "January 2026"


# ---------------------------------------------------------------------------
# ensureOutputDir
# ---------------------------------------------------------------------------


class TestEnsureOutputDir:
    def test_creates_new_directory(self, tmp_path):
        target = tmp_path / "new" / "nested" / "dir"
        assert not target.exists()

        result = ensureOutputDir(target)

        assert target.is_dir()
        assert result == target

    def test_existing_directory_is_not_an_error(self, tmp_path):
        target = tmp_path / "existing"
        target.mkdir()

        result = ensureOutputDir(target)

        assert result == target


# ---------------------------------------------------------------------------
# defaultOutputDir
# ---------------------------------------------------------------------------


class TestDefaultOutputDir:
    def test_sanitises_special_characters_in_group_name(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir("My Group!", window)

        assert "my_group_" in str(result)

    def test_includes_month_key_in_path(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir("Team", window)

        assert "2026-03" in str(result)

    def test_result_is_inside_output_subdirectory(self):
        window = resolveMonthWindow("2026-03")
        result = defaultOutputDir("Team", window)

        assert result.parts[-3] == "output" or "output" in result.parts


# ---------------------------------------------------------------------------
# defaultUserDataDir
# ---------------------------------------------------------------------------


class TestDefaultUserDataDir:
    def test_returns_path(self):
        result = defaultUserDataDir()
        assert isinstance(result, Path)

    def test_path_contains_profile_segment(self):
        result = defaultUserDataDir()
        assert "profile" in result.parts


# ---------------------------------------------------------------------------
# writeCsv
# ---------------------------------------------------------------------------


class TestWriteCsv:
    def test_writes_header_and_rows(self, tmp_path):
        output = tmp_path / "out.csv"
        rows = [{"name": "Alice", "count": 3}, {"name": "Bob", "count": 1}]
        fields = ["name", "count"]

        writeCsv(output, rows, fields)

        lines = output.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "name,count"
        assert lines[1] == "Alice,3"
        assert lines[2] == "Bob,1"

    def test_creates_parent_directories(self, tmp_path):
        output = tmp_path / "nested" / "dir" / "out.csv"
        writeCsv(output, [], ["col"])
        assert output.exists()

    def test_empty_rows_writes_only_header(self, tmp_path):
        output = tmp_path / "empty.csv"
        writeCsv(output, [], ["a", "b"])
        with output.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == ["a", "b"]
            assert list(reader) == []

    def test_unicode_content_is_preserved(self, tmp_path):
        output = tmp_path / "unicode.csv"
        rows = [{"name": "Ångström", "count": 1}]
        writeCsv(output, rows, ["name", "count"])
        content = output.read_text(encoding="utf-8")
        assert "Ångström" in content
