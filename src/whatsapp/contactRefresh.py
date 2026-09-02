"""Company-filtered WhatsApp contact refresh."""

from __future__ import annotations

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.contactDirectory import WhatsAppContactDirectory
from whatsapp.contactStore import ContactStore
from whatsapp.names import stripContactNameMarker
from whatsapp.selectors import DEFAULT_SELECTORS, WhatsAppSelectors


class FilteredWhatsAppContactDirectory(WhatsAppContactDirectory):
    """Refresh contacts returned by a WhatsApp New Chat search term."""

    def refresh(self, companySearch: str) -> int:
        searchText = companySearch.strip()
        if not searchText:
            raise ValueError("contact company search must not be empty")

        capturedBefore = self.store.count()
        if self.config.dryRun:
            self.logger.info(
                "dry run: skipping WhatsApp contact refresh for company %s; existing entries: %s",
                searchText,
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
                self.searchText = searchText
                if not self.searchContacts(page, searchText):
                    self.logger.info(
                        "contact refresh skipped: contact search unavailable for %s",
                        searchText,
                    )
                    return capturedBefore
                unresolvedNames = self.scrapeContactList(page)
                self.resolveContactProfiles(page, unresolvedNames)
            finally:
                browserContext.close()

        capturedAfter = self.store.count()
        self.logger.info(
            "contact phone database entries: %s (%s new) for company search %s",
            capturedAfter,
            max(0, capturedAfter - capturedBefore),
            searchText,
        )
        return capturedAfter

    def storedContactName(self, displayName: str) -> str:
        """Drop the HWFC contact-only surname marker before persistence."""
        return stripContactNameMarker(displayName)

    def extractContactPair(self, row: dict[str, str]) -> tuple[str, str] | None:
        pair = super().extractContactPair(row)
        if pair is None:
            return None
        displayName, phoneNumber = pair
        storedName = self.storedContactName(displayName)
        if not storedName:
            return None
        return storedName, phoneNumber

    def resolveContactProfiles(self, page, contactNames: list[str]) -> None:
        """Resolve full WhatsApp display names but persist names without the marker."""
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
                    storedName = self.storedContactName(contactName)
                    if storedName:
                        self.store.upsert(storedName, phoneNumber)
                        self.logger.debug(
                            "contact phone captured from profile: %s -> %s",
                            storedName,
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
        """Open the exact filtered New Chat result and inspect its contact info."""
        if not self.openNewChatPanel(page):
            return ""

        self.searchText = contactName
        if not self.searchContacts(page, contactName):
            self.logger.debug(
                "unable to search filtered contact profile: %s", contactName
            )
            return ""

        row = self.findFilteredContactRow(page, contactName)
        if row is None:
            self.logger.debug("filtered contact result not found: %s", contactName)
            return ""

        try:
            row.click(timeout=2000)
            self.logger.debug("opened filtered contact result: %s", contactName)
        except Exception as exc:
            self.logger.debug(
                "unable to open filtered contact result %s: %s", contactName, exc
            )
            return ""

        page.wait_for_timeout(700)
        if not self.openContactInfo(page, contactName):
            self.logger.debug("contact info header unavailable: %s", contactName)
            return ""
        page.wait_for_timeout(600)

        values = self.readContactInfoValues(page)
        self.logger.debug("contact info values for %s: %s", contactName, values[:12])
        for value in values:
            phoneNumber = self.extractPhoneNumber(value)
            if phoneNumber:
                return phoneNumber
        return ""

    def findFilteredContactRow(self, page, contactName: str):
        """Locate the exact contact result row within the New Chat drawer."""
        escapedName = contactName.replace('"', '\\"')
        selectors = (
            f'[data-testid="new-chat-drawer"] [data-testid="cell-frame-title"][title="{escapedName}"]',
            f'[data-testid="new-chat-drawer"] [title="{escapedName}"]',
        )
        for selector in selectors:
            try:
                titleNode = page.locator(selector).first
                if not titleNode.is_visible(timeout=500):
                    continue
                row = titleNode.locator(
                    'xpath=ancestor::*[@data-testid="cell-frame-container"][1]'
                )
                if row.count() and row.first.is_visible(timeout=500):
                    return row.first
                return titleNode
            except Exception:
                continue
        return None

    def searchContacts(self, page, searchText: str) -> bool:
        searchBox = self.findNewChatSearchBox(page)
        if searchBox is None:
            searchBox = self.findContactSearchBox(page)
        if searchBox is None:
            searchBox = self.findFallbackContactSearchBox(page)

        if searchBox is not None:
            try:
                self.enterSearchText(page, searchBox, searchText)
                self.logger.debug("contact company search entered: %s", searchText)
                return True
            except Exception as exc:
                self.logger.debug(
                    "unable to enter contact company search %s using locator: %s",
                    searchText,
                    exc,
                )

        if self.enterSearchTextIntoFocusedControl(page, searchText):
            self.logger.debug(
                "contact company search entered using focused control: %s", searchText
            )
            return True

        self.logVisibleEditableControls(page)
        self.logger.debug("contact search box unavailable")
        return False

    def findNewChatSearchBox(self, page):
        """Use the search field inside the New Chat drawer, never the main chat search."""
        selectors = (
            '[data-testid="new-chat-drawer"] input[aria-label="Search name, number or @username"]',
            '[data-testid="new-chat-drawer"] [aria-label="Search name, number or @username"]',
            '[data-testid="new-chat-drawer"] input[placeholder="Search name, number or @username"]',
            '[data-testid="new-chat-drawer"] [data-testid="chat-list-search-container"] input',
        )
        for selector in selectors:
            try:
                candidate = page.locator(selector).first
                if candidate.is_visible(timeout=300):
                    self.logger.debug(
                        "using new-chat contact search selector: %s", selector
                    )
                    return candidate
            except Exception:
                continue
        return None

    def findFallbackContactSearchBox(self, page):
        """Find an editable control inside the New Chat drawer."""
        selectors = (
            '[data-testid="new-chat-drawer"] input',
            '[data-testid="new-chat-drawer"] textarea',
            '[data-testid="new-chat-drawer"] [role="textbox"]',
            '[data-testid="new-chat-drawer"] [contenteditable="true"]',
            '[data-testid="new-chat-drawer"] [contenteditable="plaintext-only"]',
        )
        for selector in selectors:
            try:
                candidates = page.locator(selector)
                for index in range(candidates.count() - 1, -1, -1):
                    candidate = candidates.nth(index)
                    if not candidate.is_visible(timeout=250):
                        continue
                    self.logger.debug(
                        "using fallback contact search selector: %s index=%s",
                        selector,
                        index,
                    )
                    return candidate
            except Exception:
                continue
        return None

    def enterSearchText(self, page, searchBox, searchText: str) -> None:
        try:
            searchBox.fill(searchText, timeout=1500)
        except Exception:
            searchBox.focus(timeout=1000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(searchText, delay=30)
        page.wait_for_timeout(700)

    def enterSearchTextIntoFocusedControl(self, page, searchText: str) -> bool:
        """Use the focused New Chat search field when WhatsApp hides its attributes."""
        try:
            editable = page.evaluate(
                """() => {
                    const node = document.activeElement;
                    const drawer = document.querySelector('[data-testid="new-chat-drawer"]');
                    if (!node || !drawer || !drawer.contains(node)) return false;
                    const tag = (node.tagName || '').toLowerCase();
                    const role = (node.getAttribute && node.getAttribute('role')) || '';
                    const editable = (node.getAttribute && node.getAttribute('contenteditable')) || '';
                    return tag === 'input' || tag === 'textarea' || role === 'textbox' ||
                        editable === 'true' || editable === 'plaintext-only';
                }"""
            )
            if not editable:
                return False
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(searchText, delay=30)
            page.wait_for_timeout(700)
            return True
        except Exception as exc:
            self.logger.debug("focused contact search fallback failed: %s", exc)
            return False

    def readVisibleContactRows(self, page) -> list[dict[str, str]]:
        """Read only contact result rows inside the New Chat drawer."""
        try:
            rows = page.evaluate(
                """() => {
                    const drawer = document.querySelector('[data-testid="new-chat-drawer"]');
                    if (!drawer) return [];
                    const visible = node => {
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        return rect.width > 20 && rect.height > 20 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const nodes = Array.from(
                        drawer.querySelectorAll('[data-testid="cell-frame-container"]')
                    ).filter(visible);
                    return nodes.map(node => {
                        const text = (node.innerText || '').trim();
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
                        return {text, metadata: metadata.join(' ')};
                    }).filter(row => row.text);
                }"""
            )
            filteredRows = self.filterRowsForSearch(rows, self.searchText)
            self.logger.debug(
                "contact search result rows for %s: %s",
                self.searchText,
                [self.extractContactName(row) for row in filteredRows],
            )
            return filteredRows
        except Exception as exc:
            self.logger.debug("unable to inspect filtered contact rows: %s", exc)
            return []

    def filterRowsForSearch(
        self, rows: list[dict[str, str]], searchText: str
    ) -> list[dict[str, str]]:
        """Keep only result rows whose displayed contact name matches the search term."""
        searchKey = searchText.strip().casefold()
        if not searchKey:
            return []
        return [
            row for row in rows if searchKey in self.extractContactName(row).casefold()
        ]

    def scrollContactPanel(self, page) -> bool:
        """Scroll only within the New Chat drawer search results."""
        try:
            result = page.evaluate(
                """() => {
                    const drawer = document.querySelector('[data-testid="new-chat-drawer"]');
                    if (!drawer) return {moved: false};
                    const candidates = Array.from(drawer.querySelectorAll('*'))
                        .filter(node => {
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
                        before + Math.max(300, target.clientHeight * 0.8),
                        target.scrollHeight - target.clientHeight
                    );
                    return {moved: target.scrollTop > before};
                }"""
            )
            return bool(result and result.get("moved"))
        except Exception as exc:
            self.logger.debug("unable to scroll filtered contact results: %s", exc)
            return False

    def logVisibleEditableControls(self, page) -> None:
        try:
            controls = page.evaluate(
                """() => Array.from(document.querySelectorAll(
                    '[data-testid="new-chat-drawer"] input, '
                    + '[data-testid="new-chat-drawer"] textarea, '
                    + '[data-testid="new-chat-drawer"] [role="textbox"], '
                    + '[data-testid="new-chat-drawer"] [contenteditable]'
                )).filter(node => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 &&
                        style.display !== 'none' && style.visibility !== 'hidden';
                }).map(node => ({
                    tag: (node.tagName || '').toLowerCase(),
                    role: node.getAttribute('role') || '',
                    contenteditable: node.getAttribute('contenteditable') || '',
                    placeholder: node.getAttribute('placeholder') || '',
                    ariaLabel: node.getAttribute('aria-label') || '',
                    dataTab: node.getAttribute('data-tab') || '',
                    x: Math.round(node.getBoundingClientRect().x),
                    y: Math.round(node.getBoundingClientRect().y)
                })).slice(0, 20)"""
            )
            self.logger.debug("visible new-chat editable controls: %s", controls)
        except Exception as exc:
            self.logger.debug("unable to inspect editable controls: %s", exc)


def refreshContacts(
    config: RuntimeConfig,
    companySearch: str,
    selectors: WhatsAppSelectors | None = None,
) -> int:
    """Refresh the private contact database using a company search term."""
    selectedSelectors = selectors or DEFAULT_SELECTORS
    store = ContactStore(config.outputDir / "contacts.sqlite3").open()
    logger = getLogger(level=config.logLevel)
    try:
        logger.value("contact company search", companySearch)
        return FilteredWhatsAppContactDirectory(
            config=config,
            selectors=selectedSelectors,
            store=store,
        ).refresh(companySearch)
    finally:
        store.close()
