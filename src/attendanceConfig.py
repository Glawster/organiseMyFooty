from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
import calendar
import csv


@dataclass(frozen=True)
class MonthWindow:
    monthKey: str
    startDate: date
    endDate: date

    @property
    def displayName(self) -> str:
        return self.startDate.strftime("%B %Y")


@dataclass(frozen=True)
class RuntimeConfig:
    groupName: str
    monthWindow: MonthWindow
    outputDir: Path
    userDataDir: Path
    headless: bool
    dryRun: bool
    timeoutMs: int
    limitPolls: Optional[int]
    browserChannel: Optional[str]
    includeNoVotes: bool
    resume: bool
    pollTitleFilter: Optional[str]
    myName: str = "Andy"


def resolveMonthWindow(monthText: Optional[str] = None) -> MonthWindow:
    """
    Convert YYYY-MM to an inclusive month window.
    If omitted, uses the previous calendar month.
    """
    today = date.today()
    if not monthText:
        firstThisMonth = today.replace(day=1)
        lastPrevMonth = firstThisMonth - timedelta(days=1)
        startDate = lastPrevMonth.replace(day=1)
        endDate = lastPrevMonth
        return MonthWindow(
            monthKey=startDate.strftime("%Y-%m"),
            startDate=startDate,
            endDate=endDate,
        )

    try:
        parsed = datetime.strptime(monthText, "%Y-%m")
    except ValueError as exc:
        raise ValueError(
            f"invalid month format: {monthText!r}; expected YYYY-MM"
        ) from exc

    year = parsed.year
    month = parsed.month
    lastDay = calendar.monthrange(year, month)[1]
    startDate = date(year, month, 1)
    endDate = date(year, month, lastDay)
    return MonthWindow(
        monthKey=f"{year:04d}-{month:02d}",
        startDate=startDate,
        endDate=endDate,
    )


def ensureOutputDir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def defaultOutputDir(groupName: str, monthWindow: MonthWindow) -> Path:
    safeGroup = (
        "".join(ch if ch.isalnum() else "_" for ch in groupName).strip("_").lower()
    )
    return Path.cwd() / "output" / f"{safeGroup}_{monthWindow.monthKey}"


def defaultUserDataDir() -> Path:
    return Path.home() / ".local" / "share" / "organiseMyWhatsApp" / "profile"


def writeCsv(path: Path, rows: list[dict], fieldNames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldNames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
