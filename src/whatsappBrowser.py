from __future__ import annotations

from collections import OrderedDict
import time

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import drawBox, getLogger  # type: ignore[import]
from whatsappSelectors import WhatsAppSelectors

from whatsappCache import PollCacheStore
from whatsappModels import PollRecord
from whatsappParsing import PollTextParser
from whatsappRecords import deduplicateRecords

logger = getLogger()


class WhatsAppPollScraper:
    def __init__(
        self,
        config: RuntimeConfig,
        selectors: WhatsAppSelectors,
        parser: PollTextParser,
        cacheStore: PollCacheStore,
    ):
        self.config = config
        self.selectors = selectors
        self.parser = parser
        self.cacheStore = cacheStore
        self.logger = logger

    # ## scrape orchestration
    def collectPollAttendance(self) -> list[PollRecord]:
        from playwright.sync_api import sync_playwright

        recordsByPollKey = self.cacheStore.loadPollCache()
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

                    pollCount += self.scrapePollLocator(
                        page=page,
                        locator=locator,
                        index=index,
                        totalPolls=totalPolls,
                        recordsByPollKey=recordsByPollKey,
                    )

            finally:
                browserContext.close()

        self.cacheStore.savePollCache(recordsByPollKey)
        return self.cacheStore.flattenCachedPolls(recordsByPollKey)

    def scrapePollLocator(
        self,
        page,
        locator,
        index: int,
        totalPolls: int,
        recordsByPollKey: OrderedDict[str, list[PollRecord]],
    ) -> int:
        sourceText = self.extractPollSourceText(locator)

        if (
            self.config.pollTitleFilter
            and self.config.pollTitleFilter.lower() not in sourceText.lower()
        ):
            self.logger.info(
                "skipping poll due to title filter: %s",
                self.config.pollTitleFilter,
            )
            return 0

        pollKey, pollTitle, _pollDateText = self.parser.buildPollKeyFromSourceText(
            sourceText
        )
        shouldRecheck = self.cacheStore.shouldRecheckPoll(index, totalPolls)
        cachedRecords = recordsByPollKey.get(pollKey)

        if cachedRecords and not shouldRecheck:
            self.logger.info(
                "using cached poll %s/%s: %s", index, totalPolls, pollTitle
            )
            return 1

        if cachedRecords and shouldRecheck:
            self.logger.info(
                "rechecking recent poll %s/%s: %s", index, totalPolls, pollTitle
            )
        else:
            self.logger.info("opening poll %s/%s: %s", index, totalPolls, pollTitle)

        try:
            if not self.openPollVotes(locator):
                return 0
        except Exception as exc:
            self.logger.warning("unable to open poll votes dialog: %s", exc)
            return 0

        dialog = None
        try:
            dialog, dialogText = self.waitForDialog(page)
            self.expandAllVoters(dialog)
            dialogText = self.readDialogText(dialog, fallback=dialogText)

            pollRecords = self.buildPollRecordsFromDialog(
                locator=locator,
                dialog=dialog,
                dialogText=dialogText,
                sourceText=sourceText,
            )
            if not pollRecords:
                return 0

            pollKey = self.parser.buildPollKeyFromParts(
                pollTitle=pollRecords[0].pollTitle,
                pollDateText=pollRecords[0].pollDateText,
                sourceHint=sourceText[:240],
            )
            recordsByPollKey[pollKey] = deduplicateRecords(pollRecords)
            return 1
        except Exception as exc:
            self.logger.warning("unable to scrape poll votes: %s", exc)
            return 0
        finally:
            self.closeDialog(page, dialog)

    def buildPollRecordsFromDialog(
        self,
        locator,
        dialog,
        dialogText: str,
        sourceText: str,
    ) -> list[PollRecord]:
        pollTitle = self.parser.extractPollTitleFromDialog(dialogText) or (
            self.parser.extractPollTitle(dialog, sourceText=sourceText)
            or "unknown poll"
        )
        if not self.parser.isValidSessionPoll(pollTitle):
            self.logger.info("skipping poll with invalid session title: %s", pollTitle)
            return []

        rawDateText = self.extractPollDateText(locator, sourceText)
        pollDateText = self.parser.normaliseDateText(rawDateText)
        sessionDateText = self.parser.calculateSessionDateText(
            pollTitle=pollTitle,
            pollDateText=pollDateText,
        )

        drawBox(sourceText[:500])
        self.logger.value("raw date text", rawDateText)
        self.logger.value("poll date text", pollDateText)
        self.logger.value("session date text", sessionDateText)

        pollRecords: list[PollRecord] = []
        yesVoters = self.parser.extractOptionVotersFromText(
            dialogText, optionTexts=self.selectors.yesOptionTexts
        )
        for voterName in yesVoters:
            pollRecords.append(
                PollRecord(
                    pollTitle=pollTitle,
                    pollDateText=pollDateText,
                    sessionDateText=sessionDateText,
                    option="Yes",
                    voterName=voterName,
                    sourceHint=sourceText[:240],
                )
            )

        if self.config.includeNoVotes:
            noVoters = self.parser.extractOptionVotersFromText(
                dialogText, optionTexts=self.selectors.noOptionTexts
            )
            for voterName in noVoters:
                pollRecords.append(
                    PollRecord(
                        pollTitle=pollTitle,
                        pollDateText=pollDateText,
                        sessionDateText=sessionDateText,
                        option="No",
                        voterName=voterName,
                        sourceHint=sourceText[:240],
                    )
                )

        return pollRecords

    # ## whatsapp navigation
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

        lastError: Exception | None = None
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
            page.wait_for_timeout(800)

    # ## poll card discovery
    def findPollCards(self, page) -> list:
        pollLocators: list = []
        seenKeys: set[str] = set()
        selectors = (
            '[data-testid="poll-view-votes"]',
            'div[role="button"]:has-text("View votes")',
            'span:has-text("View votes")',
            'text="View votes"',
        )

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
                key = f"{selector}|{index}|{sourceText[:120]}"
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

    def extractPollDateText(self, locator, sourceText: str) -> str:
        textDate = self.parser.extractLikelyDateText(sourceText)
        if textDate:
            return textDate

        script = r"""
        (node) => {
            const isDateText = (value) => {
                const text = (value || "").trim();
                return /^(today|yesterday)$/i.test(text)
                    || /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(text);
            };

            const nodeRect = node.getBoundingClientRect();
            const candidates = Array.from(document.querySelectorAll("span, div"))
                .map((el) => {
                    const text = (el.innerText || el.textContent || "").trim();
                    if (!isDateText(text)) {
                        return null;
                    }

                    const rect = el.getBoundingClientRect();
                    return {
                        text,
                        top: rect.top,
                        bottom: rect.bottom,
                        left: rect.left,
                        right: rect.right,
                    };
                })
                .filter(Boolean)
                .filter((item) => item.bottom <= nodeRect.top + 5)
                .sort((a, b) => b.bottom - a.bottom);

            return candidates.length ? candidates[0].text : "";
        }
        """

        try:
            return str(locator.evaluate(script, timeout=1000) or "")
        except Exception as exc:
            self.logger.warning("unable to derive poll date: %s", exc)
            return ""

    # ## dialog utilities
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

    def expandAllVoters(self, panel) -> None:
        previousText = ""

        for _ in range(20):
            try:
                buttons = panel.get_by_text("See all", exact=False)
                count = buttons.count()

                for i in range(count):
                    try:
                        btn = buttons.nth(i)
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=2000)
                            panel.page.wait_for_timeout(500)
                    except Exception:
                        continue

                panel.hover()
                panel.page.mouse.wheel(0, 1200)
                panel.page.wait_for_timeout(500)

                currentText = panel.inner_text(timeout=2000)
                if currentText == previousText:
                    break

                previousText = currentText

            except Exception:
                return

    def logPollPanelDiagnostics(self, page) -> None:
        for textAnchor in ("Poll details", "View votes", "Yes", "No"):
            try:
                count = page.get_by_text(textAnchor, exact=False).count()
                self.logger.value(f"visible text count {textAnchor}", count)
            except Exception:
                continue

    def openPollVotes(self, locator) -> bool:
        disabled = locator.get_attribute("aria-disabled", timeout=1000)
        if disabled == "true":
            self.logger.info("poll skipped disabled")
            return False

        locator.scroll_into_view_if_needed(timeout=self.config.timeoutMs)
        locator.click(timeout=self.config.timeoutMs)
        return True

    def readDialogText(self, dialog, fallback: str = "") -> str:
        try:
            text = dialog.inner_text(timeout=2000)
            return text if text.strip() else fallback
        except Exception:
            return fallback

    def waitForDialog(self, page):
        try:
            header = page.get_by_text("Poll details", exact=False).last
            header.wait_for(state="visible", timeout=3000)

            panel = header.locator("xpath=ancestor::*[contains(., 'members voted')][1]")
            panel.wait_for(state="visible", timeout=3000)

            text = panel.inner_text(timeout=3000)
            return panel, text

        except Exception:
            self.logPollPanelDiagnostics(page)
            raise TimeoutError("unable to locate poll results panel")
