from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import csv
import json

from attendanceConfig import RuntimeConfig, writeCsv
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
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
        self.logger.info(
            "scan mode: %s; cutoff: %s",
            "override" if self.config.override else "captured-poll boundary",
            self.config.scanSince.isoformat() if self.config.scanSince else "none",
        )
        records = self.pollScraper.collectPollAttendance()
        records = self.attendanceStore.attendanceRecords(
            self.config.monthWindow.startDate, self.config.monthWindow.endDate
        )
        self.logger.info("poll vote rows collected: %s", len(records))

        rawRows = [asdict(record) for record in records]
        summaryRows = self.reportBuilder.buildSummaryRows(records)
        reportRows = self.reportBuilder.buildAttendanceReportRows(records)
        self.logChangeSummary()

        if not rawRows:
            self.logger.warning(
                "no poll rows collected; exports will not be overwritten"
            )
            self.logger.done("attendance export")
            return

        self.writeSummaryRows(summaryRows)
        self.writeReportRows(reportRows)
        self.writeSocialMediaSummaryText(reportRows)
        self.writePreviewJson(rawRows, summaryRows, reportRows)
        self.logger.done("attendance export")

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
        attendeeRowCount = sum(
            bool(
                row and row[0].strip() and row[0].strip().casefold() != "session total"
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

        self.writeAttendanceReportCsv(
            reportPath,
            reportRows,
        )

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
    def buildSocialMediaSummaryText(self, reportRows: list[list[str]]) -> str:
        if len(reportRows) < 6:
            return "Attendance summary unavailable."

        dateRow = reportRows[1]
        sessionIndexes = [
            index for index, value in enumerate(dateRow[1:], start=1) if value.strip()
        ]

        if not sessionIndexes:
            return "Attendance summary unavailable."

        title = self.buildSocialMediaSummaryTitle(dateRow, sessionIndexes)
        totalSessions = len(sessionIndexes)
        sessionLabel = "session" if totalSessions == 1 else "sessions"
        lines = [title, f"{totalSessions} {sessionLabel}"]
        voterRows = [
            row
            for row in reportRows[5:]
            if row and row[0].strip() and row[0].strip().casefold() != "session total"
        ]
        voterNameWidth = max((len(row[0].strip()) for row in voterRows), default=0)

        for row in voterRows:
            voterName = row[0].strip()

            statuses = [
                row[index].strip().lower() if index < len(row) else ""
                for index in sessionIndexes
            ]
            yesCount = statuses.count("yes")

            lines.append(
                f"- {voterName:<{voterNameWidth}}... " f"{yesCount}/{totalSessions}"
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

    def writeSocialMediaSummaryText(self, reportRows: list[list[str]]) -> None:
        summaryPath = self.getMonthStampedPath("socialMediaSummary", ".txt")
        summaryText = self.buildSocialMediaSummaryText(reportRows)

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
