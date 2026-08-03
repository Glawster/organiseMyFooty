from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionStatus(str, Enum):
    """Supported lifecycle states for a logical session."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PollRecord:
    pollTitle: str
    pollDateText: str
    sessionDateText: str
    option: str
    voterName: str
    sourceHint: str
    sessionStatus: SessionStatus = SessionStatus.SCHEDULED


@dataclass(frozen=True)
class PollSession:
    pollKey: str
    pollTitle: str
    sessionDateText: str
    weekNumber: int
    sessionName: str
    venueName: str
    sessionStatus: SessionStatus = SessionStatus.SCHEDULED
