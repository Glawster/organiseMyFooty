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


def test_get_state_group_names_reads_legacy_group_name():
    assert getStateGroupNames({"groupName": "Legacy Group"}) == ["Legacy Group"]


def test_parser_accepts_repeated_group_options():
    parser = buildParser({})

    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )

    assert args.groupNames == ["First Group", "Second Group"]


def test_parser_keeps_saved_groups_separate_when_group_option_is_used():
    parser = buildParser({"groupNames": ["First Group", "Second Group"]})

    args = parser.parse_args(["-g", "Second Group"])

    assert args.groupNames == ["Second Group"]
    assert args.savedGroupNames == ["First Group", "Second Group"]


def test_group_selection_uses_explicit_groups_or_all_saved_groups():
    savedGroupNames = ["First Group", "Second Group"]

    assert groupNamesResolve(["Second Group"], savedGroupNames) == ["Second Group"]
    assert groupNamesResolve(None, savedGroupNames) == savedGroupNames


def test_parser_accepts_config_and_view_flags():
    parser = buildParser({})

    args = parser.parse_args(["--config", "--view", "-g", "First Group"])

    assert args.showConfig is True
    assert args.viewAttendance is True


def test_build_config_uses_multiple_groups_for_runtime_and_output():
    parser = buildParser({})
    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )

    config = buildConfig(args, dryRun=True, logLevel=logging.INFO)

    assert config.runtime.groupName == "First Group + Second Group"
    assert config.runtime.effectiveGroupNames == ("First Group", "Second Group")
    assert config.runtime.outputDir.name == "output"


def test_serialise_runtime_config_exposes_resolved_values():
    parser = buildParser({})
    args = parser.parse_args(["-g", "First Group", "--month", "2026-03"])

    config = buildConfig(args, dryRun=True, logLevel=logging.INFO)
    payload = serialiseRuntimeConfig(config.runtime)

    assert payload["groupName"] == "First Group"
    assert payload["monthWindow"]["monthKey"] == "2026-03"
    assert payload["outputDir"].endswith("output")


def test_save_state_accumulates_groups_without_duplicates(tmp_path, monkeypatch):
    stateFile = tmp_path / "state.json"
    stateFile.write_text(
        json.dumps(
            {
                "groupName": "First Group",
                "groupNames": ["First Group", "Second Group"],
                "month": "2026-02",
            }
        )
    )
    monkeypatch.setattr("main.getStateFile", lambda: stateFile)

    saveState(["Second Group", "Third Group"], "2026-03")

    state = json.loads(stateFile.read_text())
    assert state["groupName"] == "First Group"
    assert state["groupNames"] == ["First Group", "Second Group", "Third Group"]
    assert state["month"] == "2026-03"


def test_override_uses_standard_two_month_calendar_horizon():
    assert resolveScanCutoff(True, None, date(2026, 8, 1)) == date(2026, 6, 1)


def test_custom_scan_since_is_inclusive_and_requires_override():
    cutoff = parseScanSince("2026-02-15")

    assert resolveScanCutoff(True, cutoff, date(2026, 8, 1)) == date(2026, 2, 15)
    with pytest.raises(ValueError, match="requires --override"):
        resolveScanCutoff(False, cutoff, date(2026, 8, 1))


def test_scan_since_rejects_invalid_and_future_dates():
    with pytest.raises(ValueError, match="expected YYYY-MM-DD"):
        parseScanSince("15 February")
    with pytest.raises(ValueError, match="future"):
        resolveScanCutoff(True, date(2026, 8, 2), date(2026, 8, 1))
