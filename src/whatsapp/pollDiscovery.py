from __future__ import annotations

from attendanceConfig import RuntimeConfig
from organiseMyProjects.logUtils import getLogger  # type: ignore[import]
from whatsapp.parsing import PollTextParser
from whatsapp.selectors import WhatsAppSelectors

logger = getLogger()
MAX_SOURCE_KEY_LENGTH = 300
MAX_DEBUG_TEXT_LENGTH = 240
MAX_DOM_DEBUG_ANCESTOR_DEPTH = 6


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

    def pollHasCancellationReaction(self, locator) -> bool | None:
        """Return reaction state, or ``None`` when WhatsApp cannot be inspected."""
        participantName = (self.config.cancellationEmojiName or "").strip()
        if not participantName:
            return False

        # The visible reaction pill can sit just outside WhatsApp's inner message
        # node. Inspect bounded ancestors and reaction-related subtrees rather than
        # requiring the emoji and participant name on the same DOM element.
        script = r"""
        (node, participantName) => {
            const normalise = (value) => (value || "").replace(/\s+/g, " ").trim();
            const name = participantName.toLocaleLowerCase();
            const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const participantPattern = new RegExp(
                `(^|[^\\p{L}\\p{N}])${escapedName}($|[^\\p{L}\\p{N}])`,
                'u'
            );
            const valuesFor = (root) => {
                const values = [];
                const seen = new Set();
                const add = (value) => {
                    const text = normalise(value);
                    if (!text || seen.has(text)) return;
                    seen.add(text);
                    values.push(text);
                };
                add(root?.innerText || root?.textContent || "");
                add(root?.getAttribute?.('aria-label'));
                add(root?.getAttribute?.('title'));
                add(root?.getAttribute?.('data-testid'));
                for (const element of root?.querySelectorAll?.(
                    '[aria-label], [title], [data-testid], span, div, button'
                ) || []) {
                    const ariaLabel = element.getAttribute('aria-label') || '';
                    const title = element.getAttribute('title') || '';
                    const testId = element.getAttribute('data-testid') || '';
                    const text = normalise(element.innerText || element.textContent || '');
                    if (
                        /react/i.test(testId)
                        || ariaLabel.includes('😢')
                        || title.includes('😢')
                        || text.includes('😢')
                        || participantPattern.test(ariaLabel.toLocaleLowerCase())
                        || participantPattern.test(title.toLocaleLowerCase())
                    ) {
                        add(ariaLabel);
                        add(title);
                        add(testId);
                        add(text);
                    }
                }
                return values;
            };

            const roots = [];
            const seenRoots = new Set();
            const addRoot = (root) => {
                if (root && !seenRoots.has(root)) {
                    seenRoots.add(root);
                    roots.push(root);
                }
            };
            addRoot(node.closest('[data-id]'));
            addRoot(node.closest('[data-testid*="msg"]'));
            let current = node;
            for (let depth = 0; current && depth < 6; depth += 1) {
                addRoot(current);
                current = current.parentElement;
            }

            const candidates = [];
            for (const root of roots) {
                const rootValues = valuesFor(root);
                const rootText = rootValues.join(' | ');
                const hasEmoji = rootText.includes('😢');
                const hasParticipant = participantPattern.test(rootText.toLocaleLowerCase());
                if (hasEmoji || hasParticipant) {
                    candidates.push(...rootValues);
                }
                if (hasEmoji && hasParticipant) {
                    return {
                        matched: true,
                        candidates: Array.from(new Set(candidates)).slice(0, 12),
                    };
                }

                for (const element of root.querySelectorAll(
                    '[data-testid*="react" i], [aria-label*="😢"], [title*="😢"]'
                )) {
                    let reactionRoot = element;
                    for (let depth = 0; reactionRoot && depth < 4; depth += 1) {
                        const values = valuesFor(reactionRoot);
                        const combined = values.join(' | ');
                        candidates.push(...values);
                        if (
                            combined.includes('😢')
                            && participantPattern.test(combined.toLocaleLowerCase())
                        ) {
                            return {
                                matched: true,
                                candidates: Array.from(new Set(candidates)).slice(0, 12),
                            };
                        }
                        reactionRoot = reactionRoot.parentElement;
                    }
                }
            }

            return {
                matched: false,
                candidates: Array.from(new Set(candidates)).slice(0, 12),
            };
        }
        """
        try:
            result = locator.evaluate(script, participantName)
            if isinstance(result, dict):
                candidates = result.get("candidates") or []
                self.logger.debug(
                    "reaction candidates participant=%s matched=%s values=%s",
                    participantName,
                    bool(result.get("matched")),
                    candidates,
                )
                return bool(result.get("matched"))
            return bool(result)
        except Exception as exc:
            self.logger.warning("Unable to inspect poll reactions: %s", exc)
            return None

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

            const collectDateTexts = (root) => {
                const values = [];
                const seen = new Set();
                const add = (value) => {
                    const text = (value || "").trim();
                    if (!isDateText(text) || seen.has(text)) {
                        return;
                    }
                    seen.add(text);
                    values.push(text);
                };

                add(root?.innerText || root?.textContent || "");
                for (const el of root?.querySelectorAll?.("span, div") || []) {
                    add(el.innerText || el.textContent || "");
                }
                return values;
            };

            const collectDateAttributes = (root) => {
                const values = [];
                const seen = new Set();
                const add = (value) => {
                    const text = (value || "").trim();
                    const matches = text.match(
                        /\b\d{1,2}\/\d{1,2}\/(?:\d{2}|\d{4})\b/g
                    ) || [];
                    for (const match of matches) {
                        if (!seen.has(match)) {
                            seen.add(match);
                            values.push(match);
                        }
                    }
                };
                for (const el of root?.querySelectorAll?.(
                    '[data-pre-plain-text], [aria-label], [title]'
                ) || []) {
                    add(el.getAttribute('data-pre-plain-text'));
                    add(el.getAttribute('aria-label'));
                    add(el.getAttribute('title'));
                }
                return values;
            };

            const textPreview = (el) => (el?.innerText || el?.textContent || "")
                .replace(/\s+/g, " ")
                .trim()
                .slice(0, 120);

            const collectPreviousSiblingDates = (root) => {
                const dates = [];
                let sibling = root?.previousElementSibling;
                while (sibling && dates.length < 4) {
                    const siblingDates = collectDateTexts(sibling);
                    if (siblingDates.length) {
                        dates.push(...siblingDates);
                        break;
                    }
                    sibling = sibling.previousElementSibling;
                }
                return dates;
            };

            const primaryNode = node.closest('[data-id]')
                || node.closest('.focusable-list-item')
                || node.closest('[data-testid*="msg"]')
                || node.closest('[role="row"]')
                || node;
            const candidateNodes = [];
            const seenNodes = new Set();
            let candidate = primaryNode;
            while (candidate && candidateNodes.length < 8) {
                if (!seenNodes.has(candidate)) {
                    seenNodes.add(candidate);
                    candidateNodes.push(candidate);
                }
                candidate = candidate.parentElement;
            }
            const matchedCandidate = candidateNodes
                .map((candidateNode, index) => ({
                    candidateNode,
                    index,
                    dates: collectPreviousSiblingDates(candidateNode),
                }))
                .find((item) => item.dates.length);
            const messageNode = matchedCandidate?.candidateNode || primaryNode;
            const previousSiblingDates = matchedCandidate?.dates || [];
            const parentTagNames = [];
            let parent = messageNode.parentElement;
            while (parent && parentTagNames.length < 6) {
                parentTagNames.push(parent.tagName);
                parent = parent.parentElement;
            }
            const messageRect = primaryNode.getBoundingClientRect();

            const visibleDateHeaders = Array.from(document.querySelectorAll("span, div"))
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
                        height: rect.height,
                        width: rect.width,
                    };
                })
                .filter(Boolean)
                .filter((item) => item.height > 0 && item.width > 0)
                .filter((item) => item.bottom <= messageRect.top + 5)
                .sort((a, b) => b.bottom - a.bottom)
                .filter((item, index, items) => {
                    if (index === 0) {
                        return true;
                    }
                    const previous = items[index - 1];
                    return item.text !== previous.text
                        || Math.abs(item.bottom - previous.bottom) > 2;
                });

            const chatDateHeaders = Array.from(document.querySelectorAll(
                '[data-testid*="date" i], [role="separator"], time'
            ))
                .flatMap((el) => collectDateTexts(el).map((text) => ({
                    text,
                    rect: el.getBoundingClientRect(),
                })))
                .filter((item) => item.rect.bottom <= messageRect.top + 5)
                .sort((a, b) => b.rect.bottom - a.rect.bottom)
                .map((item) => item.text);

            const attributedDates = collectDateAttributes(document)
                .map((text) => ({ text, element: Array.from(document.querySelectorAll(
                    '[data-pre-plain-text], [aria-label], [title]'
                )).find((el) => [
                    el.getAttribute('data-pre-plain-text'),
                    el.getAttribute('aria-label'),
                    el.getAttribute('title'),
                ].some((value) => (value || '').includes(text))) }))
                .filter((item) => item.element)
                .map((item) => ({
                    text: item.text,
                    rect: item.element.getBoundingClientRect(),
                }))
                .filter((item) => item.rect.bottom <= messageRect.top + 5)
                .sort((a, b) => b.rect.bottom - a.rect.bottom)
                .map((item) => item.text);

            return {
                messageNodeDiagnostics: {
                    tagName: messageNode.tagName,
                    dataTestid: messageNode.getAttribute("data-testid"),
                    dataId: messageNode.getAttribute("data-id"),
                    parentTagNames,
                    ancestorIndex: matchedCandidate?.index || 0,
                    previousSiblingTagName: messageNode.previousElementSibling?.tagName || "",
                    previousSiblingText: textPreview(messageNode.previousElementSibling),
                    visualLookupTop: messageRect.top,
                },
                visibleDateHeaders: visibleDateHeaders.map((item) => item.text),
                chatDateHeaders,
                attributedDates,
                previousSiblingDates,
            };
        }
        """

        try:
            return self.selectDomFallbackDate(locator.evaluate(script, timeout=1000))
        except Exception as exc:
            self.logger.warning("Unable to derive poll date: %s", exc)
            return ""

    def selectDomFallbackDate(self, payload) -> str:
        if isinstance(payload, str):
            return payload

        if not isinstance(payload, dict):
            return ""

        previousSiblingDates = payload.get("previousSiblingDates") or []
        visibleDateHeaders = (
            payload.get("visibleDateHeaders")
            or payload.get("precedingVisibleDates")
            or []
        )
        chatDateHeaders = payload.get("chatDateHeaders") or []
        attributedDates = payload.get("attributedDates") or []
        messageNodeDiagnostics = payload.get("messageNodeDiagnostics") or {}
        if messageNodeDiagnostics:
            self.logger.debug(
                "date lookup node tag=%s data-testid=%s data-id=%s ancestor index=%s visual top=%s parent tags=%s previous sibling tag=%s previous sibling text=%s",
                messageNodeDiagnostics.get("tagName"),
                messageNodeDiagnostics.get("dataTestid"),
                messageNodeDiagnostics.get("dataId"),
                messageNodeDiagnostics.get("ancestorIndex"),
                messageNodeDiagnostics.get("visualLookupTop"),
                messageNodeDiagnostics.get("parentTagNames"),
                messageNodeDiagnostics.get("previousSiblingTagName"),
                messageNodeDiagnostics.get("previousSiblingText"),
            )
        self.logger.debug(
            "date candidates visible headers=%s chat headers=%s attributes=%s previous sibling dates=%s",
            visibleDateHeaders[:5],
            chatDateHeaders[:5],
            attributedDates[:5],
            previousSiblingDates,
        )

        # Prefer date evidence local to the poll message. The broad visual scan can
        # contain unrelated date-like message text from WhatsApp's virtualised DOM.
        for key, values in (
            ("previousSiblingDates", previousSiblingDates),
            ("chatDateHeaders", chatDateHeaders),
            ("attributedDates", attributedDates),
            ("visibleDateHeaders", visibleDateHeaders),
        ):
            for value in values:
                text = str(value or "").strip()
                if text:
                    self.logger.debug(
                        "selected date candidate %s from %s",
                        text,
                        key,
                    )
                    return text
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

    def extractStableMessageKey(self, locator) -> str:
        """Return WhatsApp's message data-id, excluding generic DOM test ids."""
        try:
            value = locator.locator(
                "xpath=ancestor-or-self::*[@data-id][1]"
            ).first.get_attribute("data-id", timeout=1000)
            return str(value or "")
        except Exception:
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
        except Exception as exc:
            self.logger.debug("Unable to read poll source text from locator: %s", exc)

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
        """Return nearby DOM text/attributes for a poll button when normal extraction fails.

        This runs a small script in the browser via Playwright's ``evaluate()`` so we can
        inspect the live WhatsApp DOM around a poll button. The script walks up through the
        nearest message container and a bounded number of ancestors, collecting unique text
        plus stable attributes like aria-label, title, data-testid, and data-id. A Python
        placeholder replacement injects the maximum ancestor depth into the browser-side
        script while keeping the traversal limit explicit in this module.
        """
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
            for (let depth = 0; current && depth < __MAX_DOM_DEBUG_ANCESTOR_DEPTH__; depth += 1) {
                targets.push(current);
                current = current.parentElement;
            }

            for (const el of targets) {
                add(el.innerText || el.textContent || "");
                add(el.getAttribute("aria-label"));
                add(el.getAttribute("title"));
                add(el.getAttribute("data-testid"));
                add(el.getAttribute("data-id"));
            }

            return collected.join("\n");
        }
        """
        script = script.replace(
            "__MAX_DOM_DEBUG_ANCESTOR_DEPTH__",
            str(MAX_DOM_DEBUG_ANCESTOR_DEPTH),
        )

        try:
            return str(locator.evaluate(script, timeout=1000) or "")
        except Exception:
            return ""

    def logSkippedPollCandidate(self, locator) -> None:
        """Log a compact DOM snapshot when a visible poll candidate has no usable source text."""
        debugText = self.extractPollDomDebugText(locator)
        if debugText:
            self.logger.info(
                "skipping poll candidate missing usable source text: %s",
                debugText[:MAX_DEBUG_TEXT_LENGTH],
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
