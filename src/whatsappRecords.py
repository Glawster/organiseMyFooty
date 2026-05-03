from __future__ import annotations

from whatsappModels import PollRecord


def deduplicateRecords(records: list[PollRecord]) -> list[PollRecord]:
    output: list[PollRecord] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for record in records:
        key = (
            record.pollTitle,
            record.pollDateText,
            record.sessionDateText,
            record.option,
            record.voterName,
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output
