from __future__ import annotations

import logging

from main import buildConfig, buildParser, getStateGroupNames, serialiseRuntimeConfig


def test_get_state_group_names_reads_legacy_group_name():
    assert getStateGroupNames({"groupName": "Legacy Group"}) == ["Legacy Group"]


def test_parser_accepts_repeated_group_options():
    parser = buildParser({})

    args = parser.parse_args(
        ["-g", "First Group", "-g", "Second Group", "--month", "2026-03"]
    )

    assert args.groupNames == ["First Group", "Second Group"]


def test_parser_accepts_config_and_view_flags():
    parser = buildParser({})

    args = parser.parse_args(["--config", "--view", "-g", "First Group"])

    assert args.showConfig is True
    assert args.viewCache is True


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
