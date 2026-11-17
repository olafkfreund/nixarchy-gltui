---
status: draft
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
- The empty list tells these states apart:
  - **loading:** discovery has not finished and nothing has been found yet;
  - **error:** shows the error, plus what to do ("run `glab auth login`,
    then press `r`") when it is a login or setup error;
  - **no projects:** discovery finished and found none;
  - **no matches:** a filter is set and nothing matches it.
- When nothing is wrong, the search box still shows its normal hint and
  progress text.
- The smoke test covers each empty state, and checks that the error stays
  visible with text in the search box.

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

1. **Where does the error go while searching?** I recommend a one-line error
   strip between the search box and the list, shown only when there is an
   error or a pause. The other option is to replace the footer hint while
   there is an error.
2. **Should the empty list show the login steps?** I recommend yes, for the
   `auth` and `setup` errors only. It costs one line and is what a new user
   needs.
