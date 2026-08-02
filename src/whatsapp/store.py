"""Durable SQLite attendance storage and reconciliation."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import re
import sqlite3

from organiseMyProjects.logUtils import getLogger  # type: ignore[import]

from whatsapp.models import PollRecord

logger = getLogger()
SCHEMA_VERSION = 1
VALID_RESPONSES = {"yes", "no", "maybe", "unknown"}
RESPONSE_PRIORITY = {"yes": 4, "maybe": 3, "no": 2, "unknown": 1}


@dataclass
class ChangeSummary:
    sessionsAdded: int = 0
    sessionsUpdated: int = 0
    sessionsRemoved: int = 0
    sessionsUnchanged: int = 0
    membersAdded: int = 0
    membersUpdated: int = 0
    membersRemoved: int = 0
    membersUnchanged: int = 0
    attendanceAdded: int = 0
    attendanceUpdated: int = 0
    attendanceRemoved: int = 0
    attendanceUnchanged: int = 0
    attendanceConflicted: int = 0


def normaliseName(value: str) -> str:
    """Return a conservative member identity key."""
    return " ".join(value.casefold().split())


def utcNow() -> str:
    """Return a sortable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AttendanceStore:
    """Own SQLite schema, migrations, reconciliation, and attendance queries."""

    def __init__(self, path: Path, sessionParser=None):
        self.path = Path(path)
        self.sessionParser = sessionParser
        self.logger = logger
        self.summary = ChangeSummary()
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "AttendanceStore":
        self.open()
        return self

    def __exit__(self, excType, exc, traceback) -> None:
        self.close()

    ## lifecycle

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def open(self) -> "AttendanceStore":
        if self._connection is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        self._connection = connection
        self.schemaMigrate()
        connection.execute(
            "UPDATE scans SET status='failed', completed_at=?, boundary_reason='interrupted' WHERE status='running'",
            (utcNow(),),
        )
        connection.commit()
        return self

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self.open()
        assert self._connection is not None
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit one complete unit, rolling it back on any failure."""
        connection = self.connection
        try:
            connection.execute("BEGIN")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    ## schema

    def schemaMigrate(self) -> None:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"attendance store schema {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version == 0:
            with self.transaction() as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (
                        id INTEGER PRIMARY KEY,
                        session_date TEXT,
                        start_time TEXT,
                        name TEXT NOT NULL,
                        normalised_name TEXT NOT NULL,
                        venue TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'scheduled',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(session_date, start_time, normalised_name, venue)
                    );
                    CREATE TABLE members (
                        id INTEGER PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        normalised_name TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE member_aliases (
                        id INTEGER PRIMARY KEY,
                        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                        alias TEXT NOT NULL,
                        normalised_alias TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE sources (
                        id INTEGER PRIMARY KEY,
                        source_type TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(source_type, external_id)
                    );
                    CREATE TABLE session_sources (
                        id INTEGER PRIMARY KEY,
                        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        external_id TEXT NOT NULL,
                        source_title TEXT NOT NULL DEFAULT '',
                        poll_date TEXT,
                        source_hint TEXT NOT NULL DEFAULT '',
                        captured_successfully INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(source_id, external_id)
                    );
                    CREATE TABLE attendance (
                        id INTEGER PRIMARY KEY,
                        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                        response TEXT NOT NULL CHECK(response IN ('yes','no','maybe','unknown')),
                        conflicted INTEGER NOT NULL DEFAULT 0,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        UNIQUE(session_id, member_id)
                    );
                    CREATE TABLE attendance_observations (
                        id INTEGER PRIMARY KEY,
                        session_source_id INTEGER NOT NULL REFERENCES session_sources(id) ON DELETE CASCADE,
                        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                        response TEXT NOT NULL CHECK(response IN ('yes','no','maybe','unknown')),
                        raw_member_name TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(session_source_id, member_id)
                    );
                    CREATE TABLE scans (
                        id INTEGER PRIMARY KEY,
                        source_id INTEGER REFERENCES sources(id),
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        scope_start TEXT,
                        scope_end TEXT,
                        status TEXT NOT NULL,
                        boundary_reason TEXT,
                        detail TEXT
                    );
                    CREATE INDEX idx_sessions_date ON sessions(session_date);
                    CREATE INDEX idx_alias_member ON member_aliases(member_id);
                    CREATE INDEX idx_session_sources_session ON session_sources(session_id);
                    CREATE INDEX idx_attendance_member_session ON attendance(member_id, session_id);
                    CREATE INDEX idx_observations_attendance ON attendance_observations(session_id, member_id, active);
                    CREATE INDEX idx_scans_source_started ON scans(source_id, started_at);
                    PRAGMA user_version = 1;
                    """
                )

    ## scans

    def scanFinish(
        self,
        scanId: int,
        status: str,
        boundaryReason: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.connection.execute(
            "UPDATE scans SET completed_at=?, status=?, boundary_reason=?, detail=? WHERE id=?",
            (utcNow(), status, boundaryReason, detail, scanId),
        )
        self.connection.commit()

    def scanStart(
        self,
        sourceId: int | None,
        scopeStart: date | None,
        scopeEnd: date | None,
    ) -> int:
        cursor = self.connection.execute(
            "INSERT INTO scans(source_id, started_at, scope_start, scope_end, status) VALUES(?,?,?,?,?)",
            (
                sourceId,
                utcNow(),
                scopeStart.isoformat() if scopeStart else None,
                scopeEnd.isoformat() if scopeEnd else None,
                "running",
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    ## identity

    def memberAliasAdd(self, memberId: int, alias: str) -> None:
        key = normaliseName(alias)
        existing = self.connection.execute(
            "SELECT member_id FROM member_aliases WHERE normalised_alias=?", (key,)
        ).fetchone()
        if existing and int(existing[0]) != memberId:
            raise ValueError(
                f"ambiguous alias already belongs to another member: {alias}"
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO member_aliases(member_id, alias, normalised_alias, created_at) VALUES(?,?,?,?)",
            (memberId, alias.strip(), key, utcNow()),
        )
        self.connection.commit()

    def memberResolve(self, displayName: str) -> int:
        key = normaliseName(displayName)
        rows = self.connection.execute(
            """SELECT id FROM members WHERE normalised_name=?
               UNION SELECT member_id FROM member_aliases WHERE normalised_alias=?""",
            (key, key),
        ).fetchall()
        ids = {int(row[0]) for row in rows}
        if len(ids) > 1:
            raise ValueError(f"ambiguous member identity: {displayName}")
        if ids:
            self.summary.membersUnchanged += 1
            return ids.pop()
        now = utcNow()
        cursor = self.connection.execute(
            "INSERT INTO members(display_name, normalised_name, created_at, updated_at) VALUES(?,?,?,?)",
            (displayName.strip(), key, now, now),
        )
        self.summary.membersAdded += 1
        self.logger.info("member created: %s", displayName)
        return int(cursor.lastrowid)

    def sourceEnsure(self, sourceType: str, externalId: str, displayName: str) -> int:
        now = utcNow()
        self.connection.execute(
            """INSERT INTO sources(source_type, external_id, display_name, created_at, updated_at)
               VALUES(?,?,?,?,?) ON CONFLICT(source_type, external_id) DO UPDATE SET
               display_name=excluded.display_name, updated_at=excluded.updated_at""",
            (sourceType, externalId, displayName, now, now),
        )
        row = self.connection.execute(
            "SELECT id FROM sources WHERE source_type=? AND external_id=?",
            (sourceType, externalId),
        ).fetchone()
        assert row
        return int(row[0])

    def sourcePollCaptured(
        self, sourceType: str, sourceExternalId: str, pollExternalId: str
    ) -> bool:
        if not pollExternalId:
            return False
        row = self.connection.execute(
            """SELECT ss.captured_successfully FROM session_sources ss
               JOIN sources s ON s.id=ss.source_id
               WHERE s.source_type=? AND s.external_id=? AND ss.external_id=?""",
            (sourceType, sourceExternalId, pollExternalId),
        ).fetchone()
        return bool(row and row[0])

    ## reconciliation

    def pollReconcile(
        self,
        sourceName: str,
        pollExternalId: str,
        records: Iterable[PollRecord],
        complete: bool = True,
        observedAt: str | None = None,
    ) -> int:
        """Reconcile one successfully read poll as an atomic checkpoint."""
        recordList = list(records)
        if not recordList:
            raise ValueError("cannot reconcile a poll without records")
        if not pollExternalId:
            raise ValueError("a stable poll external identity is required")
        observedAt = observedAt or utcNow()
        with self.transaction():
            sourceId = self.sourceEnsure(
                "whatsapp", normaliseName(sourceName), sourceName
            )
            existingSource = self.connection.execute(
                "SELECT session_id FROM session_sources WHERE source_id=? AND external_id=?",
                (sourceId, pollExternalId),
            ).fetchone()
            sessionId = (
                int(existingSource[0])
                if existingSource
                else self._sessionResolve(recordList[0], observedAt)
            )
            sessionSourceId = self._sessionSourceResolve(
                sourceId, sessionId, pollExternalId, recordList[0], observedAt
            )
            seenMembers: set[int] = set()
            for record in recordList:
                memberId = self.memberResolve(record.voterName)
                seenMembers.add(memberId)
                self._observationUpsert(
                    sessionSourceId, sessionId, memberId, record, observedAt
                )
            if complete:
                self._observationsRemoveMissing(
                    sessionSourceId, seenMembers, observedAt
                )
            affectedMembers = seenMembers | {
                int(row[0])
                for row in self.connection.execute(
                    "SELECT member_id FROM attendance_observations WHERE session_source_id=?",
                    (sessionSourceId,),
                )
            }
            for memberId in affectedMembers:
                self._attendanceResolve(sessionId, memberId, observedAt)
        return sessionId

    def _attendanceResolve(
        self, sessionId: int, memberId: int, observedAt: str
    ) -> None:
        rows = self.connection.execute(
            "SELECT response FROM attendance_observations WHERE session_id=? AND member_id=? AND active=1",
            (sessionId, memberId),
        ).fetchall()
        current = self.connection.execute(
            "SELECT response FROM attendance WHERE session_id=? AND member_id=?",
            (sessionId, memberId),
        ).fetchone()
        if not rows:
            if current:
                self.connection.execute(
                    "DELETE FROM attendance WHERE session_id=? AND member_id=?",
                    (sessionId, memberId),
                )
                self.summary.attendanceRemoved += 1
                self.logger.info(
                    "member removed from session: %s/%s", memberId, sessionId
                )
            return
        responses = {str(row[0]) for row in rows}
        conflicted = len(responses) > 1
        response = max(responses, key=lambda value: RESPONSE_PRIORITY[value])
        if conflicted:
            self.summary.attendanceConflicted += 1
            self.logger.warning(
                "conflicting observations: session %s member %s", sessionId, memberId
            )
        if current is None:
            self.connection.execute(
                "INSERT INTO attendance(session_id, member_id, response, conflicted, first_seen_at, last_seen_at) VALUES(?,?,?,?,?,?)",
                (sessionId, memberId, response, conflicted, observedAt, observedAt),
            )
            self.summary.attendanceAdded += 1
            self.logger.info(
                "member added to session: %s/%s (%s)", memberId, sessionId, response
            )
        elif current[0] != response:
            self.connection.execute(
                "UPDATE attendance SET response=?, conflicted=?, last_seen_at=? WHERE session_id=? AND member_id=?",
                (response, conflicted, observedAt, sessionId, memberId),
            )
            self.summary.attendanceUpdated += 1
            self.logger.info(
                "attendance response changed: %s/%s %s", memberId, sessionId, response
            )
        else:
            self.connection.execute(
                "UPDATE attendance SET conflicted=?, last_seen_at=? WHERE session_id=? AND member_id=?",
                (conflicted, observedAt, sessionId, memberId),
            )
            self.summary.attendanceUnchanged += 1

    def _observationUpsert(
        self,
        sessionSourceId: int,
        sessionId: int,
        memberId: int,
        record: PollRecord,
        observedAt: str,
    ) -> None:
        response = record.option.strip().casefold()
        if response not in VALID_RESPONSES:
            response = "unknown"
        now = utcNow()
        self.connection.execute(
            """INSERT INTO attendance_observations(
                   session_source_id, session_id, member_id, response, raw_member_name,
                   observed_at, active, created_at, updated_at)
               VALUES(?,?,?,?,?,?,1,?,?)
               ON CONFLICT(session_source_id, member_id) DO UPDATE SET
                   response=excluded.response, raw_member_name=excluded.raw_member_name,
                   observed_at=excluded.observed_at, active=1, updated_at=excluded.updated_at""",
            (
                sessionSourceId,
                sessionId,
                memberId,
                response,
                record.voterName,
                observedAt,
                now,
                now,
            ),
        )

    def _observationsRemoveMissing(
        self, sessionSourceId: int, seenMembers: set[int], observedAt: str
    ) -> None:
        rows = self.connection.execute(
            "SELECT member_id FROM attendance_observations WHERE session_source_id=? AND active=1",
            (sessionSourceId,),
        ).fetchall()
        missing = {int(row[0]) for row in rows} - seenMembers
        for memberId in missing:
            self.connection.execute(
                "UPDATE attendance_observations SET active=0, updated_at=? WHERE session_source_id=? AND member_id=?",
                (observedAt, sessionSourceId, memberId),
            )

    def _sessionResolve(self, record: PollRecord, now: str) -> int:
        sessionDate, startTime = self._sessionDateTime(record.sessionDateText)
        name, venue = self._sessionParts(record.pollTitle)
        key = normaliseName(name)
        row = self.connection.execute(
            """SELECT id FROM sessions WHERE session_date IS ? AND start_time IS ?
               AND normalised_name=? AND venue=?""",
            (sessionDate, startTime, key, venue),
        ).fetchone()
        if row:
            self.summary.sessionsUnchanged += 1
            return int(row[0])
        candidates = self.connection.execute(
            "SELECT id FROM sessions WHERE session_date IS ? AND start_time IS ? AND venue=?",
            (sessionDate, startTime, venue),
        ).fetchall()
        if len(candidates) == 1:
            sessionId = int(candidates[0][0])
            self.connection.execute(
                "UPDATE sessions SET name=?, normalised_name=?, updated_at=? WHERE id=?",
                (name, key, now, sessionId),
            )
            self.summary.sessionsUpdated += 1
            self.logger.info("session updated: %s %s", sessionDate, name)
            return sessionId
        cursor = self.connection.execute(
            """INSERT INTO sessions(session_date, start_time, name, normalised_name, venue, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (sessionDate, startTime, name, key, venue, now, now),
        )
        self.summary.sessionsAdded += 1
        self.logger.info("session created: %s %s", sessionDate, name)
        return int(cursor.lastrowid)

    def _sessionSourceResolve(
        self,
        sourceId: int,
        sessionId: int,
        externalId: str,
        record: PollRecord,
        now: str,
    ) -> int:
        row = self.connection.execute(
            "SELECT id, session_id FROM session_sources WHERE source_id=? AND external_id=?",
            (sourceId, externalId),
        ).fetchone()
        if row:
            if int(row[1]) != sessionId:
                self.connection.execute(
                    "UPDATE session_sources SET session_id=?, source_title=?, poll_date=?, source_hint=?, captured_successfully=1, updated_at=? WHERE id=?",
                    (
                        sessionId,
                        record.pollTitle,
                        record.pollDateText,
                        record.sourceHint,
                        now,
                        int(row[0]),
                    ),
                )
            return int(row[0])
        cursor = self.connection.execute(
            """INSERT INTO session_sources(source_id, session_id, external_id, source_title, poll_date,
                   source_hint, captured_successfully, created_at, updated_at) VALUES(?,?,?,?,?,?,1,?,?)""",
            (
                sourceId,
                sessionId,
                externalId,
                record.pollTitle,
                record.pollDateText,
                record.sourceHint,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    ## queries

    def attendanceRecords(self, startDate: date, endDate: date) -> list[PollRecord]:
        rows = self.connection.execute(
            """SELECT s.name, s.session_date, s.start_time, s.venue, a.response, m.display_name,
                      COALESCE(ss.source_title, '') source_title,
                      COALESCE(ss.source_hint, '') source_hint
               FROM attendance a JOIN sessions s ON s.id=a.session_id
               JOIN members m ON m.id=a.member_id
               LEFT JOIN session_sources ss ON ss.session_id=s.id
               WHERE s.session_date BETWEEN ? AND ?
               GROUP BY a.id ORDER BY s.session_date, s.start_time, m.normalised_name""",
            (startDate.isoformat(), endDate.isoformat()),
        ).fetchall()
        return [
            PollRecord(
                pollTitle=row["source_title"]
                or " ".join(
                    dict.fromkeys(
                        part
                        for part in (row["name"], row["start_time"], row["venue"])
                        if part
                    )
                ),
                pollDateText=row["session_date"].replace("-", ""),
                sessionDateText=row["session_date"].replace("-", "")
                + (f" {row['start_time']}" if row["start_time"] else ""),
                option=row["response"],
                voterName=row["display_name"],
                sourceHint=row["source_hint"],
            )
            for row in rows
        ]

    def attendanceQuery(
        self,
        startDate: date,
        endDate: date,
        response: str | None = None,
        group: str | None = None,
        venue: str | None = None,
        sourceType: str | None = None,
    ) -> list[sqlite3.Row]:
        """Query effective attendance using optional response/source metadata filters."""
        conditions = ["se.session_date BETWEEN ? AND ?"]
        params: list[object] = [startDate.isoformat(), endDate.isoformat()]
        for column, value in (
            ("a.response", response.casefold() if response else None),
            ("so.display_name", group),
            ("se.venue", venue),
            ("so.source_type", sourceType),
        ):
            if value is not None:
                conditions.append(f"{column}=?")
                params.append(value)
        return self.connection.execute(
            """SELECT DISTINCT a.*, se.session_date, se.name session_name,
                      se.venue, m.display_name member_name, so.source_type,
                      so.display_name source_name
               FROM attendance a JOIN sessions se ON se.id=a.session_id
               JOIN members m ON m.id=a.member_id
               JOIN session_sources ss ON ss.session_id=se.id
               JOIN sources so ON so.id=ss.source_id WHERE """
            + " AND ".join(conditions)
            + " ORDER BY se.session_date, m.normalised_name",
            params,
        ).fetchall()

    def membersForSession(
        self, sessionId: int, responses: Iterable[str] | None = None
    ) -> list[sqlite3.Row]:
        params: list[object] = [sessionId]
        condition = ""
        if responses:
            values = [value.casefold() for value in responses]
            condition = f" AND a.response IN ({','.join('?' for _ in values)})"
            params.extend(values)
        return self.connection.execute(
            "SELECT m.*, a.response, a.conflicted FROM attendance a JOIN members m ON m.id=a.member_id WHERE a.session_id=?"
            + condition
            + " ORDER BY m.normalised_name",
            params,
        ).fetchall()

    def observationsForAttendance(
        self, sessionId: int, memberId: int
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT ao.*, s.source_type, s.display_name source_name, ss.external_id
               FROM attendance_observations ao JOIN session_sources ss ON ss.id=ao.session_source_id
               JOIN sources s ON s.id=ss.source_id WHERE ao.session_id=? AND ao.member_id=?
               ORDER BY ao.observed_at""",
            (sessionId, memberId),
        ).fetchall()

    def sessionsForMember(
        self, memberId: int, startDate: date, endDate: date
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT s.*, a.response, a.conflicted FROM attendance a JOIN sessions s ON s.id=a.session_id
               WHERE a.member_id=? AND s.session_date BETWEEN ? AND ? ORDER BY s.session_date, s.start_time""",
            (memberId, startDate.isoformat(), endDate.isoformat()),
        ).fetchall()

    def sessionsInRange(self, startDate: date, endDate: date) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM sessions WHERE session_date BETWEEN ? AND ? ORDER BY session_date, start_time",
            (startDate.isoformat(), endDate.isoformat()),
        ).fetchall()

    ## parsing helpers

    def _sessionDateTime(self, value: str) -> tuple[str | None, str | None]:
        match = re.match(r"^(\d{4})(\d{2})(\d{2})(?:\s+(\d{2}:\d{2}))?", value)
        if not match:
            return None, None
        return f"{match[1]}-{match[2]}-{match[3]}", match[4]

    def _sessionParts(self, title: str) -> tuple[str, str]:
        if self.sessionParser is not None:
            name = self.sessionParser.extractSessionName(title)
            _time, venue = self.sessionParser.extractSessionParts(title)
            return name or "Session", venue
        venue = ""
        name = " ".join(title.split()).strip() or "Session"
        return name, venue
