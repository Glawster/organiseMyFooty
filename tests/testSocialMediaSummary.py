from __future__ import annotations

import csv

from pathlib import Path

from socialMediaSummary import (
    buildSocialMediaSummary,
    buildSocialMediaSummaryFromAttendanceReport,
)


class TestBuildSocialMediaSummary:
    def test_builds_paste_ready_monthly_summary(self):
        rows = [
            ["", "20260303", "20260305"],
            ["", "week 1", ""],
            ["name", "Tuesday Training", "Thursday Training"],
            ["Alice", "yes", "no"],
            ["Bob", "", "yes"],
        ]

        assert buildSocialMediaSummary(rows) == (
            "March 2026 attendance summary\n"
            "2 sessions\n"
            "- Alice: 1/2 attended, 1 no, 0 no reply\n"
            "- Bob: 1/2 attended, 0 no, 1 no reply"
        )

    def test_returns_fallback_when_sessions_are_missing(self):
        rows = [[""], [""], ["name"]]

        assert buildSocialMediaSummary(rows) == "Attendance summary unavailable."


class TestBuildSocialMediaSummaryFromAttendanceReport:
    def test_reads_attendance_report_csv(self, tmp_path: Path):
        reportPath = tmp_path / "attendanceReport.csv"
        rows = [
            ["", "20260401"],
            ["", "week 1"],
            ["name", "Training"],
            ["Charlie", "yes"],
        ]

        with reportPath.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

        assert buildSocialMediaSummaryFromAttendanceReport(reportPath) == (
            "April 2026 attendance summary\n"
            "1 session\n"
            "- Charlie: 1/1 attended, 0 no, 0 no reply"
        )
