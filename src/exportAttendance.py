from __future__ import annotations

import argparse
from pathlib import Path

from attendanceConfig import (
    RuntimeConfig,
    defaultOutputDir,
    defaultUserDataDir,
    ensureOutputDir,
    resolveMonthWindow,
)
from whatsappAttendance import AttendanceExporter


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export WhatsApp poll attendance for a given group and month.",
    )
    parser.add_argument(
        "--group",
        required=True,
        dest="groupName",
        help="exact WhatsApp group name",
    )
    parser.add_argument(
        "--month",
        help="target month in YYYY-MM; default is previous calendar month",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output directory for CSV files",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=defaultUserDataDir(),
        help="persistent browser profile directory for WhatsApp Web login reuse",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=15000,
        help="selector/action timeout in milliseconds",
    )
    parser.add_argument(
        "--limit-polls",
        type=int,
        help="optional limit for test runs",
    )
    parser.add_argument(
        "--browser-channel",
        help="optional playwright browser channel, e.g. chrome",
    )
    parser.add_argument(
        "--include-no-votes",
        action="store_true",
        help="also collect No voters into the raw export and summary",
    )
    parser.add_argument(
        "--poll-title-filter",
        help="only process polls whose source text contains this substring",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run browser without showing the window",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reserved for future checkpoint/resume logic",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="execute changes and write CSV exports (default is dry-run)",
    )
    return parser


def main() -> None:
    parser = buildParser()
    args = parser.parse_args()

    monthWindow = resolveMonthWindow(args.month)
    outputDir = ensureOutputDir(
        args.output or defaultOutputDir(args.groupName, monthWindow)
    )
    userDataDir = ensureOutputDir(args.user_data_dir)

    config = RuntimeConfig(
        groupName=args.groupName,
        monthWindow=monthWindow,
        outputDir=outputDir,
        userDataDir=userDataDir,
        headless=args.headless,
        dryRun=not args.confirm,
        timeoutMs=args.timeout_ms,
        limitPolls=args.limit_polls,
        browserChannel=args.browser_channel,
        includeNoVotes=args.include_no_votes,
        resume=args.resume,
        pollTitleFilter=args.poll_title_filter,
    )

    AttendanceExporter(config).run()


if __name__ == "__main__":
    main()
