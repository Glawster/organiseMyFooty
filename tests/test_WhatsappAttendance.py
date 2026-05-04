"""Tests for refactored WhatsApp modules."""

from __future__ import annotations

from pathlib import Path
from datetime import date

from attendanceConfig import MonthWindow, RuntimeConfig

from whatsapp.models import PollRecord
from whatsapp.parsing import PollTextParser
from whatsapp.reports import AttendanceReportBuilder
from whatsapp.records import deduplicateRecords
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollDialog import PollDialog
from whatsapp.selectors import DEFAULT_SELECTORS

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


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def test_extract_likely_date_text():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    assert parser.extractLikelyDateText("Training\n10:30\nYes") == "10:30"


def test_clean_voter_names():
    parser = PollTextParser(_make_config(), DEFAULT_SELECTORS)
    result = parser.cleanVoterNames(["Alice", "Alice", "10:30", "Yes"])
    assert result == ["Alice"]


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


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


class StubItem:
    def __init__(self, text: str):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text

    def locator(self, *_args, **_kwargs):
        raise RuntimeError


class StubCollection:
    def __init__(self, texts):
        self.texts = texts

    def count(self):
        return len(self.texts)

    def nth(self, index):
        return StubItem(self.texts[index])


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
