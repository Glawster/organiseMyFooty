from __future__ import annotations

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import drawBox, getLogger  # type: ignore[import]
from whatsapp.models import PollRecord
from whatsapp.parsing import PollTextParser
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()


class PollRecordsBuilder:
    def __init__(
        self,
        config: RuntimeConfig,
        selectors: WhatsAppSelectors,
        parser: PollTextParser,
        discovery: PollDiscovery,
    ):
        self.config = config
        self.selectors = selectors
        self.parser = parser
        self.discovery = discovery
        self.logger = logger

    ## public api

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
            self.logger.info("skipping invalid session title: %s", pollTitle)
            return []

        rawDateText = self.discovery.extractPollDateText(locator, sourceText)
        pollDateText = self.parser.normaliseDateText(rawDateText)
        sessionDateText = self.parser.calculateSessionDateText(
            pollTitle=pollTitle,
            pollDateText=pollDateText,
        )

        drawBox(sourceText[:500], width=40)
        self.logger.value("raw date text", rawDateText)
        self.logger.value("poll date text", pollDateText)
        self.logger.value("session date text", sessionDateText)

        pollRecords = self.buildOptionRecords(
            dialogText=dialogText,
            pollTitle=pollTitle,
            pollDateText=pollDateText,
            sessionDateText=sessionDateText,
            sourceHint=sourceText[:240],
        )
        self.logger.value("poll vote rows", len(pollRecords))
        return pollRecords

    ## record construction

    def buildOptionRecords(
        self,
        dialogText: str,
        pollTitle: str,
        pollDateText: str,
        sessionDateText: str,
        sourceHint: str,
    ) -> list[PollRecord]:
        pollRecords: list[PollRecord] = []

        yesVoters = self.parser.extractOptionVotersFromText(
            dialogText, optionTexts=self.selectors.yesOptionTexts
        )
        pollRecords.extend(
            self.buildRecordsForOption(
                pollTitle=pollTitle,
                pollDateText=pollDateText,
                sessionDateText=sessionDateText,
                option="Yes",
                voterNames=yesVoters,
                sourceHint=sourceHint,
            )
        )

        if self.config.includeNoVotes:
            noVoters = self.parser.extractOptionVotersFromText(
                dialogText, optionTexts=self.selectors.noOptionTexts
            )
            pollRecords.extend(
                self.buildRecordsForOption(
                    pollTitle=pollTitle,
                    pollDateText=pollDateText,
                    sessionDateText=sessionDateText,
                    option="No",
                    voterNames=noVoters,
                    sourceHint=sourceHint,
                )
            )

        return pollRecords

    def buildRecordsForOption(
        self,
        pollTitle: str,
        pollDateText: str,
        sessionDateText: str,
        option: str,
        voterNames: list[str],
        sourceHint: str,
    ) -> list[PollRecord]:
        return [
            PollRecord(
                pollTitle=pollTitle,
                pollDateText=pollDateText,
                sessionDateText=sessionDateText,
                option=option,
                voterName=voterName,
                sourceHint=sourceHint,
            )
            for voterName in voterNames
        ]
