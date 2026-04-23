"""Tests for non-browser helper methods in whatsappAttendance module."""

from __future__ import annotations

from pathlib import Path

import pytest

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsappAttendance import AttendanceExporter, PollRecord

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
