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
        description="Export WhatsApp poll attendance for a group and month."
    )

    parser.add_argument(
        "-g",
        "--group",
        required=True,
        dest="groupName",
        help="exact WhatsApp group name",
    )

    parser.add_argument(
        "-m",
        "--month",
        help="target month in YYYY-MM (default: previous month)",
    )

    parser.add_argument(
        "-y",
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

    outputDir = ensureOutputDir(defaultOutputDir(args.groupName, monthWindow))

    userDataDir = ensureOutputDir(defaultUserDataDir())

    runtime = RuntimeConfig(
        groupName=args.groupName,
        monthWindow=monthWindow,
        outputDir=outputDir,
        userDataDir=userDataDir,
        headless=False,
        dryRun=dryRun,
        timeoutMs=15000,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=False,
        resume=False,
        pollTitleFilter=None,
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
