"""Persistent local lookup for WhatsApp contact phone numbers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def normaliseContactName(value: str) -> str:
    return " ".join(value.casefold().split())


def utcNow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ContactStore:
    """Keep private contact names and phone numbers outside generated reports."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None

    def open(self) -> "ContactStore":
        if self._connection is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        self._connection = connection
        connection.execute(
            """CREATE TABLE IF NOT EXISTS contacts (
                   normalised_name TEXT PRIMARY KEY,
                   display_name TEXT NOT NULL,
                   phone_number TEXT NOT NULL,
                   updated_at TEXT NOT NULL
               )"""
        )
        connection.commit()
        return self

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self.open()
        assert self._connection is not None
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def upsert(self, displayName: str, phoneNumber: str) -> None:
        displayName = displayName.strip()
        phoneNumber = self.normalisePhoneNumber(phoneNumber)
        if not displayName or not phoneNumber:
            return
        self.connection.execute(
            """INSERT INTO contacts(normalised_name, display_name, phone_number, updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(normalised_name) DO UPDATE SET
                   display_name=excluded.display_name,
                   phone_number=excluded.phone_number,
                   updated_at=excluded.updated_at""",
            (
                normaliseContactName(displayName),
                displayName,
                phoneNumber,
                utcNow(),
            ),
        )
        self.connection.commit()

    def phoneLookup(self) -> dict[str, str]:
        rows = self.connection.execute(
            "SELECT normalised_name, phone_number FROM contacts"
        ).fetchall()
        return {str(row["normalised_name"]): str(row["phone_number"]) for row in rows}

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM contacts").fetchone()
        return int(row[0]) if row else 0

    def normalisePhoneNumber(self, value: str) -> str:
        digits = "".join(character for character in value if character.isdigit())
        if digits.startswith("44"):
            return "0" + digits[2:]
        return digits
