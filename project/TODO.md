# TODO

- [ ] Handle cancelled WhatsApp sessions marked with "(cancelled)" in the title
  - Preserve the original session title
  - Match "(cancelled)" case-insensitively
  - Record the session as cancelled in output
  - Skip cancelled sessions from attendance processing

- [ ] Explore a Qt interface for the app
  - Review whether a Qt front end fits the current export workflow
  - Keep business logic reusable outside the UI
  - Identify the smallest UI surface worth building first