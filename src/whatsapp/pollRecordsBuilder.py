from __future__ import annotations

from datetime import datetime
import re

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
        pollDateDisplay = self._formatDateDisplay(
            pollDateText, fallbackText=rawDateText
        )
        sessionDateText = self.parser.calculateSessionDateText(
            pollTitle=pollTitle,
            pollDateText=pollDateText,
        )
        sessionDateDisplay = self._formatDateDisplay(sessionDateText)

        boxText = "\n".join(
            [
                sourceText[:500].rstrip(),
                "",
                f"raw date:     {rawDateText}",
                f"poll date:    {pollDateDisplay}",
                f"session date: {sessionDateDisplay}",
            ]
        )

        drawBox(boxText, width=44)

        if not self.parser.isSessionInMonthWindow(sessionDateText):
            self.logger.info(
                "skipping poll outside month window: %s (%s)",
                pollTitle,
                sessionDateText or "unknown date",
            )
            return []

        pollRecords = self.buildOptionRecords(
            dialogText=dialogText,
            pollTitle=pollTitle,
            pollDateText=pollDateText,
            sessionDateText=sessionDateText,
            sourceHint=sourceText[:240],
        )
        self.logger.value("poll vote rows", len(pollRecords))
        return pollRecords

    ## display utilities

    def _formatDateDisplay(self, text: str, fallbackText: str = "") -> str:
        if not text:
            return ""

        try:
            datePart = datetime.strptime(text[:8], "%Y%m%d").strftime("%d/%m/%Y")
        except ValueError:
            return text

        sourceForTime = text if text else fallbackText
        if fallbackText:
            sourceForTime = f"{text} {fallbackText}".strip()

        timeMatch = re.search(r"\b(\d{1,2}):(\d{2})\b", sourceForTime)
        if not timeMatch:
            return f"{datePart} 00:00"

        hour = int(timeMatch.group(1))
        minute = int(timeMatch.group(2))
        return f"{datePart} {hour:02d}:{minute:02d}"

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
