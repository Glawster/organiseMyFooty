from __future__ import annotations

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()


class PollDialog:
    def __init__(self, config: RuntimeConfig, selectors: WhatsAppSelectors):
        self.config = config
        self.selectors = selectors
        self.logger = logger

    ## public api

    def openPollVotes(self, locator) -> bool:
        disabled = locator.get_attribute("aria-disabled", timeout=1000)
        if disabled == "true":
            self.logger.info("poll skipped disabled")
            return False

        locator.scroll_into_view_if_needed(timeout=self.config.timeoutMs)
        locator.click(timeout=self.config.timeoutMs)
        return True

    def waitForDialog(self, page):
        try:
            header = page.get_by_text("Poll details", exact=False).last
            header.wait_for(state="visible", timeout=3000)

            panel = header.locator("xpath=ancestor::*[contains(., 'members voted')][1]")
            panel.wait_for(state="visible", timeout=3000)

            text = panel.inner_text(timeout=3000)
            return panel, text

        except Exception:
            self.logPollPanelDiagnostics(page)
            raise TimeoutError("Unable to locate poll results panel.")

    def readDialogText(self, dialog, fallback: str = "") -> str:
        try:
            text = dialog.inner_text(timeout=2000)
            return text if text.strip() else fallback
        except Exception:
            return fallback

    def expandAllVoters(self, panel, initialText: str = "") -> list[str]:
        """Return distinct panel snapshots while scrolling its virtual voter list."""
        dialogTexts = [initialText] if initialText.strip() else []

        for _ in range(20):
            try:
                buttons = panel.get_by_text("See all", exact=False)
                count = buttons.count()

                for i in range(count):
                    try:
                        btn = buttons.nth(i)
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=2000)
                            panel.page.wait_for_timeout(500)
                    except Exception:
                        continue

                currentText = panel.inner_text(timeout=2000)
                if currentText.strip() and currentText not in dialogTexts:
                    dialogTexts.append(currentText)

                scrollResult = panel.evaluate(
                    """panel => {
                        const candidates = [panel, ...panel.querySelectorAll('*')];
                        const scrollable = candidates
                            .filter(node => node.scrollHeight > node.clientHeight + 1)
                            .sort((left, right) =>
                                (right.scrollHeight - right.clientHeight) -
                                (left.scrollHeight - left.clientHeight)
                            )[0];
                        if (!scrollable) return { moved: false, atEnd: true };
                        const before = scrollable.scrollTop;
                        const step = Math.max(scrollable.clientHeight * 0.8, 400);
                        scrollable.scrollTop = Math.min(
                            before + step,
                            scrollable.scrollHeight - scrollable.clientHeight
                        );
                        return {
                            moved: scrollable.scrollTop > before,
                            atEnd: scrollable.scrollTop + scrollable.clientHeight >=
                                scrollable.scrollHeight - 1
                        };
                    }"""
                )
                try:
                    panel.hover()
                    panel.page.mouse.wheel(0, 800)
                except Exception:
                    pass
                panel.page.wait_for_timeout(500)

                currentText = panel.inner_text(timeout=2000)
                if currentText.strip() and currentText not in dialogTexts:
                    dialogTexts.append(currentText)

                if not scrollResult.get("moved") or scrollResult.get("atEnd"):
                    break

            except Exception:
                break

        return dialogTexts

    def closeDialog(self, page, dialog) -> None:
        for selector in self.selectors.closeDialogCandidates:
            try:
                control = page.locator(selector).first
                if control.is_visible(timeout=1000):
                    control.click(timeout=self.config.timeoutMs)
                    page.wait_for_timeout(400)
                    return
            except Exception:
                continue

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

    ## diagnostics

    def logPollPanelDiagnostics(self, page) -> None:
        for textAnchor in ("Poll details", "View votes", "Yes", "No"):
            try:
                count = page.get_by_text(textAnchor, exact=False).count()
                self.logger.value(f"visible text count {textAnchor}", count)
            except Exception:
                continue
