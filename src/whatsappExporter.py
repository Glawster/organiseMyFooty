from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import csv
import json

from attendanceConfig import RuntimeConfig, writeCsv
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsappSelectors import DEFAULT_SELECTORS, WhatsAppSelectors

from whatsappBrowser import WhatsAppPollScraper
from whatsappCache import PollCacheStore
from whatsappParsing import PollTextParser
from whatsappReports import AttendanceReportBuilder

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
        self.logger.info("starting export for group: %s", self.config.groupName)
        self.logger.info("month window: %s", self.config.monthWindow.monthKey)
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
        self.writePreviewJson(rawRows, summaryRows, reportRows)
        self.logger.done("attendance export")

    # ## csv write utilities
    def writeAttendanceReportCsv(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

    def writePollRows(self, rawRows: list[dict]) -> None:
        self.logger.action("write polls.csv rows: %s", len(rawRows))
        if self.config.dryRun:
            return

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
        self.logger.action(
            "write attendanceReport.csv rows: %s", max(0, len(reportRows) - 3)
        )
        if self.config.dryRun:
            return

        self.writeAttendanceReportCsv(
            self.config.outputDir / "attendanceReport.csv",
            reportRows,
        )

    def writeSummaryRows(self, summaryRows: list[dict]) -> None:
        self.logger.action("write attendanceSummary.csv rows: %s", len(summaryRows))
        if self.config.dryRun:
            return

        writeCsv(
            self.config.outputDir / "attendanceSummary.csv",
            summaryRows,
            ["name", "yesCount", "noCount", "totalVotes", "pollsResponded"],
        )

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
            "month": self.config.monthWindow.monthKey,
            "rawPollRows": rawRows,
            "summaryRows": summaryRows,
            "attendanceReportRows": reportRows,
        }

        self.logger.action("write preview json: %s", previewPath)
        if self.config.dryRun:
            return

        previewPath.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
