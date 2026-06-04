from __future__ import annotations

import csv

from datetime import datetime
from pathlib import Path


def buildSocialMediaSummaryFromAttendanceReport(path: Path) -> str:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return buildSocialMediaSummary(rows)


def buildSocialMediaSummary(rows: list[list[str]]) -> str:
    if len(rows) < 3:
        return "Attendance summary unavailable."

    sessionHeader = rows[2]
    sessionIndexes = [
        index for index, value in enumerate(sessionHeader[1:], start=1) if value.strip()
    ]

    if not sessionIndexes:
        return "Attendance summary unavailable."

    title = buildSummaryTitle(rows[0], sessionIndexes)
    totalSessions = len(sessionIndexes)
    sessionLabel = "session" if totalSessions == 1 else "sessions"
    lines = [title, f"{totalSessions} {sessionLabel}"]

    for row in rows[3:]:
        if not row:
            continue

        name = row[0].strip()
        if not name:
            continue

        statuses = [
            row[index].strip().lower() if index < len(row) else ""
            for index in sessionIndexes
        ]
        yesCount = sum(1 for status in statuses if status == "yes")
        noCount = sum(1 for status in statuses if status == "no")
        noReplyCount = totalSessions - yesCount - noCount

        lines.append(
            f"- {name}: {yesCount}/{totalSessions} attended, "
            f"{noCount} no, {noReplyCount} no reply"
        )

    return "\n".join(lines)


def buildSummaryTitle(dateHeader: list[str], sessionIndexes: list[int]) -> str:
    for index in sessionIndexes:
        if index >= len(dateHeader):
            continue

        dateText = dateHeader[index].strip()
        if not dateText:
            continue

        try:
            sessionDate = datetime.strptime(dateText, "%Y%m%d")
        except ValueError:
            continue

        return f"{sessionDate.strftime('%B %Y')} attendance summary"

    return "Attendance summary"
