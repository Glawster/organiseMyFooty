from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.cache import PollCacheStore
from whatsapp.models import PollRecord
from whatsapp.navigation import WhatsAppNavigation
from whatsapp.parsing import PollTextParser
from whatsapp.pollDialog import PollDialog
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.records import deduplicateRecords
from whatsapp.selectors import WhatsAppSelectors

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

        self.navigation = WhatsAppNavigation(config=config, selectors=selectors)
        self.discovery = PollDiscovery(
            config=config,
            selectors=selectors,
            parser=parser,
        )
        self.dialog = PollDialog(config=config, selectors=selectors)
        self.recordsBuilder = PollRecordsBuilder(
            config=config,
            selectors=selectors,
            parser=parser,
            discovery=self.discovery,
        )
        self.stopAfterCurrentPass = False

    ## date window helpers

    def extractVisiblePollDates(self, pollLocators: list) -> list[date]:
        visibleDates: list[date] = []

        for locator in pollLocators:
            sourceText = self.discovery.extractPollSourceText(locator)
            rawDateText = self.discovery.extractPollDateText(
                locator,
                sourceText,
                allowDomFallback=False,
            )
            pollDateText = self.parser.normaliseDateText(rawDateText)
            if not pollDateText:
                continue

            try:
                visibleDates.append(datetime.strptime(pollDateText, "%Y%m%d").date())
            except ValueError:
                continue

        return visibleDates

    def getStrictLookbackStartDate(self) -> date:
        return self.config.monthWindow.startDate - timedelta(days=7)

    def shouldStopForStrictLookback(self, pollLocators: list) -> bool:
        if not self.config.strictMonth:
            return False

        visibleDates = self.extractVisiblePollDates(pollLocators)
        if not visibleDates:
            return False

        oldestVisibleDate = min(visibleDates)
        lookbackStartDate = self.getStrictLookbackStartDate()

        if oldestVisibleDate >= lookbackStartDate:
            return False

        self.logger.info(
            "reached before strict lookback window: oldest visible poll date %s, cutoff %s",
            oldestVisibleDate,
            lookbackStartDate,
        )
        return True

    ## public api

    def collectPollAttendance(self) -> list[PollRecord]:
        from playwright.sync_api import sync_playwright

        recordsByPollKey = self.cacheStore.loadPollCache()
        pollCount = 0
        seenPollKeys: set[str] = set()
        self.stopAfterCurrentPass = False

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
                self.navigation.waitForWhatsAppReady(page)
                self.navigation.openGroup(page, self.config.groupName)
                self.navigation.scrollChatToLatest(page)

                for scrollPass in range(120):
                    pollLocators = self.discovery.findPollCards(page)
                    self.logger.debug(
                        "candidate poll cards found: %s (scroll pass %s)",
                        len(pollLocators),
                        scrollPass + 1,
                    )

                    if pollLocators:
                        self.logVisiblePollCandidates(pollLocators, seenPollKeys)

                    for locator in pollLocators:
                        sourceText = self.discovery.extractPollSourceText(locator)
                        messageKey = self.discovery.extractMessageKey(locator)
                        key = self.discovery.buildPollLocatorKey(messageKey, sourceText)

                        if key in seenPollKeys:
                            continue

                        seenPollKeys.add(key)

                        if self.hasReachedPollLimit(pollCount):
                            break

                        pollCount += self.scrapePollLocator(
                            page=page,
                            locator=locator,
                            index=pollCount + 1,
                            totalPolls=len(seenPollKeys),
                            recordsByPollKey=recordsByPollKey,
                        )

                    if self.hasReachedPollLimit(pollCount):
                        break

                    if self.stopAfterCurrentPass:
                        break

                    if self.shouldStopForStrictLookback(pollLocators):
                        break

                    self.navigation.scrollChatHistory(page, scrollPasses=1)
                    page.wait_for_timeout(900)

            finally:
                browserContext.close()

        self.cacheStore.savePollCache(recordsByPollKey)
        return self.cacheStore.flattenCachedPolls(recordsByPollKey)

    ## scrape orchestration

    def scrapePollLocator(
        self,
        page,
        locator,
        index: int,
        totalPolls: int,
        recordsByPollKey: OrderedDict[str, list[PollRecord]],
    ) -> int:
        sourceText = self.discovery.extractPollSourceText(locator)

        if self.shouldSkipForTitleFilter(sourceText):
            return 0

        pollTitle = self.parser.extractPollTitle(sourceText=sourceText)
        rawDateText = ""
        if self.parser.isValidSessionPoll(pollTitle):
            rawDateText = self.discovery.extractPollDateText(locator, sourceText)

        if self.shouldStopForPastMonthWindow(locator, sourceText, rawDateText):
            self.stopAfterCurrentPass = True
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

        self.logPollAction(
            cachedRecords=bool(cachedRecords),
            shouldRecheck=shouldRecheck,
            index=index,
            totalPolls=totalPolls,
            pollTitle=pollTitle,
        )

        try:
            if not self.dialog.openPollVotes(locator):
                return 0
        except Exception as exc:
            self.logger.warning("Unable to open poll votes dialog: %s", exc)
            return 0

        dialog = None
        try:
            dialog, dialogText = self.dialog.waitForDialog(page)
            self.dialog.expandAllVoters(dialog)
            dialogText = self.dialog.readDialogText(dialog, fallback=dialogText)

            pollRecords = self.recordsBuilder.buildPollRecordsFromDialog(
                locator=locator,
                dialog=dialog,
                dialogText=dialogText,
                sourceText=sourceText,
                rawDateText=rawDateText,
            )
            if not pollRecords:
                return 0

            for record in pollRecords[:1]:
                self.logger.info(
                    "resolved: %s -> %s -> %s -> %s",
                    record.pollTitle,
                    record.pollDateText,
                    record.sessionDateText,
                    record.sourceHint.replace("\n", " | "),
                )

            pollKey = self.buildScrapedPollKey(
                sourceText=sourceText,
                pollRecord=pollRecords[0],
                fallbackPollKey=pollKey,
            )
            recordsByPollKey[pollKey] = deduplicateRecords(pollRecords)
            return 1
        except Exception as exc:
            self.logger.warning("Unable to scrape poll votes: %s", exc)
            return 0
        finally:
            self.dialog.closeDialog(page, dialog)

    ## filtering helpers

    def hasReachedPollLimit(self, pollCount: int) -> bool:
        if self.config.limitPolls is None:
            return False

        if pollCount < self.config.limitPolls:
            return False

        self.logger.info("poll limit reached: %s", self.config.limitPolls)
        return True

    def shouldSkipForTitleFilter(self, sourceText: str) -> bool:
        if not self.config.pollTitleFilter:
            return False

        shouldSkip = self.config.pollTitleFilter.lower() not in sourceText.lower()
        if shouldSkip:
            self.logger.info(
                "skipping poll title filter: %s",
                self.config.pollTitleFilter,
            )
        return shouldSkip

    def shouldStopForPastMonthWindow(
        self, locator, sourceText: str, rawDateText: str = ""
    ) -> bool:
        if not self.config.strictMonth:
            return False

        pollTitle = self.parser.extractPollTitle(sourceText=sourceText)
        if not self.parser.isValidSessionPoll(pollTitle):
            return False

        if not rawDateText:
            rawDateText = self.discovery.extractPollDateText(locator, sourceText)
        pollDateText = self.parser.normaliseDateText(rawDateText)
        if not pollDateText:
            return False

        sessionDateText = self.parser.calculateSessionDateText(
            pollTitle=pollTitle,
            pollDateText=pollDateText,
        )
        sessionDate = self.parser.parseSessionDateValue(sessionDateText)
        if sessionDate is None:
            return False

        if sessionDate >= self.config.monthWindow.startDate:
            return False

        self.logger.info(
            "reached before month window via session date: %s (%s)",
            pollTitle,
            sessionDateText,
        )
        return True

    def sourceTextHasStablePollDate(self, sourceText: str) -> bool:
        rawDateText = self.parser.extractLikelyDateText(sourceText)
        return bool(self.parser.normaliseDateText(rawDateText))

    def buildScrapedPollKey(
        self, sourceText: str, pollRecord: PollRecord, fallbackPollKey: str
    ) -> str:
        pollKey = self.parser.buildPollKeyFromParts(
            pollTitle=pollRecord.pollTitle,
            pollDateText=pollRecord.pollDateText,
            sourceHint=pollRecord.sourceHint.replace("\n", " | "),
        )

        return pollKey or fallbackPollKey

    ## logging helpers

    def logVisiblePollCandidates(
        self, pollLocators: list, seenPollKeys: set[str]
    ) -> None:
        candidateKeysSeenThisPass: set[str] = set()

        for locator in pollLocators:
            sourceText = self.discovery.extractPollSourceText(locator)
            messageKey = self.discovery.extractMessageKey(locator)
            key = self.discovery.buildPollLocatorKey(messageKey, sourceText)
            if key in seenPollKeys or key in candidateKeysSeenThisPass:
                continue

            candidateKeysSeenThisPass.add(key)
            pollTitle = self.parser.extractPollTitle(sourceText=sourceText)
            self.logger.debug("found poll: %s", pollTitle or sourceText[:50])

    def logPollAction(
        self,
        cachedRecords: bool,
        shouldRecheck: bool,
        index: int,
        totalPolls: int,
        pollTitle: str,
    ) -> None:
        if cachedRecords and shouldRecheck:
            self.logger.info(
                "rechecking recent poll %s/%s: %s",
                index,
                totalPolls,
                pollTitle,
            )
            return

        self.logger.debug("-" * 60)
        self.logger.doing(f"processing poll {index}/{totalPolls}: {pollTitle}")
