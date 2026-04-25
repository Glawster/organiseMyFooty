from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional
import csv
import json
import re
import time

from attendanceConfig import RuntimeConfig, writeCsv
from whatsappSelectors import DEFAULT_SELECTORS, WhatsAppSelectors

try:
    from organiseMyProjects.logUtils import getLogger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    def getLogger(name: str):  # type: ignore
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger


@dataclass(frozen=True)
class PollRecord:
    pollTitle: str
    pollDateText: str
    option: str
    voterName: str
    sourceHint: str


@dataclass(frozen=True)
class PollSession:
    pollKey: str
    pollTitle: str
    weekNumber: int
    sessionName: str


class DryRunMixin:
    @property
    def prefix(self) -> str:
        return "...[] " if self.config.dryRun else "..."


class AttendanceExporter(DryRunMixin):
    def __init__(
        self, config: RuntimeConfig, selectors: WhatsAppSelectors | None = None
    ):
        self.config = config
        self.selectors = selectors or DEFAULT_SELECTORS
        self.logger = getLogger("organiseMyFooty.exportAttendance")

    def run(self) -> None:
        self.logger.info(
            "%sstarting export for group: %s", self.prefix, self.config.groupName
        )
        self.logger.info(
            "%smonth window: %s", self.prefix, self.config.monthWindow.monthKey
        )
        self.logger.info("%soutput dir: %s", self.prefix, self.config.outputDir)

        if self.config.dryRun:
            self.logger.info(
                "%sdry run enabled; browser automation will inspect the UI but will not overwrite exports",
                self.prefix,
            )

        records = self.collectPollAttendance()
        self.logger.info("%spoll vote rows collected: %s", self.prefix, len(records))

        rawRows = [asdict(record) for record in records]
        summaryRows = self.buildSummaryRows(records)
        reportRows = self.buildAttendanceReportRows(records)

        if self.config.dryRun:
            self.logger.info(
                "%swould write polls.csv rows: %s", self.prefix, len(rawRows)
            )
            self.logger.info(
                "%swould write attendanceSummary.csv rows: %s",
                self.prefix,
                len(summaryRows),
            )
            self.logger.info(
                "%swould write attendanceReport.csv rows: %s",
                self.prefix,
                max(0, len(reportRows) - 2),
            )
            self.writePreviewJson(rawRows, summaryRows, reportRows)
            return

        writeCsv(
            self.config.outputDir / "polls.csv",
            rawRows,
            ["pollTitle", "pollDateText", "option", "voterName", "sourceHint"],
        )
        writeCsv(
            self.config.outputDir / "attendanceSummary.csv",
            summaryRows,
            ["name", "yesCount", "noCount", "totalVotes", "pollsResponded"],
        )
        self.writeAttendanceReportCsv(
            self.config.outputDir / "attendanceReport.csv",
            reportRows,
        )
        self.writePreviewJson(rawRows, summaryRows, reportRows)
        self.logger.info("%sexport complete", self.prefix)

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
        if self.config.dryRun:
            self.logger.info("%swould write preview json: %s", self.prefix, previewPath)
            return

        previewPath.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def writeAttendanceReportCsv(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

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
            row["pollsResponded"].add(f"{record.pollTitle}|{record.pollDateText}")  # type: ignore[union-attr]

        outputRows: list[dict] = []
        for voterName in sorted(summary, key=str.casefold):
            row = summary[voterName]
            outputRows.append(
                {
                    "name": voterName,
                    "yesCount": int(row["yesCount"]),
                    "noCount": int(row["noCount"]),
                    "totalVotes": int(row["totalVotes"]),
                    "pollsResponded": len(row["pollsResponded"]),  # type: ignore[arg-type]
                }
            )
        return outputRows

    def buildAttendanceReportRows(self, records: list[PollRecord]) -> list[list[str]]:
        """Build a two-row-header report with dynamic sessions.

        Sessions are discovered from scraped poll titles. Week numbers are inferred
        per repeated session name: the first poll for a session is week 1, the
        second poll for that same session is week 2, and so on.
        """
        if not records:
            return [[""], ["name"]]

        pollSessions = self.buildPollSessions(records)
        sessionNames = self.extractOrderedSessionNames(pollSessions)
        maxWeek = max(session.weekNumber for session in pollSessions.values())

        weekHeader = [""]
        sessionHeader = ["name"]
        for weekNumber in range(1, maxWeek + 1):
            for sessionIndex, sessionName in enumerate(sessionNames):
                weekHeader.append(f"week {weekNumber}" if sessionIndex == 0 else "")
                sessionHeader.append(sessionName)

        voterNames = sorted({record.voterName for record in records}, key=str.casefold)
        attendance = self.buildAttendanceLookup(records, pollSessions)

        rows = [weekHeader, sessionHeader]
        for voterName in voterNames:
            row = [voterName]
            for weekNumber in range(1, maxWeek + 1):
                for sessionName in sessionNames:
                    row.append(attendance.get((voterName, weekNumber, sessionName), ""))
            rows.append(row)

        return rows

    def buildPollSessions(
        self, records: list[PollRecord]
    ) -> OrderedDict[str, PollSession]:
        pollKeys: OrderedDict[str, str] = OrderedDict()
        for record in records:
            pollKeys.setdefault(self.buildPollKey(record), record.pollTitle)

        sessionCounts: defaultdict[str, int] = defaultdict(int)
        pollSessions: OrderedDict[str, PollSession] = OrderedDict()

        for pollKey, pollTitle in pollKeys.items():
            sessionName = self.extractSessionName(pollTitle)
            sessionCounts[sessionName] += 1
            pollSessions[pollKey] = PollSession(
                pollKey=pollKey,
                pollTitle=pollTitle,
                weekNumber=sessionCounts[sessionName],
                sessionName=sessionName,
            )

        return pollSessions

    def extractOrderedSessionNames(
        self, pollSessions: OrderedDict[str, PollSession]
    ) -> list[str]:
        sessions: OrderedDict[str, None] = OrderedDict()
        for pollSession in pollSessions.values():
            sessions.setdefault(pollSession.sessionName, None)
        return list(sessions.keys())

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
        return f"{record.pollTitle}|{record.pollDateText}|{record.sourceHint[:80]}"

    def extractSessionName(self, pollTitle: str) -> str:
        title = " ".join(pollTitle.split()).strip()
        return re.sub(r"\s+", " ", title) or "unknown session"

    def collectPollAttendance(self) -> list[PollRecord]:
        from playwright.sync_api import sync_playwright

        records: list[PollRecord] = []
        pollCount = 0

        with sync_playwright() as playwright:
            browserContext = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.userDataDir),
                headless=self.config.headless,
                channel=self.config.browserChannel,
                viewport={"width": 1440, "height": 1100},
            )
            try:
                page = browserContext.new_page()
                page.goto(self.selectors.webUrl)
                self.waitForWhatsAppReady(page)
                self.openGroup(page, self.config.groupName)
                self.scrollChatHistory(page)

                pollLocators = self.findPollCards(page)
                self.logger.info(
                    "%scandidate poll cards found: %s", self.prefix, len(pollLocators)
                )

                for index, locator in enumerate(pollLocators, start=1):
                    if (
                        self.config.limitPolls is not None
                        and pollCount >= self.config.limitPolls
                    ):
                        self.logger.info(
                            "%spoll limit reached: %s",
                            self.prefix,
                            self.config.limitPolls,
                        )
                        break

                    try:
                        locator.scroll_into_view_if_needed(
                            timeout=self.config.timeoutMs
                        )
                        sourceText = locator.inner_text(timeout=self.config.timeoutMs)
                    except Exception:
                        sourceText = ""

                    if (
                        self.config.pollTitleFilter
                        and self.config.pollTitleFilter.lower()
                        not in sourceText.lower()
                    ):
                        self.logger.info(
                            "%sskipping poll due to title filter: %s",
                            self.prefix,
                            self.config.pollTitleFilter,
                        )
                        continue

                    self.logger.info("%sopening poll %s", self.prefix, index)
                    try:
                        locator.click(timeout=self.config.timeoutMs)
                    except Exception:
                        try:
                            locator.get_by_text(
                                self.selectors.viewVotesText, exact=False
                            ).click(timeout=self.config.timeoutMs)
                        except Exception as exc:
                            self.logger.warning(
                                "Unable to open poll votes dialog: %s", exc
                            )
                            continue

                    dialog = self.waitForDialog(page)
                    self.expandAllVoters(dialog)

                    pollTitle = (
                        self.extractPollTitle(dialog, sourceText=sourceText)
                        or "unknown poll"
                    )
                    pollDateText = self.extractLikelyDateText(sourceText) or ""

                    yesVoters = self.extractOptionVoters(
                        dialog, optionTexts=self.selectors.yesOptionTexts
                    )
                    for voterName in yesVoters:
                        records.append(
                            PollRecord(
                                pollTitle=pollTitle,
                                pollDateText=pollDateText,
                                option="Yes",
                                voterName=voterName,
                                sourceHint=sourceText[:240],
                            )
                        )

                    if self.config.includeNoVotes:
                        noVoters = self.extractOptionVoters(
                            dialog, optionTexts=self.selectors.noOptionTexts
                        )
                        for voterName in noVoters:
                            records.append(
                                PollRecord(
                                    pollTitle=pollTitle,
                                    pollDateText=pollDateText,
                                    option="No",
                                    voterName=voterName,
                                    sourceHint=sourceText[:240],
                                )
                            )

                    pollCount += 1
                    self.closeDialog(page, dialog)

            finally:
                browserContext.close()

        return self.deduplicateRecords(records)

    def waitForWhatsAppReady(self, page) -> None:
        page.wait_for_load_state("domcontentloaded")
        self.logger.info("%swaiting for WhatsApp Web to be ready...", self.prefix)
        deadline = time.time() + max(60, self.config.timeoutMs / 1000)

        while time.time() < deadline:
            for selector in self.selectors.iterSearchSelectors():
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=1000):
                        self.logger.info(
                            "%swhatsapp ready via selector: %s", self.prefix, selector
                        )
                        return
                except Exception:
                    continue
            time.sleep(1)

        raise TimeoutError(
            "whatsapp web did not become ready; make sure you are logged in"
        )

    def openGroup(self, page, groupName: str) -> None:
        self.logger.info("%sopening group: %s", self.prefix, groupName)

        lastError: Optional[Exception] = None
        for selector in self.selectors.iterSearchSelectors():
            try:
                searchBox = page.locator(selector).first
                searchBox.click(timeout=self.config.timeoutMs)
                searchBox.fill("")
                searchBox.type(groupName, delay=40)
                break
            except Exception as exc:
                lastError = exc
                continue
        else:
            raise RuntimeError(f"unable to find whatsapp search box: {lastError}")

        candidate = page.get_by_text(groupName, exact=True).first
        candidate.click(timeout=self.config.timeoutMs)

    def scrollChatHistory(self, page, scrollPasses: int = 12) -> None:
        self.logger.info("%sscrolling chat history to load older polls...", self.prefix)
        for _ in range(scrollPasses):
            page.mouse.wheel(0, -2000)
            page.wait_for_timeout(500)

    def findPollCards(self, page) -> list:
        pollLocators: list = []
        seenKeys: set[str] = set()

        for selector in self.selectors.iterPollSelectors():
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                item = locator.nth(index)
                try:
                    text = item.inner_text(timeout=1000)
                except Exception:
                    text = f"item-{index}"
                key = f"{selector}|{text[:120]}"
                if key in seenKeys:
                    continue
                seenKeys.add(key)
                pollLocators.append(item)

        return pollLocators

    def waitForDialog(self, page):
        for selector in self.selectors.iterDialogSelectors():
            try:
                dialog = page.locator(selector).last
                dialog.wait_for(state="visible", timeout=self.config.timeoutMs)
                return dialog
            except Exception:
                continue
        raise TimeoutError("unable to locate votes dialog")

    def expandAllVoters(self, dialog) -> None:
        """Expand all lazy-loaded voter rows inside the current poll dialog."""
        for _ in range(10):
            clicked = False
            try:
                buttons = dialog.get_by_text(re.compile(r"^See all", re.IGNORECASE))
                count = buttons.count()
            except Exception:
                break

            for index in range(count):
                try:
                    button = buttons.nth(index)
                    if button.is_visible(timeout=500):
                        button.click(timeout=self.config.timeoutMs)
                        dialog.page.wait_for_timeout(300)
                        clicked = True
                except Exception:
                    continue

            if not clicked:
                break

    def extractPollTitle(self, dialog, sourceText: str = "") -> str:
        lines = [line.strip() for line in sourceText.splitlines() if line.strip()]

        # Typical poll card text:
        # 0 = sender
        # 1 = poll title/session
        # 2 = Select one or more
        if len(lines) >= 2:
            return lines[1]
        if lines:
            return lines[0]
        return "unknown poll"

    def extractLikelyDateText(self, sourceText: str) -> str:
        match = re.search(self.selectors.likelyMessageTimePattern, sourceText)
        return match.group(0) if match else ""

    def extractOptionVoters(self, dialog, optionTexts: Iterable[str]) -> list[str]:
        """
        Heuristic extractor.

        The exact DOM for poll results may change. This implementation looks for
        a visible section with the option label, then collects person-like rows
        beneath it until the next option heading.
        """
        optionNames = tuple(optionTexts)
        dialogText = dialog.inner_text(timeout=self.config.timeoutMs)
        lines = [line.strip() for line in dialogText.splitlines() if line.strip()]

        captured: list[str] = []
        inSection = False

        for line in lines:
            if line in optionNames:
                inSection = True
                continue

            if inSection and line in set(
                self.selectors.yesOptionTexts + self.selectors.noOptionTexts
            ):
                break

            if inSection:
                if self.looksLikeVoteCount(line):
                    continue
                if self.looksLikeSystemText(line):
                    continue
                captured.append(line)

        return self.cleanVoterNames(captured)

    def looksLikeVoteCount(self, line: str) -> bool:
        lowered = line.lower().strip()
        compact = lowered.replace(" ", "")
        return compact.isdigit() or bool(re.fullmatch(r"\d+votes?", lowered))

    def looksLikeSystemText(self, line: str) -> bool:
        lowered = line.lower().strip()
        systemFragments = (
            "select one or more",
            "view votes",
            "poll details",
            "message",
        )
        return any(fragment in lowered for fragment in systemFragments)

    def cleanVoterNames(self, names: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()

        for name in names:
            value = " ".join(name.split()).strip()
            if not value:
                continue
            if len(value) > 80:
                continue
            if re.search(r"\b\d{1,2}:\d{2}\b", value):
                continue
            if value.lower() in {"yes", "no", "you"}:
                continue
            if value.lower().startswith("see all"):
                continue
            if value.lower().endswith("vote") or value.lower().endswith("votes"):
                continue
            if value.startswith("~ "):
                value = value[2:].strip()
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        return cleaned

    def closeDialog(self, page, dialog) -> None:
        for selector in self.selectors.closeDialogCandidates:
            try:
                control = page.locator(selector).first
                if control.is_visible(timeout=1000):
                    control.click(timeout=self.config.timeoutMs)
                    page.wait_for_timeout(400)
                    return
            except Exception:
                continue

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

    def deduplicateRecords(self, records: list[PollRecord]) -> list[PollRecord]:
        output: list[PollRecord] = []
        seen: set[tuple[str, str, str, str]] = set()
        for record in records:
            key = (
                record.pollTitle,
                record.pollDateText,
                record.option,
                record.voterName,
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(record)
        return output
