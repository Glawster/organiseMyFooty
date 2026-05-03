from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable
import re

from attendanceConfig import RuntimeConfig
from whatsappSelectors import WhatsAppSelectors


WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class PollTextParser:
    def __init__(self, config: RuntimeConfig, selectors: WhatsAppSelectors):
        self.config = config
        self.selectors = selectors

    # ## date utilities
    def calculateSessionDateText(self, pollTitle: str, pollDateText: str) -> str:
        sessionWeekday = self.extractSessionWeekday(pollTitle)
        if not sessionWeekday or not pollDateText:
            return ""

        try:
            pollDate = datetime.strptime(pollDateText, "%Y%m%d")
        except ValueError:
            return ""

        targetWeekday = WEEKDAY_MAP[sessionWeekday]
        daysForward = (targetWeekday - pollDate.weekday()) % 7
        if daysForward == 0:
            daysForward = 7

        return (pollDate + timedelta(days=daysForward)).strftime("%Y%m%d")

    def normaliseDateText(self, dateText: str) -> str:
        text = " ".join(dateText.split()).strip().lower()
        if not text:
            return ""

        dateMatch = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", text)
        if dateMatch:
            try:
                dt = datetime.strptime(dateMatch.group(1), "%d/%m/%Y")
                return dt.strftime("%Y%m%d")
            except ValueError:
                pass

        today = datetime.now()
        if text.startswith("today"):
            return today.strftime("%Y%m%d")
        if text.startswith("yesterday"):
            return (today - timedelta(days=1)).strftime("%Y%m%d")

        weekday = text.split(" at ", maxsplit=1)[0]
        if weekday in WEEKDAY_MAP:
            daysBack = (today.weekday() - WEEKDAY_MAP[weekday]) % 7
            if daysBack == 0:
                daysBack = 7
            return (today - timedelta(days=daysBack)).strftime("%Y%m%d")

        return ""

    # ## key utilities
    def buildPollKeyFromParts(
        self, pollTitle: str, pollDateText: str, sourceHint: str
    ) -> str:
        if pollDateText:
            return f"{pollTitle}|{pollDateText}"
        return f"{pollTitle}|{sourceHint[:80]}"

    def buildPollKeyFromSourceText(self, sourceText: str) -> tuple[str, str, str]:
        pollTitle = self.extractPollTitle(sourceText=sourceText) or "unknown poll"
        rawDateText = self.extractLikelyDateText(sourceText) or ""
        pollDateText = self.normaliseDateText(rawDateText)
        pollKey = self.buildPollKeyFromParts(
            pollTitle=pollTitle,
            pollDateText=pollDateText,
            sourceHint=sourceText[:240],
        )
        return pollKey, pollTitle, pollDateText

    # ## title utilities
    def extractSessionName(self, pollTitle: str) -> str:
        title = " ".join(pollTitle.split()).strip()
        return re.sub(r"\s+", " ", title) or "unknown session"

    def extractSessionWeekday(self, pollTitle: str) -> str:
        match = re.match(
            r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            pollTitle.strip(),
            re.IGNORECASE,
        )
        return match.group(1).lower() if match else ""

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

        for index, line in enumerate(lines):
            if line.lower() != "select one or more":
                continue
            for candidate in reversed(lines[:index]):
                lowered = candidate.lower()
                if lowered in ignoredLines:
                    continue
                if self.looksLikeVoteCount(candidate):
                    continue
                if re.search(r"\b\d{1,2}:\d{2}\b", candidate):
                    continue
                return candidate

        return "unknown poll"

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

    def isValidSessionPoll(self, pollTitle: str) -> bool:
        return bool(
            re.match(
                r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
                pollTitle.strip(),
                re.IGNORECASE,
            )
        )

    # ## voter utilities
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
            if value.lower() == "you":
                value = self.config.myName or "You"
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

    def extractOptionVotersFromText(
        self, dialogText: str, optionTexts: Iterable[str]
    ) -> list[str]:
        optionNames = tuple(optionTexts)
        allOptionNames = set(
            self.selectors.yesOptionTexts + self.selectors.noOptionTexts
        )
        lines = [line.strip() for line in dialogText.splitlines() if line.strip()]

        captured: list[str] = []
        inSection = False

        for line in lines:
            if line in optionNames:
                inSection = True
                continue
            if inSection and line in allOptionNames:
                break
            if inSection:
                if self.looksLikeVoteCount(line):
                    continue
                if self.looksLikeSystemText(line):
                    continue
                captured.append(line)

        return self.cleanVoterNames(captured)

    def extractOptionVoters(self, dialog, optionTexts: Iterable[str]) -> list[str]:
        try:
            dialogText = dialog.inner_text(timeout=2000)
        except Exception:
            return []
        return self.extractOptionVotersFromText(dialogText, optionTexts)

    # ## text matching utilities
    def extractLikelyDateText(self, sourceText: str) -> str:
        match = re.search(
            r"\b(?:today|yesterday|\d{1,2}/\d{1,2}/\d{4})\b",
            sourceText,
            re.IGNORECASE,
        )
        return match.group(0) if match else ""

    def looksLikeSystemText(self, line: str) -> bool:
        lowered = line.lower().strip()
        systemFragments = (
            "select one or more",
            "view votes",
            "poll details",
            "message",
        )
        return any(fragment in lowered for fragment in systemFragments)

    def looksLikeVoteCount(self, line: str) -> bool:
        lowered = line.lower().strip()
        compact = lowered.replace(" ", "")
        return compact.isdigit() or bool(re.fullmatch(r"\d+votes?", lowered))
