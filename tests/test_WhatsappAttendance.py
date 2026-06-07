"""Tests for refactored WhatsApp modules."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from datetime import date, datetime

from attendanceConfig import MonthWindow, RuntimeConfig

from whatsapp.models import PollRecord
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.parsing import PollTextParser
from whatsapp.reports import AttendanceReportBuilder
from whatsapp.records import deduplicateRecords
from whatsapp.cache import PollCacheStore
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollDialog import PollDialog
from whatsapp.navigation import WhatsAppNavigation
from whatsapp.scraper import WhatsAppPollScraper
from whatsapp.selectors import DEFAULT_SELECTORS
from whatsapp.constants import POLL_CACHE_VERSION
from whatsapp.exporter import AttendanceExporter

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> RuntimeConfig:
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


def test_deduplicate_records_removes_duplicates():
    records = [_record(), _record()]
    result = deduplicateRecords(records)
    assert len(result) == 1


def test_runtime_config_defaults_to_strict_month():
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


def test_extract_likely_time_text():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    assert parser.extractLikelyTimeText("Training\n10:30\nYes") == "10:30"


def test_clean_voter_names():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    result = parser.cleanVoterNames(["Alice", "Alice", "10:30", "Yes"])
    assert result == ["Alice"]


def test_is_session_in_month_window_returns_true_when_not_strict():
    parser = PollTextParser(_make_config(strictMonth=False), DEFAULT_SELECTORS)

    assert parser.isSessionInMonthWindow("20260406 19:00") is True


def test_is_session_in_month_window_returns_false_for_out_of_month_strict():
    parser = PollTextParser(_make_config(strictMonth=True), DEFAULT_SELECTORS)

    assert parser.isSessionInMonthWindow("20260406 19:00") is False


def test_calculate_session_date_text_prefers_explicit_date_in_title():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)

    assert (
        parser.calculateSessionDateText(
            "Friday 12th June NIWFF club tournament", "20260511"
        )
        == "20260612 00:00"
    )


def test_calculate_session_date_text_accepts_session_prefix():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)

    assert (
        parser.calculateSessionDateText("Session Sunday 7pm", "20260501")
        == "20260503 19:00"
    )


def test_is_valid_session_poll_accepts_session_prefix():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)

    assert parser.isValidSessionPoll("Session Wednesday 11am") is True


class StubDiscoveryWithDate:
    def __init__(self, raw_date_text: str):
        self.raw_date_text = raw_date_text

    def extractPollDateText(self, locator, sourceText: str) -> str:
        return self.raw_date_text


def test_build_poll_records_from_dialog_skips_out_of_month_when_strict():
    config = _make_config(strictMonth=True)
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


def test_build_poll_records_from_dialog_keeps_out_of_month_when_not_strict():
    config = _make_config(strictMonth=False)
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


def test_build_poll_records_from_dialog_skips_explicit_future_month_when_strict():
    config = _make_config(
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


def test_poll_cache_payload_respects_strict_mode():
    config = _make_config(strictMonth=True)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    cache_store = PollCacheStore(config=config, parser=parser)

    is_valid = cache_store.isValidCachePayload(
        {
            "version": POLL_CACHE_VERSION,
            "groupName": config.groupName,
            "month": config.monthWindow.monthKey,
            "strictMonth": False,
        },
        Path("/tmp/pollCache.json"),
    )

    assert is_valid is False


def test_save_poll_cache_logs_skip_in_dry_run(tmp_path):
    config = _make_config(outputDir=tmp_path, dryRun=True)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    cache_store = PollCacheStore(config=config, parser=parser)

    cache_store.savePollCache({"poll-1": [_record()]})

    assert cache_store.getPollCachePath().exists() is False
    assert (
        "action",
        ("write poll cache: %s", cache_store.getPollCachePath()),
        {},
    ) not in (cache_store.logger.messages)
    assert (
        "info",
        ("dry run: skipping poll cache write: %s", cache_store.getPollCachePath()),
        {},
    ) in cache_store.logger.messages


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


def test_build_summary_rows_counts_votes():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
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


def test_build_attendance_report_rows_supports_date_only_session_dates():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
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

    assert rows[0] == ["week", "week 1"]
    assert rows[1] == ["date", "02/03/26"]
    assert rows[3] == ["day", "Monday"]
    assert rows[5] == ["Alice", "yes"]


def test_write_preview_json_logs_skip_in_dry_run(tmp_path):
    config = _make_config(outputDir=tmp_path, dryRun=True)
    exporter = AttendanceExporter(config)
    preview_path = tmp_path / "exportPreview.json"

    exporter.writePreviewJson(
        rawRows=[{"pollTitle": "Training"}], summaryRows=[], reportRows=[]
    )

    assert preview_path.exists() is False
    assert ("action", ("write preview json: %s", preview_path), {}) not in (
        exporter.logger.messages
    )
    assert (
        "info",
        ("dry run: skipping preview json write: %s", preview_path),
        {},
    ) in exporter.logger.messages


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


class StubItem:
    def __init__(self, text: str, evaluated_text: str = ""):
        self.text = text
        self.evaluated_text = evaluated_text

    def inner_text(self, timeout=None):
        return self.text

    def locator(self, *_args, **_kwargs):
        raise RuntimeError

    def evaluate(self, *_args, **_kwargs):
        return self.evaluated_text


class StubNestedLocator:
    def __init__(self, text: str):
        self.text = text
        self.first = self

    def inner_text(self, timeout=None):
        return self.text


class StubItemWithLocatorTexts(StubItem):
    def __init__(self, text: str, locator_texts: dict[str, str]):
        super().__init__(text)
        self.locator_texts = locator_texts

    def locator(self, selector, *_args, **_kwargs):
        if selector in self.locator_texts:
            return StubNestedLocator(self.locator_texts[selector])
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


def test_find_poll_cards():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)

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


def test_find_poll_cards_keeps_distinct_polls_with_same_message_key():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = StubDiscoveryWithSharedMessageKey(
        _make_config(), DEFAULT_SELECTORS, parser
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


def test_extract_poll_date_text_falls_back_to_dom_date_when_source_only_has_time():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)
    item = StubItem("Training\n10:30\nYes")
    item.evaluate = lambda *_args, **_kwargs: "01/03/2026"

    assert discovery.extractPollDateText(item, item.text) == "01/03/2026"


def test_extract_poll_date_text_can_skip_dom_fallback():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)
    item = StubItem("Training\n10:30\nYes")
    item.evaluate = lambda *_args, **_kwargs: "01/03/2026"

    assert discovery.extractPollDateText(item, item.text) == "01/03/2026"
    assert discovery.extractPollDateText(item, item.text, allowDomFallback=False) == ""


def test_extract_poll_date_text_reads_short_year_date_from_source_text():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)

    assert (
        discovery.extractPollDateText(None, "Posted 1/5/26\nSession Sunday 7pm")
        == "1/5/26"
    )
    assert parser.normaliseDateText("1/5/26") == "20260501"


def test_extract_poll_date_text_reads_weekday_date_from_source_text(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 5)

    monkeypatch.setattr("whatsapp.parsing.datetime", FixedDateTime)

    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)

    assert discovery.extractPollDateText(None, "Posted Friday\nSession Sunday 7pm") == (
        "Friday"
    )
    assert parser.normaliseDateText("Friday") == "20260529"


def test_extract_poll_source_text_prefers_message_container_over_view_votes_label():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)
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


def test_extract_poll_source_text_falls_back_to_dom_debug_text():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)
    item = StubItem(
        "View votes",
        evaluated_text="Posted 1/5/26\nSession Sunday 7pm 3/5/26\nView votes",
    )

    assert (
        discovery.extractPollSourceText(item)
        == "Posted 1/5/26\nSession Sunday 7pm 3/5/26\nView votes"
    )


def test_find_poll_cards_logs_dom_debug_text_for_skipped_candidate():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    discovery = PollDiscovery(_make_config(), DEFAULT_SELECTORS, parser)

    page = StubPage(
        {
            'div[role="button"]:has-text("View votes")': StubItemCollection(
                [StubItem("View votes", evaluated_text="aria-label only poll")]
            ),
        }
    )

    results = discovery.findPollCards(page)

    assert results == []
    assert discovery.logger.has_call(
        "info",
        "skipping poll candidate missing usable source text: %s",
        "aria-label only poll",
    )


class StubDiscoveryWithVisiblePollDates:
    def __init__(self, raw_dates_by_locator):
        self.raw_dates_by_locator = raw_dates_by_locator

    def extractPollSourceText(self, locator):
        return str(locator)

    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        return self.raw_dates_by_locator[sourceText]


class StubDiscoveryWithOnlyDomFallbackDates(StubDiscoveryWithVisiblePollDates):
    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        if not allowDomFallback:
            return ""
        return self.raw_dates_by_locator[sourceText]


class StubDiscoveryWithSourceTextAndDates:
    def __init__(self, source_text_by_locator, raw_dates_by_locator):
        self.source_text_by_locator = source_text_by_locator
        self.raw_dates_by_locator = raw_dates_by_locator

    def extractPollSourceText(self, locator):
        return self.source_text_by_locator[locator]

    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        return self.raw_dates_by_locator[locator]

    def extractMessageKey(self, locator) -> str:
        return str(locator)

    def buildPollLocatorKey(self, messageKey: str, sourceText: str) -> str:
        return f"{messageKey}|{sourceText}"


def test_should_stop_for_strict_lookback_with_all_polls_before_cutoff():
    config = _make_config(
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
        cacheStore=PollCacheStore(config=config, parser=parser),
    )
    scraper.discovery = StubDiscoveryWithVisiblePollDates(
        {
            "poll-a": "23/04/2026",
            "poll-b": "22/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is True


def test_should_not_stop_for_strict_lookback_when_oldest_visible_poll_is_at_cutoff():
    config = _make_config(
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
        cacheStore=PollCacheStore(config=config, parser=parser),
    )
    scraper.discovery = StubDiscoveryWithVisiblePollDates(
        {
            "poll-a": "25/04/2026",
            "poll-b": "24/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is False


def test_should_stop_for_strict_lookback_when_older_poll_is_visible_with_newer_loaded_poll():
    config = _make_config(
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
        cacheStore=PollCacheStore(config=config, parser=parser),
    )
    scraper.discovery = StubDiscoveryWithVisiblePollDates(
        {
            "poll-a": "24/04/2026",
            "poll-b": "22/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is True


def test_should_not_stop_for_strict_lookback_when_only_dom_fallback_dates_exist():
    config = _make_config(
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
        cacheStore=PollCacheStore(config=config, parser=parser),
    )
    scraper.discovery = StubDiscoveryWithOnlyDomFallbackDates(
        {
            "poll-a": "23/04/2026",
            "poll-b": "22/04/2026",
        }
    )

    assert scraper.shouldStopForStrictLookback(["poll-a", "poll-b"]) is False


def test_scrape_poll_locator_marks_stop_when_session_date_is_before_month_window():
    config = _make_config(
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
        cacheStore=PollCacheStore(config=config, parser=parser),
    )
    scraper.discovery = StubDiscoveryWithSourceTextAndDates(
        source_text_by_locator={
            "poll-a": "Posted 24/04/2026\nTuesday 7pm\nView votes",
        },
        raw_dates_by_locator={"poll-a": "24/04/2026"},
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


def test_scrape_poll_locator_does_not_mark_stop_for_session_inside_month_window():
    config = _make_config(
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
        cacheStore=PollCacheStore(config=config, parser=parser),
    )
    scraper.discovery = StubDiscoveryWithSourceTextAndDates(
        source_text_by_locator={
            "poll-a": "Posted 24/04/2026\nFriday 7pm\nView votes",
        },
        raw_dates_by_locator={"poll-a": "24/04/2026"},
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


def test_build_scraped_poll_key_uses_source_hint_when_date_only_comes_from_dom():
    parser = PollTextParser(_make_config(strictMonth=True), DEFAULT_SELECTORS)
    scraper = WhatsAppPollScraper(
        config=_make_config(strictMonth=True),
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        cacheStore=PollCacheStore(config=_make_config(strictMonth=True), parser=parser),
    )
    poll_record = PollRecord(
        pollTitle="Tuesday 10.30am LLC",
        pollDateText="20260504",
        sessionDateText="20260505 10:30",
        option="Yes",
        voterName="Alice",
        sourceHint="",
    )
    source_text = (
        "Tuesday 10.30am LLC\nSelect one or more\nYes\n18\nNo\n14\n08:39\nView votes"
    )

    poll_key = scraper.buildScrapedPollKey(
        sourceText=source_text,
        pollRecord=poll_record,
        fallbackPollKey="fallback-key",
    )

    assert poll_key == f"{poll_record.pollTitle}|{source_text[:80]}"


def test_build_poll_records_from_dialog_keeps_short_year_source_dates_when_strict():
    config = _make_config(
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


def test_build_poll_records_from_dialog_keeps_weekday_source_dates_when_strict(
    monkeypatch,
):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 5)

    monkeypatch.setattr("whatsapp.parsing.datetime", FixedDateTime)

    config = _make_config(
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


def test_close_dialog_uses_close_button():
    dialog = PollDialog(_make_config(), DEFAULT_SELECTORS)
    control = FakeControl(True)
    page = FakePage({'button[aria-label="Close"]': control})

    dialog.closeDialog(page, None)
    assert control.clicked is True


def test_close_dialog_falls_back_to_escape():
    dialog = PollDialog(_make_config(), DEFAULT_SELECTORS)
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
    def __init__(self, evaluate_result):
        self.evaluate_result = evaluate_result
        self.mouse = FakeMouse()

    def get_by_text(self, *_args, **_kwargs):
        return FakeControl(False)

    def evaluate(self, *_args, **_kwargs):
        return self.evaluate_result

    def wait_for_timeout(self, *_args):
        pass


def test_scroll_chat_to_latest_skips_mouse_wheel_when_preferred_panel_scrolls():
    navigation = WhatsAppNavigation(_make_config(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": True,
            "usedPreferredTarget": True,
            "dataTestId": "conversation-panel-messages",
        }
    )

    navigation.scrollChatToLatest(page)

    assert page.mouse.wheels == []


def test_scroll_chat_to_latest_falls_back_to_mouse_wheel_without_preferred_panel():
    navigation = WhatsAppNavigation(_make_config(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": False,
            "usedPreferredTarget": False,
            "reason": "no preferred target",
        }
    )

    navigation.scrollChatToLatest(page)

    assert page.mouse.wheels == [(0, 2500)]


def test_scroll_chat_history_skips_mouse_wheel_when_preferred_panel_scrolls():
    navigation = WhatsAppNavigation(_make_config(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": True,
            "usedPreferredTarget": True,
            "dataTestId": "conversation-panel-messages",
        }
    )

    navigation.scrollChatHistory(page)

    assert page.mouse.wheels == []


def test_scroll_chat_history_falls_back_to_mouse_wheel_without_preferred_scroll():
    navigation = WhatsAppNavigation(_make_config(), DEFAULT_SELECTORS)
    page = FakeNavigationPage(
        {
            "didScroll": False,
            "usedPreferredTarget": False,
            "dataTestId": "pane-side",
        }
    )

    navigation.scrollChatHistory(page)

    assert page.mouse.wheels == [(0, -2500)]
