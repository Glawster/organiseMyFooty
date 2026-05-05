from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta

from whatsapp.models import PollRecord, PollSession
from whatsapp.parsing import PollTextParser


class AttendanceReportBuilder:
    def __init__(self, parser: PollTextParser):
        self.parser = parser

    # ## summary utilities
    def buildSummaryRows(self, records: list[PollRecord]) -> list[dict]:
        summary: dict[str, dict[str, int | set[str]]] = {}
        for record in records:
            row = summary.setdefault(
                record.voterName,
                {
                    "yesCount": 0,
                    "noCount": 0,
                    "totalVotes": 0,
                    "pollsResponded": set(),
                },
            )
            row["totalVotes"] += 1  # type: ignore[operator]
            if record.option.lower() == "yes":
                row["yesCount"] += 1  # type: ignore[operator]
            elif record.option.lower() == "no":
                row["noCount"] += 1  # type: ignore[operator]
            row["pollsResponded"].add(
                f"{record.pollTitle}|{record.sessionDateText or record.pollDateText}"
            )  # type: ignore[union-attr]

        outputRows: list[dict] = []
        for voterName in sorted(summary, key=str.casefold):
            row = summary[voterName]
            outputRows.append(
                {
                    "name": voterName,
                    "yesCount": int(row["yesCount"]),  # type: ignore[arg-type]
                    "noCount": int(row["noCount"]),  # type: ignore[arg-type]
                    "totalVotes": int(row["totalVotes"]),  # type: ignore[arg-type]
                    "pollsResponded": len(row["pollsResponded"]),  # type: ignore[arg-type]
                }
            )
        return outputRows

    # ## report table utilities
    def buildAttendanceReportRows(self, records: list[PollRecord]) -> list[list[str]]:
        if not records:
            return [[""], [""], ["name"]]

        pollSessions = self.buildPollSessions(records)
        maxWeek = max(session.weekNumber for session in pollSessions.values())

        sessionsByWeek: dict[int, list[PollSession]] = {}
        for session in pollSessions.values():
            sessionsByWeek.setdefault(session.weekNumber, []).append(session)

        for week in sessionsByWeek.values():
            week.sort(
                key=lambda s: datetime.strptime(
                    s.sessionDateText or "99991231 00:00",
                    "%Y%m%d %H:%M",
                )
            )

        dateHeader = [""]
        weekHeader = [""]
        sessionHeader = ["name"]
        columns: list[PollSession] = []

        for weekNumber in range(1, maxWeek + 1):
            for i, session in enumerate(sessionsByWeek.get(weekNumber, [])):
                dateHeader.append(self.formatSessionDateText(session.sessionDateText))
                weekHeader.append(f"week {weekNumber}" if i == 0 else "")
                sessionHeader.append(session.sessionName)
                columns.append(session)

        voterNames = sorted({r.voterName for r in records}, key=str.casefold)
        attendance = self.buildAttendanceLookup(records, pollSessions)

        rows = [weekHeader, dateHeader, sessionHeader]
        for voter in voterNames:
            row = [voter]
            for session in columns:
                row.append(
                    attendance.get((voter, session.weekNumber, session.sessionName), "")
                )
            rows.append(row)

        return rows

    # ## session utilities
    def buildAttendanceLookup(
        self,
        records: list[PollRecord],
        pollSessions: OrderedDict[str, PollSession],
    ) -> dict[tuple[str, int, str], str]:
        attendance: dict[tuple[str, int, str], str] = {}
        for record in records:
            pollSession = pollSessions[self.buildPollKey(record)]
            key = (record.voterName, pollSession.weekNumber, pollSession.sessionName)
            current = attendance.get(key, "")

            if record.option.lower() == "yes":
                attendance[key] = "yes"
            elif record.option.lower() == "no" and current != "yes":
                attendance[key] = "no"

        return attendance

    def buildPollKey(self, record: PollRecord) -> str:
        return self.parser.buildPollKeyFromParts(
            pollTitle=record.pollTitle,
            pollDateText=record.pollDateText,
            sourceHint=record.sourceHint,
        )

    def buildPollSessions(
        self, records: list[PollRecord]
    ) -> OrderedDict[str, PollSession]:
        pollRows: OrderedDict[str, PollRecord] = OrderedDict()
        for record in records:
            pollRows.setdefault(self.buildPollKey(record), record)

        sortedRows = sorted(
            pollRows.items(),
            key=lambda item: (
                item[1].sessionDateText or "99999999",
                item[1].pollTitle.casefold(),
            ),
        )

        weekNumbersByKey: OrderedDict[str, int] = OrderedDict()
        pollSessions: OrderedDict[str, PollSession] = OrderedDict()

        for pollKey, record in sortedRows:
            sessionName = self.parser.extractSessionName(record.pollTitle)
            sessionWeekKey = self.buildSessionWeekKey(record.sessionDateText)

            if sessionWeekKey not in weekNumbersByKey:
                weekNumbersByKey[sessionWeekKey] = len(weekNumbersByKey) + 1

            pollSessions[pollKey] = PollSession(
                pollKey=pollKey,
                pollTitle=record.pollTitle,
                sessionDateText=record.sessionDateText,
                weekNumber=weekNumbersByKey[sessionWeekKey],
                sessionName=sessionName,
            )

        return pollSessions

    def buildSessionWeekKey(self, sessionDateText: str) -> str:
        if not sessionDateText:
            return "unknown"
        try:
            sessionDate = datetime.strptime(sessionDateText[:8], "%Y%m%d")
        except ValueError:
            return "unknown"

        weekStart = sessionDate - timedelta(days=sessionDate.weekday())
        return weekStart.strftime("%Y%m%d")

    def extractOrderedSessionNames(
        self, pollSessions: OrderedDict[str, PollSession]
    ) -> list[str]:
        sessions: OrderedDict[str, None] = OrderedDict()
        for pollSession in pollSessions.values():
            sessions.setdefault(pollSession.sessionName, None)
        return list(sessions.keys())

    def formatSessionDateText(self, sessionDateText: str) -> str:
        if not sessionDateText:
            return ""

        try:
            return datetime.strptime(
                sessionDateText,
                "%Y%m%d %H:%M",
            ).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return sessionDateText
