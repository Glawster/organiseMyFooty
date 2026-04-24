"""Tests for non-browser helper methods in whatsappAttendance module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from attendanceConfig import MonthWindow, RuntimeConfig
import whatsappAttendance
from whatsappAttendance import AttendanceExporter, PollRecord, PollTarget

from datetime import date

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> RuntimeConfig:
    """Return a minimal RuntimeConfig suitable for unit tests."""
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
    )
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _make_exporter(**overrides) -> AttendanceExporter:
    return AttendanceExporter(_make_config(**overrides))


def _record(
    pollTitle="Match 1",
    pollDateText="10:00",
    option="Yes",
    voterName="Alice",
    sourceHint="",
) -> PollRecord:
    return PollRecord(
        pollTitle=pollTitle,
        pollDateText=pollDateText,
        option=option,
        voterName=voterName,
        sourceHint=sourceHint,
    )


# ---------------------------------------------------------------------------
# deduplicateRecords
# ---------------------------------------------------------------------------


class TestDeduplicateRecords:
    def test_no_duplicates_unchanged(self):
        exporter = _make_exporter()
        records = [
            _record(voterName="Alice"),
            _record(voterName="Bob"),
        ]
        result = exporter.deduplicateRecords(records)
        assert result == records

    def test_exact_duplicate_removed(self):
        exporter = _make_exporter()
        records = [_record(), _record()]
        result = exporter.deduplicateRecords(records)
        assert len(result) == 1

    def test_different_option_not_deduplicated(self):
        exporter = _make_exporter()
        records = [
            _record(option="Yes"),
            _record(option="No"),
        ]
        result = exporter.deduplicateRecords(records)
        assert len(result) == 2

    def test_preserves_order_of_first_occurrence(self):
        exporter = _make_exporter()
        r1 = _record(voterName="Alice")
        r2 = _record(voterName="Bob")
        r3 = _record(voterName="Alice")  # duplicate
        result = exporter.deduplicateRecords([r1, r2, r3])
        assert result == [r1, r2]


# ---------------------------------------------------------------------------
# buildSummaryRows
# ---------------------------------------------------------------------------


class TestBuildSummaryRows:
    def test_empty_records_returns_empty_list(self):
        exporter = _make_exporter()
        assert exporter.buildSummaryRows([]) == []

    def test_counts_yes_votes(self):
        exporter = _make_exporter()
        records = [
            _record(pollTitle="P1", voterName="Alice", option="Yes"),
            _record(pollTitle="P2", voterName="Alice", option="Yes"),
        ]
        rows = exporter.buildSummaryRows(records)
        alice = next(r for r in rows if r["name"] == "Alice")
        assert alice["yesCount"] == 2
        assert alice["noCount"] == 0
        assert alice["totalVotes"] == 2

    def test_counts_no_votes(self):
        exporter = _make_exporter()
        records = [
            _record(voterName="Bob", option="No"),
        ]
        rows = exporter.buildSummaryRows(records)
        bob = rows[0]
        assert bob["noCount"] == 1
        assert bob["yesCount"] == 0

    def test_polls_responded_counts_unique_polls(self):
        exporter = _make_exporter()
        records = [
            _record(pollTitle="P1", pollDateText="d1", voterName="Alice"),
            _record(pollTitle="P1", pollDateText="d1", voterName="Alice", option="No"),
            _record(pollTitle="P2", pollDateText="d2", voterName="Alice"),
        ]
        rows = exporter.buildSummaryRows(records)
        alice = rows[0]
        assert alice["pollsResponded"] == 2

    def test_output_sorted_by_name(self):
        exporter = _make_exporter()
        records = [
            _record(voterName="Zara"),
            _record(voterName="Alice"),
            _record(voterName="Mike"),
        ]
        rows = exporter.buildSummaryRows(records)
        names = [r["name"] for r in rows]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# looksLikeVoteCount
# ---------------------------------------------------------------------------


class TestLooksLikeVoteCount:
    def test_plain_digit_is_vote_count(self):
        exporter = _make_exporter()
        assert exporter.looksLikeVoteCount("5") is True

    def test_digit_with_spaces_is_vote_count(self):
        exporter = _make_exporter()
        assert exporter.looksLikeVoteCount("1 2") is True

    def test_votes_suffix_singular(self):
        exporter = _make_exporter()
        assert exporter.looksLikeVoteCount("1vote") is True

    def test_votes_suffix_plural(self):
        exporter = _make_exporter()
        assert exporter.looksLikeVoteCount("3votes") is True

    def test_name_is_not_vote_count(self):
        exporter = _make_exporter()
        assert exporter.looksLikeVoteCount("Alice") is False

    def test_mixed_alphanumeric_is_not_vote_count(self):
        exporter = _make_exporter()
        assert exporter.looksLikeVoteCount("abc123") is False


# ---------------------------------------------------------------------------
# looksLikeSystemText
# ---------------------------------------------------------------------------


class TestLooksLikeSystemText:
    def test_view_votes_is_system_text(self):
        exporter = _make_exporter()
        assert exporter.looksLikeSystemText("View votes") is True

    def test_select_one_or_more_is_system_text(self):
        exporter = _make_exporter()
        assert exporter.looksLikeSystemText("Select one or more") is True

    def test_poll_label_is_system_text(self):
        exporter = _make_exporter()
        assert exporter.looksLikeSystemText("This is a poll") is True

    def test_person_name_is_not_system_text(self):
        exporter = _make_exporter()
        assert exporter.looksLikeSystemText("Alice Johnson") is False

    def test_case_insensitive(self):
        exporter = _make_exporter()
        assert exporter.looksLikeSystemText("VIEW VOTES") is True


# ---------------------------------------------------------------------------
# cleanVoterNames
# ---------------------------------------------------------------------------


class TestCleanVoterNames:
    def test_removes_empty_strings(self):
        exporter = _make_exporter()
        result = exporter.cleanVoterNames(["Alice", "", "Bob"])
        assert "" not in result

    def test_removes_names_over_80_chars(self):
        exporter = _make_exporter()
        long_name = "A" * 81
        result = exporter.cleanVoterNames([long_name])
        assert result == []

    def test_removes_yes_and_no_values(self):
        exporter = _make_exporter()
        result = exporter.cleanVoterNames(["Yes", "No", "Alice"])
        assert "Yes" not in result
        assert "No" not in result
        assert "Alice" in result

    def test_removes_time_patterns(self):
        exporter = _make_exporter()
        result = exporter.cleanVoterNames(["10:30", "Alice"])
        assert "10:30" not in result
        assert "Alice" in result

    def test_deduplicates_names(self):
        exporter = _make_exporter()
        result = exporter.cleanVoterNames(["Alice", "Alice", "Bob"])
        assert result.count("Alice") == 1

    def test_collapses_extra_whitespace(self):
        exporter = _make_exporter()
        result = exporter.cleanVoterNames(["  Alice  Jones  "])
        assert result == ["Alice Jones"]

    def test_preserves_valid_names(self):
        exporter = _make_exporter()
        names = ["Alice", "Bob Smith", "Charlie"]
        result = exporter.cleanVoterNames(names)
        assert result == names


# ---------------------------------------------------------------------------
# DryRunMixin.prefix
# ---------------------------------------------------------------------------


class TestDryRunPrefix:
    def test_prefix_when_dry_run_true(self):
        exporter = _make_exporter(dryRun=True)
        assert exporter.prefix == "...[] "

    def test_prefix_when_dry_run_false(self):
        exporter = _make_exporter(dryRun=False)
        assert exporter.prefix == "..."


# ---------------------------------------------------------------------------
# extractLikelyDateText
# ---------------------------------------------------------------------------


class TestExtractLikelyDateText:
    def test_extracts_time_from_source_text(self):
        exporter = _make_exporter()
        result = exporter.extractLikelyDateText("Training tonight\n10:30\nYes")
        assert result == "10:30"

    def test_extracts_single_digit_hour(self):
        exporter = _make_exporter()
        result = exporter.extractLikelyDateText("Poll sent 9:05 am")
        assert result == "9:05"

    def test_returns_empty_string_when_no_time(self):
        exporter = _make_exporter()
        result = exporter.extractLikelyDateText("Training tonight")
        assert result == ""

    def test_does_not_match_partial_numbers(self):
        exporter = _make_exporter()
        # "1234:56" is not a plausible time; the regex requires word boundaries
        # on both sides of the pattern, so it must not be surrounded by word
        # characters (digits or letters).
        result = exporter.extractLikelyDateText("code1234:56end")
        assert result == ""


# ---------------------------------------------------------------------------
# extractPollSummaryText / extractMessageTestId
# ---------------------------------------------------------------------------


class TestPollTargetHelpers:
    class FakeMessageContainer:
        def __init__(self, messageTestId: str | None):
            self.messageTestId = messageTestId
            self.first = self

        def get_attribute(self, name):
            assert name == "data-testid"
            return self.messageTestId

    class FakePollLocator:
        def __init__(
            self, messageTestId: str | None = None, should_raise: bool = False
        ):
            self.messageTestId = messageTestId
            self.should_raise = should_raise

        def locator(self, selector):
            assert selector.startswith("xpath=ancestor-or-self::*")
            if self.should_raise:
                raise RuntimeError("no ancestor")
            return TestPollTargetHelpers.FakeMessageContainer(self.messageTestId)

    def test_extract_poll_summary_text_returns_first_non_empty_line(self):
        exporter = _make_exporter()

        assert (
            exporter.extractPollSummaryText("\n  \nTraining Night\nView votes")
            == "Training Night"
        )

    def test_extract_poll_summary_text_returns_empty_string_when_no_content(self):
        exporter = _make_exporter()

        assert exporter.extractPollSummaryText("\n   \n") == ""
        assert exporter.extractPollSummaryText("") == ""

    def test_extract_message_test_id_returns_value_when_present(self):
        exporter = _make_exporter()
        locator = self.FakePollLocator(messageTestId="conv-msg-123")

        assert exporter.extractMessageTestId(locator) == "conv-msg-123"

    def test_extract_message_test_id_returns_empty_string_on_failure(self):
        exporter = _make_exporter()

        assert (
            exporter.extractMessageTestId(self.FakePollLocator(messageTestId=None))
            == ""
        )
        assert (
            exporter.extractMessageTestId(self.FakePollLocator(should_raise=True)) == ""
        )


# ---------------------------------------------------------------------------
# logger initialisation
# ---------------------------------------------------------------------------


class TestLoggerInitialisation:
    def test_passes_include_console_true_to_log_utils(self, monkeypatch):
        captured = {}

        def fake_get_logger(name, **kwargs):
            captured["name"] = name
            captured["kwargs"] = kwargs
            return "logger"

        monkeypatch.setattr(whatsappAttendance, "_logUtilsGetLogger", fake_get_logger)

        logger = whatsappAttendance.getLogger("test.logger", dryRun=True)

        assert logger == "logger"
        assert captured == {
            "name": "test.logger",
            "kwargs": {"includeConsole": True, "dryRun": True},
        }

    @pytest.mark.parametrize("dry_run", [False, True])
    def test_passes_dry_run_state_to_log_utils(self, monkeypatch, dry_run):
        captured = {}

        def fake_get_logger(name, **kwargs):
            captured["name"] = name
            captured["kwargs"] = kwargs
            return "logger"

        monkeypatch.setattr(whatsappAttendance, "_logUtilsGetLogger", fake_get_logger)

        logger = whatsappAttendance.getLogger("test.logger", dryRun=dry_run)

        assert logger == "logger"
        assert captured == {
            "name": "test.logger",
            "kwargs": {"includeConsole": True, "dryRun": dry_run},
        }


class TestLogUtilsTestStub:
    def test_conftest_installs_log_utils_stub(self):
        log_utils = sys.modules["organiseMyProjects.logUtils"]

        logger = log_utils.getLogger("stub.logger", includeConsole=True, dryRun=True)

        assert logger.name == "stub.logger"
        assert logger.kwargs == {"includeConsole": True, "dryRun": True}

        assert logger.info("message") is None
        assert logger.warning("message") is None
        assert logger.debug("message") is None
        assert logger.action("message") is None
        assert logger.doing("message") is None
        assert logger.done("message") is None
        assert logger.value("name", "value") is None


class TestPollTargetOpening:
    class FakePollButtonLocator:
        def __init__(self, name: str, should_fail: bool = False):
            self.name = name
            self.first = self
            self.clicked = False
            self.scrolled = False
            self.filtered_by = []
            self.should_fail = should_fail

        def filter(self, has_text=None):
            self.filtered_by.append(has_text)
            return self

        def scroll_into_view_if_needed(self, timeout=None):
            if self.should_fail:
                raise RuntimeError(f"scroll failed for {self.name}")
            self.scrolled = True

        def click(self, timeout=None):
            if self.should_fail:
                raise RuntimeError(f"click failed for {self.name}")
            self.clicked = True

    class FakePollPage:
        def __init__(self, locator_map):
            self.locator_map = locator_map
            self.requested_selectors = []

        def locator(self, selector):
            self.requested_selectors.append(selector)
            return self.locator_map.setdefault(
                selector, TestPollTargetOpening.FakePollButtonLocator(selector)
            )

    def test_build_poll_button_selector_prefers_message_test_id(self):
        exporter = _make_exporter()
        target = PollTarget(
            selector='div:has-text("View votes")',
            sourceText="Training\nView votes",
            messageTestId="conv-msg-123",
        )

        assert exporter.buildPollButtonSelector(target) == (
            '[data-testid="conv-msg-123"] [data-testid="poll-view-votes"]'
        )

    def test_open_poll_target_uses_stable_message_selector_when_available(self):
        exporter = _make_exporter()
        target = PollTarget(
            selector='div:has-text("View votes")',
            sourceText="Training\nView votes",
            messageTestId="conv-msg-123",
        )
        stable_selector = exporter.buildPollButtonSelector(target)
        stable_locator = self.FakePollButtonLocator(stable_selector)
        page = self.FakePollPage({stable_selector: stable_locator})

        exporter.openPollTarget(page, target)

        assert page.requested_selectors[0] == stable_selector
        assert stable_locator.scrolled is True
        assert stable_locator.clicked is True

    def test_open_poll_target_raises_last_error_when_all_candidates_fail(self):
        exporter = _make_exporter()
        target = PollTarget(
            selector='div:has-text("View votes")',
            sourceText="Training\nView votes",
        )
        generic_locator = self.FakePollButtonLocator(target.selector, should_fail=True)
        page = self.FakePollPage({target.selector: generic_locator})

        with pytest.raises(
            RuntimeError, match="failed to interact with poll vote button"
        ):
            exporter.openPollTarget(page, target)


# ---------------------------------------------------------------------------
# findPollCards
# ---------------------------------------------------------------------------


class TestFindPollCards:
    class StubLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append(message % args if args else message)

    class StubPollItem:
        def __init__(self, text: str):
            self.text = text

        def inner_text(self, timeout=None):
            return self.text

    class StubPollCollection:
        def __init__(self, texts):
            self.texts = list(texts)

        def count(self):
            return len(self.texts)

        def nth(self, index):
            return TestFindPollCards.StubPollItem(self.texts[index])

    class StubPollPage:
        def __init__(self, selector_map):
            self.selector_map = selector_map

        def locator(self, selector):
            return self.selector_map[selector]

    def test_logs_progress_for_large_poll_scan(self, monkeypatch):
        exporter = _make_exporter()
        exporter.logger = self.StubLogger()
        monkeypatch.setattr(exporter, "extractMessageTestId", lambda locator: "")

        selector_map = {
            '[data-testid="poll-view-votes"]': self.StubPollCollection([]),
            'div[role="button"]:has-text("View votes")': self.StubPollCollection([]),
            'div:has-text("View votes")': self.StubPollCollection(
                [f"Training {index}" for index in range(60)]
            ),
        }
        page = self.StubPollPage(selector_map)

        result = exporter.findPollCards(page)

        assert len(result) == 60
        assert any(
            "scanning 60 poll candidate(s) for selector 'div:has-text(\"View votes\")'"
            in message
            for message in exporter.logger.messages
        )
        assert any(
            "processed 25/60 poll candidate(s) for selector 'div:has-text(\"View votes\")'"
            in message
            for message in exporter.logger.messages
        )
        assert any(
            "processed 50/60 poll candidate(s) for selector 'div:has-text(\"View votes\")'"
            in message
            for message in exporter.logger.messages
        )
        assert any(
            "poll discovery complete: 60 unique poll target(s)" in message
            for message in exporter.logger.messages
        )


# ---------------------------------------------------------------------------
# waitForDialog / closeDialog
# ---------------------------------------------------------------------------


class FakeDialogLocator:
    def __init__(self, visible: bool):
        self.visible = visible
        self.last = self
        self.timeouts = []

    def is_visible(self, timeout=None):
        self.timeouts.append(timeout)
        return self.visible


class FakeControlLocator:
    def __init__(self, visible: bool):
        self.visible = visible
        self.first = self
        self.clicked = False
        self.timeouts = []

    def is_visible(self, timeout=None):
        self.timeouts.append(timeout)
        return self.visible

    def click(self, timeout=None):
        self.clicked = True


class FakePage:
    def __init__(self, locator_map):
        self.locator_map = locator_map
        self.waits = []
        self.escape_presses = []
        self.keyboard = self

    def locator(self, selector):
        return self.locator_map[selector]

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)

    def press(self, key):
        self.escape_presses.append(key)


class TestDialogHandling:
    def test_wait_for_dialog_returns_visible_fallback_selector(self):
        selectors = _make_exporter().selectors
        visible_selector = '[data-testid="drawer"]'
        locator_map = {
            selector: FakeDialogLocator(selector == visible_selector)
            for selector in selectors.iterDialogSelectors()
        }
        page = FakePage(locator_map)
        exporter = _make_exporter(timeoutMs=10)

        dialog = exporter.waitForDialog(page)

        assert dialog is locator_map[visible_selector]
        assert locator_map[visible_selector].timeouts
        assert all(
            timeout is not None and 0 < timeout <= 1000
            for timeout in locator_map[visible_selector].timeouts
        )

    def test_close_dialog_uses_back_button_when_close_unavailable(self):
        exporter = _make_exporter()
        locator_map = {
            'button[aria-label="Close"]': FakeControlLocator(False),
            '[role="button"][aria-label="Close"]': FakeControlLocator(False),
            'button[aria-label="Back"]': FakeControlLocator(True),
            '[role="button"][aria-label="Back"]': FakeControlLocator(False),
        }
        page = FakePage(locator_map)

        exporter.closeDialog(page, dialog=None)

        assert locator_map['button[aria-label="Back"]'].clicked is True
        assert page.escape_presses == []
