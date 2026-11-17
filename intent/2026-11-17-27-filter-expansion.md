---
status: draft
issue: 27
author: olafkfreund
---

# Intent: Keep rows open while searching, and open the projects that match

## Problem

Typing in the search box throws away the user's view:

- **Every change to the filter collapses everything.**
  `onFilterTextChanged` (`PipelinesPanel.qml:42-46`) sets `expanded = ({})`
  on every keystroke. Pipelines and stages the user had opened close, and
  clearing the search does not bring them back.
- **A match inside a project stays hidden.** The filter keeps a project when
  one of its pipelines matches by name, title, branch or status
  (`Model.rows`, `PipelinesModel.js:83-87`). But the project row is
  collapsed, so the matching pipeline is not visible until the user expands
  it by hand. Searching for a branch name shows a list of closed projects.

## Proposed outcome

- **Expansion survives searching.** Rows the user expanded before or while
  searching stay expanded while the filter changes.
- **Matching projects open by themselves.** A project that is in the
  results only because one of its pipelines matches shows those pipelines
  without a keypress.
- **Clearing the search restores the view.** When the filter is emptied,
  the expansion state is what the user had: their own expansions are kept,
  and projects opened only by the search close again.
- **The user stays in control.** While searching, the user can still
  collapse an auto-opened project, and it stays collapsed for that search.
- **Selection:** the cursor still goes to the first row when the filter
  changes, as today.
- **Tests:**
  - the model tests cover the expansion rules;
  - the smoke test, run in the microVM, covers typing a filter, the
    auto-opened project, collapsing it, and clearing the search.

## Affected users and systems

- Files: `PipelinesPanel.qml` (the filter handler and expansion state),
  `PipelinesModel.js` (`rows()`, if the auto-open rule lives there),
  `tests/model.cjs` and `tests/qml-smoke.py`.
- `Polling.js` and `gitlab.py` are not expected to change.
- It ships through the usual chain to p620 and razer; p510 stays on 1.0.0.

## Constraints

- **No new GitLab requests.** Polling fetches job lists only for an expanded
  pipeline that is selected (`Polling.js:59,74,106`). So auto-opening is
  limited to project rows, which only show pipelines the panel already has.
  Pipelines and stages are never auto-opened.
- The existing smoke check "search resets collapsed results"
  (`tests/qml-smoke.py:496`) expects searching to collapse rows. It changes
  with this behaviour.
- Smoke tests run in the microVM only, never on the host desktop.
- The keys do not change.

## Open questions

1. **Which projects open automatically?** I recommend only those that are
   in the results because a pipeline matches, not those whose own name
   matches. Searching for a project name then shows a short list of
   projects, not every pipeline of each one.
2. **Jobs:** the issue says "a matching pipeline or job". Today the filter
   does not look at job names at all. Job lists are fetched only for the
   selected, expanded pipeline, so most jobs are not known. I recommend
   leaving job matching out of this issue and noting it on #27.
3. **Expansions made while searching:** should a pipeline the user opens
   during a search stay open after the search is cleared? I recommend yes:
   it was the user's own action.
