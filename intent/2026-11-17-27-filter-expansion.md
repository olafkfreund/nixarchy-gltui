---
status: approved
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
- **Auto-opened means really open.** An auto-opened project shows the open
  arrow (`▾`), and Left collapses it, the same as a project the user opened.
  Today both of those read the `expanded` map directly
  (`PipelinesPanel.qml:138-144`, `:455`), so this rule has to be applied
  there too, not only in `Model.rows()`.
- **The user stays in control.**
  - **Collapsing during a search:** an auto-opened project the user
    collapses stays collapsed until the search text changes. That survives
    polling updates.
  - **Explicit actions last:** a project or pipeline the user opens or
    collapses during a search keeps that state after the search is
    cleared, because it was the user's own action.
  - **Auto-openings are temporary:** they disappear when the search is
    cleared.
- **Polling keeps it current.** When a poll brings in a new matching
  pipeline, its project opens. When a match disappears, the project closes,
  unless the user opened it. Repeated poll updates never reopen a project
  the user collapsed in this search.
- **Hidden rows stay remembered, not inspected.** A pipeline or stage that
  is open but hidden by the filter keeps its expansion. It is not the
  selected or inspected pipeline: the cursor and polling's selection follow
  the visible rows, as now (`PipelinesPanel.qml:42-45`, `:177-184`).
- **The "+N more" row is unchanged.** It still appears only without a
  filter, or when the project itself matches (`PipelinesModel.js:103`).
- **Selection:** the cursor still goes to the first row when the filter
  changes, as today.
- **Tests:**
  - the model tests cover the expansion rules;
  - the smoke test, run in the microVM, covers:
    - typing a filter, and the auto-opened project with its arrow;
    - collapsing it with Left, and that collapse surviving `adopt()`;
    - a pipeline match arriving by poll, and one disappearing;
    - run and stage expansion kept through a search;
    - clearing the search.

    The existing selection-sync checks (`tests/qml-smoke.py:468-486`) still
    pass.

## Affected users and systems

- Files: `PipelinesPanel.qml` (the filter handler and expansion state),
  `PipelinesModel.js` (`rows()`, if the auto-open rule lives there),
  `tests/model.cjs` and `tests/qml-smoke.py`.
- `Polling.js` and `gitlab.py` are not expected to change.
- It ships through the usual chain to p620 and razer; p510 stays on 1.0.0.

## Constraints

- **No requests caused by searching itself.** Auto-opening is limited to
  project rows, which only show pipelines the panel already has. Pipelines
  and stages are never auto-opened, and job lists are fetched only for the
  selected, expanded pipeline (`Polling.js:59,74,106`).
  - **Kept pipelines still get normal polling.** A pipeline that stays open
    through a search is "kept" (`Polling.js:172-174`), so it can still get
    its usual final-status lookup (`Polling.js:183-187`). That is the same
    as today without a search; until now, searching dropped those lookups
    by closing everything.
- The existing smoke check "search resets collapsed results"
  (`tests/qml-smoke.py:496`) expects searching to collapse rows. It changes
  with this behaviour.
- Smoke tests run in the microVM only, never on the host desktop.
- The keys do not change.

## Open questions

1. **Which projects open automatically?** I recommend only those that are
   in the results because a pipeline matches, not those whose own name or
   description matches (`PipelinesModel.js:84`). Searching for a project name then shows a short list of
   projects, not every pipeline of each one.
2. **Jobs:** the issue says "a matching pipeline or job". Today the filter
   does not look at job names at all. Job lists are fetched only for the
   selected, expanded pipeline, so most jobs are not known. I recommend
   leaving job matching out of this issue and noting it on #27.
3. **Expansions made while searching:** should a pipeline the user opens
   during a search stay open after the search is cleared? I recommend yes:
   it was the user's own action.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It confirmed
both problems and the line references, and agreed with all three
recommendations. I checked each finding in the code and folded it in
above:
- "no new requests" was too strong: kept pipelines still get normal
  final-status lookups (`Polling.js:172-187`). Codex confirmed this with an
  in-memory check;
- hidden open rows must not stay selected or inspected;
- auto-opening must reach the arrow and the Left key, not only `rows()`;
- poll updates must keep auto-opening current without reopening a project
  the user collapsed;
- project descriptions match like names, and the "+N more" row is a
  regression case.
