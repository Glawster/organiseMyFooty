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

    # Broad selectors — any one visible means WhatsApp Web has fully loaded.
    # Used only by waitForWhatsAppReady; add new entries here if the UI changes.
    readyIndicatorCandidates: tuple[str, ...] = (
        '[aria-label="Search or start a new chat"]',
        '[placeholder="Search or start a new chat"]',
        '[data-testid="chat-list"]',
        '[aria-label="Chat list"]',
        "#pane-side",
        # Legacy data-tab attributes (older WhatsApp Web builds)
        '[contenteditable="true"][data-tab="3"]',
        '[contenteditable="true"][data-tab="4"]',
    )

    # Interactive search-box selectors — must be clickable/typeable.
    # Used by openGroup to find and focus the search input.
    searchBoxCandidates: tuple[str, ...] = (
        '[aria-label="Search or start a new chat"]',
        '[placeholder="Search or start a new chat"]',
        '[data-testid="search-input"]',
        '[title="Search or start a new chat"]',
        # Legacy data-tab attributes (older WhatsApp Web builds)
        '[contenteditable="true"][data-tab="3"]',
        '[contenteditable="true"][data-tab="4"]',
        'div[role="textbox"]',
    )

    chatHeaderCandidates: tuple[str, ...] = (
        "header [title]",
        'header span[dir="auto"]',
    )

    pollCardCandidates: tuple[str, ...] = (
        '[data-testid="poll-view-votes"]',
        'div[role="button"]:has-text("View votes")',
        'div:has-text("View votes")',
    )

    viewVotesText: str = "View votes"

    dialogCandidates: tuple[str, ...] = (
        # Semantic dialog roles — catches some WhatsApp Web builds.
        'div[role="dialog"]',
        'div[aria-modal="true"]',
        # data-testid patterns used in recent WhatsApp Web builds.
        '[data-testid="popup-contents"]',
        '[data-testid="drawer"]',
        # Animation/modal attribute used in some builds.
        "div[data-animate-modal-body]",
        # Aria-labelled panels that appear for vote results.
        '[aria-label="Poll results"]',
        '[aria-label="View votes"]',
        # Fallbacks for drawer-like vote panels that expose back/close controls.
        'aside:has([aria-label="Back"])',
        'aside:has([aria-label="Close"])',
        'section:has([aria-label="Back"])',
        'section:has([aria-label="Close"])',
        # Last-resort English-text fallbacks for current WhatsApp Web poll panels.
        # Keep these near the end because they are more brittle than aria/test-id selectors.
        'div:has([aria-label="Back"]):has-text("Yes")',
        'div:has([aria-label="Close"]):has-text("Yes")',
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

    likelyMessageTimePattern: str = r"\b\d{1,2}:\d{2}\b"

    def iterReadySelectors(self) -> Iterable[str]:
        return self.readyIndicatorCandidates

    def iterSearchSelectors(self) -> Iterable[str]:
        return self.searchBoxCandidates

    def iterPollSelectors(self) -> Iterable[str]:
        return self.pollCardCandidates

    def iterDialogSelectors(self) -> Iterable[str]:
        return self.dialogCandidates


DEFAULT_SELECTORS = WhatsAppSelectors()
