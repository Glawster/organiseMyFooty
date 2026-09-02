"""Best-effort extraction of WhatsApp contact names and phone numbers."""

from __future__ import annotations

import re

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.contactStore import ContactStore
from whatsapp.navigation import WhatsAppNavigation
from whatsapp.selectors import WhatsAppSelectors


class WhatsAppContactDirectory:
    """Refresh a private contact lookup from the authenticated WhatsApp Web UI."""

    def __init__(
        self,
        config: RuntimeConfig,
        selectors: WhatsAppSelectors,
        store: ContactStore,
    ):
        self.config = config
        self.selectors = selectors
        self.store = store
        self.logger = getLogger(level=config.logLevel)
        self.navigation = WhatsAppNavigation(config=config, selectors=selectors)

    def refresh(self) -> int:
        capturedBefore = self.store.count()
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping WhatsApp contact refresh; existing entries: %s",
                capturedBefore,
            )
            return capturedBefore

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browserContext = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.userDataDir),
                headless=self.config.headless,
                channel=self.config.browserChannel,
                viewport={"width": 1440, "height": 1100},
            )
            try:
                page = browserContext.new_page()
                page.goto(self.selectors.webUrl)
                self.navigation.waitForWhatsAppReady(page)
                if not self.openNewChatPanel(page):
                    self.logger.info(
                        "contact refresh skipped: new-chat panel unavailable"
                    )
                    return capturedBefore
                unresolvedNames = self.scrapeContactList(page)
                self.resolveContactProfiles(page, unresolvedNames)
            finally:
                browserContext.close()

        capturedAfter = self.store.count()
        self.logger.info(
            "contact phone database entries: %s (%s new)",
            capturedAfter,
            max(0, capturedAfter - capturedBefore),
        )
        return capturedAfter

    def openNewChatPanel(self, page) -> bool:
        selectors = (
            '[data-testid="start-new-chat"]',
            '[aria-label="New chat"]',
            '[title="New chat"]',
            'button:has([data-icon="new-chat-outline"])',
            '[data-icon="new-chat-outline"]',
        )
        for selector in selectors:
            try:
                control = page.locator(selector).first
                if not control.is_visible(timeout=500):
                    continue
                control.click(timeout=2000)
                page.wait_for_timeout(800)
                self.logger.debug("opened new-chat panel using selector: %s", selector)
                return True
            except Exception:
                continue
        self.logger.debug("new-chat panel controls were not found")
        return False

    def scrapeContactList(self, page) -> list[str]:
        seenNames: set[str] = set()
        unresolvedNames: list[str] = []
        stalledPasses = 0

        for passIndex in range(80):
            rows = self.readVisibleContactRows(page)
            self.logger.debug(
                "contact list pass %s visible candidate rows: %s",
                passIndex + 1,
                len(rows),
            )
            newNames = 0
            for row in rows:
                displayName = self.extractContactName(row)
                if not displayName:
                    continue
                nameKey = displayName.casefold()
                if nameKey in seenNames:
                    continue
                seenNames.add(nameKey)
                newNames += 1

                pair = self.extractContactPair(row)
                if pair is not None:
                    name, phoneNumber = pair
                    self.store.upsert(name, phoneNumber)
                    self.logger.debug(
                        "contact phone captured from list metadata: %s -> %s",
                        name,
                        self.maskPhoneForLog(phoneNumber),
                    )
                else:
                    unresolvedNames.append(displayName)
                    self.logger.debug(
                        "contact has no phone in list metadata: %s", displayName
                    )

            moved = self.scrollContactPanel(page)
            self.logger.debug("contact list scroll moved: %s", moved)
            if newNames == 0 and not moved:
                stalledPasses += 1
            else:
                stalledPasses = 0
            if stalledPasses >= 2:
                break
            page.wait_for_timeout(350)

        self.logger.debug(
            "contact names discovered: %s; requiring profile lookup: %s",
            len(seenNames),
            len(unresolvedNames),
        )
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        return unresolvedNames

    def resolveContactProfiles(self, page, contactNames: list[str]) -> None:
        """Resolve saved contacts whose list row does not expose their number."""
        for index, contactName in enumerate(contactNames, start=1):
            try:
                self.logger.debug(
                    "contact profile lookup %s/%s: %s",
                    index,
                    len(contactNames),
                    contactName,
                )
                phoneNumber = self.resolveContactProfile(page, contactName)
                if phoneNumber:
                    self.store.upsert(contactName, phoneNumber)
                    self.logger.debug(
                        "contact phone captured from profile: %s -> %s",
                        contactName,
                        self.maskPhoneForLog(phoneNumber),
                    )
                else:
                    self.logger.debug(
                        "contact profile exposed no phone number: %s", contactName
                    )
            except Exception as exc:
                self.logger.debug(
                    "unable to resolve contact profile %s: %s", contactName, exc
                )
            finally:
                self.dismissPanels(page)

    def resolveContactProfile(self, page, contactName: str) -> str:
        if not self.openNewChatPanel(page):
            return ""

        searchBox = self.findContactSearchBox(page)
        if searchBox is not None:
            try:
                searchBox.click(timeout=1000)
                try:
                    searchBox.fill("")
                except Exception:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                searchBox.type(contactName, delay=20)
                page.wait_for_timeout(500)
            except Exception as exc:
                self.logger.debug(
                    "unable to search contact %s in new-chat panel: %s",
                    contactName,
                    exc,
                )

        matches = page.get_by_text(contactName, exact=True)
        clicked = False
        for matchIndex in range(matches.count() - 1, -1, -1):
            candidate = matches.nth(matchIndex)
            try:
                if not candidate.is_visible(timeout=300):
                    continue
                candidate.click(timeout=1500)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            return ""

        page.wait_for_timeout(600)
        if not self.openContactInfo(page, contactName):
            return ""
        page.wait_for_timeout(500)

        values = self.readContactInfoValues(page)
        self.logger.debug("contact info values for %s: %s", contactName, values[:12])
        for value in values:
            phoneNumber = self.extractPhoneNumber(value)
            if phoneNumber:
                return phoneNumber
        return ""

    def findContactSearchBox(self, page):
        selectors = (
            '[placeholder*="Search name or number" i]',
            '[aria-label*="Search name or number" i]',
            '[placeholder*="Search contacts" i]',
            '[aria-label*="Search contacts" i]',
            '[contenteditable="true"][role="textbox"]',
        )
        for selector in selectors:
            try:
                candidates = page.locator(selector)
                for index in range(candidates.count() - 1, -1, -1):
                    candidate = candidates.nth(index)
                    if candidate.is_visible(timeout=300):
                        return candidate
            except Exception:
                continue
        return None

    def openContactInfo(self, page, contactName: str) -> bool:
        selectors = (
            f'header [title="{contactName}"]',
            f'header span[title="{contactName}"]',
            'header [data-testid="conversation-info-header"]',
            "header",
        )
        for selector in selectors:
            try:
                candidate = page.locator(selector).first
                if not candidate.is_visible(timeout=500):
                    continue
                candidate.click(timeout=1500)
                return True
            except Exception:
                continue
        return False

    def readContactInfoValues(self, page) -> list[str]:
        try:
            result = page.evaluate(
                """() => {
                    const values = [];
                    const seen = new Set();
                    const nodes = Array.from(document.querySelectorAll('*'));
                    for (const node of nodes) {
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        if (rect.width <= 0 || rect.height <= 0 ||
                            style.visibility === 'hidden' || style.display === 'none') {
                            continue;
                        }
                        if (rect.left < window.innerWidth * 0.45) continue;
                        const candidates = [node.innerText || ''];
                        for (const name of [
                            'data-id', 'data-lid', 'data-testid', 'aria-label',
                            'title', 'href', 'id'
                        ]) {
                            const value = node.getAttribute && node.getAttribute(name);
                            if (value) candidates.push(value);
                        }
                        for (const value of candidates) {
                            const clean = String(value || '').trim();
                            if (!clean || seen.has(clean)) continue;
                            seen.add(clean);
                            values.push(clean);
                        }
                    }
                    return values;
                }"""
            )
            return [str(value) for value in result]
        except Exception as exc:
            self.logger.debug("unable to inspect contact info panel: %s", exc)
            return []

    def dismissPanels(self, page) -> None:
        for _ in range(3):
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
            except Exception:
                break

    def readVisibleContactRows(self, page) -> list[dict[str, str]]:
        try:
            rows = page.evaluate(
                """() => {
                    const visible = node => {
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        return rect.width > 20 && rect.height > 20 &&
                            rect.left < window.innerWidth * 0.55 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const selectors = [
                        '[role="row"]',
                        '[role="listitem"]',
                        '[data-testid*="cell-frame-container"]',
                        '[data-testid*="contact"]',
                        '[tabindex="-1"]',
                    ];
                    const nodes = Array.from(document.querySelectorAll(selectors.join(',')))
                        .filter(visible);
                    const unique = [];
                    const seen = new Set();
                    for (const node of nodes) {
                        const text = (node.innerText || '').trim();
                        if (!text || seen.has(text)) continue;
                        seen.add(text);
                        const metadata = [];
                        for (const candidate of [node, ...node.querySelectorAll('*')]) {
                            for (const name of [
                                'data-id','data-lid','data-testid','aria-label',
                                'title','href','id'
                            ]) {
                                const value = candidate.getAttribute && candidate.getAttribute(name);
                                if (value) metadata.push(`${name}=${value}`);
                            }
                        }
                        unique.push({text, metadata: metadata.join(' ')});
                    }
                    return unique;
                }"""
            )
            if rows:
                self.logger.debug("contact row sample: %s", rows[:3])
            return rows
        except Exception as exc:
            self.logger.debug("unable to inspect contact rows: %s", exc)
            return []

    def scrollContactPanel(self, page) -> bool:
        try:
            result = page.evaluate(
                """() => {
                    const candidates = Array.from(document.querySelectorAll('*'))
                        .filter(node => {
                            const rect = node.getBoundingClientRect();
                            if (rect.width < 250 || rect.height < 250 ||
                                rect.left > window.innerWidth * 0.55) return false;
                            const style = window.getComputedStyle(node);
                            return node.scrollHeight > node.clientHeight + 20 &&
                                /(auto|scroll)/.test(`${style.overflow} ${style.overflowY}`);
                        })
                        .sort((a, b) =>
                            (b.scrollHeight - b.clientHeight) -
                            (a.scrollHeight - a.clientHeight)
                        );
                    if (!candidates.length) return {moved: false};
                    const target = candidates[0];
                    const before = target.scrollTop;
                    target.scrollTop = Math.min(
                        before + Math.max(400, target.clientHeight * 0.8),
                        target.scrollHeight - target.clientHeight
                    );
                    return {moved: target.scrollTop > before};
                }"""
            )
            return bool(result and result.get("moved"))
        except Exception as exc:
            self.logger.debug("unable to scroll contact list: %s", exc)
            return False

    def extractContactName(self, row: dict[str, str]) -> str:
        text = str(row.get("text", "") or "").strip()
        ignoredLines = {
            "new group",
            "new contact",
            "new community",
            "contacts on whatsapp",
            "frequently contacted",
        }
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate or candidate.casefold() in ignoredLines:
                continue
            if self.extractPhoneNumber(candidate):
                continue
            if len(candidate) > 100:
                continue
            return candidate
        return ""

    def extractContactPair(self, row: dict[str, str]) -> tuple[str, str] | None:
        displayName = self.extractContactName(row)
        if not displayName:
            return None
        text = str(row.get("text", "") or "").strip()
        metadata = str(row.get("metadata", "") or "")
        phoneNumber = self.extractPhoneNumber(f"{text} {metadata}")
        if not phoneNumber:
            return None
        return displayName, phoneNumber

    def extractPhoneNumber(self, value: str) -> str:
        compact = re.sub(r"[\s().-]", "", value)
        explicit = re.search(r"(?<!\d)(?:\+44|44|0)7\d{9}(?!\d)", compact)
        if explicit:
            return self.normalisePhoneNumber(explicit.group(0))

        jid = re.search(r"(?<!\d)(44\d{10})(?:@|%40)(?:c\.us|s\.whatsapp\.net)", value)
        if jid:
            return self.normalisePhoneNumber(jid.group(1))
        return ""

    def normalisePhoneNumber(self, value: str) -> str:
        digits = "".join(character for character in value if character.isdigit())
        if digits.startswith("44"):
            return "0" + digits[2:]
        return digits

    def maskPhoneForLog(self, value: str) -> str:
        digits = self.normalisePhoneNumber(value)
        if len(digits) < 5:
            return "..."
        return f"{digits[:2]}...{digits[-3:]}"
