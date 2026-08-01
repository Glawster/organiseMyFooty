"""Installable CLI entrypoint for organiseMyFooty."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from attendanceConfig import (
    RuntimeConfig,
    defaultOutputDir,
    defaultUserDataDir,
    ensureOutputDir,
    resolveMonthWindow,
)
from organiseMyProjects.logUtils import getLogger, setApplication  # type: ignore
from whatsappAttendance import AttendanceExporter

APPLICATION_NAME = "organiseMyFooty"

setApplication(APPLICATION_NAME)
logger = getLogger(includeConsole=False)


@dataclass
class Config:
    runtime: RuntimeConfig


_MONTH_LOOKUP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def normaliseMonthInput(monthInput: str | None) -> str | None:
    if not monthInput:
        return None

    value = monthInput.strip().lower()

    if len(value) == 7 and value[4] == "-":
        return value

    if value.isdigit():
        monthNum = int(value)
    else:
        monthNum = _MONTH_LOOKUP.get(value)

    if not monthNum or not 1 <= monthNum <= 12:
        raise ValueError(f"Invalid month: {monthInput}")

    now = datetime.now()
    year = now.year

    if monthNum > now.month:
        year -= 1

    return f"{year:04d}-{monthNum:02d}"


def getStateFile() -> Path:
    return Path.home() / ".config" / APPLICATION_NAME / "state.json"


def loadState() -> dict:
    stateFile = getStateFile()

    if not stateFile.exists():
        return {}

    try:
        return json.loads(stateFile.read_text())
    except json.JSONDecodeError:
        return {}


def getStateGroupNames(state: dict) -> list[str]:
    groupNames = state.get("groupNames")
    if isinstance(groupNames, list):
        return [str(name).strip() for name in groupNames if str(name).strip()]

    groupName = state.get("groupName")
    if groupName:
        return [str(groupName).strip()]

    return []


def normaliseGroupNames(groupNames: list[str] | None) -> list[str]:
    if not groupNames:
        return []

    return [name.strip() for name in groupNames if name.strip()]


def formatGroupNames(groupNames: list[str] | tuple[str, ...]) -> str:
    return " + ".join(groupNames)


def saveState(groupNames: list[str], month: str | None) -> None:
    stateFile = getStateFile()
    stateFile.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "groupName": groupNames[0] if groupNames else "",
        "groupNames": groupNames,
        "month": month,
    }

    stateFile.write_text(json.dumps(state, indent=2))


def buildParser(state: dict) -> argparse.ArgumentParser:
    savedGroupNames = getStateGroupNames(state)
    parser = argparse.ArgumentParser(
        description="Export WhatsApp poll attendance for one or more groups and a month."
    )
    parser.set_defaults(savedGroupNames=savedGroupNames)

    parser.add_argument(
        "-g",
        "--group",
        action="append",
        dest="groupNames",
        metavar="GROUP",
        help="exact WhatsApp group name; repeat for multiple groups",
    )

    parser.add_argument(
        "-m",
        "--month",
        default=state.get("month"),
        help="month as YYYY-MM, name or number. Defaults to previous month if not specified.",
    )

    parser.add_argument(
        "-y",
        "--confirm",
        action="store_true",
        help="execute changes and write CSV exports (default is dry-run)",
    )

    parser.add_argument(
        "--cache",
        action="store_true",
        help="use cached poll results when available (default is to rescrape polls)",
    )

    parser.add_argument(
        "--view",
        dest="viewCache",
        action="store_true",
        help="view cached poll records instead of running an export",
    )

    parser.add_argument(
        "--config",
        dest="showConfig",
        action="store_true",
        help="print the resolved runtime configuration and exit",
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="enable debug logging",
    )

    return parser


def buildConfig(args: argparse.Namespace, dryRun: bool, logLevel: int) -> Config:
    month = normaliseMonthInput(args.month)
    monthWindow = resolveMonthWindow(month)
    groupNames = tuple(normaliseGroupNames(args.groupNames))

    outputDir = ensureOutputDir(defaultOutputDir(groupNames, monthWindow))
    userDataDir = ensureOutputDir(defaultUserDataDir())

    runtime = RuntimeConfig(
        groupName=formatGroupNames(groupNames),
        monthWindow=monthWindow,
        outputDir=outputDir,
        userDataDir=userDataDir,
        headless=False,
        dryRun=dryRun,
        timeoutMs=15000,
        logLevel=logLevel,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=False,
        resume=False,
        pollTitleFilter=None,
        usePollCache=args.cache,
        groupNames=groupNames,
    )

    return Config(runtime=runtime)


def serialiseRuntimeConfig(runtime: RuntimeConfig) -> dict:
    return {
        "groupName": runtime.groupName,
        "groupNames": list(runtime.groupNames),
        "monthWindow": {
            "monthKey": runtime.monthWindow.monthKey,
            "startDate": runtime.monthWindow.startDate.isoformat(),
            "endDate": runtime.monthWindow.endDate.isoformat(),
            "displayName": runtime.monthWindow.displayName,
        },
        "outputDir": str(runtime.outputDir),
        "userDataDir": str(runtime.userDataDir),
        "headless": runtime.headless,
        "dryRun": runtime.dryRun,
        "timeoutMs": runtime.timeoutMs,
        "logLevel": runtime.logLevel,
        "limitPolls": runtime.limitPolls,
        "browserChannel": runtime.browserChannel,
        "includeNoVotes": runtime.includeNoVotes,
        "resume": runtime.resume,
        "pollTitleFilter": runtime.pollTitleFilter,
        "usePollCache": runtime.usePollCache,
        "strictMonth": runtime.strictMonth,
        "myName": runtime.myName,
        "effectiveGroupNames": list(runtime.effectiveGroupNames),
    }


def serialiseCachedPolls(recordsByPollKey) -> dict:
    return {
        pollKey: [record.__dict__ for record in records]
        for pollKey, records in recordsByPollKey.items()
    }


def run(config: Config) -> None:
    appLogger = getLogger(level=config.runtime.logLevel)

    appLogger.value("groups", ", ".join(config.runtime.effectiveGroupNames))
    appLogger.value("dryRun", config.runtime.dryRun)
    appLogger.value("logLevel", config.runtime.logLevel)

    AttendanceExporter(config.runtime).run()


def viewCache(config: Config) -> None:
    exporter = AttendanceExporter(config.runtime)
    recordsByPollKey = exporter.cacheStore.loadPollCache(force=True)

    payload = {
        "groupNames": list(config.runtime.effectiveGroupNames),
        "month": config.runtime.monthWindow.monthKey,
        "cachePath": str(exporter.cacheStore.getPollCachePath()),
        "polls": serialiseCachedPolls(recordsByPollKey),
    }

    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> None:
    state = loadState()
    parser = buildParser(state)
    args = parser.parse_args()
    args.groupNames = normaliseGroupNames(args.groupNames) or args.savedGroupNames

    if not args.groupNames and not (args.showConfig or args.viewCache):
        parser.error("--group is required.")

    dryRun = not args.confirm
    logLevel = logging.DEBUG if args.debug else logging.INFO
    appLogger = getLogger(includeConsole=True, dryRun=dryRun, level=logLevel)

    appLogger.doing("starting application")

    config = buildConfig(args, dryRun, logLevel)

    if args.showConfig:
        print(
            json.dumps(
                serialiseRuntimeConfig(config.runtime), indent=2, ensure_ascii=False
            )
        )
        return

    if args.viewCache:
        viewCache(config)
        return

    run(config)
    saveState(groupNames=args.groupNames, month=normaliseMonthInput(args.month))

    appLogger.done("application complete")
