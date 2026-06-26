from __future__ import annotations

import logging

from main import buildConfig, buildParser, getStateGroupNames


def test_get_state_group_names_reads_legacy_group_name():
    assert getStateGroupNames({"groupName": "Legacy Group"}) == ["Legacy Group"]


def test_parser_accepts_repeated_group_options():
    parser = buildParser({})

    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )

    assert args.groupNames == ["First Group", "Second Group"]


def test_build_config_uses_multiple_groups_for_runtime_and_output():
    parser = buildParser({})
    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )

    config = buildConfig(args, dryRun=True, logLevel=logging.INFO)

    assert config.runtime.groupName == "First Group + Second Group"
    assert config.runtime.effectiveGroupNames == ("First Group", "Second Group")
    assert "first_group__second_group_2026-03" in str(config.runtime.outputDir)
