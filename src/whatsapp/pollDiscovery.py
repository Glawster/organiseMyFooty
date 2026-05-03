from __future__ import annotations

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.parsing import PollTextParser
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()


class PollDiscovery:
    def __init__(
        self,
        config: RuntimeConfig,
        selectors: WhatsAppSelectors,
        parser: PollTextParser,
    ):
        self.config = config
        self.selectors = selectors
        self.parser = parser
        self.logger = logger

    ## public api

    def findPollCards(self, page) -> list:
        pollLocators: list = []
        seenKeys: set[str] = set()
        selectors = (
            '[data-testid="poll-view-votes"]',
            'div[role="button"]:has-text("View votes")',
            'span:has-text("View votes")',
            'text="View votes"',
        )

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                item = self.resolvePollButton(locator.nth(index))
                sourceText = self.extractPollSourceText(item)
                if self.selectors.viewVotesText.lower() not in sourceText.lower():
                    continue

                key = f"{selector}|{index}|{sourceText[:120]}"
                if key in seenKeys:
                    continue

                seenKeys.add(key)
                pollLocators.append(item)

        self.logger.value("candidate poll cards found", len(pollLocators))
        return pollLocators

    def extractPollDateText(self, locator, sourceText: str) -> str:
        textDate = self.parser.extractLikelyDateText(sourceText)
        if textDate:
            return textDate

        script = r"""
        (node) => {
            const isDateText = (value) => {
                const text = (value || "").trim();
                return /^(today|yesterday)$/i.test(text)
                    || /^\d{1,2}\/\d{1,2}\/\d{4}$/.test(text);
            };

            const nodeRect = node.getBoundingClientRect();
            const candidates = Array.from(document.querySelectorAll("span, div"))
                .map((el) => {
                    const text = (el.innerText || el.textContent || "").trim();
                    if (!isDateText(text)) {
                        return null;
                    }

                    const rect = el.getBoundingClientRect();
                    return {
                        text,
                        top: rect.top,
                        bottom: rect.bottom,
                        left: rect.left,
                        right: rect.right,
                    };
                })
                .filter(Boolean)
                .filter((item) => item.bottom <= nodeRect.top + 5)
                .sort((a, b) => b.bottom - a.bottom);

            return candidates.length ? candidates[0].text : "";
        }
        """

        try:
            return str(locator.evaluate(script, timeout=1000) or "")
        except Exception as exc:
            self.logger.warning("Unable to derive poll date: %s", exc)
            return ""

    ## locator helpers

    def resolvePollButton(self, locator):
        try:
            text = locator.inner_text(timeout=500)
            if self.selectors.viewVotesText.lower() in text.lower():
                return locator
        except Exception:
            pass

        for selector in (
            '[data-testid="poll-view-votes"]',
            'div[role="button"]:has-text("View votes")',
            f'text="{self.selectors.viewVotesText}"',
        ):
            try:
                button = locator.locator(selector).first
                if button.is_visible(timeout=500):
                    return button
            except Exception:
                continue
        return locator

    def extractMessageKey(self, locator) -> str:
        for selector in (
            'xpath=ancestor-or-self::*[@data-testid][contains(@data-testid, "msg")][1]',
            "xpath=ancestor-or-self::*[@data-id][1]",
        ):
            try:
                value = locator.locator(selector).first.get_attribute(
                    "data-testid", timeout=1000
                )
                if value:
                    return value
            except Exception:
                pass

            try:
                value = locator.locator(selector).first.get_attribute(
                    "data-id", timeout=1000
                )
                if value:
                    return value
            except Exception:
                pass

        return ""

    def extractPollSourceText(self, locator) -> str:
        for selector in (
            'xpath=ancestor-or-self::*[@data-testid][contains(@data-testid, "msg")][1]',
            "xpath=ancestor-or-self::*[@data-id][1]",
            'xpath=ancestor::*[contains(., "View votes")][1]',
        ):
            try:
                text = locator.locator(selector).first.inner_text(timeout=1000)
                if text.strip():
                    return text
            except Exception:
                continue

        try:
            return locator.inner_text(timeout=1000)
        except Exception:
            return ""
