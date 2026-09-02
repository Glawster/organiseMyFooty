"""Tests for the private WhatsApp contact phone directory."""

from datetime import date
from pathlib import Path

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.contactDirectory import WhatsAppContactDirectory
from whatsapp.contactRefresh import FilteredWhatsAppContactDirectory
from whatsapp.contactStore import ContactStore
from whatsapp.selectors import DEFAULT_SELECTORS


def _makeConfig(tmpPath: Path) -> RuntimeConfig:
    return RuntimeConfig(
        groupName="Test Group",
        monthWindow=MonthWindow(
            monthKey="2026-08",
            startDate=date(2026, 8, 1),
            endDate=date(2026, 8, 31),
        ),
        outputDir=tmpPath,
        userDataDir=tmpPath / "profile",
        headless=True,
        dryRun=True,
        timeoutMs=5000,
        logLevel=20,
        limitPolls=None,
        browserChannel=None,
        includeNoVotes=False,
        resume=False,
        pollTitleFilter=None,
    )


def testContactStorePersistsNormalisedUkPhone(tmp_path):
    store = ContactStore(tmp_path / "contacts.sqlite3").open()
    store.upsert("Mina", "+44 7810 878563")
    store.close()

    store = ContactStore(tmp_path / "contacts.sqlite3").open()
    assert store.phoneLookup() == {"mina": "07810878563"}
    store.close()


def testContactDirectoryExtractsPhoneFromWhatsappJidMetadata(tmp_path):
    store = ContactStore(tmp_path / "contacts.sqlite3").open()
    directory = WhatsAppContactDirectory(
        _makeConfig(tmp_path), DEFAULT_SELECTORS, store
    )

    pair = directory.extractContactPair(
        {
            "text": "Mina\nHey there! I am using WhatsApp.",
            "metadata": "data-id=447810878563@c.us",
        }
    )

    assert pair == ("Mina", "07810878563")
    store.close()


def testContactDirectoryExtractsVisibleUkPhone(tmp_path):
    store = ContactStore(tmp_path / "contacts.sqlite3").open()
    directory = WhatsAppContactDirectory(
        _makeConfig(tmp_path), DEFAULT_SELECTORS, store
    )

    pair = directory.extractContactPair(
        {"text": "Mina\n+44 7810 878563", "metadata": ""}
    )

    assert pair == ("Mina", "07810878563")
    store.close()


def testFilteredContactDirectoryKeepsOnlyMatchingContactNames(tmp_path):
    store = ContactStore(tmp_path / "contacts.sqlite3").open()
    directory = FilteredWhatsAppContactDirectory(
        _makeConfig(tmp_path), DEFAULT_SELECTORS, store
    )
    rows = [
        {"text": "She HWFC", "metadata": "title=She HWFC"},
        {"text": "Mina Bingham", "metadata": "title=Mina Bingham"},
        {"text": "HWFC Refs", "metadata": "title=HWFC Refs"},
    ]

    assert directory.filterRowsForSearch(rows, "HWFC") == [
        {"text": "She HWFC", "metadata": "title=She HWFC"},
        {"text": "HWFC Refs", "metadata": "title=HWFC Refs"},
    ]
    store.close()
