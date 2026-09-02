"""Regression coverage for crying-face-only session cancellation."""

from datetime import date
from pathlib import Path
import re

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.parsing import PollTextParser
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.selectors import DEFAULT_SELECTORS


class ReactionLocator:
    def __init__(self, values: list[str]):
        self.values = values

    def evaluate(self, _script, marker: str):
        markerPattern = re.compile(rf"(?<!\w){re.escape(marker.casefold())}(?!\w)")
        return {
            "matched": any(
                "😢" in value and markerPattern.search(value.casefold())
                for value in self.values
            ),
            "candidates": self.values,
        }


def makeConfig() -> RuntimeConfig:
    return RuntimeConfig(
        groupName="Test Group",
        monthWindow=MonthWindow(
            monthKey="2026-08",
            startDate=date(2026, 8, 1),
            endDate=date(2026, 8, 31),
        ),
        outputDir=Path("/tmp/test_cancelled_rule"),
        userDataDir=Path("/tmp/test_cancelled_rule_profile"),
        headless=True,
        dryRun=True,
        timeoutMs=5000,
        logLevel=20,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=True,
        resume=False,
        pollTitleFilter=None,
    )


def testAnyCryingFaceReactionCancelsWithoutParticipantConfiguration():
    config = makeConfig()
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    discovery = PollDiscovery(config, DEFAULT_SELECTORS, parser)

    assert config.cancellationEmojiName == "reaction"
    assert (
        discovery.pollHasCancellationReaction(
            ReactionLocator(["reaction 😢. View reactions"])
        )
        is True
    )


def testOtherReactionDoesNotCancel():
    config = makeConfig()
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    discovery = PollDiscovery(config, DEFAULT_SELECTORS, parser)

    assert (
        discovery.pollHasCancellationReaction(
            ReactionLocator(["reaction 😂. View reactions"])
        )
        is False
    )
