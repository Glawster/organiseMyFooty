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
from whatsapp.cache import PollCacheStore
from whatsapp.parsing import PollTextParser
from whatsapp.reports import AttendanceReportBuilder

logger = getLogger()


class AttendanceExporter:
    def __init__(
        self, config: RuntimeConfig, selectors: WhatsAppSelectors | None = None
    ):
        self.config = config
        self.selectors = selectors or DEFAULT_SELECTORS
        self.logger = logger

        self.parser = PollTextParser(config=self.config, selectors=self.selectors)
        self.cacheStore = PollCacheStore(config=self.config, parser=self.parser)
        self.reportBuilder = AttendanceReportBuilder(parser=self.parser)
        self.pollScraper = WhatsAppPollScraper(
            config=self.config,
            selectors=self.selectors,
            parser=self.parser,
            cacheStore=self.cacheStore,
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

        records = self.pollScraper.collectPollAttendance()
        self.logger.info("poll vote rows collected: %s", len(records))

        rawRows = [asdict(record) for record in records]
        summaryRows = self.reportBuilder.buildSummaryRows(records)
        reportRows = self.reportBuilder.buildAttendanceReportRows(records)

        if not rawRows:
            self.logger.warning(
                "no poll rows collected; exports will not be overwritten"
            )
            return

        self.writePollRows(rawRows)
        self.writeSummaryRows(summaryRows)
        self.writeReportRows(reportRows)
        self.writeSocialMediaSummaryText(reportRows)
        self.writePreviewJson(rawRows, summaryRows, reportRows)
        self.logger.done("attendance export")

    # ## csv write utilities
    def writeAttendanceReportCsv(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

    def writePollRows(self, rawRows: list[dict]) -> None:
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping polls.csv write (%s rows)", len(rawRows)
            )
            return
        self.logger.action("write polls.csv rows: %s", len(rawRows))

        writeCsv(
            self.config.outputDir / "polls.csv",
            rawRows,
            [
                "pollTitle",
                "pollDateText",
                "sessionDateText",
                "option",
                "voterName",
                "sourceHint",
            ],
        )

    def writeReportRows(self, reportRows: list[list[str]]) -> None:
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping attendanceReport.csv write (%s rows)",
                max(0, len(reportRows) - 3),
            )
            return
        self.logger.action(
            "write attendanceReport.csv rows: %s", max(0, len(reportRows) - 3)
        )

        self.writeAttendanceReportCsv(
            self.config.outputDir / "attendanceReport.csv",
            reportRows,
        )

    def writeSummaryRows(self, summaryRows: list[dict]) -> None:
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping attendanceSummary.csv write (%s rows)",
                len(summaryRows),
            )
            return
        self.logger.action("write attendanceSummary.csv rows: %s", len(summaryRows))

        writeCsv(
            self.config.outputDir / "attendanceSummary.csv",
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
        voterRows = [row for row in reportRows[5:] if row and row[0].strip()]
        voterNameWidth = max((len(row[0].strip()) for row in voterRows), default=0)

        for row in voterRows:
            voterName = row[0].strip()

            statuses = [
                row[index].strip().lower() if index < len(row) else ""
                for index in sessionIndexes
            ]
            yesCount = statuses.count("yes")

            lines.append(
                f"{voterName:<{voterNameWidth}} ... " f"{yesCount}/{totalSessions}"
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
        summaryPath = self.config.outputDir / "socialMediaSummary.txt"
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
        previewPath = self.config.outputDir / "exportPreview.json"
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
