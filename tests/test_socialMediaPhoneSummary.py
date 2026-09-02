"""Tests for masked phone identifiers in the social-media attendance summary."""

from datetime import date
from pathlib import Path

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.exporter import AttendanceExporter
from whatsapp.parsing import PollTextParser
from whatsapp.pollDialog import PollDialog
from whatsapp.pollDiscovery import PollDiscovery
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.selectors import DEFAULT_SELECTORS
from whatsapp.models import SessionStatus


class MetadataDialog:
    def evaluate(self, _script, _voterNames):
        return {"Mina": "+44 7810 878563"}


def _makeConfig(**overrides) -> RuntimeConfig:
    defaults = dict(
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
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def testPollRecordsRetainPhoneMetadataBesideVoterName():
    config = _makeConfig()
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    discovery = PollDiscovery(config, DEFAULT_SELECTORS, parser)
    builder = PollRecordsBuilder(config, DEFAULT_SELECTORS, parser, discovery)

    records = builder.buildOptionRecords(
        dialogText=(
            "Sunday 2pm Football Factory\n"
            "Yes\n"
            "Tom\n"
            "+44 7810 878563\n"
            "Sammy Leathem\n"
            "No\n"
        ),
        pollTitle="Sunday 2pm Football Factory",
        pollDateText="20260806",
        sessionDateText="20260809 14:00",
        sourceHint="test",
        sessionStatus=SessionStatus.SCHEDULED,
    )

    assert [(record.voterName, record.voterPhone) for record in records] == [
        ("Tom", "447810878563"),
        ("Sammy Leathem", ""),
    ]


def testSocialMediaSummaryMasksSingleNamePhoneAndAlignsColumns(tmp_path):
    config = _makeConfig(outputDir=tmp_path)
    exporter = AttendanceExporter(config)
    reportRows = [
        ["week", "week 1", ""],
        ["date", "03/08/26", "05/08/26"],
        ["venue", "Football Factory", "LLC"],
        ["day", "Monday", "Wednesday"],
        ["name", "19:00", "10:30"],
        ["Tom", "yes", "yes"],
        ["Sammy Leathem", "yes", ""],
        ["session total", "2", "1"],
    ]

    summaryText = exporter.buildSocialMediaSummaryText(
        reportRows,
        voterPhones={"tom": "447810878563", "sammy leathem": "447700900123"},
    )

    assert summaryText == (
        "August 2026 attendance summary\n"
        "2 sessions\n"
        "- Tom (07...563)... 2/2\n"
        "- Sammy Leathem ... 1/2"
    )
    assert "123" not in summaryText


def testMaskPhoneNumberNormalisesUkCountryCodeAndShowsPrefixAndFinalThreeDigits(
    tmp_path,
):
    exporter = AttendanceExporter(_makeConfig(outputDir=tmp_path))

    assert exporter.maskPhoneNumber("+44 7810 878563") == "07...563"
    assert exporter.maskPhoneNumber("447810878563") == "07...563"
    assert exporter.maskPhoneNumber("07810878563") == "07...563"


def testHiddenContactPhoneMetadataCanIdentifySingleNameVoter():
    dialog = PollDialog(_makeConfig(), DEFAULT_SELECTORS)

    assert dialog.extractVoterPhoneMetadata(MetadataDialog(), ["Mina"]) == {
        "mina": "447810878563"
    }
