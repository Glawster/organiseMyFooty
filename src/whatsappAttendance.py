from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
import csv
import json
import re
import time

from attendanceConfig import RuntimeConfig, writeCsv
from whatsappSelectors import DEFAULT_SELECTORS, WhatsAppSelectors

from organiseMyProjects.logUtils import getLogger

logger = getLogger()

POLL_CACHE_VERSION = 1
RECENT_POLLS_TO_RECHECK = 2
IGNORE_POLL_CACHE = True  # temporary while stabilising poll discovery


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


class AttendanceExporter:
    def __init__(
        self, config: RuntimeConfig, selectors: WhatsAppSelectors | None = None
    ):
        self.config = config
        self.selectors = selectors or DEFAULT_SELECTORS
        self.logger = logger

    def run(self) -> None:
        self.logger.doing("attendance export")
        self.logger.info("starting export for group: %s", self.config.groupName)
        self.logger.info("month window: %s", self.config.monthWindow.monthKey)
        self.logger.info("output dir: %s", self.config.outputDir)

        records = self.collectPollAttendance()
        self.logger.info("poll vote rows collected: %s", len(records))

        rawRows = [asdict(record) for record in records]
        summaryRows = self.buildSummaryRows(records)
        reportRows = self.buildAttendanceReportRows(records)

        if not rawRows:
            self.logger.warning(
                "no poll rows collected; exports will not be overwritten"
            )
            return

        self.logger.action("write polls.csv rows: %s", len(rawRows))
        if not self.config.dryRun:
            writeCsv(
                self.config.outputDir / "polls.csv",
                rawRows,
                ["pollTitle", "pollDateText", "option", "voterName", "sourceHint"],
            )

        self.logger.action("write attendanceSummary.csv rows: %s", len(summaryRows))
        if not self.config.dryRun:
            writeCsv(
                self.config.outputDir / "attendanceSummary.csv",
                summaryRows,
                ["name", "yesCount", "noCount", "totalVotes", "pollsResponded"],
            )

        self.logger.action(
            "write attendanceReport.csv rows: %s", max(0, len(reportRows) - 2)
        )
        if not self.config.dryRun:
            self.writeAttendanceReportCsv(
                self.config.outputDir / "attendanceReport.csv",
                reportRows,
            )

        self.writePreviewJson(rawRows, summaryRows, reportRows)
        self.logger.done("attendance export")

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
        if not self.config.dryRun:
            previewPath.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def writeAttendanceReportCsv(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

    def getPollCachePath(self) -> Path:
        return self.config.outputDir / "pollCache.json"

    def loadPollCache(self) -> OrderedDict[str, list[PollRecord]]:
        if IGNORE_POLL_CACHE:
            self.logger.info("poll cache ignored")
            return OrderedDict()

        cachePath = self.getPollCachePath()
        if not cachePath.exists():
            return OrderedDict()

        try:
            payload = json.loads(cachePath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.logger.warning(
                "poll cache is not valid json and will be ignored: %s", cachePath
            )
            return OrderedDict()

        if payload.get("version") != POLL_CACHE_VERSION:
            self.logger.info("ignoring old poll cache version: %s", cachePath)
            return OrderedDict()

        if payload.get("groupName") != self.config.groupName:
            self.logger.info("ignoring poll cache for different group: %s", cachePath)
            return OrderedDict()

        if payload.get("month") != self.config.monthWindow.monthKey:
            self.logger.info("ignoring poll cache for different month: %s", cachePath)
            return OrderedDict()

        cachedPolls: OrderedDict[str, list[PollRecord]] = OrderedDict()
        rawPolls = payload.get("polls", {})
        if not isinstance(rawPolls, dict):
            return cachedPolls

        for pollKey, rawRecords in rawPolls.items():
            if not isinstance(rawRecords, list):
                continue
            records = self.recordsFromCacheRows(rawRecords)
            if records:
                cachedPolls[pollKey] = records

        self.logger.info("loaded cached poll result(s): %s", len(cachedPolls))
        return cachedPolls

    def savePollCache(
        self, recordsByPollKey: OrderedDict[str, list[PollRecord]]
    ) -> None:
        cachePath = self.getPollCachePath()

        if not recordsByPollKey:
            self.logger.warning(
                "poll cache not written because no poll records were scraped"
            )
            return

        self.logger.action("write poll cache: %s", cachePath)
        if not self.config.dryRun:
            cachePath.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": POLL_CACHE_VERSION,
                "groupName": self.config.groupName,
                "month": self.config.monthWindow.monthKey,
                "savedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "recentPollsToRecheck": RECENT_POLLS_TO_RECHECK,
                "polls": {
                    pollKey: [asdict(record) for record in records]
                    for pollKey, records in recordsByPollKey.items()
                },
            }
            cachePath.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def recordsFromCacheRows(self, rows: list[dict]) -> list[PollRecord]:
        records: list[PollRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                records.append(
                    PollRecord(
                        pollTitle=str(row["pollTitle"]),
                        pollDateText=str(row["pollDateText"]),
                        option=str(row["option"]),
                        voterName=str(row["voterName"]),
                        sourceHint=str(row["sourceHint"]),
                    )
                )
            except KeyError:
                continue
        return self.deduplicateRecords(records)

    def flattenCachedPolls(
        self, recordsByPollKey: OrderedDict[str, list[PollRecord]]
    ) -> list[PollRecord]:
        records: list[PollRecord] = []
        for pollRecords in recordsByPollKey.values():
            records.extend(pollRecords)
        return self.deduplicateRecords(records)

    def shouldRecheckPoll(self, index: int, totalPolls: int) -> bool:
        return index > max(0, totalPolls - RECENT_POLLS_TO_RECHECK)

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
        return self.buildPollKeyFromParts(
            pollTitle=record.pollTitle,
            pollDateText=record.pollDateText,
            sourceHint=record.sourceHint,
        )

    def buildPollKeyFromParts(
        self, pollTitle: str, pollDateText: str, sourceHint: str
    ) -> str:
        return f"{pollTitle}|{pollDateText}|{sourceHint[:80]}"

    def buildPollKeyFromSourceText(self, sourceText: str) -> tuple[str, str, str]:
        pollTitle = self.extractPollTitle(sourceText=sourceText) or "unknown poll"
        pollDateText = self.extractLikelyDateText(sourceText) or ""
        pollKey = self.buildPollKeyFromParts(
            pollTitle=pollTitle,
            pollDateText=pollDateText,
            sourceHint=sourceText[:240],
        )
        return pollKey, pollTitle, pollDateText

    def extractSessionName(self, pollTitle: str) -> str:
        title = " ".join(pollTitle.split()).strip()
        return re.sub(r"\s+", " ", title) or "unknown session"

    def collectPollAttendance(self) -> list[PollRecord]:
        from playwright.sync_api import sync_playwright

        recordsByPollKey = self.loadPollCache()
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
                totalPolls = len(pollLocators)
                self.logger.info("candidate poll cards found: %s", totalPolls)

                for index, locator in enumerate(pollLocators, start=1):
                    if (
                        self.config.limitPolls is not None
                        and pollCount >= self.config.limitPolls
                    ):
                        self.logger.info(
                            "poll limit reached: %s", self.config.limitPolls
                        )
                        break

                    sourceText = self.extractPollSourceText(locator)

                    if (
                        self.config.pollTitleFilter
                        and self.config.pollTitleFilter.lower()
                        not in sourceText.lower()
                    ):
                        self.logger.info(
                            "skipping poll due to title filter: %s",
                            self.config.pollTitleFilter,
                        )
                        continue

                    pollKey, pollTitle, pollDateText = self.buildPollKeyFromSourceText(
                        sourceText
                    )
                    shouldRecheck = self.shouldRecheckPoll(index, totalPolls)
                    cachedRecords = recordsByPollKey.get(pollKey)

                    if cachedRecords and not shouldRecheck:
                        self.logger.info(
                            "using cached poll %s/%s: %s",
                            index,
                            totalPolls,
                            pollTitle,
                        )
                        pollCount += 1
                        continue

                    if cachedRecords and shouldRecheck:
                        self.logger.info(
                            "rechecking recent poll %s/%s: %s",
                            index,
                            totalPolls,
                            pollTitle,
                        )
                    else:
                        self.logger.info(
                            "opening poll %s/%s: %s",
                            index,
                            totalPolls,
                            pollTitle,
                        )

                    try:
                        if not self.openPollVotes(locator):
                            continue
                    except Exception as exc:
                        self.logger.warning("unable to open poll votes dialog: %s", exc)
                        continue

                    dialog = None
                    try:
                        dialog, dialogText = self.waitForDialog(page)
                        self.expandAllVoters(dialog)
                        dialogText = self.readDialogText(dialog, fallback=dialogText)

                        pollTitle = self.extractPollTitleFromDialog(dialogText) or (
                            self.extractPollTitle(dialog, sourceText=sourceText)
                            or "unknown poll"
                        )
                        pollDateText = self.extractLikelyDateText(sourceText) or ""
                        pollKey = self.buildPollKeyFromParts(
                            pollTitle=pollTitle,
                            pollDateText=pollDateText,
                            sourceHint=sourceText[:240],
                        )
                        pollRecords: list[PollRecord] = []

                        yesVoters = self.extractOptionVotersFromText(
                            dialogText, optionTexts=self.selectors.yesOptionTexts
                        )
                        for voterName in yesVoters:
                            pollRecords.append(
                                PollRecord(
                                    pollTitle=pollTitle,
                                    pollDateText=pollDateText,
                                    option="Yes",
                                    voterName=voterName,
                                    sourceHint=sourceText[:240],
                                )
                            )

                        if self.config.includeNoVotes:
                            noVoters = self.extractOptionVotersFromText(
                                dialogText, optionTexts=self.selectors.noOptionTexts
                            )
                            for voterName in noVoters:
                                pollRecords.append(
                                    PollRecord(
                                        pollTitle=pollTitle,
                                        pollDateText=pollDateText,
                                        option="No",
                                        voterName=voterName,
                                        sourceHint=sourceText[:240],
                                    )
                                )

                        recordsByPollKey[pollKey] = self.deduplicateRecords(pollRecords)
                        pollCount += 1
                    except Exception as exc:
                        self.logger.warning("unable to scrape poll votes: %s", exc)
                    finally:
                        self.closeDialog(page, dialog)

            finally:
                browserContext.close()

        self.savePollCache(recordsByPollKey)
        return self.flattenCachedPolls(recordsByPollKey)

    def waitForWhatsAppReady(self, page) -> None:
        page.wait_for_load_state("domcontentloaded")
        self.logger.info("waiting for WhatsApp Web to be ready")
        deadline = time.time() + max(60, self.config.timeoutMs / 1000)

        while time.time() < deadline:
            for selector in self.selectors.iterSearchSelectors():
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=1000):
                        self.logger.info("whatsapp ready via selector: %s", selector)
                        return
                except Exception:
                    continue
            time.sleep(1)

        raise TimeoutError(
            "whatsapp web did not become ready; make sure you are logged in"
        )

    def openGroup(self, page, groupName: str) -> None:
        self.logger.info("opening group: %s", groupName)

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
        self.logger.info("scrolling chat history to load older polls")
        for _ in range(scrollPasses):
            page.mouse.wheel(0, -2000)
            page.wait_for_timeout(500)

    def findPollCards(self, page) -> list:
        pollLocators: list = []
        seenKeys: set[str] = set()

        selectors = ('[data-testid="poll-view-votes"]',)

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                item = self.resolvePollButton(locator.nth(index))
                sourceText = self.extractPollSourceText(item)
                if self.selectors.viewVotesText.lower() not in sourceText.lower():
                    continue
                key = self.extractMessageKey(item) or f"{selector}|{sourceText[:120]}"
                if key in seenKeys:
                    continue
                seenKeys.add(key)
                pollLocators.append(item)

        return pollLocators

    def resolvePollButton(self, locator):
        try:
            text = locator.inner_text(timeout=500)
            if self.selectors.viewVotesText.lower() in text.lower():
                return locator
        except Exception:
            pass

        for selector in (
            '[data-testid="poll-view-votes"]',
            'div[role="button"]:has-text("View votes")',
            f'text="{self.selectors.viewVotesText}"',
        ):
            try:
                button = locator.locator(selector).first
                if button.is_visible(timeout=500):
                    return button
            except Exception:
                continue
        return locator

    def extractMessageKey(self, locator) -> str:
        for selector in (
            'xpath=ancestor-or-self::*[@data-testid][contains(@data-testid, "msg")][1]',
            "xpath=ancestor-or-self::*[@data-id][1]",
        ):
            try:
                value = locator.locator(selector).first.get_attribute(
                    "data-testid", timeout=1000
                )
                if value:
                    return value
            except Exception:
                pass
            try:
                value = locator.locator(selector).first.get_attribute(
                    "data-id", timeout=1000
                )
                if value:
                    return value
            except Exception:
                pass
        return ""

    def extractPollSourceText(self, locator) -> str:
        for selector in (
            'xpath=ancestor-or-self::*[@data-testid][contains(@data-testid, "msg")][1]',
            "xpath=ancestor-or-self::*[@data-id][1]",
            'xpath=ancestor::*[contains(., "View votes")][1]',
        ):
            try:
                text = locator.locator(selector).first.inner_text(timeout=1000)
                if text.strip():
                    return text
            except Exception:
                continue

        try:
            return locator.inner_text(timeout=1000)
        except Exception:
            return ""

    def waitForDialog(self, page):
        try:
            header = page.get_by_text("Poll details", exact=False).last
            header.wait_for(state="visible", timeout=3000)

            panel = header.locator("xpath=ancestor::*[contains(., 'members voted')][1]")
            panel.wait_for(state="visible", timeout=3000)

            text = panel.inner_text(timeout=3000)
            self.logger.value("poll panel sample", text[:300])
            return panel, text

        except Exception:
            self.logPollPanelDiagnostics(page)
            raise TimeoutError("unable to locate poll results panel")

    def readDialogText(self, dialog, fallback: str = "") -> str:
        try:
            text = dialog.inner_text(timeout=2000)
            return text if text.strip() else fallback
        except Exception:
            return fallback

    def logPollPanelDiagnostics(self, page) -> None:
        for textAnchor in ("Poll details", "View votes", "Yes", "No"):
            try:
                count = page.get_by_text(textAnchor, exact=False).count()
                self.logger.value(f"visible text count {textAnchor}", count)
            except Exception:
                continue

        try:
            bodyText = page.locator("body").inner_text(timeout=2000)
            self.logger.value("body text sample", bodyText[-500:])
        except Exception:
            pass

    def expandAllVoters(self, panel) -> None:
        for _ in range(5):
            try:
                buttons = panel.get_by_text("See all", exact=False)
                count = buttons.count()

                if count == 0:
                    return

                for i in range(count):
                    try:
                        btn = buttons.nth(i)
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=2000)
                            panel.page.wait_for_timeout(500)
                    except Exception:
                        continue

            except Exception:
                return

    def extractPollTitle(self, dialog=None, sourceText: str = "") -> str:
        ignoredLines = {
            "all",
            "view votes",
            "select one or more",
            "poll details",
            "yes",
            "no",
        }

        lines = [line.strip() for line in sourceText.splitlines() if line.strip()]

        for line in lines:
            lowered = line.lower()
            if lowered in ignoredLines:
                continue
            if self.looksLikeVoteCount(line):
                continue
            if re.search(r"\b\d{1,2}:\d{2}\b", line):
                continue
            return line

        return "unknown poll"

    def extractLikelyDateText(self, sourceText: str) -> str:
        match = re.search(self.selectors.likelyMessageTimePattern, sourceText)
        return match.group(0) if match else ""

    def extractOptionVoters(self, dialog, optionTexts: Iterable[str]) -> list[str]:
        try:
            dialogText = dialog.inner_text(timeout=2000)
        except Exception:
            return []
        return self.extractOptionVotersFromText(dialogText, optionTexts)

    def extractOptionVotersFromText(
        self, dialogText: str, optionTexts: Iterable[str]
    ) -> list[str]:
        optionNames = tuple(optionTexts)
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

    def extractPollTitleFromDialog(self, dialogText: str) -> str:
        ignoredLines = {
            "poll details",
            "yes",
            "no",
            "view votes",
            "select one or more",
        }

        for line in [line.strip() for line in dialogText.splitlines() if line.strip()]:
            lowered = line.lower()
            if lowered in ignoredLines:
                continue
            if "members voted" in lowered:
                continue
            if self.looksLikeVoteCount(line):
                continue
            return line

        return ""

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

    def openPollVotes(self, locator) -> bool:
        disabled = locator.get_attribute("aria-disabled", timeout=1000)
        if disabled == "true":
            self.logger.info("poll skipped disabled")
            return False

        locator.scroll_into_view_if_needed(timeout=self.config.timeoutMs)
        locator.click(timeout=self.config.timeoutMs)
        return True
