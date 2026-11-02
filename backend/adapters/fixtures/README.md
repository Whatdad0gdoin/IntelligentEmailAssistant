# Fixture mailbox

Synthetic messages that stand in for a real mail server while the source
adapter is fixture-backed. Nothing here is a real person's email.

This directory occupies the position an IMAP host would occupy in the
architecture. It is a *source* the app reads from, never a place the app writes
to, so it does not conflict with NFR-03 ("no email body persisted"): the
constraint is on what the application stores, not on where mail comes from.

Coverage is deliberate. Between them the first six messages exercise every
preprocessing branch in `orchestrator/preprocess.py`, and the seventh carries
attachments:

| File | Category it should attract | Exercises |
|---|---|---|
| 01 | Work | quoted reply chain (`On ... wrote:`), `>` quoting, threading headers |
| 02 | Studies | plain text, bulk sender, legal footer |
| 03 | Personal | short informal text, no signature |
| 04 | Promotions | HTML-only body, unsubscribe footer |
| 05 | Studies | sign-off block plus title signature |
| 06 | Work | `--` signature delimiter, confidentiality notice |
| 07 | Work | a PDF invoice, a CSV schedule and a PNG attached, listed in the inbox and opened with View or Save; rebuilt byte for byte by `tools/build_attachment_fixture.py` |

`X-Unread` stands in for the IMAP Seen flag, which is per-mailbox state rather
than a header.
