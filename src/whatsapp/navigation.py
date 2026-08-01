from __future__ import annotations

import time

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()


class GroupNotFoundError(RuntimeError):
    pass


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
            for selector in self.selectors.iterReadySelectors():
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

        self.prepareForGroupSearch(page)
        self.typeInSearchBox(page, groupName)

        candidate = page.get_by_text(groupName, exact=True).first
        try:
            candidate.click(timeout=self.config.timeoutMs)
        except Exception as exc:
            raise GroupNotFoundError(
                f'WhatsApp group not found with exact name: "{groupName}"'
            ) from exc
        self.waitForChatPanel(page)
        self.logger.info("group opened")

    def waitForChatPanel(self, page) -> None:
        try:
            page.wait_for_selector(
                '[data-testid="conversation-panel-messages"]',
                timeout=self.config.timeoutMs,
            )
        except Exception:
            page.wait_for_timeout(1000)

    def clickJumpToLatestControls(self, page) -> bool:
        for selector in (
            '[aria-label*="bottom" i]',
            '[aria-label*="latest" i]',
            '[title*="bottom" i]',
            '[title*="latest" i]',
            'button:has([data-icon="down"])',
            'span[data-icon="down"]',
        ):
            try:
                control = page.locator(selector).last
                if control.is_visible(timeout=300):
                    control.click(timeout=1000)
                    page.wait_for_timeout(700)
                    self.logger.debug("clicked jump-to-latest control: %s", selector)
                    return True
            except Exception:
                continue

        return False

    def pressJumpToLatestKeys(self, page) -> None:
        try:
            panel = page.locator('[data-testid="conversation-panel-messages"]').first
            panel.click(timeout=1000)
        except Exception:
            pass

        for key in ("End", "Control+End"):
            try:
                page.keyboard.press(key)
                page.wait_for_timeout(500)
            except Exception:
                continue

    ## search helpers

    def prepareForGroupSearch(self, page) -> None:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
        except Exception:
            pass

        self.activateSearch(page)

    def activateSearch(self, page) -> None:
        for selector in self.selectors.searchActivatorCandidates:
            try:
                control = page.locator(selector).first
                if control.is_visible(timeout=750):
                    control.click(timeout=2000)
                    page.wait_for_timeout(300)
                    return
            except Exception:
                continue

    def typeInSearchBox(self, page, groupName: str) -> None:
        lastError: Exception | None = None

        for attempt in range(2):
            for selector in self.selectors.iterSearchSelectors():
                try:
                    searchBox = page.locator(selector).first
                    searchBox.click(timeout=self.config.timeoutMs)
                    self.clearSearchBox(page, searchBox)
                    searchBox.type(groupName, delay=40)
                    return
                except Exception as exc:
                    lastError = exc
                    continue

            if attempt == 0:
                self.logger.info("retrying group search after reopening search")
                self.prepareForGroupSearch(page)

        raise RuntimeError(f"Unable to find WhatsApp search box: {lastError}")

    def clearSearchBox(self, page, searchBox) -> None:
        try:
            searchBox.fill("")
            return
        except Exception:
            pass

        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
        except Exception:
            pass

    def scrollChatToLatest(self, page) -> None:
        self.clickJumpToLatestControls(page)
        self.pressJumpToLatestKeys(page)

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

            if (!preferredTarget && !scrollables.length) {
                return {
                    didScroll: false,
                    usedPreferredTarget: false,
                    reason: 'no scrollable candidates',
                };
            }

            const targets = preferredTarget
                ? [preferredTarget]
                : scrollables.slice(0, 5).map((item) => item.el);
            const results = targets.map((target) => {
                const before = target.scrollTop;
                target.scrollTop = target.scrollHeight;
                return {
                    didScroll: target.scrollTop !== before,
                    before,
                    after: target.scrollTop,
                    scrollHeight: target.scrollHeight,
                    clientHeight: target.clientHeight,
                    dataTestId: target.getAttribute('data-testid'),
                    text: (target.innerText || '').slice(0, 120),
                };
            });
            const changed = results.find((item) => item.didScroll) || results[0];

            return {
                ...changed,
                usedPreferredTarget: true,
                candidateCount: scrollables.length,
            };
        }
        """

        result = None
        for attempt in range(5):
            try:
                result = page.evaluate(script)
                self.logger.debug("chat jump-to-latest result: %s", result)
            except Exception as exc:
                self.logger.warning(
                    "Unable to jump chat to latest, falling back to mouse wheel: %s",
                    exc,
                )

            if result and result.get("usedPreferredTarget"):
                page.wait_for_timeout(500)
                continue

            if attempt < 4:
                page.wait_for_timeout(500)
                continue

            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(500)

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

                if self.clickOlderMessagesBanner(page):
                    continue

                continue

            page.wait_for_timeout(1200)
