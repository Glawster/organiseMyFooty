from datetime import date
from pathlib import Path

from attendanceConfig import MonthWindow, RuntimeConfig
from whatsapp.contactRefresh import FilteredWhatsAppContactDirectory
from whatsapp.contactStore import ContactStore
from whatsapp.names import stripContactNameMarker
from whatsapp.parsing import PollTextParser
from whatsapp.pollRecordsBuilder import PollRecordsBuilder
from whatsapp.selectors import DEFAULT_SELECTORS
from whatsapp.models import SessionStatus


class StubDiscovery:
    pass


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


def testStripContactNameMarkerOnlyRemovesTrailingHwfc():
    assert stripContactNameMarker("She HWFC") == "She"
    assert stripContactNameMarker("She hwfc") == "She"
    assert stripContactNameMarker("HWFC Refs") == "HWFC Refs"
    assert stripContactNameMarker("Andrew Wilson") == "Andrew Wilson"


def testPollRecordsDoNotPersistHwfcMarker(tmp_path):
    config = _makeConfig(tmp_path)
    parser = PollTextParser(config, DEFAULT_SELECTORS)
    builder = PollRecordsBuilder(
        config=config,
        selectors=DEFAULT_SELECTORS,
        parser=parser,
        discovery=StubDiscovery(),
    )

    records = builder.buildOptionRecords(
        dialogText="Sunday 2pm Football Factory\nYes\nShe HWFC\n+44 7810 878563\n",
        pollTitle="Sunday 2pm Football Factory",
        pollDateText="20260806",
        sessionDateText="20260809 14:00",
        sourceHint="test",
        sessionStatus=SessionStatus.SCHEDULED,
    )

    assert len(records) == 1
    assert records[0].voterName == "She"
    assert records[0].voterPhone == "447810878563"
    assert builder.voterPhones == {"she": "447810878563"}


def testFilteredContactDirectoryStoresNameWithoutHwfcMarker(tmp_path):
    store = ContactStore(tmp_path / "contacts.sqlite3").open()
    directory = FilteredWhatsAppContactDirectory(
        _makeConfig(tmp_path), DEFAULT_SELECTORS, store
    )

    pair = directory.extractContactPair(
        {
            "text": "She HWFC\n+44 7810 878563",
            "metadata": "",
        }
    )

    assert pair == ("She", "07810878563")
    store.close()
