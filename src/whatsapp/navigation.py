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
        self.logger.info("...waiting for whatsapp web")
        deadline = time.time() + max(60, self.config.timeoutMs / 1000)

        while time.time() < deadline:
            for selector in self.selectors.iterSearchSelectors():
                try:
                    locator = page.locator(selector).first
                    if locator.is_visible(timeout=1000):
                        self.logger.info("...whatsapp ready selector: %s", selector)
                        return
                except Exception:
                    continue
            time.sleep(1)

        raise TimeoutError(
            "WhatsApp Web did not become ready; make sure you are logged in."
        )

    def openGroup(self, page, groupName: str) -> None:
        self.logger.info("...opening group: %s", groupName)

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
        self.logger.info("group opened...")

    def scrollChatHistory(self, page, scrollPasses: int = 12) -> None:
        self.logger.info("...scrolling chat history")
        for _ in range(scrollPasses):
            page.mouse.wheel(0, -2000)
            page.wait_for_timeout(800)
