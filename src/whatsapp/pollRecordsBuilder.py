from __future__ import annotations

from datetime import datetime
import re

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import drawBox, getLogger  # type: ignore[import]
from whatsapp.models import PollRecord, SessionStatus
from whatsapp.names import stripContactNameMarker
from whatsapp.parsing import PollTextParser
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()


class IncompletePollVotesError(ValueError):
    """Raised when WhatsApp's displayed vote count exceeds captured voters."""


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
        self.voterPhones: dict[str, str] = {}

    ## public api

    def buildPollRecordsFromDialog(
        self,
        locator,
        dialog,
        dialogText: str,
        sourceText: str,
        rawDateText: str = "",
        dialogTexts: list[str] | None = None,
        cancelledByReaction: bool = False,
    ) -> list[PollRecord]:
        pollTitle = self.parser.extractPollTitleFromDialog(dialogText) or (
            self.parser.extractPollTitle(dialog, sourceText=sourceText)
            or "unknown poll"
        )
        if not self.parser.isValidSessionPoll(pollTitle):
            self.logger.info("skipping invalid session title: %s", pollTitle)
            return []

        if not rawDateText:
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
        sessionStatus = (
            SessionStatus.CANCELLED if cancelledByReaction else SessionStatus.SCHEDULED
        )

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

        if sessionStatus is SessionStatus.CANCELLED:
            self.logger.info(
                "cancellation indicator found: emoji=%s participant=%s poll=%s",
                "😢",
                self.config.cancellationEmojiName,
                pollTitle,
            )

        pollRecordsByIdentity: dict[tuple[str, str], PollRecord] = {}
        for snapshotText in dialogTexts or [dialogText]:
            for record in self.buildOptionRecords(
                dialogText=snapshotText,
                pollTitle=pollTitle,
                pollDateText=pollDateText,
                sessionDateText=sessionDateText,
                sourceHint=sourceText[:240],
                sessionStatus=sessionStatus,
            ):
                identity = (record.option.casefold(), record.voterName.casefold())
                previousRecord = pollRecordsByIdentity.get(identity)
                if previousRecord is None or record.voterPhone:
                    pollRecordsByIdentity[identity] = record

        pollRecords = list(pollRecordsByIdentity.values())
        if sessionStatus is SessionStatus.CANCELLED and not pollRecords:
            # A voterless sentinel allows persistence to retain the session and
            # its source status without fabricating an attendance observation.
            pollRecords.append(
                PollRecord(
                    pollTitle=pollTitle,
                    pollDateText=pollDateText,
                    sessionDateText=sessionDateText,
                    option="",
                    voterName="",
                    sourceHint=sourceText[:240],
                    sessionStatus=sessionStatus,
                )
            )
        expectedYesVotes = self.parser.extractOptionVoteCountFromText(
            sourceText, self.selectors.yesOptionTexts
        )
        actualYesVotes = sum(
            record.option.casefold() == "yes" for record in pollRecords
        )
        if expectedYesVotes is not None and actualYesVotes < expectedYesVotes:
            raise IncompletePollVotesError(
                f"captured {actualYesVotes} of {expectedYesVotes} Yes voters"
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
        sessionStatus: SessionStatus,
    ) -> list[PollRecord]:
        pollRecords: list[PollRecord] = []

        yesVoters = self.parser.extractOptionVotersFromText(
            dialogText, optionTexts=self.selectors.yesOptionTexts
        )
        yesPhones = self._extractVoterPhones(
            dialogText, optionTexts=self.selectors.yesOptionTexts
        )
        pollRecords.extend(
            self.buildRecordsForOption(
                pollTitle=pollTitle,
                pollDateText=pollDateText,
                sessionDateText=sessionDateText,
                option="Yes",
                voterNames=yesVoters,
                voterPhones=yesPhones,
                sourceHint=sourceHint,
                sessionStatus=sessionStatus,
            )
        )

        if self.config.includeNoVotes:
            noVoters = self.parser.extractOptionVotersFromText(
                dialogText, optionTexts=self.selectors.noOptionTexts
            )
            noPhones = self._extractVoterPhones(
                dialogText, optionTexts=self.selectors.noOptionTexts
            )
            pollRecords.extend(
                self.buildRecordsForOption(
                    pollTitle=pollTitle,
                    pollDateText=pollDateText,
                    sessionDateText=sessionDateText,
                    option="No",
                    voterNames=noVoters,
                    voterPhones=noPhones,
                    sourceHint=sourceHint,
                    sessionStatus=sessionStatus,
                )
            )

        for record in pollRecords:
            if record.voterName and record.voterPhone:
                self.voterPhones[record.voterName.casefold()] = record.voterPhone

        return pollRecords

    def buildRecordsForOption(
        self,
        pollTitle: str,
        pollDateText: str,
        sessionDateText: str,
        option: str,
        voterNames: list[str],
        sourceHint: str,
        sessionStatus: SessionStatus,
        voterPhones: dict[str, str] | None = None,
    ) -> list[PollRecord]:
        voterPhones = voterPhones or {}
        records: list[PollRecord] = []
        for voterName in voterNames:
            storedName = stripContactNameMarker(voterName)
            if not storedName:
                continue
            records.append(
                PollRecord(
                    pollTitle=pollTitle,
                    pollDateText=pollDateText,
                    sessionDateText=sessionDateText,
                    option=option,
                    voterName=storedName,
                    sourceHint=sourceHint,
                    sessionStatus=sessionStatus,
                    voterPhone=voterPhones.get(storedName.casefold(), ""),
                )
            )
        return records

    ## voter metadata utilities

    def _extractVoterPhones(
        self, dialogText: str, optionTexts: tuple[str, ...]
    ) -> dict[str, str]:
        """Return phone metadata keyed by the cleaned voter name preceding it."""
        optionNames = {value.casefold() for value in optionTexts}
        allOptionNames = {
            value.casefold()
            for value in self.selectors.yesOptionTexts + self.selectors.noOptionTexts
        }
        lines = [line.strip() for line in dialogText.splitlines() if line.strip()]
        phones: dict[str, str] = {}
        previousVoterName = ""
        inSection = False

        for line in lines:
            folded = line.casefold()
            if folded in optionNames:
                inSection = True
                previousVoterName = ""
                continue
            if inSection and folded in allOptionNames:
                break
            if not inSection:
                continue
            if self.parser.looksLikeVoteCount(line) or self.parser.looksLikeSystemText(
                line
            ):
                continue

            if self._looksLikePhoneNumber(line):
                if previousVoterName:
                    phones[previousVoterName.casefold()] = self._normalisePhoneNumber(
                        line
                    )
                continue

            cleanedNames = self.parser.cleanVoterNames([line])
            previousVoterName = (
                stripContactNameMarker(cleanedNames[0]) if cleanedNames else ""
            )

        return phones

    def _looksLikePhoneNumber(self, value: str) -> bool:
        if not re.fullmatch(r"\+?[\d\s().-]+", value):
            return False
        return sum(character.isdigit() for character in value) >= 7

    def _normalisePhoneNumber(self, value: str) -> str:
        digits = "".join(character for character in value if character.isdigit())
        return digits
