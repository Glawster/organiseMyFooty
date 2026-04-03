from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class WhatsAppSelectors:
    """
    Centralised selectors and text heuristics.

    These are intentionally easy to edit because WhatsApp Web markup changes.
    Prefer role/text/aria selectors where possible.
    """

    webUrl: str = "https://web.whatsapp.com/"

    searchBoxCandidates: tuple[str, ...] = (
        '[contenteditable="true"][data-tab="3"]',
        '[contenteditable="true"][data-tab="4"]',
        'div[role="textbox"]',
    )

    chatHeaderCandidates: tuple[str, ...] = (
        "header [title]",
        'header span[dir="auto"]',
    )

    pollCardCandidates: tuple[str, ...] = (
        'div[role="button"]:has-text("View votes")',
        'div:has-text("View votes")',
    )

    viewVotesText: str = "View votes"

    dialogCandidates: tuple[str, ...] = (
        'div[role="dialog"]',
        'div[aria-modal="true"]',
    )

    closeDialogCandidates: tuple[str, ...] = (
        'button[aria-label="Close"]',
        '[role="button"][aria-label="Close"]',
    )

    backCandidates: tuple[str, ...] = (
        'button[aria-label="Back"]',
        '[role="button"][aria-label="Back"]',
    )

    yesOptionTexts: tuple[str, ...] = ("Yes",)
    noOptionTexts: tuple[str, ...] = ("No",)

    likelyMessageTimePattern: str = r"\\b\\d{1,2}:\\d{2}\\b"

    def iterSearchSelectors(self) -> Iterable[str]:
        return self.searchBoxCandidates

    def iterPollSelectors(self) -> Iterable[str]:
        return self.pollCardCandidates

    def iterDialogSelectors(self) -> Iterable[str]:
        return self.dialogCandidates


DEFAULT_SELECTORS = WhatsAppSelectors()
