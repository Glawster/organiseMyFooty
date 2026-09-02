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
            panel = self.findVisibleDialogCandidate(page)
            if panel is not None:
                return panel, panel.inner_text(timeout=3000)

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

    def findVisibleDialogCandidate(self, page):
        """Find a rerendered poll drawer without relying on its heading text."""
        controlPanel = self.findPanelFromNavigationControl(page)
        if controlPanel is not None:
            return controlPanel

        for selector in self.selectors.iterDialogSelectors():
            try:
                candidates = page.locator(selector)
                matches = []
                for index in range(candidates.count() - 1, -1, -1):
                    candidate = candidates.nth(index)
                    if not candidate.is_visible(timeout=500):
                        continue
                    if candidate.locator(
                        '[data-testid="conversation-panel-messages"]'
                    ).count():
                        continue
                    text = candidate.inner_text(timeout=1000)
                    lines = {line.strip().casefold() for line in text.splitlines()}
                    if "yes" in lines:
                        matches.append((len(text), candidate))
                if matches:
                    _, candidate = min(matches, key=lambda item: item[0])
                    self.logger.debug(
                        "recovered expanded poll panel using selector: %s",
                        selector,
                    )
                    return candidate
            except Exception:
                continue

        for selector in self.selectors.closeDialogCandidates:
            try:
                controls = page.locator(selector)
                for index in range(controls.count() - 1, -1, -1):
                    control = controls.nth(index)
                    if not control.is_visible(timeout=500):
                        continue
                    candidate = control.locator(
                        "xpath=ancestor::*[.//*[normalize-space()='Yes']][1]"
                    )
                    if (
                        candidate.is_visible(timeout=500)
                        and not candidate.locator(
                            '[data-testid="conversation-panel-messages"]'
                        ).count()
                    ):
                        self.logger.debug(
                            "recovered expanded poll panel from close control"
                        )
                        return candidate
            except Exception:
                continue

        return None

    def findPanelFromNavigationControl(self, page):
        """Resolve the smallest drawer-sized ancestor of a Back/Close control."""
        matches = []
        selectors = (
            *self.selectors.backCandidates,
            *self.selectors.closeDialogCandidates,
        )
        for selector in selectors:
            try:
                controls = page.locator(selector)
                for controlIndex in range(controls.count() - 1, -1, -1):
                    control = controls.nth(controlIndex)
                    if not control.is_visible(timeout=500):
                        continue
                    ancestors = control.locator("xpath=ancestor::*")
                    for ancestorIndex in range(ancestors.count()):
                        candidate = ancestors.nth(ancestorIndex)
                        if candidate.locator(
                            '[data-testid="conversation-panel-messages"]'
                        ).count():
                            continue
                        box = candidate.bounding_box(timeout=500)
                        if not box or box["width"] < 280 or box["height"] < 400:
                            continue
                        text = candidate.inner_text(timeout=1000)
                        if not text.strip():
                            continue
                        matches.append(
                            (box["width"] * box["height"], len(text), candidate)
                        )
            except Exception:
                continue

        if not matches:
            return None

        _, _, panel = min(matches, key=lambda item: (item[0], item[1]))
        self.logger.debug("recovered expanded poll panel from navigation control")
        return panel

    def readDialogText(self, dialog, fallback: str = "") -> str:
        try:
            text = dialog.inner_text(timeout=2000)
            return text if text.strip() else fallback
        except Exception:
            return fallback

    def extractVoterPhoneMetadata(
        self, dialog, voterNames: list[str]
    ) -> dict[str, str]:
        """Read phone numbers hidden in accessible metadata beside known voter names."""
        if not dialog or not voterNames:
            return {}

        script = r"""
        (panel, voterNames) => {
            const phonePattern = /\+?\d[\d\s().-]{5,}\d/g;
            const valuesFor = (root) => {
                const values = [];
                const add = (value) => {
                    const text = (value || '').replace(/\s+/g, ' ').trim();
                    if (text) values.push(text);
                };
                add(root?.getAttribute?.('aria-label'));
                add(root?.getAttribute?.('title'));
                add(root?.getAttribute?.('data-pre-plain-text'));
                for (const item of root?.querySelectorAll?.(
                    '[aria-label], [title], [data-pre-plain-text]'
                ) || []) {
                    add(item.getAttribute('aria-label'));
                    add(item.getAttribute('title'));
                    add(item.getAttribute('data-pre-plain-text'));
                }
                return values;
            };
            const result = {};
            const all = Array.from(panel.querySelectorAll('*'));
            for (const voterName of voterNames) {
                const matches = all.filter((element) =>
                    (element.textContent || '').trim() === voterName
                );
                for (const match of matches) {
                    const roots = [];
                    const row = match.closest(
                        '[role="listitem"], [role="row"], [data-testid*="contact" i], [data-testid*="cell" i]'
                    );
                    if (row) roots.push(row);
                    let node = match.parentElement;
                    for (let depth = 0; node && depth < 3; depth += 1) {
                        roots.push(node);
                        node = node.parentElement;
                    }
                    let found = '';
                    for (const root of roots) {
                        const values = valuesFor(root);
                        for (const value of values) {
                            const candidates = value.match(phonePattern) || [];
                            found = candidates.find((candidate) =>
                                (candidate.match(/\d/g) || []).length >= 7
                            ) || '';
                            if (found) break;
                        }
                        if (found) break;
                    }
                    if (found) {
                        result[voterName] = found;
                        break;
                    }
                }
            }
            return result;
        }
        """
        try:
            values = dialog.evaluate(script, voterNames)
        except Exception as exc:
            self.logger.debug("unable to inspect voter phone metadata: %s", exc)
            return {}

        phones: dict[str, str] = {}
        if not isinstance(values, dict):
            return phones
        for voterName, rawPhone in values.items():
            digits = "".join(
                character for character in str(rawPhone) if character.isdigit()
            )
            if len(digits) >= 7:
                phones[str(voterName).casefold()] = digits
        if phones:
            self.logger.debug(
                "hidden voter phone metadata found for: %s", sorted(phones)
            )
        return phones

    def expandAllVoters(self, panel, initialText: str = "") -> list[str]:
        """Return distinct panel snapshots while scrolling its virtual voter list."""
        dialogTexts = [initialText] if initialText.strip() else []
        expandedOption = ""

        for _ in range(20):
            try:
                buttons = panel.get_by_text(
                    re.compile(r"^See all(?:\s+\(\d+\s+more\))?$", re.IGNORECASE)
                )
                count = buttons.count()
                self.logger.value("poll voter expand controls", count)
                expandedControls = 0

                controls = []
                for i in range(count):
                    try:
                        btn = buttons.nth(i)
                        option = self.inferExpandOption(btn)
                        if option.casefold() == "yes":
                            controls.append((option, i, btn))
                    except Exception:
                        continue
                if controls:
                    self.logger.debug(
                        "poll voter expand options selected: %s",
                        [option for option, _, _ in controls],
                    )
                elif count:
                    self.logger.debug("no Yes voter expansion control found")

                for option, _, btn in controls:
                    try:
                        if btn.is_visible(timeout=500):
                            btn.scroll_into_view_if_needed(timeout=1000)
                            try:
                                btn.click(timeout=2000)
                            except Exception:
                                btn.click(timeout=2000, force=True)
                            expandedControls += 1
                            if option:
                                expandedOption = option
                                self.logger.debug(
                                    "expanding voter option: %s", expandedOption
                                )
                            panel.page.wait_for_timeout(750)
                            break
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
                        expandedText = self.labelExpandedSnapshot(
                            expandedText, expandedOption
                        )
                        if expandedText.strip() and expandedText not in dialogTexts:
                            dialogTexts.append(expandedText)
                    except Exception as exc:
                        self.logger.debug(
                            "unable to re-resolve expanded poll dialog: %s", exc
                        )
                    continue

                currentText = panel.inner_text(timeout=2000)
                currentText = self.labelExpandedSnapshot(currentText, expandedOption)
                if currentText.strip() and currentText not in dialogTexts:
                    dialogTexts.append(currentText)

                scrollResult = panel.evaluate(
                    """panel => {
                        const candidates = [panel, ...panel.querySelectorAll('*')];
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
                            const step = Math.max(scrollable.clientHeight * 0.8, 200);
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
                currentText = self.labelExpandedSnapshot(currentText, expandedOption)
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

    def inferExpandOption(self, control) -> str:
        """Identify the option section containing a See all control."""
        try:
            option = control.evaluate(
                r"""control => {
                    let node = control.parentElement;
                    while (node) {
                        const lines = (node.innerText || '')
                            .split('\n')
                            .map(line => line.trim())
                            .filter(Boolean);
                        const controlIndex = lines.findIndex(line =>
                            /^See all(?:\s+\(\d+\s+more\))?$/i.test(line)
                        );
                        if (controlIndex >= 0) {
                            for (let index = controlIndex - 1; index >= 0; index--) {
                                if (/^(Yes|No)$/i.test(lines[index])) {
                                    return lines[index];
                                }
                            }
                        }
                        node = node.parentElement;
                    }

                    const controlRect = control.getBoundingClientRect();
                    const headings = Array.from(document.querySelectorAll('*'))
                        .filter(candidate => /^(Yes|No)$/i.test(
                            (candidate.textContent || '').trim()
                        ))
                        .map(candidate => ({
                            text: (candidate.textContent || '').trim(),
                            rect: candidate.getBoundingClientRect(),
                        }))
                        .filter(candidate =>
                            candidate.rect.width > 0 &&
                            candidate.rect.height > 0 &&
                            candidate.rect.top < controlRect.top &&
                            Math.abs(candidate.rect.left - controlRect.left) < 500
                        )
                        .map(candidate => ({
                            ...candidate,
                            distance:
                                controlRect.top - candidate.rect.bottom +
                                Math.abs(controlRect.left - candidate.rect.left),
                        }))
                        .sort((left, right) => left.distance - right.distance);
                    return headings.length ? headings[0].text : '';
                }"""
            )
            return option.title() if option.casefold() in {"yes", "no"} else ""
        except Exception:
            return ""

    def labelExpandedSnapshot(self, text: str, option: str) -> str:
        """Restore an option heading omitted by WhatsApp's expanded list view."""
        if not option or not text.strip():
            return text
        lines = {line.strip().casefold() for line in text.splitlines()}
        if option.casefold() in lines:
            return text
        return f"{option}\n{text}"

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
