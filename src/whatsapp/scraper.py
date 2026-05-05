from __future__ import annotations

from collections import OrderedDict

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

    ## public api

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
                self.navigation.waitForWhatsAppReady(page)
                self.navigation.openGroup(page, self.config.groupName)
                self.navigation.scrollChatHistory(page)
                self.discovery.logVisiblePollText(page)

                pollLocators = self.discovery.findPollCards(page)
                totalPolls = len(pollLocators)

                for index, locator in enumerate(pollLocators, start=1):
                    if self.hasReachedPollLimit(pollCount):
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

    ## logging helpers

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

        self.logger.info("poll %s/%s: %s", index, totalPolls, pollTitle)
        self.logger.doing("opening poll")
