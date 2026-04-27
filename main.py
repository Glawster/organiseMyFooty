#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# -------------------------------------------------------------------
# logging setup (must be top-level)
# -------------------------------------------------------------------
from organiseMyProjects.logUtils import getLogger, setApplication

sys.path.insert(0, str(Path(__file__).parent / "src"))

thisApplication = Path(__file__).parent.name
setApplication(thisApplication)

logger = getLogger(includeConsole=False)

# -------------------------------------------------------------------
# imports (after sys.path tweak)
# -------------------------------------------------------------------
from attendanceConfig import (  # noqa: E402
    RuntimeConfig,
    defaultOutputDir,
    defaultUserDataDir,
    ensureOutputDir,
    resolveMonthWindow,
)
from whatsappAttendance import AttendanceExporter  # noqa: E402


# -------------------------------------------------------------------
# config wrapper (optional but keeps structure clean)
# -------------------------------------------------------------------
@dataclass
class Config:
    runtime: RuntimeConfig


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------
def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export WhatsApp poll attendance for a given group and month."
    )

    parser.add_argument("--group", required=True, dest="groupName")
    parser.add_argument("--month")

    parser.add_argument("--output", type=Path)

    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=defaultUserDataDir(),
    )

    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--limit-polls", type=int)
    parser.add_argument("--browser-channel")

    parser.add_argument("--include-no-votes", action="store_true")
    parser.add_argument("--poll-title-filter")

    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--resume", action="store_true")

    parser.add_argument(
        "--confirm",
        action="store_true",
        help="execute changes (default is dry-run)",
    )

    return parser


# -------------------------------------------------------------------
# CONFIG BUILD
# -------------------------------------------------------------------
def buildConfig(args: argparse.Namespace, dryRun: bool) -> Config:
    monthWindow = resolveMonthWindow(args.month)

    outputDir = ensureOutputDir(
        args.output or defaultOutputDir(args.groupName, monthWindow)
    )

    userDataDir = ensureOutputDir(args.user_data_dir)

    runtime = RuntimeConfig(
        groupName=args.groupName,
        monthWindow=monthWindow,
        outputDir=outputDir,
        userDataDir=userDataDir,
        headless=args.headless,
        dryRun=dryRun,
        timeoutMs=args.timeout_ms,
        limitPolls=args.limit_polls,
        browserChannel=args.browser_channel,
        includeNoVotes=args.include_no_votes,
        resume=args.resume,
        pollTitleFilter=args.poll_title_filter,
    )

    return Config(runtime=runtime)


# -------------------------------------------------------------------
# RUN
# -------------------------------------------------------------------
def run(config: Config) -> None:
    logger = getLogger()

    logger.info("...starting attendance export")
    logger.info(f"...group: {config.runtime.groupName}")
    logger.info(f"...dryRun: {config.runtime.dryRun}")

    AttendanceExporter(config.runtime).run()

    logger.info("attendance export complete...")


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main() -> None:
    parser = buildParser()
    args = parser.parse_args()

    dryRun = not args.confirm

    # REQUIRED logging pattern
    logger = getLogger(includeConsole=True, dryRun=dryRun)

    logger.info("...starting application")

    config = buildConfig(args, dryRun)

    run(config)

    logger.info("application complete...")


# -------------------------------------------------------------------
# ENTRY POINT
# -------------------------------------------------------------------
if __name__ == "__main__":
    main()
