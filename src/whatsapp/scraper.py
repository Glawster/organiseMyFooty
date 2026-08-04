from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.models import PollRecord
from whatsapp.navigation import GroupNotFoundError, WhatsAppNavigation
from whatsapp.parsing import PollTextParser
from whatsapp.pollDialog import PollDialog
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.records import deduplicateRecords
from whatsapp.selectors import WhatsAppSelectors
from whatsapp.store import AttendanceStore, normaliseName

logger = getLogger()


class WhatsAppPollScraper:
    def __init__(
        self,
        config: RuntimeConfig,
        selectors: WhatsAppSelectors,
        parser: PollTextParser,
        attendanceStore: AttendanceStore | None = None,
    ):
        self.config = config
        self.selectors = selectors
        self.parser = parser
        self.attendanceStore = attendanceStore
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
        if self.config.override and self.config.scanSince:
            return self.config.scanSince
        return self.config.monthWindow.startDate - timedelta(days=7)

    def shouldStopForStrictLookback(self, pollLocators: list) -> bool:
        if not self.config.strictMonth and not self.config.override:
            return False

        visibleDates = self.extractVisiblePollDates(pollLocators)
        if not visibleDates:
            return False

        oldestVisibleDate = min(visibleDates)
        lookbackStartDate = self.getStrictLookbackStartDate()

        if oldestVisibleDate >= lookbackStartDate:
            return False

        if self.config.override:
            self.logger.info(
                "reached override horizon: oldest poll date %s, cutoff %s",
                oldestVisibleDate,
                lookbackStartDate,
            )
        else:
            self.logger.info(
                "reached before strict lookback window: oldest visible poll date %s, cutoff %s",
                oldestVisibleDate,
                lookbackStartDate,
            )
        return True

    ## public api

    def capturedPollIsBoundary(self, groupName: str, stableMessageKey: str) -> bool:
        """Return whether a reliable source identity ends this group's normal scan."""
        return bool(
            self.attendanceStore
            and stableMessageKey
            and not self.config.override
            and self.attendanceStore.sourcePollCaptured(
                "whatsapp", normaliseName(groupName), stableMessageKey
            )
        )

    def collectPollAttendance(self) -> list[PollRecord]:
        from playwright.sync_api import sync_playwright

        recordsByPollKey: OrderedDict[str, list[PollRecord]] = OrderedDict()
        pollCount = 0
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

                for groupName in self.config.effectiveGroupNames:
                    self.logger.info("collecting polls from group: %s", groupName)
                    seenPollKeys: set[str] = set()
                    self.stopAfterCurrentPass = False
                    scanId = None
                    if self.attendanceStore:
                        sourceId = self.attendanceStore.sourceEnsure(
                            "whatsapp", normaliseName(groupName), groupName
                        )
                        self.attendanceStore.connection.commit()
                        scanId = self.attendanceStore.scanStart(
                            sourceId, self.config.scanSince, date.today()
                        )
                    boundaryReason = "history_exhausted"

                    try:
                        self.navigation.openGroup(page, groupName)
                    except GroupNotFoundError as exc:
                        self.logger.warning("%s; skipping group", exc)
                        if self.attendanceStore and scanId is not None:
                            self.attendanceStore.scanFinish(
                                scanId, "failed", "group_not_found", str(exc)
                            )
                        continue
                    self.navigation.scrollChatToLatest(page)
                    noHistoryProgressPasses = 0

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
                            stableMessageKey = self.discovery.extractStableMessageKey(
                                locator
                            )
                            key = self.discovery.buildPollLocatorKey(
                                messageKey, sourceText
                            )

                            if key in seenPollKeys:
                                continue

                            if self.capturedPollIsBoundary(groupName, stableMessageKey):
                                self.logger.info(
                                    "captured poll boundary: %s in %s",
                                    stableMessageKey,
                                    groupName,
                                )
                                boundaryReason = "captured_poll"
                                self.stopAfterCurrentPass = True
                                break

                            seenPollKeys.add(key)

                            if self.hasReachedPollLimit(pollCount):
                                break

                            pollCount += self.scrapePollLocator(
                                page=page,
                                locator=locator,
                                index=pollCount + 1,
                                totalPolls=len(seenPollKeys),
                                recordsByPollKey=recordsByPollKey,
                                groupName=groupName,
                                pollExternalId=stableMessageKey,
                            )

                        if self.hasReachedPollLimit(pollCount):
                            break

                        if self.stopAfterCurrentPass:
                            break

                        if self.shouldStopForStrictLookback(pollLocators):
                            boundaryReason = "date_window"
                            break

                        madeHistoryProgress = self.navigation.scrollChatHistory(
                            page, scrollPasses=1
                        )
                        if madeHistoryProgress:
                            noHistoryProgressPasses = 0
                        else:
                            noHistoryProgressPasses += 1
                            if noHistoryProgressPasses >= 3:
                                self.logger.info("chat history exhausted")
                                break
                        page.wait_for_timeout(900)

                    if self.hasReachedPollLimit(pollCount):
                        self.logger.info(
                            "stopping before remaining groups because poll limit was reached"
                        )
                        break

                    self.logger.info(
                        "finished group: %s (polls collected so far: %s)",
                        groupName,
                        pollCount,
                    )
                    if self.attendanceStore and scanId is not None:
                        scanStatus = "completed"
                        if self.hasReachedPollLimit(pollCount):
                            scanStatus, boundaryReason = "partial", "scan_limit"
                        elif self.config.pollTitleFilter:
                            scanStatus, boundaryReason = "partial", "title_filter"
                        self.attendanceStore.scanFinish(
                            scanId, scanStatus, boundaryReason
                        )

            finally:
                browserContext.close()

        if self.attendanceStore:
            return self.attendanceStore.attendanceRecords(
                self.config.monthWindow.startDate, self.config.monthWindow.endDate
            )
        records = [
            record
            for pollRecords in recordsByPollKey.values()
            for record in pollRecords
        ]
        return deduplicateRecords(records)

    ## scrape orchestration

    def scrapePollLocator(
        self,
        page,
        locator,
        index: int,
        totalPolls: int,
        recordsByPollKey: OrderedDict[str, list[PollRecord]],
        groupName: str | None = None,
        pollExternalId: str = "",
    ) -> int:
        groupName = groupName or self.config.groupName
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

        basePollKey, pollTitle, _pollDateText = self.buildPollKeyForLocator(
            sourceText=sourceText,
            pollTitle=pollTitle,
            rawDateText=rawDateText,
        )
        pollKey = self.buildGroupPollKey(groupName, basePollKey)
        self.logPollAction(
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
            dialogTexts = self.dialog.expandAllVoters(dialog, initialText=dialogText)
            dialogText = self.dialog.readDialogText(dialog, fallback=dialogText)
            if dialogText not in dialogTexts:
                dialogTexts.append(dialogText)

            pollRecords = self.recordsBuilder.buildPollRecordsFromDialog(
                locator=locator,
                dialog=dialog,
                dialogText=dialogText,
                sourceText=sourceText,
                rawDateText=rawDateText,
                dialogTexts=dialogTexts,
            )
            if not pollRecords:
                return 0

            for record in pollRecords[:1]:
                self.logger.debug(
                    "resolved: %s -> %s -> %s -> %s",
                    record.pollTitle,
                    record.pollDateText,
                    record.sessionDateText,
                    record.sourceHint.replace("\n", " | "),
                )

            basePollKey = self.buildScrapedPollKey(
                sourceText=sourceText,
                pollRecord=pollRecords[0],
                fallbackPollKey=basePollKey,
            )
            pollKey = self.buildGroupPollKey(groupName, basePollKey)
            recordsByPollKey[pollKey] = deduplicateRecords(pollRecords)
            if self.attendanceStore and not self.config.dryRun:
                self.attendanceStore.pollReconcile(
                    groupName,
                    pollExternalId or f"derived:{pollKey}",
                    pollRecords,
                    complete=True,
                )
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
        if not self.config.strictMonth and not self.config.override:
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

        cutoff = (
            self.config.scanSince
            if self.config.override and self.config.scanSince
            else self.config.monthWindow.startDate
        )
        if sessionDate >= cutoff:
            return False

        self.logger.info(
            "reached scan cutoff via session date: %s (%s)",
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

    def buildPollKeyForLocator(
        self,
        sourceText: str,
        pollTitle: str,
        rawDateText: str,
    ) -> tuple[str, str, str]:
        pollDateText = self.parser.normaliseDateText(rawDateText)
        if pollDateText:
            pollKey = self.parser.buildPollKeyFromParts(
                pollTitle=pollTitle,
                pollDateText=pollDateText,
                sourceHint=sourceText[:240],
            )
            return pollKey, pollTitle, pollDateText

        return self.parser.buildPollKeyFromSourceText(sourceText)

    def buildGroupPollKey(self, groupName: str, pollKey: str) -> str:
        return f"{groupName.casefold()}|{pollKey}"

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
        index: int,
        totalPolls: int,
        pollTitle: str,
    ) -> None:
        self.logger.debug("-" * 60)
        self.logger.doing(f"processing poll {index}/{totalPolls}: {pollTitle}")
