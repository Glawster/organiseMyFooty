# Cancelled sessions

A session is cancelled when its WhatsApp poll has the crying-face emoji `😢`
(Unicode code point U+1F622) as a message reaction. The identity of the person
who added the reaction is not significant. Other emojis do not cancel a session.

No CLI configuration is required. The former `--emoji NAME` option and its
saved `emojiName` state value have been removed. Crying-face cancellation is
always enabled for session polls.

The attendance store preserves the poll's original title and captured votes
while recording its cancelled status separately. Cancelled sessions remain
queryable for audit but are excluded from effective attendance, member totals,
session totals and social-media summaries. Removing the `😢` reaction restores
the session on the next successful scan.

Because reactions can change after a poll has been captured, cancellation
recognition must revisit captured polls in the selected month so reaction
additions and removals can be reconciled.

WhatsApp Web's accessible reaction metadata can change. The current live DOM
exposes the reaction bubble as values such as `reaction 😢. View reactions`,
which is sufficient to establish cancellation without opening the participant
list. If reaction inspection itself fails, the application preserves the
previous stored state rather than inferring cancellation or restoration.
Captured voter observations remain stored when a poll is cancelled; only their
contribution to effective attendance is suppressed.
