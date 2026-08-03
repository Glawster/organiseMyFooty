from __future__ import annotations

import re

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

            dialogPanel = header.locator("xpath=ancestor::*[@role='dialog'][1]")
            try:
                dialogPanel.wait_for(state="visible", timeout=1000)
                panel = dialogPanel
            except Exception:
                panel = header.locator(
                    "xpath=ancestor::*[contains(., 'members voted')][1]"
                )
            panel.wait_for(state="visible", timeout=3000)

            text = panel.inner_text(timeout=3000)
            return panel, text

        except Exception as headerError:
            # Expanding "See all" re-renders some WhatsApp poll drawers and can
            # temporarily remove the Poll details heading.  The vote summary is
            # retained, so use it to recover the replacement panel.
            try:
                memberCount = page.get_by_text(
                    re.compile(r"\d+\s+of\s+\d+\s+members?\s+voted", re.IGNORECASE)
                ).last
                memberCount.wait_for(state="visible", timeout=3000)
                panel = memberCount.locator(
                    "xpath=ancestor::*[.//*[normalize-space()='Yes'] "
                    "and .//*[normalize-space()='No']][1]"
                )
                panel.wait_for(state="visible", timeout=3000)
                text = panel.inner_text(timeout=3000)
                return panel, text
            except Exception:
                self.logger.debug(
                    "unable to locate poll panel from its heading: %s", headerError
                )
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
                buttons = panel.get_by_text(
                    re.compile(r"^See all(?:\s+\(\d+\s+more\))?$", re.IGNORECASE)
                )
                count = buttons.count()
                self.logger.value("poll voter expand controls", count)
                expandedControls = 0

                for i in range(count):
                    try:
                        btn = buttons.nth(i)
                        if btn.is_visible(timeout=500):
                            btn.scroll_into_view_if_needed(timeout=1000)
                            btn.click(timeout=2000, force=True)
                            expandedControls += 1
                            panel.page.wait_for_timeout(750)
                    except Exception as exc:
                        self.logger.debug(
                            "unable to expand poll voter control: %s", exc
                        )
                        continue
                if expandedControls:
                    self.logger.value("poll voter controls expanded", expandedControls)
                    try:
                        page = panel.page
                        panel, expandedText = self.waitForDialog(page)
                        if expandedText.strip() and expandedText not in dialogTexts:
                            dialogTexts.append(expandedText)
                    except Exception as exc:
                        self.logger.debug(
                            "unable to re-resolve expanded poll dialog: %s", exc
                        )
                    continue

                currentText = panel.inner_text(timeout=2000)
                if currentText.strip() and currentText not in dialogTexts:
                    dialogTexts.append(currentText)

                scrollResult = panel.evaluate(
                    """panel => {
                        const ancestors = [];
                        let ancestor = panel.parentElement;
                        while (ancestor && ancestors.length < 6) {
                            ancestors.push(ancestor);
                            ancestor = ancestor.parentElement;
                        }
                        const candidates = [
                            panel,
                            ...panel.querySelectorAll('*'),
                            ...ancestors,
                        ];
                        const scrollables = candidates.filter(node => {
                            const style = window.getComputedStyle(node);
                            const overflow = `${style.overflow} ${style.overflowY}`;
                            return node.scrollHeight > node.clientHeight + 1
                                && /(auto|scroll)/.test(overflow);
                        });
                        if (!scrollables.length) {
                            return { moved: false, atEnd: true, count: 0 };
                        }
                        const results = scrollables.map(scrollable => {
                            const before = scrollable.scrollTop;
                            const step = Math.max(
                                scrollable.clientHeight * 0.8,
                                200
                            );
                            scrollable.scrollTop = Math.min(
                                before + step,
                                scrollable.scrollHeight - scrollable.clientHeight
                            );
                            return {
                                moved: scrollable.scrollTop > before,
                                atEnd: scrollable.scrollTop + scrollable.clientHeight >=
                                    scrollable.scrollHeight - 1,
                                tagName: scrollable.tagName,
                                role: scrollable.getAttribute('role'),
                                dataTestId: scrollable.getAttribute('data-testid'),
                                before,
                                after: scrollable.scrollTop,
                                clientHeight: scrollable.clientHeight,
                                scrollHeight: scrollable.scrollHeight,
                                overflow: window.getComputedStyle(scrollable).overflowY,
                            };
                        });
                        return {
                            moved: results.some(result => result.moved),
                            atEnd: results.every(result => result.atEnd),
                            count: results.length,
                            results,
                        };
                    }"""
                )
                self.logger.debug("poll voter scroll result: %s", scrollResult)
                snapshotCountBeforeScroll = len(dialogTexts)
                if not scrollResult.get("moved"):
                    try:
                        panel.hover()
                        panel.page.mouse.wheel(0, 400)
                    except Exception:
                        pass
                panel.page.wait_for_timeout(500)

                currentText = panel.inner_text(timeout=2000)
                if currentText.strip() and currentText not in dialogTexts:
                    dialogTexts.append(currentText)

                if (
                    not scrollResult.get("moved")
                    and len(dialogTexts) == snapshotCountBeforeScroll
                ):
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
