---
status: draft
issue: 27
spec: spec/2026-11-17-27-filter-expansion.md
coders:
  1: codex   # small pure helpers and the rows() refactor that must keep its output
  2: codex   # tricky state logic: shown / searchCollapsed and the expand table
  3: coder   # smoke-test stages, following the existing esteps pattern
  4: coder   # README and version bump
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Keep rows open while searching, and open the projects that match

Self-contained. Branch `feat/27-filter-expansion`, based on `e2b13c0`
(v1.2.0). Line numbers are for that commit; match on the quoted code.
`Polling.js` and `gitlab.py` must not change.

## Approved decisions (from the spec)

### Three pieces of state on the panel root

- **`expanded`:** the user's explicit openings. The filter never changes it.
- **`searchCollapsed`:** a new `property var searchCollapsed: ({})`. It holds
  `repo:` keys the user collapsed during the current search, and resets to
  `({})` whenever `filterText` changes and on a host change in
  `configure()`.
- **`shown`:** a new writable `property var shown: ({})`. It is assigned at
  the start of every `rebuild()`:
  `shown = Model.merge(expanded, Model.autoOpen(repos, filterText), searchCollapsed)`.
  `Model.rows()`, the arrow, `expand()` and `Polling.select` all read
  `shown`. Polling reads only `repo:run` keys, so this is request-neutral.

### `Model.autoOpen(repos, filter)`

It returns `{"repo:<path>": true}` for each project where all of these
hold:
- the query is not empty;
- `repoMatches(repo, q)` is false, meaning the name and description do not
  match;
- some `runMatches(run, q)` is true.

`repoMatches` and `runMatches` are the two expressions currently inline in
`rows()`, moved out so both functions share them. `rows()` output does not
change.

### `Model.merge(expanded, auto, collapsed)`

It returns a new object: a copy of `expanded`, plus the `auto` keys, minus
the `collapsed` keys. It never mutates its inputs. It copies with
`Object.keys(...).forEach` and checks with `Object.prototype.hasOwnProperty`.

### `expand(collapse)`, for `repo`, `run` and `stage` rows only

"Open" means `shown[key]` is true.

| Action | Row | Effect |
|---|---|---|
| Left, or Right on an open row | open `repo` | delete it from `expanded`; if `filterText` is set, also set `searchCollapsed[key]=true` |
| Left, or Right on an open row | open `run` or `stage` | delete it from `expanded` |
| Left | closed row, or a `more`, `job` or `message` row | move to the parent (today's code) |
| Right/Enter | closed `repo`, `run` or `stage` | set `expanded[key]=true` and delete it from `searchCollapsed` |
| Right/Enter | `more`, `job` or `message` | nothing (today's guard) |

### Filter change

`onFilterTextChanged` sets `searchCollapsed = ({})`, then runs
`rebuild(true)` and `selectionChanged(false)`. It no longer clears
`expanded`.

## Corrections to the spec

The plan's smoke sequence (step 3, E1–E10) is the reference. It corrects
the spec's verification wording without changing any approved behaviour:
- **Explicit project collapse (spec step 7):** with filter `fix`, `b/two` is
  already auto-open, so the first Right closes it. The plan presses Right
  twice to reach an explicit opening, as the toggle table requires.
- **Key boundaries (spec step 8):** these run after the filter is cleared,
  on the restored `build` job rows, and on a name-matched project with
  hidden pipelines. With filter `fix` there is no job or `more` row to
  select.

## Steps

1. **`PipelinesModel.js` and `tests/model.cjs`: the helpers.**
   - **Matching helpers.** In `rows()`, the two expressions move into new
     top-level functions:
     - `(repo.repo + " " + (repo.description || "")).toLowerCase().indexOf(query) >= 0`
       becomes `repoMatches(repo, query)`;
     - `[run.name, run.display_title, run.head_branch, state(run)].join(" ").toLowerCase().indexOf(query) >= 0`
       becomes `runMatches(run, query)`.

     `rows()` calls them. The query is already lowercased there; pass it
     the same way.
   - **`autoOpen(repos, filter)` and `merge(expanded, auto, collapsed)`:**
     add them as in the decisions above.
   - **`tests/model.cjs`.** For `autoOpen`:
     - an empty filter returns `{}`;
     - a name match is not opened;
     - a description match is not opened;
     - a pipeline name, title, branch or status match is opened;
     - a project with no match is not opened.

     For `merge`:
     - it adds the auto keys and removes the collapsed ones;
     - it does not mutate any input;
     - prototype-looking keys are safe: a project named `constructor` gives
       the key `repo:constructor`, and `merge` copies it like any other.

     And a refactor guard: `rows()` gives the same rows as before for the
     existing fixtures, which are already asserted in the file.

   Check: `node tests/model.cjs >/dev/null && node tests/polling.cjs >/dev/null`.

   Traps: ES5 only in `PipelinesModel.js`, because it is loaded by QML and
   by Node `vm`. That means no `const`, arrows, spread or `Object.assign`
   on `null`-prototype objects.

2. **`PipelinesPanel.qml`: state, rebuild, keys and arrow.**
   - **New root properties:** add `property var shown: ({})` and
     `property var searchCollapsed: ({})` next to `property var expanded`.
   - **`rebuild(resetSelection)`:**
     - start with the `shown = Model.merge(...)` line;
     - change `Model.rows(repos, expanded, details, filterText, now)` to use
       `shown`.
   - **`onFilterTextChanged`:** replace `expanded = ({})` with
     `searchCollapsed = ({})`, and keep `rebuild(true)` and
     `selectionChanged(false)`.
   - **`selectionChanged(immediate)`:** pass `shown` instead of `expanded`
     to `Polling.select`.
   - **`expand(collapse)`:** rewrite it per the expand table. Keep the
     existing parent-navigation branch, from `cursor = Model.selection(entries, row.parent, cursor)`
     through `return`, and the trailing `rebuild()`,
     `selectionChanged(true)` and `pump()`. Assign `expanded` and
     `searchCollapsed` as new objects, so their bindings notify.
   - **The arrow:** in the delegate title text, change
     `root.expanded[modelData.key]` to `root.shown[modelData.key]`.
   - **`configure()`'s host reset:** in the line with
     `expanded = ({}); details = ({}); updated = ""; error = ""; cursor = 0`,
     also reset `searchCollapsed = ({})`.

   Check: `node tests/model.cjs >/dev/null && node tests/polling.cjs >/dev/null`.
   Then run the microVM smoke test (see Tests). It may fail only at the
   `:496` check, which step 3 fixes; record which checks fail.

   Traps:
   - Do not introduce a binding loop. `shown` is assigned imperatively in
     `rebuild()`, not bound.
   - `expand()` runs `rebuild()`, which reassigns `shown`. Read `shown`
     before you change the maps.

3. **`tests/qml-smoke.py`: the smoke checks.**
   - **The `:496` fix.** Before the line `panel.filterText="repo"`, add
     `panel.expanded=({})`. Rename the check label
     "search resets collapsed results" to "name matches are not
     auto-opened". The following `expand(false)`, `move(1)` and
     `expand(false)` stay as they are.
   - **New `esteps`.** Insert them immediately before the final `estep`,
     the one that sets `panel.workerBusy=false`, closes the panel, builds
     the zoom fixture and sets `stage=11`. `workerBusy` is already true.
     Use one function per numbered step below. Put each wait (`return false`
     until a delegate or state exists, or `held()`) in its own function, as
     #26 did.

     **E1. Fixture.**
     - Set `panel.polling.repos` to:
       - `{repo:"a/one",checked:"x",runs:[{id:1,name:"CI",status:"completed",conclusion:"success",run_number:1,head_branch:"main"}]}`;
       - `{repo:"b/two",checked:"x",runs:[{id:2,name:"CI",status:"completed",conclusion:"success",run_number:2,head_branch:"feature-x"},{id:3,name:"CI",status:"completed",conclusion:"success",run_number:3,head_branch:"fix-y"}]}`.
     - Set `panel.polling.details={"a/one:1":{jobs:[...]}}` with two
       completed jobs in stage `build` and one in stage `test`.
     - Set `panel.filterText=""` and
       `panel.expanded=({"repo:a/one":true,"a/one:1":true,"a/one:1:stage:build":true})`,
       then `panel.adopt()`.
     - Check that the rows include `a/one`, pipeline 1, stage `build`, its two
       job rows, and stage `test`.

     **E2. Type `feature`.** `panel.searchItem.forceActiveFocus()`, then
     `tc.keyClick` each character. Check:
     - `panel.filterText==="feature"`;
     - the rows are exactly `b/two` and pipeline 2;
     - `panel.shown["repo:b/two"]` is true;
     - the `b/two` row's arrow is open: its entry's key is in `panel.shown`,
       and its delegate title starts with `▾`;
     - `panel.expanded` still has all three `a/one` keys.

     **E3. Auto-only collapse.**
     - `listFocus()`, set the cursor to the `b/two` row, then press
       `Qt.Key_Left`.
     - Check that `searchCollapsed["repo:b/two"]` is set, the rows are only
       `b/two`, and `expanded` has no `repo:b/two`.
     - Then `panel.adopt()` and check that it is still collapsed.

     **E4. A poll-arriving match.**
     - Push
       `{id:4,name:"CI",status:"completed",conclusion:"success",run_number:4,head_branch:"feature-z"}`
       into `a/one`'s runs, then `panel.adopt()`.
     - Check that `a/one` and pipeline 4 are in the rows and
       `shown["repo:a/one"]` is true. It was already in `expanded`, so also
       check that pipeline 1 is hidden: it does not match.

     **E5. A disappearing match.** Remove pipeline 4 and `panel.adopt()`.
     Check that `a/one` is not in the rows.

     **E6. Change the search.**
     - Focus the search field, set `panel.filterText=""`, then type `fix`.
     - Check that `searchCollapsed` is empty, `b/two` and pipeline 3 are
       shown, and `b/two` is auto-open.
     - `listFocus()`, move the cursor to pipeline 3 and press Right. Check
       that `expanded["b/two:3"]` is true.

     **E7. Explicit project collapse.** Start with `b/two` auto-open. Put the
     cursor on `b/two`, then:
     1. Press Right. It closes: `searchCollapsed["repo:b/two"]` is set.
     2. Press Right again. It opens explicitly: `expanded["repo:b/two"]` is
        true and `searchCollapsed` has no `repo:b/two`.
     3. Press Left. `expanded` has no `repo:b/two`, and
        `searchCollapsed["repo:b/two"]` is set. Run `panel.adopt()` and check
        that it is still collapsed.
     4. Press Right. `expanded["repo:b/two"]` is true again; leave it open.

     **E8. Clear the filter.**
     - Focus the search field and press `Qt.Key_Escape` once.
     - Check that `filterText` is empty.
     - Check that every key in `panel.shown` is in `panel.expanded`, and the
       other way round.
     - Check that the rows include `a/one`, pipeline 1, stage `build` and its
       two job rows; `b/two` with pipelines 2 and 3; and pipeline 3 still
       expanded (`expanded["b/two:3"]`).

     **E9. Key boundaries, on the restored rows.**
     - Put the cursor on a job row under stage `build` and press Right.
       `expanded` gains no key.
     - Press Left. The cursor moves to stage `build`, its parent.

     **E10. "+N more".**
     - Set `panel.polling.repos[0].hidden={running:3}` (`a/one`) and
       `panel.adopt()`.
     - Set `panel.filterText="a/one"`, a name match. The rows include a
       `kind==="more"` row under `a/one`, because `a/one` is still in
       `expanded`.
     - Put the cursor on it, press Right (`expanded` gains no key), then
       press Left (the cursor moves to `a/one`).
     - Set `panel.filterText="main"`, which matches only through pipeline 1.
       The rows include `a/one`, and no `more` row.
     - Set `panel.filterText=""` to finish.

   Check: the microVM smoke run passes, with `passed=2 rc=0 binding_loop=0`.

   Traps:
   - **Never run `tests/qml-smoke.py` on the host desktop.**
   - `workerBusy=true` stays set during `esteps`.
   - Esc in the search field clears the filter and focuses the list
     (`PipelinesPanel.qml:371`). Esc on the list with an empty filter closes
     the panel, so press it only once.
   - Typing replaces the text cumulatively. To change the filter to `fix`,
     first set `panel.filterText=""` or select all, then type.

4. **Docs and version** (release work).
   - **`README.md`:** near the keys table row
     "↑ / ↓ while filtering | Select a search result", add one paragraph:
     - searching keeps opened rows open;
     - projects that match through a pipeline open by themselves;
     - Left closes one for that search;
     - clearing the search restores what you had opened.
   - **`manifest.json`:** `"version": "1.3.0"`.

   Check: the full test set.

## Tests

```bash
node tests/polling.cjs && node tests/model.cjs && python3 -m unittest discover -s tests
```

**QML smoke test, in the microVM only.** Never on the host desktop.

1. Start the VM once:
   ```bash
   nixarchy vm create gltui-27 --template nixarchy-desktop
   nixarchy vm run --detach gltui-27
   ```
   Wait about 45 s, until `~/.local/state/nixarchy/microvm/gltui-27/vsock-cid`
   exists.
2. Create the in-guest runner, `~/.local/state/nixarchy/microvm/gltui-27/share/run-smoke.sh`.
   The share is `/mnt/host` in the guest.
   ```sh
   #!/bin/sh
   cd /mnt/host/repo || exit 1
   { python3 tests/qml-smoke.py; echo "rc=$?"; } > /mnt/host/smoke.out 2>&1
   touch /mnt/host/smoke.done
   ```
3. Each run, from the repo root:
   ```sh
   share=~/.local/state/nixarchy/microvm/gltui-27/share
   rm -rf "${share:?}/repo" && mkdir "$share/repo" && git ls-files -z | xargs -0 tar -c | tar -x -C "$share/repo"
   rm -f "$share/smoke.done" "$share/smoke.out"
   echo '[{"tool":"launch","args":{"argv":["sh","/mnt/host/run-smoke.sh"],"timeout":2,"generation":"@generation"}}]' \
     | ~/.claude/skills/ai-mirror/mirror-vm gltui-27 - --out /tmp/gltui-27-shots >/dev/null 2>&1
   for i in $(seq 1 60); do [ -f "$share/smoke.done" ] && break; sleep 5; done
   echo "passed=$(grep -c QML_CHECKS_PASSED "$share/smoke.out") $(grep -o 'rc=[0-9]*' "$share/smoke.out" | tail -1) binding_loop=$(grep -c 'binding loop' "$share/smoke.out")"
   grep 'CHECK FAILED' "$share/smoke.out"
   ```
   Expected: `passed=2 rc=0 binding_loop=0`. Run one copy at a time.
4. Afterwards, remove the VM:
   ```bash
   nixarchy vm stop gltui-27
   ```
   When `nixarchy vm list` shows it stopped, run:
   ```bash
   nixarchy vm rm gltui-27
   ```

**Review:** a fresh Opus agent, given only this plan and `git diff`, and
Codex's read-only review of the diff.

**Release, after the PR merges:**
1. Tag `v1.3.0`.
2. Open the nixarchy pin bump PR.
3. Lock nixos_config's `nixarchy/nixarchy-gltui` node (the #3024 and #3036
   approach).
4. Switch p620, keeping its live overrides, then razer. Announce on the bus
   first.

p510 stays on 1.0.0.

## Rollback

Revert the PR's merge commit and release `v1.3.1`, or point the pins back at
`e2b13c0` (v1.2.0). No data or config format changes.
