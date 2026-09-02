"""Tests for refactored WhatsApp modules."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from datetime import date, datetime

import pytest

from attendanceConfig import MonthWindow, RuntimeConfig

from whatsapp.models import PollRecord
from whatsapp.pollRecordsBuilder import IncompletePollVotesError, PollRecordsBuilder
from whatsapp.parsing import PollTextParser
from whatsapp.reports import AttendanceReportBuilder
from whatsapp.records import deduplicateRecords
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollDialog import PollDialog
from whatsapp.navigation import GroupNotFoundError, WhatsAppNavigation
from whatsapp.scraper import WhatsAppPollScraper
from whatsapp.selectors import DEFAULT_SELECTORS
from whatsapp.exporter import AttendanceExporter

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _makeConfig(**overrides) -> RuntimeConfig:
    defaults = dict(
        groupName="Test Group",
        monthWindow=MonthWindow(
            monthKey="2026-03",
            startDate=date(2026, 3, 1),
            endDate=date(2026, 3, 31),
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
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _record(**overrides) -> PollRecord:
    defaults = dict(
        pollTitle="Monday Training",
        pollDateText="20260301",
        sessionDateText="20260302",
        option="Yes",
        voterName="Alice",
        sourceHint="",
    )
    defaults.update(overrides)
    return PollRecord(**defaults)


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------


def testDeduplicateRecordsRemovesDuplicates():
    records = [_record(), _record()]
    result = deduplicateRecords(records)
    assert len(result) == 1


def testRuntimeConfigDefaultsToStrictMonth():
    config = RuntimeConfig(
        groupName="Test Group",
        monthWindow=MonthWindow(
            monthKey="2026-03",
            startDate=date(2026, 3, 1),
            endDate=date(2026, 3, 31),
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
    )

    assert config.strictMonth is True


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def testExtractLikelyTimeText():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    assert parser.extractLikelyTimeText("Training\n10:30\nYes") == "10:30"


def testCleanVoterNames():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    result = parser.cleanVoterNames(["Alice", "Alice", "10:30", "Yes"])
    assert result == ["Alice"]


def testCleanVoterNamesRejectsPhoneNumberMetadata():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)

    assert parser.cleanVoterNames(["Sammy Leathem", "+44 7810 878563"]) == [
        "Sammy Leathem"
    ]


def testExtractOptionVoteCountFromPollCardText():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)

    assert (
        parser.extractOptionVoteCountFromText(
            "Wednesday 11am Football Factory\nYes\n13\nNo\n11",
            DEFAULT_SELECTORS.yesOptionTexts,
        )
        == 13
    )


def testIsSessionInMonthWindowReturnsTrueWhenNotStrict():
    parser = PollTextParser(_makeConfig(strictMonth=False), DEFAULT_SELECTORS)

    assert parser.isSessionInMonthWindow("20260406 19:00") is True


def testIsSessionInMonthWindowReturnsFalseForOutOfMonthStrict():
    parser = PollTextParser(_makeConfig(strictMonth=True), DEFAULT_SELECTORS)

    assert parser.isSessionInMonthWindow("20260406 19:00") is False


def testCalculateSessionDateTextPrefersExplicitDateInTitle():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)

    assert (
        parser.calculateSessionDateText(
            "Friday 12th June NIWFF club tournament", "20260511"
        )
        == "20260612 00:00"
    )


def testCalculateSessionDateTextAcceptsSessionPrefix():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)

    assert (
        parser.calculateSessionDateText("Session Sunday 7pm", "20260501")
        == "20260503 19:00"
    )


def testIsValidSessionPollAcceptsSessionPrefix():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)

    assert parser.isValidSessionPoll("Session Wednesday 11am") is True


class StubDiscoveryWithDate:
    def __init__(self, rawDateText: str):
        self.rawDateText = rawDateText

    def extractPollDateText(self, locator, sourceText: str) -> str:
        return self.rawDateText


def testBuildPollRecordsFromDialogSkipsOutOfMonthWhenStrict():
    config = _makeConfig(strictMonth=True)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscoveryWithDate("01/04/2026"),
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText="Monday 7pm LLC\nYes\nAlice",
        sourceText="Monday 7pm LLC\n01/04/2026\nView votes",
    )

    assert records == []


def testBuildPollRecordsFromDialogKeepsOutOfMonthWhenNotStrict():
    config = _makeConfig(strictMonth=False)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscoveryWithDate("01/04/2026"),
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText="Monday 7pm LLC\nYes\nAlice",
        sourceText="Monday 7pm LLC\n01/04/2026\nView votes",
    )

    assert len(records) == 1
    assert records[0].sessionDateText == "20260406 19:00"


def testBuildPollRecordsCombinesVirtualisedVoterSnapshots():
    config = _makeConfig(strictMonth=False)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscoveryWithDate("09/06/2026"),
    )
    firstSnapshot = (
        "Wednesday 11am Football Factory\nYes\nYou\nPete\nSammy Leathem\n"
        "+44 7810 878563\nShe\nTrevor Spiers\n+44 7394 976065\nNo"
    )
    secondSnapshot = (
        "Wednesday 11am Football Factory\nYes\nTerry\nJohn McDonald\nTom\nMina\n"
        "Eamon Quinn\nJim Davis\nIvaan Gilliland\nKate Robinson\nNo"
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText=firstSnapshot,
        dialogTexts=[firstSnapshot, secondSnapshot],
        sourceText=(
            "Wednesday 11am Football Factory\nSelect one or more\n"
            "Yes\n13\nNo\n11\nView votes"
        ),
    )

    assert len(records) == 13
    assert {record.voterName for record in records} >= {
        "Andy Wilson",
        "Pete",
        "Terry",
        "Kate Robinson",
    }
    assert not any(record.voterName.startswith("+44") for record in records)


def testBuildPollRecordsRejectsIncompleteVoterCapture():
    config = _makeConfig(strictMonth=False)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscoveryWithDate("09/06/2026"),
    )

    with pytest.raises(IncompletePollVotesError, match="captured 5 of 13"):
        builder.buildPollRecordsFromDialog(
            locator=None,
            dialog=None,
            dialogText=(
                "Wednesday 11am Football Factory\nYes\nYou\nPete\n"
                "Sammy Leathem\nShe\nTrevor Spiers\nNo"
            ),
            sourceText=(
                "Wednesday 11am Football Factory\nSelect one or more\n"
                "Yes\n13\nNo\n11\nView votes"
            ),
        )


def testBuildPollRecordsFromDialogPrefersPreDialogDate():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscoveryWithDate("06/05/2026"),
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText="Sunday 7pm football factory\nYes\nAlice",
        sourceText="Sunday 7pm football factory\nSelect one or more\nView votes",
        rawDateText="09/05/2026",
    )

    assert len(records) == 1
    assert records[0].pollDateText == "20260509"
    assert records[0].sessionDateText == "20260510 19:00"


def testBuildPollRecordsFromDialogSkipsExplicitFutureMonthWhenStrict():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscoveryWithDate("11/05/2026"),
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText="Friday 12th June NIWFF club tournament\nYes\nAlice",
        sourceText="Friday 12th June NIWFF club tournament\nView votes",
    )

    assert records == []


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


def testBuildSummaryRowsCountsVotes():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)

    records = [
        _record(voterName="Alice", option="Yes"),
        _record(voterName="Alice", option="No"),
    ]

    rows = builder.buildSummaryRows(records)
    alice = rows[0]

    assert alice["yesCount"] == 1
    assert alice["noCount"] == 1
    assert alice["totalVotes"] == 2


def testBuildAttendanceReportRowsSupportsDateOnlySessionDates():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)

    rows = builder.buildAttendanceReportRows(
        [
            _record(
                pollTitle="Monday Training",
                pollDateText="20260301",
                sessionDateText="20260302",
                voterName="Alice",
            )
        ]
    )

    assert rows[0] == ["Week", "week 1"]
    assert rows[1] == ["Date", "02/03/26"]
    assert rows[3] == ["Day", "Monday"]
    assert rows[5] == ["Alice", "yes"]
    assert rows[6] == ["Session Total", "1"]


def testBuildAttendanceReportRowsCountsOnlyYesVotesInSessionTotal():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)

    rows = builder.buildAttendanceReportRows(
        [
            _record(voterName="Alice", option="Yes"),
            _record(voterName="Bob", option="No"),
        ]
    )

    assert rows[-1] == ["Session Total", "1"]


def testBuildEmptyAttendanceReportHasAllHeaderRows():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    builder = AttendanceReportBuilder(parser)

    assert builder.buildAttendanceReportRows([]) == [
        ["Week"],
        ["Date"],
        ["Venue"],
        ["Day"],
        ["Name"],
    ]


def testWritePreviewJsonLogsSkipInDryRun(tmp_path):
    config = _makeConfig(outputDir=tmp_path, dryRun=True)
    exporter = AttendanceExporter(config)
    previewPath = tmp_path / "exportPreview-2026-03.json"

    exporter.writePreviewJson(
        rawRows=[{"pollTitle": "Training"}], summaryRows=[], reportRows=[]
    )

    assert previewPath.exists() is False
    assert ("action", ("write preview json: %s", previewPath), {}) not in (
        exporter.logger.messages
    )
    assert (
        "info",
        ("dry run: skipping preview json write: %s", previewPath),
        {},
    ) in exporter.logger.messages


def testBuildSocialMediaSummaryTextFromAttendanceReportRows(tmp_path):
    config = _makeConfig(outputDir=tmp_path)
    exporter = AttendanceExporter(config)

    reportRows = [
        ["Week", "week 1", ""],
        ["Date", "03/05/26", "05/05/26"],
        ["Venue", "Football Factory", "LLC"],
        ["Day", "Sunday", "Tuesday"],
        ["Name", "19:00", "10:30"],
        ["Al", "yes", ""],
        ["Bob", "no", "yes"],
        ["Session Total", "1", "1"],
    ]

    assert exporter.buildSocialMediaSummaryText(reportRows) == (
        "May 2026 attendance summary\n" "2 sessions\n" "- Al ... 1/2\n" "- Bob... 1/2"
    )


def testWriteSocialMediaSummaryTextLogsSkipInDryRun(tmp_path):
    config = _makeConfig(outputDir=tmp_path, dryRun=True)
    exporter = AttendanceExporter(config)
    summaryPath = tmp_path / "socialMediaSummary-2026-03.txt"

    exporter.writeSocialMediaSummaryText([])

    assert summaryPath.exists() is False
    assert (
        "info",
        ("dry run: skipping socialMediaSummary.txt write: %s", summaryPath),
        {},
    ) in exporter.logger.messages


def testRunBuildsOutputFromAllDatabaseRecordsNotOnlyScannedGroup(tmp_path, monkeypatch):
    config = _makeConfig(
        groupName="Selected Group",
        groupNames=("Selected Group",),
        outputDir=tmp_path,
    )
    exporter = AttendanceExporter(config)
    scannedRecord = _record(voterName="Recently Scanned")
    databaseRecords = [
        _record(voterName="Recently Scanned"),
        _record(voterName="Previously Stored"),
    ]
    writtenRecords = {}

    monkeypatch.setattr(
        exporter.pollScraper, "collectPollAttendance", lambda: [scannedRecord]
    )
    monkeypatch.setattr(
        exporter.attendanceStore,
        "attendanceRecords",
        lambda _startDate, _endDate: databaseRecords,
    )
    monkeypatch.setattr(exporter, "writeSummaryRows", lambda _rows: None)
    monkeypatch.setattr(exporter, "writeReportRows", lambda _rows: None)
    monkeypatch.setattr(
        exporter, "writeSocialMediaSummaryText", lambda _rows, voterPhones=None: None
    )
    monkeypatch.setattr(
        exporter,
        "writePreviewJson",
        lambda rawRows, _summaryRows, _reportRows: writtenRecords.update(
            {"rawRows": rawRows}
        ),
    )

    exporter.run()

    assert [row["voterName"] for row in writtenRecords["rawRows"]] == [
        "Recently Scanned",
        "Previously Stored",
    ]


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


class StubItem:
    def __init__(self, text: str, evaluatedText: str = ""):
        self.text = text
        self.evaluatedText = evaluatedText

    def inner_text(self, timeout=None):
        return self.text

    def locator(self, *_args, **_kwargs):
        raise RuntimeError

    def evaluate(self, *_args, **_kwargs):
        return self.evaluatedText


class StubNestedLocator:
    def __init__(self, text: str):
        self.text = text
        self.first = self

    def inner_text(self, timeout=None):
        return self.text


class StubItemWithLocatorTexts(StubItem):
    def __init__(self, text: str, locatorTexts: dict[str, str]):
        super().__init__(text)
        self.locatorTexts = locatorTexts

    def locator(self, selector, *_args, **_kwargs):
        if selector in self.locatorTexts:
            return StubNestedLocator(self.locatorTexts[selector])
        raise RuntimeError


class StubCollection:
    def __init__(self, texts):
        self.texts = texts

    def count(self):
        return len(self.texts)

    def nth(self, index):
        return StubItem(self.texts[index])


class StubItemCollection:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class StubPage:
    def __init__(self, mapping):
        self.mapping = mapping

    def locator(self, selector):
        return self.mapping.get(selector, StubCollection([]))


def testFindPollCards():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)

    page = StubPage(
        {
            'div[role="button"]:has-text("View votes")': StubCollection(
                ["Poll 1 View votes"]
            ),
        }
    )

    results = discovery.findPollCards(page)
    assert len(results) == 1


class StubDiscoveryWithSharedMessageKey(PollDiscovery):
    def extractMessageKey(self, locator) -> str:
        return "msg-container"


def testFindPollCardsKeepsDistinctPollsWithSameMessageKey():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = StubDiscoveryWithSharedMessageKey(
        _makeConfig(), DEFAULT_SELECTORS, parser
    )

    page = StubPage(
        {
            'div[role="button"]:has-text("View votes")': StubCollection(
                [
                    "Monday 7pm LLC\nView votes",
                    "Wednesday 8pm LLC\nView votes",
                ]
            ),
        }
    )

    results = discovery.findPollCards(page)

    assert len(results) == 2


def testExtractPollDateTextPrefersPreviousSiblingDateOverVisibleCandidate():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)
    item = StubItem("Sunday 7pm football factory\n12:18\nView votes")
    item.evaluate = lambda *_args, **_kwargs: {
        "visibleDateHeaders": ["09/05/2026"],
        "previousSiblingDates": ["06/05/2026"],
    }

    assert discovery.extractPollDateText(item, item.text) == "06/05/2026"


def testExtractPollDateTextCanSkipDomFallback():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)
    item = StubItem("Training\n10:30\nYes")
    item.evaluate = lambda *_args, **_kwargs: "01/03/2026"

    assert discovery.extractPollDateText(item, item.text) == "01/03/2026"
    assert discovery.extractPollDateText(item, item.text, allowDomFallback=False) == ""


def testExtractPollDateTextUsesPreviousSiblingDateAsLegacyFallback():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)
    item = StubItem("Tuesday 10.30am LLC\n08:39\nView votes")
    item.evaluate = lambda *_args, **_kwargs: {
        "visibleDateHeaders": [],
        "previousSiblingDates": ["11/05/2026"],
    }

    assert discovery.extractPollDateText(item, item.text) == "11/05/2026"


def testExtractPollDateTextUsesChatStartDateHeader():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)
    item = StubItem("Sunday 7pm Football Factory\nView votes")
    item.evaluate = lambda *_args, **_kwargs: {
        "visibleDateHeaders": [],
        "chatDateHeaders": ["24/07/2026"],
        "attributedDates": [],
        "previousSiblingDates": [],
    }

    rawDateText = discovery.extractPollDateText(item, item.text)

    assert rawDateText == "24/07/2026"
    assert (
        parser.calculateSessionDateText(
            pollTitle="Sunday 7pm Football Factory",
            pollDateText=parser.normaliseDateText(rawDateText),
        )
        == "20260726 19:00"
    )


def testExtractPollDateTextReadsShortYearDateFromSourceText():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)

    assert (
        discovery.extractPollDateText(None, "Posted 1/5/26\nSession Sunday 7pm")
        == "1/5/26"
    )
    assert parser.normaliseDateText("1/5/26") == "20260501"


def testExtractPollDateTextReadsWeekdayDateFromSourceText(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 5)

    monkeypatch.setattr("whatsapp.parsing.datetime", FixedDateTime)

    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)

    assert discovery.extractPollDateText(None, "Posted Friday\nSession Sunday 7pm") == (
        "Friday"
    )
    assert parser.normaliseDateText("Friday") == "20260529"


def testExtractPollSourceTextPrefersMessageContainerOverViewVotesLabel():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)
    item = StubItemWithLocatorTexts(
        "View votes",
        {
            "xpath=ancestor-or-self::*[@data-id][1]": (
                "Monday 7pm LLC\nSelect one or more\n01/03/2026\nView votes"
            ),
            "xpath=ancestor-or-self::*[contains(., 'View votes')][1]": "View votes",
        },
    )

    assert (
        discovery.extractPollSourceText(item)
        == "Monday 7pm LLC\nSelect one or more\n01/03/2026\nView votes"
    )


def testExtractPollSourceTextFallsBackToDomDebugText():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)
    item = StubItem(
        "View votes",
        evaluatedText="Posted 1/5/26\nSession Sunday 7pm 3/5/26\nView votes",
    )

    assert (
        discovery.extractPollSourceText(item)
        == "Posted 1/5/26\nSession Sunday 7pm 3/5/26\nView votes"
    )


def testFindPollCardsLogsDomDebugTextForSkippedCandidate():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_makeConfig(), DEFAULT_SELECTORS, parser)

    page = StubPage(
        {
            'div[role="button"]:has-text("View votes")': StubItemCollection(
                [StubItem("View votes", evaluatedText="aria-label only poll")]
            ),
        }
    )

    results = discovery.findPollCards(page)

    assert results == []
    assert discovery.logger.hasCall(
        "info",
        "skipping poll candidate missing usable source text: %s",
        "aria-label only poll",
    )


class StubDiscoveryWithVisiblePollDates:
    def __init__(self, rawDatesByLocator):
        self.rawDatesByLocator = rawDatesByLocator

    def extractPollSourceText(self, locator):
        return str(locator)

    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        return self.rawDatesByLocator[sourceText]


class StubDiscoveryWithOnlyDomFallbackDates(StubDiscoveryWithVisiblePollDates):
    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        if not allowDomFallback:
            return ""
        return self.rawDatesByLocator[sourceText]


class StubDiscoveryWithSourceTextAndDates:
    def __init__(self, sourceTextByLocator, rawDatesByLocator):
        self.sourceTextByLocator = sourceTextByLocator
        self.rawDatesByLocator = rawDatesByLocator

    def extractPollSourceText(self, locator):
        return self.sourceTextByLocator[locator]

    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        return self.rawDatesByLocator[locator]

    def extractMessageKey(self, locator) -> str:
        return str(locator)

    def buildPollLocatorKey(self, messageKey: str, sourceText: str) -> str:
        return f"{messageKey}|{sourceText}"


class StubDiscoveryWithSourceTexts:
    def __init__(self, sourceTextByLocator):
        self.sourceTextByLocator = sourceTextByLocator

    def extractPollSourceText(self, locator):
        return self.sourceTextByLocator[locator]

    def extractMessageKey(self, locator) -> str:
        return str(locator)

    def buildPollLocatorKey(self, messageKey: str, sourceText: str) -> str:
        return f"{messageKey}|{sourceText}"


def testShouldStopForStrictLookbackWithAllPollsBeforeCutoff():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithVisiblePollDates(
        {
            "poll-a": "23/04/2026",
            "poll-b": "22/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is True


def testShouldNotStopForStrictLookbackWhenOldestVisiblePollIsAtCutoff():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithVisiblePollDates(
        {
            "poll-a": "25/04/2026",
            "poll-b": "24/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is False


def testShouldStopForStrictLookbackWhenOlderPollIsVisibleWithNewerLoadedPoll():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithVisiblePollDates(
        {
            "poll-a": "24/04/2026",
            "poll-b": "22/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is True


def testShouldNotStopForStrictLookbackWhenOnlyDomFallbackDatesExist():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithOnlyDomFallbackDates(
        {
            "poll-a": "23/04/2026",
            "poll-b": "22/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is False


def testScrapePollLocatorMarksStopWhenSessionDateIsBeforeMonthWindow():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithSourceTextAndDates(
        sourceTextByLocator={
            "poll-a": "Posted 24/04/2026\nTuesday 7pm\nSelect one or more\nView votes",
        },
        rawDatesByLocator={"poll-a": "24/04/2026"},
    )

    result = scraper.scrapePollLocator(
        page=None,
        locator="poll-a",
        index=1,
        totalPolls=1,
        recordsByPollKey=OrderedDict(),
    )

    assert result == 0
    assert scraper.stopAfterCurrentPass is True


def testScrapePollLocatorDoesNotMarkStopForSessionInsideMonthWindow():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithSourceTextAndDates(
        sourceTextByLocator={
            "poll-a": "Posted 28/05/2026\nMonday 7pm\nSelect one or more\nView votes",
        },
        rawDatesByLocator={"poll-a": "28/05/2026"},
    )

    scraper.dialog = PollDialog(config=config, selectors=DEFAULT_SELECTORS)
    result = scraper.scrapePollLocator(
        page=None,
        locator="poll-a",
        index=1,
        totalPolls=1,
        recordsByPollKey=OrderedDict(),
    )

    assert result == 0
    assert scraper.stopAfterCurrentPass is False


def testLogVisiblePollCandidatesLogsEachNewPollOnce():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=_makeConfig(),
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    scraper.discovery = StubDiscoveryWithSourceTexts(
        {
            "poll-a": "Posted 28/04/2026\nMonday 7pm LLC\nSelect one or more\nView votes",
            "poll-b": "Posted 30/04/2026\nWednesday 8pm LLC\nSelect one or more\nView votes",
        }
    )

    scraper.logVisiblePollCandidates(["poll-a", "poll-b"], set())

    assert scraper.logger.hasCall("debug", "found poll: %s", "Monday 7pm LLC")
    assert scraper.logger.hasCall("debug", "found poll: %s", "Wednesday 8pm LLC")


def testLogVisiblePollCandidatesSkipsPollsSeenInPreviousPasses():
    parser = PollTextParser(_makeConfig(), DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=_makeConfig(),
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    sourceTexts = {
        "poll-a": "Posted 28/04/2026\nMonday 7pm LLC\nSelect one or more\nView votes",
        "poll-b": "Posted 30/04/2026\nWednesday 8pm LLC\nSelect one or more\nView votes",
    }
    scraper.discovery = StubDiscoveryWithSourceTexts(sourceTexts)

    beforeMondayCount = sum(
        call == ("debug", ("found poll: %s", "Monday 7pm LLC"), {})
        for call in scraper.logger.messages
    )
    beforeWednesdayCount = sum(
        call == ("debug", ("found poll: %s", "Wednesday 8pm LLC"), {})
        for call in scraper.logger.messages
    )

    scraper.logVisiblePollCandidates(
        ["poll-a", "poll-b"], {f"poll-a|{sourceTexts['poll-a']}"}
    )

    afterMondayCount = sum(
        call == ("debug", ("found poll: %s", "Monday 7pm LLC"), {})
        for call in scraper.logger.messages
    )
    afterWednesdayCount = sum(
        call == ("debug", ("found poll: %s", "Wednesday 8pm LLC"), {})
        for call in scraper.logger.messages
    )

    assert afterMondayCount == beforeMondayCount
    assert afterWednesdayCount == beforeWednesdayCount + 1


def testBuildScrapedPollKeyUsesNormalizedTitleAndDate():
    parser = PollTextParser(_makeConfig(strictMonth=True), DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=_makeConfig(strictMonth=True),
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )
    pollRecord = PollRecord(
        pollTitle="Tuesday 10.30am LLC",
        pollDateText="20260504",
        sessionDateText="20260505 10:30",
        option="Yes",
        voterName="Alice",
        sourceHint="",
    )
    sourceText = (
        "Tuesday 10.30am LLC\nSelect one or more\nYes\n18\nNo\n14\n08:39\nView votes"
    )

    pollKey = scraper.buildScrapedPollKey(
        sourceText=sourceText,
        pollRecord=pollRecord,
        fallbackPollKey="fallback-key",
    )

    assert pollKey == "20260505|tuesday 10.30am llc"


def testBuildPollKeyForLocatorUsesDomHeaderDate():
    parser = PollTextParser(_makeConfig(strictMonth=True), DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=_makeConfig(strictMonth=True),
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )

    pollKey, pollTitle, pollDateText = scraper.buildPollKeyForLocator(
        sourceText=(
            "Wednesday 11am Football Factory\n"
            "Select one or more\n"
            "Yes\n"
            "8\n"
            "No\n"
            "18\n"
            "13:44\n"
            "View votes"
        ),
        pollTitle="Wednesday 11am Football Factory",
        rawDateText="Tuesday",
    )

    assert pollTitle == "Wednesday 11am Football Factory"
    assert pollDateText
    assert pollKey == parser.buildPollKeyFromParts(
        pollTitle=pollTitle,
        pollDateText=pollDateText,
        sourceHint="",
    )


def testGroupPollKeyIncludesGroupName():
    config = _makeConfig(groupName="Group One", groupNames=("Group One",))
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
    )

    assert scraper.buildGroupPollKey("Group One", "poll-1") == "group one|poll-1"


def testBuildPollRecordsFromDialogKeepsShortYearSourceDatesWhenStrict():
    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=PollDiscovery(config, DEFAULT_SELECTORS, parser),
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText="Session Sunday 7pm\nYes\nAlice",
        sourceText="Posted 1/5/26\nSession Sunday 7pm\nView votes",
    )

    assert len(records) == 1
    assert records[0].pollDateText == "20260501"
    assert records[0].sessionDateText == "20260503 19:00"


def testBuildPollRecordsFromDialogKeepsWeekdaySourceDatesWhenStrict(
    monkeypatch,
):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 5)

    monkeypatch.setattr("whatsapp.parsing.datetime", FixedDateTime)

    config = _makeConfig(
        strictMonth=True,
        monthWindow=MonthWindow(
            monthKey="2026-05",
            startDate=date(2026, 5, 1),
            endDate=date(2026, 5, 31),
        ),
    )
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=PollDiscovery(config, DEFAULT_SELECTORS, parser),
    )

    records = builder.buildPollRecordsFromDialog(
        locator=None,
        dialog=None,
        dialogText="Session Sunday 7pm\nYes\nAlice",
        sourceText="Posted Friday\nSession Sunday 7pm\nView votes",
    )

    assert len(records) == 1
    assert records[0].pollDateText == "20260529"
    assert records[0].sessionDateText == "20260531 19:00"


# ---------------------------------------------------------------------------
# dialog
# ---------------------------------------------------------------------------


class FakeControl:
    def __init__(self, visible):
        self.visible = visible
        self.first = self
        self.clicked = False

    def is_visible(self, timeout=None):
        return self.visible

    def click(self, timeout=None):
        self.clicked = True


class FakePage:
    def __init__(self, mapping):
        self.mapping = mapping
        self.keyboard = self
        self.pressed = []

    def locator(self, selector):
        return self.mapping.get(selector, FakeControl(False))

    def wait_for_timeout(self, *_args):
        pass

    def press(self, key):
        self.pressed.append(key)


class FakeEmptyCollection:
    def count(self):
        return 0


class FakeDialogMouse:
    def wheel(self, *_args):
        pass


class FakeVirtualDialogPage:
    def __init__(self):
        self.mouse = FakeDialogMouse()

    def wait_for_timeout(self, *_args):
        pass


class FakeVirtualDialogPanel:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.snapshotIndex = 0
        self.page = FakeVirtualDialogPage()

    def evaluate(self, *_args):
        if self.snapshotIndex < len(self.snapshots) - 1:
            self.snapshotIndex += 1
            return {"moved": True, "atEnd": False, "count": 2}
        return {"moved": False, "atEnd": True, "count": 2}

    def get_by_text(self, *_args, **_kwargs):
        return FakeEmptyCollection()

    def hover(self):
        pass

    def inner_text(self, timeout=None):
        return self.snapshots[self.snapshotIndex]


class FakeExpandControl:
    def __init__(self, panel):
        self.panel = panel

    def click(self, timeout=None, force=False):
        self.panel.snapshotIndex = 1

    def evaluate(self, *_args):
        return "Yes"

    def is_visible(self, timeout=None):
        return True

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def evaluate(self, *_args):
        return "Yes"


class FakeExpandCollection:
    def __init__(self, panel):
        self.panel = panel

    def count(self):
        return 1 if self.panel.snapshotIndex == 0 else 0

    def nth(self, index):
        assert index == 0
        return FakeExpandControl(self.panel)


class FakeSeeAllDialogPanel(FakeVirtualDialogPanel):
    def evaluate(self, *_args):
        return {"moved": False, "atEnd": True, "count": 0, "results": []}

    def get_by_text(self, *_args, **_kwargs):
        return FakeExpandCollection(self)


class FakeSequentialExpandControl(FakeExpandControl):
    def click(self, timeout=None, force=False):
        self.panel.snapshotIndex += 1
        self.panel.clickCount += 1


class FakeSequentialExpandCollection(FakeExpandCollection):
    def count(self):
        return int(self.panel.snapshotIndex < len(self.panel.snapshots) - 1)

    def nth(self, index):
        assert index == 0
        return FakeSequentialExpandControl(self.panel)


class FakeSequentialSeeAllDialogPanel(FakeSeeAllDialogPanel):
    def __init__(self, snapshots):
        super().__init__(snapshots)
        self.clickCount = 0

    def get_by_text(self, *_args, **_kwargs):
        return FakeSequentialExpandCollection(self)


def testExpandAllVotersCollectsEachVirtualisedSnapshot():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)
    snapshots = [
        "Sunday 2pm Football Factory\nYes\nAlex\nBlair\nCasey\nNo",
        "Sunday 2pm Football Factory\nYes\nDevon\nElliot\nFrankie\nNo",
        "Sunday 2pm Football Factory\nYes\nGray\nHarper\nNo",
    ]
    panel = FakeVirtualDialogPanel(snapshots)

    captured = dialog.expandAllVoters(panel, initialText=snapshots[0])

    assert captured == snapshots


def testExpandAllVotersClicksExactSeeAllMoreControl():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)
    snapshots = [
        "Sunday 2pm Football Factory\nYes\nAlex\nBlair\nCasey\nDevon\nElliot\nNo",
        "Sunday 2pm Football Factory\nYes\nAlex\nBlair\nCasey\nDevon\nElliot\nFrankie\nGray\nHarper\nNo",
    ]
    panel = FakeSeeAllDialogPanel(snapshots)

    captured = dialog.expandAllVoters(panel, initialText=snapshots[0])

    assert captured == snapshots


def testExpandAllVotersRechecksControlsAfterPanelReplacement():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)
    snapshots = [
        "Thursday 8pm LLC\nYes\nAlex\nBlair\nCasey\nDevon\nElliot\nNo\nMina",
        "Thursday 8pm LLC\nYes\nAlex\nBlair\nCasey\nDevon\nElliot\nNo\nMina\nNoel",
        "Thursday 8pm LLC\nYes\nAlex\nBlair\nCasey\nDevon\nElliot\nFrankie\nGray\nHarper\nNo\nMina\nNoel",
    ]
    panel = FakeSequentialSeeAllDialogPanel(snapshots)

    captured = dialog.expandAllVoters(panel, initialText=snapshots[0])

    assert panel.clickCount == 2
    assert captured == [snapshots[0], snapshots[2]]


def testExpandedVoterSnapshotRestoresMissingOptionHeading():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)

    assert dialog.labelExpandedSnapshot("Alice\nBob", "Yes") == "Yes\nAlice\nBob"
    assert dialog.labelExpandedSnapshot("Yes\nAlice\nBob", "Yes") == ("Yes\nAlice\nBob")


def testCloseDialogUsesCloseButton():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)
    control = FakeControl(True)
    page = FakePage({'button[aria-label="Close"]': control})

    dialog.closeDialog(page, None)
    assert control.clicked is True


def testCloseDialogFallsBackToEscape():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)
    page = FakePage({})

    dialog.closeDialog(page, None)
    assert "Escape" in page.pressed


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------


class FakeMouse:
    def __init__(self):
        self.wheels = []

    def wheel(self, delta_x, delta_y):
        self.wheels.append((delta_x, delta_y))


class FakeNavigationPage:
    def __init__(self, evaluateResult):
        self.evaluateResult = evaluateResult
        self.mouse = FakeMouse()

    def get_by_text(self, *_args, **_kwargs):
        return FakeControl(False)

    def evaluate(self, *_args, **_kwargs):
        return self.evaluateResult

    def wait_for_timeout(self, *_args):
        pass


class FakeKeyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


class FakeSearchControl:
    def __init__(self, *, visible=True, failClicks=0):
        self.visible = visible
        self.failClicks = failClicks
        self.first = self
        self.clicked = 0
        self.filled = []
        self.typed = []

    def is_visible(self, timeout=None):
        return self.visible

    def click(self, timeout=None):
        self.clicked += 1
        if self.clicked <= self.failClicks:
            raise TimeoutError("not clickable yet")

    def fill(self, value):
        self.filled.append(value)

    def type(self, value, delay=None):
        self.typed.append(value)


class FakeMissingSearchControl(FakeControl):
    def __init__(self):
        super().__init__(False)

    def click(self, timeout=None):
        raise TimeoutError("missing")


class FakeTextMatch:
    def __init__(self, visible=True):
        self.first = self
        self.clicked = False
        self.visible = visible

    def count(self):
        return 1

    def nth(self, index):
        assert index == 0
        return self

    def is_visible(self, timeout=None):
        return self.visible

    def click(self, timeout=None):
        self.clicked = True


class FakeMissingTextMatch(FakeTextMatch):
    def __init__(self):
        super().__init__(visible=False)

    def click(self, timeout=None):
        raise TimeoutError("missing group")


class FakeTextMatches:
    def __init__(self, matches):
        self.matches = matches

    def count(self):
        return len(self.matches)

    def nth(self, index):
        return self.matches[index]


class FakeDelayedTextMatches(FakeTextMatches):
    def __init__(self, matches, emptyCounts=1):
        super().__init__(matches)
        self.emptyCounts = emptyCounts

    def count(self):
        if self.emptyCounts:
            self.emptyCounts -= 1
            return 0
        return super().count()


class FakeOpenGroupPage:
    def __init__(self, mapping):
        self.mapping = mapping
        self.keyboard = FakeKeyboard()
        self.textMatch = FakeTextMatch()
        self.waits = []

    def locator(self, selector):
        return self.mapping.get(selector, FakeMissingSearchControl())

    def get_by_text(self, *_args, **_kwargs):
        return self.textMatch

    def wait_for_timeout(self, value):
        self.waits.append(value)


class FakeReadyPage:
    def __init__(self, mapping):
        self.mapping = mapping
        self.loadedStates = []

    def wait_for_load_state(self, state):
        self.loadedStates.append(state)

    def locator(self, selector):
        return self.mapping.get(selector, FakeControl(False))


def testWaitForWhatsappReadyUsesReadyIndicators():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    chatList = FakeControl(True)
    page = FakeReadyPage({"#pane-side": chatList})

    navigation.waitForWhatsAppReady(page)

    assert page.loadedStates == ["domcontentloaded"]


def testOpenGroupRetriesSearchAfterReopeningSearch():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    searchBox = FakeSearchControl(failClicks=2)
    activator = FakeSearchControl()
    page = FakeOpenGroupPage(
        {
            '[aria-label="Search or start a new chat"]': searchBox,
            'button[aria-label="Search"]': activator,
        }
    )

    navigation.openGroup(page, "Second Group")

    assert page.keyboard.pressed == ["Escape", "Escape"]
    assert searchBox.typed == ["Second Group"]
    assert page.textMatch.clicked is True


def testOpenGroupSkipsHiddenExactTextMatch():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    searchBox = FakeSearchControl()
    hiddenMatch = FakeTextMatch(visible=False)
    visibleMatch = FakeTextMatch()
    page = FakeOpenGroupPage({'[aria-label="Search or start a new chat"]': searchBox})
    page.textMatch = FakeTextMatches([hiddenMatch, visibleMatch])

    navigation.openGroup(page, "HWFC Information")

    assert hiddenMatch.clicked is False
    assert visibleMatch.clicked is True


def testOpenGroupWaitsForAsyncSearchResults():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    searchBox = FakeSearchControl()
    visibleMatch = FakeTextMatch()
    page = FakeOpenGroupPage({'[aria-label="Search or start a new chat"]': searchBox})
    page.textMatch = FakeDelayedTextMatches([visibleMatch])

    navigation.openGroup(page, "HWFC Information")

    assert visibleMatch.clicked is True
    assert 750 in page.waits


def testOpenGroupUsesChatListSearchNotInChatSearch():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    chatListSearch = FakeSearchControl()
    inChatSearch = FakeSearchControl()
    page = FakeOpenGroupPage(
        {
            '#side [aria-label="Search or start a new chat"]': chatListSearch,
            '[placeholder="Search"]': inChatSearch,
        }
    )

    navigation.openGroup(page, "HWFC Information")

    assert chatListSearch.typed == ["HWFC Information"]
    assert inChatSearch.typed == []


def testOpenGroupReplacesExistingChatListSearchQuery():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    activeSearch = FakeSearchControl()
    page = FakeOpenGroupPage({'#side input[placeholder="Search"]': activeSearch})

    navigation.openGroup(page, "HWFC Information")

    assert activeSearch.filled == [""]
    assert activeSearch.typed == ["HWFC Information"]


def testOpenGroupReportsMissingExactGroupName():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    searchBox = FakeSearchControl()
    page = FakeOpenGroupPage({'[aria-label="Search or start a new chat"]': searchBox})
    page.textMatch = FakeMissingTextMatch()

    try:
        navigation.openGroup(page, "Missing Group")
    except GroupNotFoundError as exc:
        assert str(exc) == ('WhatsApp group not found with exact name: "Missing Group"')
    else:
        raise AssertionError("expected GroupNotFoundError")


def testScrollChatToLatestSkipsMouseWheelWhenPreferredPanelScrolls():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": True,
            "usedPreferredTarget": True,
            "dataTestId": "conversation-panel-messages",
        }
    )

    navigation.scrollChatToLatest(page)

    assert page.mouse.wheels == []


def testScrollChatToLatestFallsBackToMouseWheelWithoutPreferredPanel():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": False,
            "usedPreferredTarget": False,
            "reason": "no preferred target",
        }
    )

    navigation.scrollChatToLatest(page)

    assert page.mouse.wheels == [(0, 2500)]


def testScrollChatHistorySkipsMouseWheelWhenPreferredPanelScrolls():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": True,
            "usedPreferredTarget": True,
            "dataTestId": "conversation-panel-messages",
        }
    )

    madeProgress = navigation.scrollChatHistory(page)

    assert page.mouse.wheels == []
    assert madeProgress is True


def testScrollChatHistoryFallsBackToMouseWheelWithoutPreferredScroll():
    navigation = WhatsAppNavigation(_makeConfig(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": False,
            "usedPreferredTarget": False,
            "dataTestId": "pane-side",
        }
    )

    madeProgress = navigation.scrollChatHistory(page)

    assert page.mouse.wheels == [(0, -2500)]
    assert madeProgress is False
