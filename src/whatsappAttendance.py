"""Compatibility wrapper for legacy imports.

Keep existing imports working:
from whatsappAttendance import AttendanceExporter, PollRecord, PollSession
"""

from __future__ import annotations

from whatsapp.exporter import AttendanceExporter
from whatsapp.models import PollRecord, PollSession

__all__ = ["AttendanceExporter", "PollRecord", "PollSession"]
