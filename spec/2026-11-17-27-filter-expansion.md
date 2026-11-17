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
| `shown` | panel (new, derived) | what is actually open: `expanded`, plus the auto-opened projects, minus `searchCollapsed` | recomputed in every `rebuild()` |

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
  "is this row open", and writes the right map:

  | Action on row | Row is open because | Effect |
  |---|---|---|
  | Left (collapse) | it is in `expanded` | delete it from `expanded`; this lasts after the search |
  | Left (collapse) | it is auto-opened only | add its key to `searchCollapsed`, for this search only |
  | Left (collapse) | not open | move to the parent, as today |
  | Right/Enter (toggle) | open, in `expanded` | delete it from `expanded` |
  | Right/Enter (toggle) | open, auto only | add to `searchCollapsed` |
  | Right/Enter (toggle) | closed | set `expanded[key]=true` and delete it from `searchCollapsed`; this lasts |

  Today's Right toggles (`next[row.key] = !next[row.key]`). That stays a
  toggle, now against `shown`.
- **The arrow** (`PipelinesPanel.qml:455`) reads `root.shown[modelData.key]`.
- **`selectionChanged`** passes `shown`.
- **`configure()`'s host reset** (`PipelinesPanel.qml:162`) also resets
  `searchCollapsed`.
- A read-only `shown` property is visible to the smoke test, as the other
  root properties are.

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
- **Behaviour change:** searching no longer collapses rows. The smoke check
  "search resets collapsed results" (`tests/qml-smoke.py:496`) is updated.
  With filter `repo`, both test projects match by name, so nothing is
  auto-opened and the count stays 2 only if nothing was expanded before. The
  plan checks the setup at that point and adjusts the expectation.
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
  1. Two projects, `a/one` and `b/two`. Only `b/two` has a pipeline on
     branch `feature-x`, and `a/one` has its pipeline expanded in
     `expanded`.
  2. Typing `feature` (with `keyClick`):
     - `b/two` is shown with its pipeline row;
     - its arrow text starts with `▾`;
     - `panel.shown["repo:b/two"]` is true;
     - `a/one` is filtered out, but `expanded` still holds its keys.
  3. Moving to `b/two` and pressing Left: `b/two` collapses and its key is in
     `searchCollapsed`. Then `adopt()`, and it stays collapsed.
  4. **A poll-arriving match:** add a `feature-y` pipeline to `a/one` and
     `adopt()`. `a/one` is now shown and auto-opened.
  5. **A disappearing match:** remove it again and `adopt()`. `a/one` is gone
     from the rows.
  6. Opening a pipeline with Right during the search adds it to `expanded`.
  7. Clearing the filter (Esc):
     - `shown` equals `expanded`;
     - `a/one`'s pipeline is open again, as before the search;
     - the pipeline opened in step 6 is still open;
     - `b/two` is closed.
  8. "+N more": a project matched by name, which has hidden pipelines,
     still shows its `more` row while filtering.

  The existing checks, including selection sync
  (`tests/qml-smoke.py:468-486`), still pass. The check at `:496` is
  adjusted as described under Risks.
