from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterable
import csv
import json
import re
import time

from attendanceConfig import RuntimeConfig, writeCsv
from whatsappSelectors import DEFAULT_SELECTORS, WhatsAppSelectors

DIALOG_POLL_INTERVAL_MS = 250  # Poll frequently without busy-waiting the browser page.


try:
    from organiseMyProjects.logUtils import getLogger as _logUtilsGetLogger  # type: ignore
except Exception:  # pragma: no cover
    _logUtilsGetLogger = None


def getLogger(name: str, dryRun: bool = False):  # type: ignore
    if _logUtilsGetLogger is not None:
        # Support both the richer organiseMyProjects logger signature and simpler
        # variants so console logging still works across installed versions.
        for kwargs in (
            {"includeConsole": True, "dryRun": dryRun},
            {"includeConsole": True},
            {},
        ):
            try:
                return _logUtilsGetLogger(name, **kwargs)
            except TypeError:
                continue

    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
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
class PollTarget:
    selector: str
    sourceText: str
    messageTestId: str = ""


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
        self.logger = getLogger(
            "organiseMyWhatsApp.exportAttendance", dryRun=self.config.dryRun
        )

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
                "%sdry run enabled; browser automation will still inspect the UI but will not overwrite exports",
                self.prefix,
            )

        records = self.collectPollAttendance()
        self.logger.info("%spoll vote rows collected: %s", self.prefix, len(records))

        rawRows = [asdict(record) for record in records]
        summaryRows = self.buildSummaryRows(records)

        if self.config.dryRun:
            self.logger.info(
                "%swould write polls.csv rows: %s", self.prefix, len(rawRows)
            )
            self.logger.info(
                "%swould write attendanceSummary.csv rows: %s",
                self.prefix,
                len(summaryRows),
            )
            self.writePreviewJson(rawRows, summaryRows)
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
        self.writePreviewJson(rawRows, summaryRows)
        self.logger.info("%sexport complete", self.prefix)

    def writePreviewJson(self, rawRows: list[dict], summaryRows: list[dict]) -> None:
        previewPath = self.config.outputDir / "exportPreview.json"
        payload = {
            "groupName": self.config.groupName,
            "month": self.config.monthWindow.monthKey,
            "rawPollRows": rawRows,
            "summaryRows": summaryRows,
        }
        if self.config.dryRun:
            self.logger.info("%swould write preview json: %s", self.prefix, previewPath)
            return

        previewPath.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

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
        for voterName in sorted(summary):
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

    def collectPollAttendance(self) -> list[PollRecord]:
        try:
            from playwright.sync_api import (
                sync_playwright,
                TimeoutError as PlaywrightTimeoutError,
            )
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "playwright is not installed; run: pip install playwright && playwright install chromium"
            ) from exc

        records: list[PollRecord] = []
        pollCount = 0

        self.logger.info(
            "%slaunching browser (user_data_dir=%s, headless=%s, channel=%s)",
            self.prefix,
            self.config.userDataDir,
            self.config.headless,
            self.config.browserChannel or "default",
        )

        with sync_playwright() as playwright:
            browserContext = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.userDataDir),
                headless=self.config.headless,
                channel=self.config.browserChannel,
                viewport={"width": 1440, "height": 1100},
            )
            try:
                page = browserContext.new_page()
                self.logger.info(
                    "%snavigating to %s", self.prefix, self.selectors.webUrl
                )
                page.goto(self.selectors.webUrl)
                self.logger.info("%spage loaded: %s", self.prefix, page.url)
                self.waitForWhatsAppReady(page)
                self.openGroup(page, self.config.groupName)
                self.scrollChatHistory(page)

                pollLocators = self.findPollCards(page)
                self.logger.info(
                    "%scandidate poll cards found: %s", self.prefix, len(pollLocators)
                )

                for index, pollTarget in enumerate(pollLocators, start=1):
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

                    sourceText = pollTarget.sourceText

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
                        self.openPollTarget(page, pollTarget)
                    except Exception as exc:
                        self.logger.warning("Unable to open poll votes dialog: %s", exc)
                        continue

                    try:
                        dialog = self.waitForDialog(page)
                    except TimeoutError:
                        self.logger.warning(
                            "%sunable to locate votes dialog for poll %s; skipping",
                            self.prefix,
                            index,
                        )
                        self.closeDialog(page, dialog=None)
                        continue
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

                    noVoters: list[str] = []
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

                    self.logger.info(
                        "%spoll %s: title=%r, yes=%s voter(s), no=%s voter(s)",
                        self.prefix,
                        index,
                        pollTitle,
                        len(yesVoters),
                        len(noVoters),
                    )

                    pollCount += 1
                    self.closeDialog(page, dialog)

            finally:
                browserContext.close()

        return self.deduplicateRecords(records)

    def waitForWhatsAppReady(self, page) -> None:
        page.wait_for_load_state("domcontentloaded")
        self.logger.info("%swaiting for WhatsApp Web to be ready...", self.prefix)
        self.logger.info(
            "%s(first run: if a QR code appears in the browser window, open WhatsApp on "
            "your phone → Linked devices → Link a device and scan it; use --timeout-ms "
            "to allow more time, e.g. --timeout-ms 300000)",
            self.prefix,
        )
        deadline = time.time() + max(120, self.config.timeoutMs / 1000)
        startTime = time.time()
        lastProgressLog = 0.0

        while time.time() < deadline:
            elapsed = int(time.time() - startTime)
            if elapsed - lastProgressLog >= 10:
                self.logger.info(
                    "%sstill waiting for whatsapp web (%ss elapsed)...",
                    self.prefix,
                    elapsed,
                )
                lastProgressLog = elapsed
            for selector in self.selectors.iterReadySelectors():
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
            "whatsapp web did not become ready; if this is your first run, scan the QR "
            "code that appears in the browser window using your phone's WhatsApp app. "
            "Use --timeout-ms to allow more time (e.g. --timeout-ms 300000)."
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
                self.logger.info(
                    "%ssearch box ready (selector: %s), typed group name",
                    self.prefix,
                    selector,
                )
                break
            except Exception as exc:
                lastError = exc
                continue
        else:
            raise RuntimeError(f"unable to find whatsapp search box: {lastError}")

        candidate = page.get_by_text(groupName, exact=True).first
        candidate.click(timeout=self.config.timeoutMs)
        self.logger.info("%sgroup chat opened", self.prefix)

    def scrollChatHistory(self, page, scrollPasses: int = 12) -> None:
        self.logger.info("%sscrolling chat history to load older polls...", self.prefix)
        for i in range(scrollPasses):
            page.mouse.wheel(0, -2000)
            page.wait_for_timeout(500)
            if (i + 1) % 4 == 0 or i + 1 == scrollPasses:
                self.logger.info(
                    "%sscroll pass %s/%s", self.prefix, i + 1, scrollPasses
                )

    def findPollCards(self, page) -> list[PollTarget]:
        pollLocators: list[PollTarget] = []
        seenKeys: set[str] = set()

        for selector in self.selectors.iterPollSelectors():
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue

            self.logger.info(
                "%spoll selector '%s' matched %s item(s)", self.prefix, selector, count
            )

            for index in range(count):
                item = locator.nth(index)
                try:
                    text = item.inner_text(timeout=1000)
                except Exception:
                    text = f"item-{index}"
                messageTestId = self.extractMessageTestId(item)
                key = f"{messageTestId or selector}|{text[:120]}"
                if key in seenKeys:
                    continue
                seenKeys.add(key)
                pollLocators.append(
                    PollTarget(
                        selector=selector,
                        sourceText=text,
                        messageTestId=messageTestId or "",
                    )
                )

        return pollLocators

    def extractMessageTestId(self, locator) -> str:
        try:
            container = locator.locator(
                'xpath=ancestor-or-self::*[starts-with(@data-testid, "conv-msg-")][1]'
            ).first
            return container.get_attribute("data-testid") or ""
        except Exception:
            return ""

    def extractPollSummaryText(self, sourceText: str) -> str:
        for line in sourceText.splitlines():
            value = line.strip()
            if value:
                return value
        return ""

    def buildPollButtonSelector(self, pollTarget: PollTarget) -> str:
        if pollTarget.messageTestId:
            return (
                f'[data-testid="{pollTarget.messageTestId}"] '
                '[data-testid="poll-view-votes"]'
            )
        return pollTarget.selector

    def openPollTarget(self, page, pollTarget: PollTarget) -> None:
        candidateLocators = [
            page.locator(self.buildPollButtonSelector(pollTarget)).first
        ]
        summaryText = self.extractPollSummaryText(pollTarget.sourceText)
        if summaryText:
            candidateLocators.append(
                page.locator(pollTarget.selector).filter(has_text=summaryText).first
            )
        if pollTarget.selector != self.buildPollButtonSelector(pollTarget):
            candidateLocators.append(page.locator(pollTarget.selector).first)

        lastError: Exception | None = None
        for locator in candidateLocators:
            try:
                locator.scroll_into_view_if_needed(timeout=self.config.timeoutMs)
                locator.click(timeout=self.config.timeoutMs)
                return
            except Exception as exc:
                lastError = exc

        if lastError is not None:
            raise lastError
        raise RuntimeError("unable to open poll votes dialog")

    def waitForDialog(self, page):
        timeoutMs = max(self.config.timeoutMs, DIALOG_POLL_INTERVAL_MS)
        deadline = time.time() + (timeoutMs / 1000)
        selectors = tuple(self.selectors.iterDialogSelectors())

        while time.time() < deadline:
            remainingMs = int((deadline - time.time()) * 1000)
            if remainingMs <= 0:
                break
            # Keep the overall deadline separate from the per-selector probe timeout so
            # we can retry multiple selector candidates within the remaining time budget.
            probeTimeoutMs = min(1000, remainingMs)
            for selector in selectors:
                try:
                    dialog = page.locator(selector).last
                    if dialog.is_visible(timeout=probeTimeoutMs):
                        self.logger.info(
                            "%svotes dialog opened via selector: %s",
                            self.prefix,
                            selector,
                        )
                        return dialog
                except Exception:
                    continue

            page.wait_for_timeout(DIALOG_POLL_INTERVAL_MS)

        raise TimeoutError("unable to locate votes dialog")

    def extractPollTitle(self, dialog, sourceText: str = "") -> str:
        try:
            headings = dialog.locator("h1, h2, h3, [role='heading']")
            if headings.count() > 0:
                title = headings.first.inner_text(timeout=1000).strip()
                if title:
                    return title
        except Exception:
            pass

        lines = [line.strip() for line in sourceText.splitlines() if line.strip()]
        if lines:
            return lines[0]
        return "unknown poll"

    def extractLikelyDateText(self, sourceText: str) -> str:
        match = re.search(self.selectors.likelyMessageTimePattern, sourceText)
        return match.group(0) if match else ""

    def extractOptionVoters(self, dialog, optionTexts: Iterable[str]) -> list[str]:
        """
        Heuristic extractor.

        The exact DOM for poll results may change.
        This implementation looks for a visible section with the option label,
        then collects person-like rows beneath it until the next option heading.
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
        compact = line.replace(" ", "")
        return compact.isdigit() or bool(re.fullmatch(r"\d+votes?", line.lower()))

    def looksLikeSystemText(self, line: str) -> bool:
        lowered = line.lower()
        systemFragments = (
            "select one or more",
            "view votes",
            "votes",
            "message",
            "poll",
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
            if value.lower() in {"yes", "no"}:
                continue
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        return cleaned

    def closeDialog(self, page, dialog) -> None:
        for selector in (
            self.selectors.closeDialogCandidates + self.selectors.backCandidates
        ):
            try:
                control = page.locator(selector).first
                if control.is_visible(timeout=1000):
                    control.click(timeout=self.config.timeoutMs)
                    page.wait_for_timeout(400)
                    self.logger.info(
                        "%sclosed dialog via selector: %s", self.prefix, selector
                    )
                    return
            except Exception:
                continue

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        self.logger.info("%sclosed dialog via Escape key", self.prefix)

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
        self.logger.info(
            "%sdeduplication: %s → %s records", self.prefix, len(records), len(output)
        )
        return output
