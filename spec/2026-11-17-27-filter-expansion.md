---
status: draft
issue: 27
intent: intent/2026-11-17-27-filter-expansion.md
---

# Spec: Keep rows open while searching, and open the projects that match

## Design

### 1. Three pieces of expansion state

| Name | Lives in | Meaning | Changed by |
|---|---|---|---|
| `expanded` | panel (exists) | the user's explicit openings, as today | Right/Enter and Left on a row; never by the filter |
| `searchCollapsed` | panel (new) | `repo:` keys the user collapsed during this search while the search had opened them | Left/Right on an auto-opened project; reset to `{}` whenever `filterText` changes |
| `shown` | panel (new, writable `property var`) | what is actually open: `expanded`, plus the auto-opened projects, minus `searchCollapsed` | assigned at the start of every `rebuild()`; the smoke test only reads it |

- `shown` is what the rows, the arrow and the keys read.
- `shown` is also what `Polling.select` gets (`PipelinesPanel.qml:175`).
  Auto-opened entries are only `repo:` keys, which polling ignores; it reads
  only `repo:run` keys (`Polling.js:59,74,106,173,243`). So passing `shown`
  rather than `expanded` changes no request.

### 2. The auto-open rule, a pure function in `PipelinesModel.js`

```js
// repo: keys that a non-empty filter admits only through a matching pipeline.
function autoOpen(repos, filter)
```

It returns an object of `"repo:<path>": true` for every project where the
query is not empty, the project's own name and description do not match,
and at least one pipeline matches. This is the approved answer to open
question 1.

`rows()` already decides this per project (`PipelinesModel.js:83-87`). The
two matching expressions move into two small helpers, `repoMatches(repo, q)`
and `runMatches(run, q)`, shared by `rows()` and `autoOpen()`. So the "is it
in the results" rule and the "open it" rule cannot drift apart. `rows()`
keeps its output exactly.

### 3. Panel changes (`PipelinesPanel.qml`)

- **`rebuild()`** first computes
  `shown = Model.merge(expanded, Model.autoOpen(repos, filterText), searchCollapsed)`
  and passes `shown` to `Model.rows()` instead of `expanded`. `merge` is a
  small pure helper: a copy of `expanded`, plus the auto keys, minus the
  `searchCollapsed` keys, using `Object.create(null)`-safe copies.

  Polling replies run `adopt()` → `rebuild()`, so a pipeline match that
  arrives by poll opens its project, and a match that disappears closes it.
  A project in `searchCollapsed` stays closed, because `searchCollapsed`
  survives `adopt()`.
- **`onFilterTextChanged`** (`PipelinesPanel.qml:42-46`) no longer clears
  `expanded`. It sets `searchCollapsed = ({})`, then runs `rebuild(true)`
  and `selectionChanged(false)` as now.
  - So the cursor still goes to the first row.
  - Hidden rows keep their expansion, but stop being selected: the cursor
    and `Polling.select` follow `current`, which is a visible row.
  - Clearing the filter is a change to `""`, so the auto keys vanish (an
    empty query opens nothing) and `searchCollapsed` resets. What is left
    is exactly `expanded`.
- **`expand(collapse)`** (`PipelinesPanel.qml:134-153`) reads `shown` for
  "is this row open". The table applies only to `repo`, `run` and `stage`
  rows, which are today's guard (`PipelinesPanel.qml:146`). On `more`,
  `job` and `message` rows, Right does nothing and Left moves to the parent,
  as today.

  | Action | Row | Effect |
  |---|---|---|
  | Left, or Right on an open row | open `repo` row | delete it from `expanded`. If a filter is set, also add it to `searchCollapsed`, so `autoOpen` cannot reopen it on the next rebuild. Both happen whether it was the user's or the search's opening. |
  | Left, or Right on an open row | open `run` or `stage` row | delete it from `expanded` (these are never auto-opened) |
  | Left | closed row, or any other kind | move to the parent, as today |
  | Right/Enter | closed `repo`, `run` or `stage` row | set `expanded[key]=true` and delete it from `searchCollapsed`; this lasts after the search |

  So collapsing a project during a search always sticks for that search,
  and collapsing one the user had opened also lasts after it. That matches
  the approved "explicit actions last". Today's Right toggles
  (`next[row.key] = !next[row.key]`); it stays a toggle, now against
  `shown`.
- **The arrow** (`PipelinesPanel.qml:455`) reads `root.shown[modelData.key]`.
- **`selectionChanged`** passes `shown`.
- **`configure()`'s host reset** (`PipelinesPanel.qml:162`) also resets
  `searchCollapsed`.
- `shown` is a plain writable `property var shown: ({})` on the root, so
  `rebuild()` can assign it. The smoke test reads it as it reads the other
  root properties.

## Alternatives rejected

- **Auto-open inside `Model.rows()` only:** the arrow and Left would not
  see it, and the intent requires that they do.
- **Write auto-opened keys into `expanded`:** the search's openings would
  outlive the search, and clearing could not tell them apart from the
  user's.
- **Recompute auto-opening only on keystrokes:** poll-arriving matches
  would be missed, which the intent rules out.
- **Keep `searchCollapsed` across filter changes until the search is
  cleared:** the approved intent says "until the search text changes".
- **Search job names:** out of scope, as approved (#27 comment).

## Risks

- **Extra work per rebuild:** `autoOpen` walks every project and its
  pipelines once per `rebuild()`. `rows()` already does the same walk, so
  the cost at most doubles a pass that is already cheap. Only a non-empty
  filter does any matching; with an empty filter, `autoOpen` returns `{}`
  at once.
- **Behaviour change:** searching no longer collapses rows. That affects
  the smoke check "search resets collapsed results"
  (`tests/qml-smoke.py:496`). At that point `expanded` still holds
  `repo:one/sub/repo` (set at `:473`), so with this change the count would
  be 3. The later steps (`:497-499`: expand, move, expand to open pipeline
  7) would then take the wrong path. The fix is one line: set
  `panel.expanded=({})` before `panel.filterText="repo"`. With it, the check
  keeps meaning "a name match shows collapsed projects" (2 rows, cursor 0),
  and `:497-499` follow the same path as today. The label becomes "name
  matches are not auto-opened".
- **Kept pipelines:** a pipeline open in `expanded` but hidden by the filter
  is still "kept" by polling, so it can get its normal final-status lookup.
  That is the same as without a search, as the intent accepts.
- **Hosts:** a panel-only change, released through the usual chain to p620
  and razer. p510 stays on 1.0.0.

## Verification

- `node tests/model.cjs`:
  - `autoOpen`:
    - an empty filter returns `{}`;
    - a project whose name matches is not opened;
    - a project matched only through a pipeline's name, title, branch or
      status is opened;
    - a project that does not match at all is not opened;
    - a description match is treated like a name match.
  - `merge`: auto keys are added, `searchCollapsed` keys are removed, and
    `expanded` is not mutated.
  - `rows()` gives identical output for the existing fixtures (the
    refactor guard).
- `node tests/polling.cjs` and `python3 -m unittest discover -s tests`: pass,
  unchanged.
- `tests/qml-smoke.py`, run in a `nixarchy-desktop` microVM only. New
  `esteps`, on a fixture with `workerBusy=true`, so no request starts:
  1. **Fixture:**
     - two projects, `a/one` and `b/two`;
     - `a/one` has pipeline 1 (branch `main`), which has cached jobs in two
       stages;
     - `b/two` has pipeline 2 (branch `feature-x`) and pipeline 3 (branch
       `fix-y`);
     - `expanded` holds `repo:a/one`, `a/one:1` and `a/one:1:stage:build`.
  2. Focus the search field and type `feature` with `keyClick`. Then:
     - `b/two` is shown with pipeline 2's row;
     - its arrow text starts with `▾`;
     - `panel.shown["repo:b/two"]` is true;
     - `a/one` is filtered out, but `expanded` still holds its three keys.
  3. **Auto-only collapse:** focus the list (`listFocus()`), put the cursor on
     `b/two` and press Left. `b/two` collapses, and `repo:b/two` is in
     `searchCollapsed`. Then `adopt()`, and it stays collapsed.
  4. **A poll-arriving match:** add pipeline 4 (branch `feature-z`) to
     `a/one` and `adopt()`. `a/one` is shown and auto-opened, with pipeline
     4.
  5. **A disappearing match:** remove pipeline 4 and `adopt()`. `a/one` is gone
     from the rows.
  6. **Changing the search clears the collapse:** focus the search field
     and type a different text, `fix`, which matches only pipeline 3.
     - `searchCollapsed` is empty;
     - `b/two` is auto-opened again, with pipeline 3.
     - Focus the list, select pipeline 3 and press Right. `b/two:3` is now
       in `expanded`.
  7. **Explicit project collapse:** with the filter still `fix`, put the
     cursor on `b/two` and press Right to open it explicitly, so
     `repo:b/two` is in `expanded`. Press Left: `repo:b/two` leaves
     `expanded` and joins `searchCollapsed`, so it stays closed after
     `adopt()`. Press Right again to reopen it, which puts it back in
     `expanded`, and leave it open.
  8. **Key boundaries:** on a `more` row or a job row, Right adds no key to
     `expanded`, and Left moves to the parent.
  9. **Clear the filter** with Esc in the search field:
     - `shown` equals `expanded`;
     - `a/one` and pipeline 1 are open again, and the `build` stage shows
       its job rows, as before the search;
     - `b/two` is open, from step 7, and `b/two:3` is still open, from step
       6.
  10. **"+N more":** a project that matches by name and has hidden pipelines
      still shows its `more` row while filtering. A project matched only
      through a pipeline does not show one.

  The existing checks, including selection sync
  (`tests/qml-smoke.py:468-486`), still pass. The check at `:496` gets the
  one-line fix described under Risks.

## Review notes

Codex reviewed the draft read-only, and confirmed that passing `shown` to
polling is request-neutral (no `repo:` key is read, `Polling.js:59-243`).
Its findings, which I checked in the code and folded in above:
- collapsing a project the user had opened would be reopened by
  `autoOpen`; collapse now also suppresses auto-opening;
- the `:496` change alone broke the steps that follow; the one-line reset
  keeps them on their path;
- smoke step 6 was unreachable; the sequence now changes the filter text
  to clear suppression;
- stage expansion and key-boundary cases were added;
- `shown` was described as both derived and read-only, and is now a
  writable property.
