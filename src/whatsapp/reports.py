from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta

from whatsapp.models import PollRecord, PollSession, SessionStatus
from whatsapp.parsing import PollTextParser


class AttendanceReportBuilder:
    def __init__(self, parser: PollTextParser):
        self.parser = parser

    # ## summary utilities
    def buildSummaryRows(self, records: list[PollRecord]) -> list[dict]:
        summary: dict[str, dict[str, int | set[str]]] = {}
        for record in records:
            if record.sessionStatus is SessionStatus.CANCELLED or not record.voterName:
                continue
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
    def buildAttendanceReportRows(
        self,
        records: list[PollRecord],
        includeAttendanceTotal: bool = False,
        includeCancelled: bool = False,
        sessionRecords: list[PollRecord] | None = None,
    ) -> list[list[str]]:
        columnRecords = sessionRecords if sessionRecords is not None else records
        reportRecords = (
            columnRecords
            if includeCancelled
            else [
                record
                for record in columnRecords
                if record.sessionStatus is SessionStatus.SCHEDULED
            ]
        )
        if not reportRecords:
            rows = [["Week"], ["Date"], ["Venue"], ["Day"], ["Name"]]
            if includeAttendanceTotal:
                for row in rows[:4]:
                    row.append("")
                rows[4].append("Total Attended")
            return rows

        pollSessions = self.buildPollSessions(reportRecords)
        maxWeek = max(session.weekNumber for session in pollSessions.values())

        sessionsByWeek: dict[int, list[PollSession]] = {}
        for session in pollSessions.values():
            sessionsByWeek.setdefault(session.weekNumber, []).append(session)

        for week in sessionsByWeek.values():
            week.sort(
                key=lambda session: self.parseSessionDateText(session.sessionDateText)
                or datetime.max
            )

        weekHeader = ["Week"]
        dateHeader = ["Date"]
        venueHeader = ["Venue"]
        dayHeader = ["Day"]
        sessionHeader = ["Name"]
        columns: list[PollSession] = []

        for weekNumber in range(1, maxWeek + 1):
            for index, session in enumerate(sessionsByWeek.get(weekNumber, [])):
                weekHeader.append(f"week {weekNumber}" if index == 0 else "")
                dateHeader.append(self.formatSessionDateText(session.sessionDateText))
                venueHeader.append(session.venueName)
                sessionDate = self.parseSessionDateText(session.sessionDateText)
                dayHeader.append(sessionDate.strftime("%A") if sessionDate else "")
                sessionHeader.append(session.sessionName)
                columns.append(session)

        if includeAttendanceTotal:
            weekHeader.append("")
            dateHeader.append("")
            venueHeader.append("")
            dayHeader.append("")
            sessionHeader.append("Total Attended")

        scheduledRecords = [
            record
            for record in records
            if record.sessionStatus is SessionStatus.SCHEDULED and record.voterName
        ]
        voterNames = sorted(
            {record.voterName for record in scheduledRecords}, key=str.casefold
        )
        attendance = self.buildAttendanceLookup(scheduledRecords, pollSessions)

        rows = [weekHeader, dateHeader, venueHeader, dayHeader, sessionHeader]
        if includeCancelled and any(
            session.sessionStatus is SessionStatus.CANCELLED for session in columns
        ):
            cancelledRow = ["Cancelled"] + [
                "cancelled" if session.sessionStatus is SessionStatus.CANCELLED else ""
                for session in columns
            ]
            if includeAttendanceTotal:
                cancelledRow.append("")
            rows.append(cancelledRow)

        for voter in voterNames:
            statuses = [
                (
                    ""
                    if session.sessionStatus is SessionStatus.CANCELLED
                    else attendance.get((voter, session.pollKey), "")
                )
                for session in columns
            ]
            row = [voter] + statuses
            if includeAttendanceTotal:
                row.append(str(statuses.count("yes")))
            rows.append(row)

        sessionTotalRow = ["Session Total"] + [
            (
                ""
                if session.sessionStatus is SessionStatus.CANCELLED
                else str(
                    sum(
                        attendance.get((voter, session.pollKey), "") == "yes"
                        for voter in voterNames
                    )
                )
            )
            for session in columns
        ]
        if includeAttendanceTotal:
            sessionTotalRow.append("")
        rows.append(sessionTotalRow)

        return rows

    # ## session utilities
    def buildAttendanceLookup(
        self,
        records: list[PollRecord],
        pollSessions: OrderedDict[str, PollSession],
    ) -> dict[tuple[str, str], str]:
        attendance: dict[tuple[str, str], str] = {}
        for record in records:
            pollSession = self.matchPollSession(record, pollSessions)
            if (
                pollSession is None
                or pollSession.sessionStatus is SessionStatus.CANCELLED
            ):
                continue
            key = (record.voterName, pollSession.pollKey)
            current = attendance.get(key, "")

            if record.option.lower() == "yes":
                attendance[key] = "yes"
            elif record.option.lower() == "no" and current != "yes":
                attendance[key] = "no"

        return attendance

    def matchPollSession(
        self,
        record: PollRecord,
        pollSessions: OrderedDict[str, PollSession],
    ) -> PollSession | None:
        matchingDate = [
            session
            for session in pollSessions.values()
            if session.sessionDateText == record.sessionDateText
        ]
        if len(matchingDate) == 1:
            return matchingDate[0]

        _timeText, venueName = self.parser.extractSessionParts(record.pollTitle)
        sessionName = self.parser.extractSessionName(record.pollTitle)
        matchingMetadata = [
            session
            for session in matchingDate
            if session.venueName.casefold() == venueName.casefold()
            and session.sessionName.casefold() == sessionName.casefold()
        ]
        if len(matchingMetadata) == 1:
            return matchingMetadata[0]

        return pollSessions.get(self.buildPollKey(record))

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
            _timeText, venueName = self.parser.extractSessionParts(record.pollTitle)
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
                venueName=venueName,
                sessionStatus=record.sessionStatus,
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
        sessionDate = self.parseSessionDateText(sessionDateText)
        if sessionDate:
            return sessionDate.strftime("%d/%m/%y")
        return sessionDateText

    def parseSessionDateText(self, sessionDateText: str) -> datetime | None:
        if not sessionDateText:
            return None

        for fmt in ("%Y%m%d %H:%M", "%Y%m%d"):
            try:
                return datetime.strptime(sessionDateText, fmt)
            except ValueError:
                continue

        return None
