from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PollRecord:
    pollTitle: str
    pollDateText: str
    sessionDateText: str
    option: str
    voterName: str
    sourceHint: str


@dataclass(frozen=True)
class PollSession:
    pollKey: str
    pollTitle: str
    sessionDateText: str
    weekNumber: int
    sessionName: str
