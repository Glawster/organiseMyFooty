"""Regression tests for WhatsApp poll date and title parsing."""

from datetime import date
from pathlib import Path

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.parsing import PollTextParser
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.selectors import DEFAULT_SELECTORS


def _makeConfig() -> RuntimeConfig:
    return RuntimeConfig(
        groupName="Test Group",
        monthWindow=MonthWindow(
            monthKey="2026-08",
            startDate=date(2026, 8, 1),
            endDate=date(2026, 8, 31),
        ),
        outputDir=Path("/tmp/test_output"),
        userDataDir=Path("/tmp/test_profile"),
        headless=True,
        dryRun=True,
        timeoutMs=5000,
        logLevel=20,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=False,
        resume=False,
        pollTitleFilter=None,
        strictMonth=True,
    )


def testSelectDomFallbackDatePrefersLocalSiblingDate():
    config = _makeConfig()
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    discovery = PollDiscovery(config, DEFAULT_SELECTORS, parser)

    payload = {
        "visibleDateHeaders": ["07/05/2026", "05/06/2026", "Wednesday"],
        "chatDateHeaders": [],
        "attributedDates": ["06/08/2026", "05/08/2026"],
        "previousSiblingDates": ["06/08/2026"],
    }

    assert discovery.selectDomFallbackDate(payload) == "06/08/2026"


def testExtractSessionPartsAcceptsAtSignBeforeTime():
    config = _makeConfig()
    parser = PollTextParser(config, DEFAULT_SELECTORS)

    assert parser.extractSessionParts("Sunday @ 2pm football factory") == (
        "14:00",
        "football factory",
    )
    assert (
        parser.calculateSessionDateText(
            "Sunday @ 2pm football factory",
            "20260821",
        )
        == "20260823 14:00"
    )
