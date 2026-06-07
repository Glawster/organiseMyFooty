from __future__ import annotations

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.parsing import PollTextParser
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()
MAX_SOURCE_KEY_LENGTH = 300


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
            'button:has-text("View votes")',
            'span:has-text("View votes")',
            'text="View votes"',
        )
        # selectors = (
        #    '[data-testid="poll-view-votes"]',
        #    'div[role="button"]:has-text("View votes")',
        #    'span:has-text("View votes")',
        #    'text="View votes"',
        # )

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
                    self.logSkippedPollCandidate(item)
                    continue

                messageKey = self.extractMessageKey(item)
                key = self.buildPollLocatorKey(messageKey, sourceText)
                if key in seenKeys:
                    continue

                seenKeys.add(key)
                pollLocators.append(item)

        return pollLocators

    def extractPollDateText(
        self, locator, sourceText: str, allowDomFallback: bool = True
    ) -> str:
        textDate = self.parser.extractLikelyDateText(sourceText)
        if textDate and self.parser.normaliseDateText(textDate):
            return textDate

        if not allowDomFallback:
            return ""

        script = r"""
        (node) => {
            const isDateText = (value) => {
                const text = (value || "").trim();
                return /^(today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$/i.test(text)
                    || /^\d{1,2}\/\d{1,2}\/(?:\d{2}|\d{4})$/.test(text);
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
        for selector in (
            '[data-testid="poll-view-votes"]',
            'div[role="button"]:has-text("View votes")',
            'button:has-text("View votes")',
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
        for selector, attribute in (
            ("xpath=ancestor-or-self::*[@data-id][1]", "data-id"),
            (
                'xpath=ancestor-or-self::*[@data-testid][contains(@data-testid, "msg")][1]',
                "data-testid",
            ),
        ):
            try:
                value = locator.locator(selector).first.get_attribute(
                    attribute, timeout=1000
                )
                if value:
                    return value
            except Exception:
                continue

        return ""

    def buildPollLocatorKey(self, messageKey: str, sourceText: str) -> str:
        sourceKey = "|".join(sourceText.split())[:MAX_SOURCE_KEY_LENGTH]
        if messageKey:
            return f"{messageKey}|{sourceKey}"
        return sourceKey

    def extractPollSourceText(self, locator) -> str:
        for selector in (
            "xpath=ancestor-or-self::*[contains(., 'Select one or more') and contains(., 'View votes')][1]",
            "xpath=ancestor-or-self::*[@data-id][1]",
            'xpath=ancestor-or-self::*[@data-testid][contains(@data-testid, "msg")][1]',
            "xpath=ancestor-or-self::*[contains(., 'View votes')][1]",
        ):
            try:
                text = locator.locator(selector).first.inner_text(timeout=1000)
                if self.pollSourceTextIsUseful(text):
                    return text
            except Exception:
                continue

        try:
            text = locator.inner_text(timeout=1000)
            if self.pollSourceTextIsUseful(text):
                return text
        except Exception:
            pass

        text = self.extractPollDomDebugText(locator)
        return text if self.pollSourceTextIsUseful(text) else ""

    def pollSourceTextIsUseful(self, text: str) -> bool:
        collapsed = " ".join(text.split()).strip().lower()
        if not collapsed:
            return False

        if collapsed in {self.selectors.viewVotesText.lower(), "select one or more"}:
            return False

        return True

    def extractPollDomDebugText(self, locator) -> str:
        script = r"""
        (node) => {
            const collected = [];
            const seen = new Set();
            const add = (value) => {
                const text = (value || "").replace(/\s+/g, " ").trim();
                if (!text || seen.has(text)) {
                    return;
                }

                seen.add(text);
                collected.push(text);
            };

            const targets = [];
            const messageRoot = node.closest('[data-id], [data-testid*="msg"]');
            if (messageRoot) {
                targets.push(messageRoot);
            }

            let current = node;
            for (let depth = 0; current && depth < 6; depth += 1) {
                targets.push(current);
                current = current.parentElement;
            }

            for (const el of targets) {
                add(el.innerText || el.textContent || "");
                add(el.getAttribute && el.getAttribute("aria-label"));
                add(el.getAttribute && el.getAttribute("title"));
                add(el.getAttribute && el.getAttribute("data-testid"));
                add(el.getAttribute && el.getAttribute("data-id"));
            }

            return collected.join("\n");
        }
        """

        try:
            return str(locator.evaluate(script, timeout=1000) or "")
        except Exception:
            return ""

    def logSkippedPollCandidate(self, locator) -> None:
        debugText = self.extractPollDomDebugText(locator)
        if debugText:
            self.logger.info(
                "skipping poll candidate missing usable source text: %s",
                debugText[:240],
            )
            return

        self.logger.info("skipping poll candidate missing usable source text")

    def logVisiblePollText(self, page) -> None:
        try:
            matches = page.locator("text=View votes")
            self.logger.info("...visible View votes count: %s", matches.count())
        except Exception as exc:
            self.logger.warning("Unable to count visible View votes: %s", exc)

        try:
            bodyText = page.locator("body").inner_text(timeout=2000)
            for line in bodyText.splitlines():
                if "View votes" in line or "Select one or more" in line:
                    self.logger.info("...visible poll marker: %s", line[:120])
        except Exception as exc:
            self.logger.warning("Unable to inspect visible poll text: %s", exc)
