---
status: approved
issue: 26
author: olafkfreund
---

# Intent: Keep errors visible and make the empty state honest

## Problem

The panel's status line is the search box's placeholder text
(`PipelinesPanel.qml:353-362`). It carries four different messages:
- an error;
- the GitLab rate-limit pause;
- discovery progress ("Discovering projects… N found");
- the hint "Search projects…".

That causes two problems:

1. **Errors disappear.** The placeholder is hidden as soon as the search box
   has text (`visible: searchField.text.length === 0`). While the box only
   has focus, it shows "Search projects…" in place of the error. A user who
   searches because projects seem to be missing never sees the reason, for
   example "not logged in", a permission error or the helper failing.
2. **The empty list says the wrong thing.** Whenever there are no rows, the
   list shows the fixed text "No matching projects or pipelines"
   (`PipelinesPanel.qml:429-435`). That includes:
   - while the first project page is still loading;
   - after login fails (`polling.auth`, `errorType` `auth` or `setup`);
   - when the account simply has no projects.

   In every one of these cases the user is told nothing matches.

## Proposed outcome

- An error or rate-limit pause has a place of its own that stays visible
  while the user searches.
- When the list is empty, it shows the first of these that applies:
  1. **Error:** the error text, with advice that depends on the cause:
     - **Login error** (`errorType` `auth`): "Run `glab auth login`, then
       press Esc and `r`."
     - **Setup error** (`setup`, for example invalid helper data): keep the
       real message and point to the shell log. Login advice would be
       wrong here.
     - **Project list refused** (`catalogueError`, a permission error):
       "Check the token's access, then press `R` to reload projects." Only
       `R` clears this error (`Polling.manual(..., catalogue)`,
       `Polling.js:51-54`).
  2. **Paused:** the rate-limit pause, when there is no error.
  3. **Loading:** discovery has not finished. If a filter is set, the text
     says the results are not final yet ("Still discovering… no matches so
     far").
  4. **No projects:** discovery finished and found none.
  5. **No matches:** a filter is set and nothing matches it.
- When there is both an error and a pause, both are shown.
- When nothing is wrong, the search box keeps its current text: "Search
  projects…", "Discovering projects… N found" and "Activity checked N/M".
  The existing `polling.error || polling.catalogueError` fallback
  (`PipelinesPanel.qml:176`) stays.
- The smoke test covers:
  - each empty state above;
  - discovery finished while activity checks are still running;
  - a pause without an error;
  - an error staying visible while the search box has text or focus.

## Affected users and systems

- Files: `PipelinesPanel.qml` and `tests/qml-smoke.py`. The polling, model
  and helper code do not change.
- Everyone using the panel; most of all, new users who are not logged in to
  `glab` yet.
- Deployed later through the usual chain: release, nixarchy pin bump,
  nixos_config lock bump.

## Constraints

- Reuse the existing state: `error`, `cooldownText`, `discoveryComplete`,
  `repos`, `filterText` and `polling.auth`. Do not add new polling state.
- Colours come from `Commons.Color`, and sizes scale with the zoom (`zf`,
  #22).
- Error text stays plain text (`Text.PlainText`), because it can contain
  server strings.
- The footer's key hints do not change. #29 owns new keys.

## Open questions

1. **Where does the error go while searching?** Decided: the strip. I recommended a one-line error
   strip between the search box and the list, shown only when there is an
   error or a pause. The other option is to replace the footer hint while
   there is an error.
2. **Should the empty list give recovery steps?** Decided: yes, worded
   by cause as listed above. A new user needs this the most.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It confirmed
both problems and the line references. Its findings, which I checked in
the code and folded in above:
- the login advice was wrong for `setup` errors;
- `r` does not reach the panel while the search box has focus;
- a refused project list leaves discovery unfinished, so treating every
  unfinished discovery as "loading" would show loading forever. That is
  why errors come first in the order above;
- only `R` clears `catalogueError`;
- the pause already shows in the footer, and can happen without an error;
- discovery can finish while activity checks are still running.

Codex agreed with both recommendations.
