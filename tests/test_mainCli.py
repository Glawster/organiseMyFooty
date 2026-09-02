from __future__ import annotations

import json
import logging
from datetime import date

import pytest

from main import (
    buildConfig,
    buildParser,
    getStateGroupNames,
    groupNamesResolve,
    parseScanSince,
    saveState,
    serialiseRuntimeConfig,
)
from attendanceConfig import resolveScanCutoff


def testGetStateGroupNamesReadsLegacyGroupName():
    assert getStateGroupNames({"groupName": "Legacy Group"}) == ["Legacy Group"]


def testParserAcceptsRepeatedGroupOptions():
    parser = buildParser({})
    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )
    assert args.groupNames == ["First Group", "Second Group"]


def testParserKeepsSavedGroupsSeparateWhenGroupOptionIsUsed():
    parser = buildParser({"groupNames": ["First Group", "Second Group"]})
    args = parser.parse_args(["-g", "Second Group"])
    assert args.groupNames == ["Second Group"]
    assert args.savedGroupNames == ["First Group", "Second Group"]


def testGroupSelectionUsesExplicitGroupsOrAllSavedGroups():
    savedGroupNames = ["First Group", "Second Group"]
    assert groupNamesResolve(["Second Group"], savedGroupNames) == ["Second Group"]
    assert groupNamesResolve(None, savedGroupNames) == savedGroupNames


def testParserAcceptsConfigViewAndGetContactsFlags():
    parser = buildParser({})
    args = parser.parse_args(
        ["--config", "--view", "--get-contacts", "HWFC", "-g", "First Group"]
    )
    assert args.showConfig is True
    assert args.viewAttendance is True
    assert args.getContacts == "HWFC"


def testParserAcceptsNoScrapeFlag():
    parser = buildParser({})
    args = parser.parse_args(["--no-scrape", "-g", "First Group", "-y"])
    assert args.noScrape is True
    assert args.confirm is True


def testGetContactsDoesNotRequireGroupArgument():
    parser = buildParser({})
    args = parser.parse_args(["--get-contacts", "HWFC"])
    assert args.getContacts == "HWFC"
    assert args.groupNames is None


def testGetContactsRequiresCompanyArgument():
    parser = buildParser({})
    with pytest.raises(SystemExit):
        parser.parse_args(["--get-contacts"])


def testGetContactsAcceptsConfirmAndDebugFlags():
    parser = buildParser({})
    args = parser.parse_args(["--get-contacts", "HWFC", "-y", "-d"])
    assert args.getContacts == "HWFC"
    assert args.confirm is True
    assert args.debug is True


def testParserRejectsRemovedEmojiOption():
    parser = buildParser({})
    with pytest.raises(SystemExit):
        parser.parse_args(["--emoji", "Alex Example"])


def testBuildConfigUsesMultipleGroupsForRuntimeAndOutput():
    parser = buildParser({})
    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )
    config = buildConfig(args, dryRun=True, logLevel=logging.INFO)
    assert config.runtime.groupName == "First Group + Second Group"
    assert config.runtime.effectiveGroupNames == ("First Group", "Second Group")
    assert config.runtime.outputDir.name == "output"
    assert config.runtime.cancellationEmojiName == "reaction"


def testBuildConfigSupportsContactOnlyModeWithoutGroups():
    parser = buildParser({})
    args = parser.parse_args(["--get-contacts", "HWFC", "--month", "2026-03"])
    args.groupNames = []
    config = buildConfig(args, dryRun=False, logLevel=logging.INFO)
    assert config.runtime.groupNames == ()
    assert config.runtime.outputDir.name == "output"


def testSerialiseRuntimeConfigExposesResolvedValues():
    parser = buildParser({})
    args = parser.parse_args(["-g", "First Group", "--month", "2026-03"])
    config = buildConfig(args, dryRun=True, logLevel=logging.INFO)
    payload = serialiseRuntimeConfig(config.runtime)
    assert payload["groupName"] == "First Group"
    assert payload["monthWindow"]["monthKey"] == "2026-03"
    assert payload["outputDir"].endswith("output")
    assert "cancellationEmojiName" not in payload


def testSaveStateAccumulatesGroupsAndRemovesLegacyEmojiName(tmp_path, monkeypatch):
    stateFile = tmp_path / "state.json"
    stateFile.write_text(
        json.dumps(
            {
                "groupName": "First Group",
                "groupNames": ["First Group", "Second Group"],
                "month": "2026-02",
                "emojiName": "Alex Example",
            }
        )
    )
    monkeypatch.setattr("main.getStateFile", lambda: stateFile)
    saveState(["Second Group", "Third Group"], "2026-03")
    state = json.loads(stateFile.read_text())
    assert state["groupName"] == "First Group"
    assert state["groupNames"] == ["First Group", "Second Group", "Third Group"]
    assert state["month"] == "2026-03"
    assert "emojiName" not in state


def testOverrideUsesStandardTwoMonthCalendarHorizon():
    assert resolveScanCutoff(True, None, date(2026, 8, 1)) == date(2026, 6, 1)


def testCustomScanSinceIsInclusiveAndRequiresOverride():
    cutoff = parseScanSince("2026-02-15")
    assert resolveScanCutoff(True, cutoff, date(2026, 8, 1)) == date(2026, 2, 15)
    with pytest.raises(ValueError, match="requires --override"):
        resolveScanCutoff(False, cutoff, date(2026, 8, 1))


def testScanSinceRejectsInvalidAndFutureDates():
    with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
        parseScanSince("15 February")
    with pytest.raises(ValueError, match="future"):
        resolveScanCutoff(True, date(2026, 8, 2), date(2026, 8, 1))
