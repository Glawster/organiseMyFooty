from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]

from whatsapp.constants import (
    IGNORE_POLL_CACHE,
    POLL_CACHE_VERSION,
    RECENT_POLLS_TO_RECHECK,
)
from whatsapp.models import PollRecord
from whatsapp.parsing import PollTextParser
from whatsapp.records import deduplicateRecords

logger = getLogger()


class PollCacheStore:
    def __init__(self, config: RuntimeConfig, parser: PollTextParser):
        self.config = config
        self.parser = parser
        self.logger = logger

    # ## cache path utilities
    def getPollCachePath(self) -> Path:
        return self.config.outputDir / "pollCache.json"

    # ## cache read utilities
    def loadPollCache(self) -> OrderedDict[str, list[PollRecord]]:
        if IGNORE_POLL_CACHE:
            self.logger.info("poll cache ignored")
            return OrderedDict()

        cachePath = self.getPollCachePath()
        if not cachePath.exists():
            return OrderedDict()

        try:
            payload = json.loads(cachePath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.logger.warning(
                "poll cache is not valid json and will be ignored: %s", cachePath
            )
            return OrderedDict()

        if not self.isValidCachePayload(payload, cachePath):
            return OrderedDict()

        cachedPolls: OrderedDict[str, list[PollRecord]] = OrderedDict()
        rawPolls = payload.get("polls", {})
        if not isinstance(rawPolls, dict):
            return cachedPolls

        for pollKey, rawRecords in rawPolls.items():
            if not isinstance(rawRecords, list):
                continue
            records = self.recordsFromCacheRows(rawRecords)
            if records:
                cachedPolls[pollKey] = records

        self.logger.info("loaded cached poll result(s): %s", len(cachedPolls))
        return cachedPolls

    def isValidCachePayload(self, payload: dict, cachePath: Path) -> bool:
        if payload.get("version") != POLL_CACHE_VERSION:
            self.logger.info("ignoring old poll cache version: %s", cachePath)
            return False
        if payload.get("groupName") != self.config.groupName:
            self.logger.info("ignoring poll cache for different group: %s", cachePath)
            return False
        if payload.get("month") != self.config.monthWindow.monthKey:
            self.logger.info("ignoring poll cache for different month: %s", cachePath)
            return False
        return True

    def recordsFromCacheRows(self, rows: list[dict]) -> list[PollRecord]:
        records: list[PollRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                records.append(
                    PollRecord(
                        pollTitle=str(row["pollTitle"]),
                        pollDateText=str(row["pollDateText"]),
                        sessionDateText=self.parser.calculateSessionDateText(
                            pollTitle=str(row["pollTitle"]),
                            pollDateText=str(row["pollDateText"]),
                        ),
                        option=str(row["option"]),
                        voterName=str(row["voterName"]),
                        sourceHint=str(row["sourceHint"]),
                    )
                )
            except KeyError:
                continue
        return deduplicateRecords(records)

    # ## cache write utilities
    def savePollCache(
        self, recordsByPollKey: OrderedDict[str, list[PollRecord]]
    ) -> None:
        cachePath = self.getPollCachePath()

        if not recordsByPollKey:
            self.logger.warning(
                "poll cache not written because no poll records were scraped"
            )
            return

        self.logger.action("write poll cache: %s", cachePath)
        if self.config.dryRun:
            return

        cachePath.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": POLL_CACHE_VERSION,
            "groupName": self.config.groupName,
            "month": self.config.monthWindow.monthKey,
            "savedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "recentPollsToRecheck": RECENT_POLLS_TO_RECHECK,
            "polls": {
                pollKey: [asdict(record) for record in records]
                for pollKey, records in recordsByPollKey.items()
            },
        }
        cachePath.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ## cache merge utilities
    def flattenCachedPolls(
        self, recordsByPollKey: OrderedDict[str, list[PollRecord]]
    ) -> list[PollRecord]:
        records: list[PollRecord] = []
        for pollRecords in recordsByPollKey.values():
            records.extend(pollRecords)
        return deduplicateRecords(records)

    def shouldRecheckPoll(self, index: int, totalPolls: int) -> bool:
        return index > max(0, totalPolls - RECENT_POLLS_TO_RECHECK)
