from __future__ import annotations

import time

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()


class WhatsAppNavigation:
    def __init__(self, config: RuntimeConfig, selectors: WhatsAppSelectors):
        self.config = config
        self.selectors = selectors
        self.logger = logger

    ## public api

    def waitForWhatsAppReady(self, page) -> None:
        page.wait_for_load_state("domcontentloaded")
        self.logger.doing("waiting for whatsapp web")
        deadline = time.time() + max(60, self.config.timeoutMs / 1000)

        while time.time() < deadline:
            for selector in self.selectors.iterSearchSelectors():
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=1000):
                        self.logger.info("whatsapp ready selector: %s", selector)
                        return
                except Exception:
                    continue
            time.sleep(1)

        raise TimeoutError(
            "WhatsApp Web did not become ready; make sure you are logged in."
        )

    def openGroup(self, page, groupName: str) -> None:
        self.logger.info("opening group: %s", groupName)

        lastError: Exception | None = None
        for selector in self.selectors.iterSearchSelectors():
            try:
                searchBox = page.locator(selector).first
                searchBox.click(timeout=self.config.timeoutMs)
                searchBox.fill("")
                searchBox.type(groupName, delay=40)
                break
            except Exception as exc:
                lastError = exc
                continue
        else:
            raise RuntimeError(f"Unable to find WhatsApp search box: {lastError}")

        candidate = page.get_by_text(groupName, exact=True).first
        candidate.click(timeout=self.config.timeoutMs)
        self.logger.info("group opened")

    def scrollChatToLatest(self, page) -> None:
        script = """
        () => {
            const isScrollable = (el) => {
                if (!el) {
                    return false;
                }

                const style = window.getComputedStyle(el);
                const canScroll =
                    ['auto', 'scroll'].includes(style.overflowY) ||
                    ['auto', 'scroll'].includes(style.overflow);

                return canScroll && el.scrollHeight > el.clientHeight + 200;
            };

            const findScrollableAncestor = (el) => {
                let current = el;
                while (current) {
                    if (isScrollable(current)) {
                        return current;
                    }
                    current = current.parentElement;
                }
                return null;
            };

            const preferredPanel = document.querySelector(
                '[data-testid="conversation-panel-messages"]'
            );
            const preferredTarget = findScrollableAncestor(preferredPanel);

            if (!preferredTarget) {
                return {
                    didScroll: false,
                    usedPreferredTarget: false,
                    reason: 'no preferred target',
                };
            }

            const before = preferredTarget.scrollTop;
            preferredTarget.scrollTop = preferredTarget.scrollHeight;

            return {
                didScroll: preferredTarget.scrollTop !== before,
                before,
                after: preferredTarget.scrollTop,
                scrollHeight: preferredTarget.scrollHeight,
                clientHeight: preferredTarget.clientHeight,
                dataTestId: preferredTarget.getAttribute('data-testid'),
                usedPreferredTarget: true,
                text: (preferredTarget.innerText || '').slice(0, 120),
            };
        }
        """

        result = None
        try:
            result = page.evaluate(script)
            self.logger.debug("chat jump-to-latest result: %s", result)
        except Exception as exc:
            self.logger.warning(
                "Unable to jump chat to latest, falling back to mouse wheel: %s",
                exc,
            )

        if not result or not result.get("usedPreferredTarget"):
            page.mouse.wheel(0, 2500)

        page.wait_for_timeout(1200)

    def clickOlderMessagesBanner(self, page) -> bool:
        for text in (
            "Click here to get older messages from your phone",
            "Use WhatsApp on your phone to see older messages",
        ):
            try:
                banner = page.get_by_text(text, exact=False).first
                if banner.is_visible(timeout=500):
                    self.logger.debug("loading older messages from phone")
                    banner.click(timeout=2000)
                    page.wait_for_timeout(2500)
                    return True
            except Exception:
                continue

        return False

    def scrollChatHistory(self, page, scrollPasses: int = 1) -> None:
        script = """
        () => {
            const isScrollable = (el) => {
                if (!el) {
                    return false;
                }

                const style = window.getComputedStyle(el);
                const canScroll =
                    ['auto', 'scroll'].includes(style.overflowY) ||
                    ['auto', 'scroll'].includes(style.overflow);

                return canScroll && el.scrollHeight > el.clientHeight + 200;
            };

            const findScrollableAncestor = (el) => {
                let current = el;
                while (current) {
                    if (isScrollable(current)) {
                        return current;
                    }
                    current = current.parentElement;
                }
                return null;
            };

            const preferredPanel = document.querySelector(
                '[data-testid="conversation-panel-messages"]'
            );
            const preferredTarget = findScrollableAncestor(preferredPanel);
            const elements = Array.from(document.querySelectorAll('*'));

            const scrollables = elements
                .filter((el) => isScrollable(el))
                .map((el) => ({
                    el,
                    dataTestId: el.getAttribute('data-testid'),
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    scrollTop: el.scrollTop,
                    text: (el.innerText || '').slice(0, 120),
                }))
                .sort((a, b) =>
                    (b.scrollHeight - b.clientHeight) -
                    (a.scrollHeight - a.clientHeight)
                );

            if (!scrollables.length) {
                return {
                    didScroll: false,
                    reason: 'no scrollable candidates',
                };
            }

            const target = preferredTarget
                ? {
                    el: preferredTarget,
                    dataTestId: preferredTarget.getAttribute('data-testid'),
                    scrollHeight: preferredTarget.scrollHeight,
                    clientHeight: preferredTarget.clientHeight,
                    text: (preferredTarget.innerText || '').slice(0, 120),
                }
                : scrollables[0];
            const before = target.el.scrollTop;
            target.el.scrollTop = Math.max(0, before - 500);

            return {
                didScroll: target.el.scrollTop !== before,
                before,
                after: target.el.scrollTop,
                scrollHeight: target.scrollHeight,
                clientHeight: target.clientHeight,
                dataTestId: target.dataTestId,
                usedPreferredTarget: Boolean(preferredTarget),
                text: target.text,
            };
        }
        """

        for _ in range(scrollPasses):
            if self.clickOlderMessagesBanner(page):
                continue

            result = None
            try:
                result = page.evaluate(script)
                self.logger.debug("chat scroll result: %s", result)
            except Exception as exc:
                self.logger.warning(
                    "Unable to scroll chat history, falling back to mouse wheel: %s",
                    exc,
                )

            if (
                not result
                or not result.get("didScroll")
                or not result.get("usedPreferredTarget")
            ):
                page.mouse.wheel(0, -2500)

            page.wait_for_timeout(1200)
