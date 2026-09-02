from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import csv
import json

from attendanceConfig import RuntimeConfig, writeCsv
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.contactDirectory import WhatsAppContactDirectory
from whatsapp.contactStore import ContactStore
from whatsapp.models import PollRecord, SessionStatus
from whatsapp.selectors import DEFAULT_SELECTORS, WhatsAppSelectors

from whatsapp.scraper import WhatsAppPollScraper
from whatsapp.parsing import PollTextParser
from whatsapp.reports import AttendanceReportBuilder
from whatsapp.store import AttendanceStore

logger = getLogger()


class AttendanceExporter:
    def __init__(
        self, config: RuntimeConfig, selectors: WhatsAppSelectors | None = None
    ):
        self.config = config
        self.selectors = selectors or DEFAULT_SELECTORS
        self.logger = logger

        self.parser = PollTextParser(config=self.config, selectors=self.selectors)
        self.attendanceStore = AttendanceStore(
            self.config.attendanceStorePath, self.parser
        ).open()
        self.reportBuilder = AttendanceReportBuilder(parser=self.parser)
        self.pollScraper = WhatsAppPollScraper(
            config=self.config,
            selectors=self.selectors,
            parser=self.parser,
            attendanceStore=self.attendanceStore,
        )

    def getMonthStampedPath(self, stem: str, suffix: str) -> Path:
        return (
            self.config.outputDir / f"{stem}-{self.config.monthWindow.monthKey}{suffix}"
        )

    @property
    def contactStorePath(self) -> Path:
        return self.config.outputDir / "contacts.sqlite3"

    # ## export orchestration
    def run(self) -> None:
        self.logger.doing("attendance export")
        self.logger.info(
            "starting export for group(s): %s",
            ", ".join(self.config.effectiveGroupNames),
        )
        self.logger.info("month window: %s", self.config.monthWindow.monthKey)
        self.logger.info("only including polls within configured month window")
        self.logger.info("output dir: %s", self.config.outputDir)

        self.logger.info("attendance store: %s", self.config.attendanceStorePath)
        self.logger.info("contact store: %s", self.contactStorePath)
        self.logger.info(
            "scan mode: %s; cutoff: %s",
            "override" if self.config.override else "reaction-aware rescan",
            self.config.scanSince.isoformat() if self.config.scanSince else "none",
        )

        contactPhones = self.loadContactPhones()
        scannedRecords = self.pollScraper.collectPollAttendance()
        voterPhones = dict(contactPhones)
        voterPhones.update(self.pollScraper.recordsBuilder.voterPhones)
        voterPhones.update(self.buildVoterPhoneLookup(scannedRecords))

        records = self.attendanceStore.attendanceRecords(
            self.config.monthWindow.startDate, self.config.monthWindow.endDate
        )
        storedSessionRecords = self.buildReportSessionRecords()
        currentSourceRecords = (
            getattr(self.pollScraper, "currentScanRecords", []) or scannedRecords
        )
        currentSessionRecords = self.buildCurrentSessionRecords(currentSourceRecords)
        sessionRecords = self.mergeReportSessionRecords(
            storedSessionRecords, currentSessionRecords
        )
        cancelledRecords = [
            record
            for record in sessionRecords
            if record.sessionStatus is SessionStatus.CANCELLED
        ]
        reportRecords = records + cancelledRecords
        self.logger.info("poll vote rows collected: %s", len(records))
        self.logger.info("sessions in report: %s", len(sessionRecords))
        self.logger.info("cancelled sessions in report: %s", len(cancelledRecords))

        rawRows = [asdict(record) for record in reportRecords]
        summaryRows = self.reportBuilder.buildSummaryRows(records)
        reportRows = self.reportBuilder.buildAttendanceReportRows(
            records,
            includeAttendanceTotal=True,
            includeCancelled=True,
            sessionRecords=sessionRecords,
        )
        self.logChangeSummary()

        if not sessionRecords:
            self.logger.warning(
                "no session rows collected; exports will not be overwritten"
            )
            self.logger.done("attendance export")
            return

        self.writeSummaryRows(summaryRows)
        self.writeReportRows(reportRows)
        self.writeSocialMediaSummaryText(reportRows, voterPhones=voterPhones)
        self.writePreviewJson(rawRows, summaryRows, reportRows)
        self.logger.done("attendance export")

    def getContacts(self) -> int:
        """Refresh the private WhatsApp contact database without scanning polls."""
        contactStore = ContactStore(self.contactStorePath).open()
        try:
            return WhatsAppContactDirectory(
                config=self.config,
                selectors=self.selectors,
                store=contactStore,
            ).refresh()
        finally:
            contactStore.close()

    def loadContactPhones(self) -> dict[str, str]:
        """Read previously captured contact phones without opening WhatsApp contacts."""
        contactStore = ContactStore(self.contactStorePath).open()
        try:
            return contactStore.phoneLookup()
        finally:
            contactStore.close()

    def buildReportSessionRecords(self) -> list[PollRecord]:
        """Build one report-column record for every persisted session."""
        records: list[PollRecord] = []
        sessions = self.attendanceStore.sessionsInRange(
            self.config.monthWindow.startDate, self.config.monthWindow.endDate
        )
        for session in sessions:
            source = self.attendanceStore.connection.execute(
                """SELECT source_title, poll_date, source_hint
                   FROM session_sources WHERE session_id=?
                   ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (int(session["id"]),),
            ).fetchone()
            sessionDate = datetime.strptime(str(session["session_date"]), "%Y-%m-%d")
            startTime = str(session["start_time"] or "").strip()
            venue = str(session["venue"] or "").strip()
            pollTitle = str(source["source_title"] or "").strip() if source else ""
            if not pollTitle:
                titleTime = self.formatPollTitleTime(startTime)
                pollTitle = f"{sessionDate.strftime('%A')} {titleTime} {venue}".strip()
            pollDateText = (
                str(source["poll_date"] or "").strip() if source else ""
            ) or sessionDate.strftime("%Y%m%d")
            sourceHint = (
                str(source["source_hint"] or "").strip() if source else ""
            ) or f"session:{session['id']}"
            sessionDateText = sessionDate.strftime("%Y%m%d")
            if startTime:
                sessionDateText += f" {startTime}"
            status = (
                SessionStatus.CANCELLED
                if str(session["status"]) == SessionStatus.CANCELLED.value
                else SessionStatus.SCHEDULED
            )
            records.append(
                PollRecord(
                    pollTitle=pollTitle,
                    pollDateText=pollDateText,
                    sessionDateText=sessionDateText,
                    option="",
                    voterName="",
                    sourceHint=sourceHint,
                    sessionStatus=status,
                )
            )
        return records

    def buildCurrentSessionRecords(self, records: list[PollRecord]) -> list[PollRecord]:
        """Reduce current scan rows to one status-bearing record per session."""
        bySession: dict[str, PollRecord] = {}
        for record in records:
            key = self.buildSessionMergeKey(record)
            previous = bySession.get(key)
            if previous is None or record.sessionStatus is SessionStatus.CANCELLED:
                bySession[key] = PollRecord(
                    pollTitle=record.pollTitle,
                    pollDateText=record.pollDateText,
                    sessionDateText=record.sessionDateText,
                    option="",
                    voterName="",
                    sourceHint=record.sourceHint,
                    sessionStatus=record.sessionStatus,
                )
        return list(bySession.values())

    def mergeReportSessionRecords(
        self,
        storedRecords: list[PollRecord],
        currentRecords: list[PollRecord],
    ) -> list[PollRecord]:
        """Merge complete stored sessions with current reaction state."""
        recordsBySession = {
            self.buildSessionMergeKey(record): record for record in storedRecords
        }
        for record in currentRecords:
            key = self.buildSessionMergeKey(record)
            existing = recordsBySession.get(key)
            if existing is None or record.sessionStatus is SessionStatus.CANCELLED:
                recordsBySession[key] = record
        return sorted(
            recordsBySession.values(),
            key=lambda record: (
                record.sessionDateText or "99999999",
                record.pollTitle.casefold(),
            ),
        )

    def buildSessionMergeKey(self, record: PollRecord) -> str:
        _timeText, venue = self.parser.extractSessionParts(record.pollTitle)
        sessionName = self.parser.extractSessionName(record.pollTitle)
        return "|".join(
            (
                record.sessionDateText,
                venue.casefold(),
                sessionName.casefold(),
            )
        )

    def formatPollTitleTime(self, timeText: str) -> str:
        if not timeText:
            return ""
        try:
            value = datetime.strptime(timeText, "%H:%M")
        except ValueError:
            return timeText
        hour = value.strftime("%I").lstrip("0") or "12"
        minute = value.strftime("%M")
        suffix = value.strftime("%p").lower()
        return f"{hour}{suffix}" if minute == "00" else f"{hour}:{minute}{suffix}"

    def logChangeSummary(self) -> None:
        changes = self.attendanceStore.summary
        self.logger.info(
            "attendance changes: sessions +%s ~%s -%s =%s; members +%s ~%s -%s =%s; attendance +%s ~%s -%s =%s conflicts=%s",
            changes.sessionsAdded,
            changes.sessionsUpdated,
            changes.sessionsRemoved,
            changes.sessionsUnchanged,
            changes.membersAdded,
            changes.membersUpdated,
            changes.membersRemoved,
            changes.membersUnchanged,
            changes.attendanceAdded,
            changes.attendanceUpdated,
            changes.attendanceRemoved,
            changes.attendanceUnchanged,
            changes.attendanceConflicted,
        )

    # ## csv write utilities
    def writeAttendanceReportCsv(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

    def writeReportRows(self, reportRows: list[list[str]]) -> None:
        reportPath = self.getMonthStampedPath("attendanceReport", ".csv")
        ignoredLabels = {"session total", "cancelled"}
        attendeeRowCount = sum(
            bool(
                row
                and row[0].strip()
                and row[0].strip().casefold() not in ignoredLabels
            )
            for row in reportRows[5:]
        )
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping attendanceReport.csv write (%s rows): %s",
                attendeeRowCount,
                reportPath,
            )
            return
        self.logger.action(
            "write attendanceReport.csv rows: %s: %s", attendeeRowCount, reportPath
        )
        self.writeAttendanceReportCsv(reportPath, reportRows)

    def writeSummaryRows(self, summaryRows: list[dict]) -> None:
        summaryPath = self.getMonthStampedPath("attendanceSummary", ".csv")
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping attendanceSummary.csv write (%s rows): %s",
                len(summaryRows),
                summaryPath,
            )
            return
        self.logger.action(
            "write attendanceSummary.csv rows: %s: %s",
            len(summaryRows),
            summaryPath,
        )
        writeCsv(
            summaryPath,
            summaryRows,
            ["name", "yesCount", "noCount", "totalVotes", "pollsResponded"],
        )

    # ## social media summary utilities
    def buildSocialMediaDisplayName(
        self, voterName: str, voterPhones: dict[str, str]
    ) -> str:
        """Add a compact phone suffix only when the captured name is one word."""
        if len(voterName.split()) != 1:
            return voterName

        phone = voterPhones.get(voterName.casefold(), "")
        if not phone:
            return voterName

        return f"{voterName} ({self.maskPhoneNumber(phone)})"

    def buildSocialMediaSummaryText(
        self,
        reportRows: list[list[str]],
        voterPhones: dict[str, str] | None = None,
    ) -> str:
        if len(reportRows) < 6:
            return "Attendance summary unavailable."

        dateRow = reportRows[1]
        datedIndexes = [
            index for index, value in enumerate(dateRow[1:], start=1) if value.strip()
        ]
        if not datedIndexes:
            return "Attendance summary unavailable."

        cancelledRow = next(
            (
                row
                for row in reportRows[5:]
                if row and row[0].strip().casefold() == "cancelled"
            ),
            None,
        )
        sessionIndexes = [
            index
            for index in datedIndexes
            if not cancelledRow
            or index >= len(cancelledRow)
            or cancelledRow[index].strip().casefold() != "cancelled"
        ]
        if not sessionIndexes:
            return "Attendance summary unavailable."

        title = self.buildSocialMediaSummaryTitle(dateRow, sessionIndexes)
        totalSessions = len(sessionIndexes)
        sessionLabel = "session" if totalSessions == 1 else "sessions"
        lines = [title, f"{totalSessions} {sessionLabel}"]
        ignoredLabels = {"session total", "cancelled"}
        voterRows = [
            row
            for row in reportRows[5:]
            if row and row[0].strip() and row[0].strip().casefold() not in ignoredLabels
        ]
        voterPhones = voterPhones or {}
        displayNames = [
            self.buildSocialMediaDisplayName(row[0].strip(), voterPhones)
            for row in voterRows
        ]
        voterNameWidth = max((len(name) for name in displayNames), default=0)
        yesCountWidth = len(str(totalSessions))

        for row, displayName in zip(voterRows, displayNames):
            statuses = [
                row[index].strip().lower() if index < len(row) else ""
                for index in sessionIndexes
            ]
            yesCount = statuses.count("yes")
            lines.append(
                f"- {displayName:<{voterNameWidth}}... "
                f"{yesCount:>{yesCountWidth}}/{totalSessions}"
            )

        return "\n".join(lines)

    def buildSocialMediaSummaryTitle(
        self, dateRow: list[str], sessionIndexes: list[int]
    ) -> str:
        for index in sessionIndexes:
            if index >= len(dateRow):
                continue
            dateText = dateRow[index].strip()
            if not dateText:
                continue
            try:
                sessionDate = datetime.strptime(dateText, "%d/%m/%y")
            except ValueError:
                continue
            return f"{sessionDate.strftime('%B %Y')} attendance summary"
        return "Attendance summary"

    def buildVoterPhoneLookup(self, records) -> dict[str, str]:
        """Build a case-insensitive phone lookup from records captured in this scan."""
        phones: dict[str, str] = {}
        for record in records:
            voterName = str(getattr(record, "voterName", "") or "").strip()
            voterPhone = str(getattr(record, "voterPhone", "") or "").strip()
            if voterName and voterPhone:
                phones[voterName.casefold()] = voterPhone
        return phones

    def maskPhoneNumber(self, phoneNumber: str) -> str:
        """Show the UK mobile prefix and final three digits only."""
        digits = "".join(character for character in phoneNumber if character.isdigit())
        if digits.startswith("44"):
            digits = "0" + digits[2:]
        if len(digits) <= 5:
            return digits
        return f"{digits[:2]}...{digits[-3:]}"

    def writeSocialMediaSummaryText(
        self,
        reportRows: list[list[str]],
        voterPhones: dict[str, str] | None = None,
    ) -> None:
        summaryPath = self.getMonthStampedPath("socialMediaSummary", ".txt")
        summaryText = self.buildSocialMediaSummaryText(
            reportRows, voterPhones=voterPhones
        )
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping socialMediaSummary.txt write: %s", summaryPath
            )
            return
        self.logger.action("write socialMediaSummary.txt: %s", summaryPath)
        summaryPath.write_text(summaryText + "\n", encoding="utf-8")

    # ## preview utilities
    def writePreviewJson(
        self,
        rawRows: list[dict],
        summaryRows: list[dict],
        reportRows: list[list[str]],
    ) -> None:
        previewPath = self.getMonthStampedPath("exportPreview", ".json")
        payload = {
            "groupName": self.config.groupName,
            "groupNames": list(self.config.effectiveGroupNames),
            "month": self.config.monthWindow.monthKey,
            "rawPollRows": rawRows,
            "summaryRows": summaryRows,
            "attendanceReportRows": reportRows,
        }
        if self.config.dryRun:
            self.logger.info("dry run: skipping preview json write: %s", previewPath)
            return
        self.logger.action("write preview json: %s", previewPath)
        previewPath.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
