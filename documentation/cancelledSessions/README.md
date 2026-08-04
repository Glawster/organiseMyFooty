# Cancelled sessions

A WhatsApp session poll is cancelled when its title contains `(cancelled)`.
Matching is case-insensitive, accepts whitespace around the word, and works
wherever the marker appears in the title. Similar unparenthesised wording does
not cancel a session.

The attendance store preserves each source's captured title unchanged and
records its status separately. Logical session matching ignores the marker, so
adding or removing it updates the existing session rather than creating a new
one.

If any retained source observation says the session is cancelled, the logical
session is cancelled. It returns to `scheduled` only after every retained
source reports it as scheduled. This prevents one source from silently erasing
another source's cancellation.

Cancelled sessions remain available through session metadata queries, but are
excluded from effective attendance queries, member totals, report columns,
session totals and social-media summaries. Captured attendance observations
remain auditable and become effective again if the session is restored.
