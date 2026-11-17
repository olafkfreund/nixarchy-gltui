---
status: draft
issue: 26
spec: spec/2026-11-17-26-error-empty-state.md
coders:
  1: codex   # small, tricky pure logic: the hint order and the empty-text order
  2: coder   # QML layout edits that follow step 1
  3: coder   # smoke-test stages that follow the existing zsteps pattern
  4: coder   # docs and version bump
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Keep errors visible and make the empty state honest

Self-contained. Branch `fix/26-error-empty-state`, based on `b055ffb`
(v1.1.0). Line numbers are for that commit; match on the quoted code.
Only `PipelinesPanel.qml`, `tests/qml-smoke.py`, `README.md` and
`manifest.json` change. `Polling.js`, `PipelinesModel.js` and `gitlab.py`
must not change.

## Approved decisions (from the spec)

### The error strip

- A `Text` with `id: errorStrip` goes between the search box and the
  hairline.
- It is visible when `root.error !== "" || root.cooldownText !== ""`.
- **Text:** the non-empty parts, joined with `" · "`:
  - the error, followed by `" — " + hint` if there is a hint;
  - the pause.
- **Style:**
  - `Commons.Color.urgent`;
  - `root.zf(Style.font.caption)`;
  - `wrapMode: Text.Wrap`, `maximumLineCount: 2` and
    `elide: Text.ElideRight`;
  - `textFormat: Text.PlainText`.
- `onVisibleChanged` and `onHeightChanged` both call `keepCursor()`, which
  uses `Qt.callLater` to run `list.positionViewAtIndex(root.cursor, ListView.Contain)`.
  It is guarded by `root.opened && root.cursor >= 0 && root.cursor < list.count`.

### `errorHint(error, catalogueError, stopped, filtering)`

The first condition that applies wins. `E` is `"Esc and "` when `filtering`
is true, and `""` otherwise.

| Condition | Hint |
|---|---|
| `error !== "" && error === catalogueError` | `"check the token's access, then press " + E + "R"` |
| `stopped`, and `error` contains neither `glab` nor `shell log` | `"see the shell log, then press " + E + "r"` |
| `stopped` | `"then press " + E + "r"` |
| otherwise | `""` |

`stopped` is `polling.auth`. No error type is tracked anywhere.

### `emptyText(error, hint, cooldownText, discoveryComplete, repoCount, filter)`

The first match wins:

| # | Condition | Text |
|---|---|---|
| 1 | `error` | `error + (hint ? " — " + hint : "")` |
| 2 | `cooldownText` | `cooldownText` |
| 3 | `!discoveryComplete` and `filter` | `"Still discovering projects… no matches so far"` |
| 3 | `!discoveryComplete` | `"Discovering projects…"` |
| 4 | `repoCount === 0` | `"No projects found on this account"` |
| 5 | `filter` | `"No projects or pipelines match “" + filter + "”"` |
| 6 | otherwise | `"No matching projects or pipelines"` |

### Placeholder, empty list and footer

- **Placeholder:** keeps "Search projects…", "Activity checked …" and
  "Discovering projects… N found". It no longer shows the error or the
  pause, and its colour is always `Commons.Color.menu.text`.
- **Empty list:** binds to `emptyText`. It wraps, is centred, uses
  `PlainText`, and is `urgent` when `root.error` is set.
- **Footer:** unchanged.

### Hooks and scope

- New read-only hooks: `errorItem: errorStrip` and `emptyItem` (the
  empty-list `Text`).
- No new polling state, and no error-type tracking.

## Steps

1. **`PipelinesPanel.qml`: add `errorHint` and `emptyText` as root
   functions.**
   - Put them next to `statusColor` (the function containing
     `if (status === "failed" || status === "error") return Commons.Color.urgent`,
     about line 221).
   - Follow the tables above exactly, and keep the code ES5-style like the
     rest of the file.
   - Add a root property:
     `readonly property string errorHintText: errorHint(error, polling.catalogueError || "", !!polling.auth, filtering)`.

   Check: `node tests/polling.cjs && node tests/model.cjs` (unchanged; both
   must still pass).

   Traps: `polling` is reassigned in `adopt()` (`polling = Object.assign({}, polling)`),
   so bindings on `polling.*` update. Do not read `polling.error` for the
   hint: `root.error` already holds `polling.error || polling.catalogueError`.

2. **`PipelinesPanel.qml`: layout.**
   - **Strip:** insert `errorStrip` after the `TextInput { id: searchField … }`
     block, before `Rectangle { id: hairline`. Use `width: parent.width`
     and the `visible`, text, style and `keepCursor` hooks from the
     decisions above, with `keepCursor` as a function on `errorStrip`.
   - **Placeholder** (`text: root.filtering ? "Search projects…" : root.cooldownText || root.error ||`):
     drop `root.cooldownText || root.error ||`, and set
     `color: Commons.Color.menu.text`.
   - **Empty list** (the `Text` with `"No matching projects or pipelines"`):
     - `id: emptyLabel` (not `emptyText`, which is the root function's
       name);
     - `width: parent.width - 2 * root.zs(Style.space(16))`;
     - `text: root.emptyText(root.error, root.errorHintText, root.cooldownText, root.discoveryComplete, root.repos.length, root.filterText)`;
     - `color: root.error ? Commons.Color.urgent : Commons.Color.menu.text`;
     - `wrapMode: Text.Wrap`, `horizontalAlignment: Text.AlignHCenter` and
       `textFormat: Text.PlainText`.

     Keep `anchors.centerIn`, `visible` and the font.
   - **Placeholder id:** give the placeholder `Text` `id: placeholder`.
   - **Hooks:** add these three after
     `readonly property Item hairlineItem: hairline`:
     - `readonly property Item errorItem: errorStrip`
     - `readonly property Item emptyItem: emptyLabel`
     - `readonly property Item placeholderItem: placeholder`

   Check: `python3 tests/qml-smoke.py` passes unchanged. This is the zoom
   risk named in the spec: the zoom fixture has a one-hour pause, so the
   strip is visible during every zoom stage. If a zoom check fails, fix the
   stage's measurement (for example, measure from `listItem.y`), not the
   strip. Record any such change here as a deviation.

   Traps:
   - An id named like a root function shadows it, which is why the label
     is called `emptyLabel`.
   - Do not add a `binding loop`. The smoke test fails on that log text.

3. **`tests/qml-smoke.py`: new `esteps` stages, before the zoom stages.**
   - Where stage 9 now builds the zoom fixture and sets `stage=10`, first
     build the error-state fixture and set `stage=10`, with `esteps`
     running at 10. The last `estep` builds the existing zoom fixture
     (moved, unchanged) and sets `stage=11`. `zsteps` move to `stage===11`.
   - **Error fixture:**
     - `panel.polling=Polling.create()` with 40 repos (as in the zoom
       fixture), `discover=false` and `catalogueComplete=true`;
     - **no** cooldown;
     - set `panel.workerBusy=true` **before** `panel.open("{}")`, so
       `pump()` starts nothing, then `panel.adopt()`.
   - **Stages, one function each** (`return false` to wait):
     1. **Direct function checks:** every row of both tables, with
        `filtering` both true and false. Among them:
        - `errorHint("Authenticate with glab auth login","",true,false)==="then press r"`;
        - `errorHint("python3 not found","",true,true)==="see the shell log, then press Esc and r"`;
        - `errorHint("x","x",false,false)==="check the token's access, then press R"`;
        - `errorHint("net","",false,false)===""`.

        And the order cases:
        - an error beats a pause;
        - a pause beats loading;
        - a project-list error during unfinished discovery shows the error;
        - loading with a filter shows "no matches so far".
     2. **No-error baseline:**
        - `!panel.errorItem.visible`;
        - the placeholder text contains `"Activity checked"`, after setting
          some repos' `checked` to `""` and calling `adopt()`;
        - restore afterwards.
     3. **Loading:** `polling.repos=[]`, `catalogueComplete=false`, then
        `adopt()`. `emptyItem.visible`, and its text is
        `"Discovering projects…"`.
     4. **No projects:** `catalogueComplete=true` and `adopt()`. The text
        is `"No projects found on this account"`.
     5. **No matches:** restore the 40 repos, set `filterText="zzz"`. The
        text is `No projects or pipelines match “zzz”`. Then clear the
        filter.
     6. **Login stop, search box focused but empty:**
        - set `polling.auth=true` and `polling.error="Authenticate with glab auth login"`, then `adopt()`;
        - `searchItem.forceActiveFocus()`;
        - `errorItem.visible`, and its text contains the error and
          `Esc and r`;
        - `placeholderItem.text` does not contain the error.
     7. **Login stop, with text typed:**
        - `tc.keyClick("z")` three times;
        - `errorItem.visible` still;
        - `emptyItem.text` starts with the error, not "No projects".
     8. **Pause only:**
        - clear the error and auth, Esc out of search, set `polling.cooldown=Date.now()+3600000`, then `adopt()`;
        - wait one tick so `now` updates; the strip text equals
          `panel.cooldownText`, with no `·`.
     9. **Cursor in view:**
        - with the pause still set, clear the filter, move the cursor to
          row 39 (`End`), wait a frame;
        - set a long error (200 characters) and `adopt()`, then wait a
          frame;
        - the strip is two lines tall (`errorItem.lineCount===2`), and
          the cursor row is inside the viewport:
          `r.y >= l.contentY && r.y + r.height <= l.contentY + l.height`
          for `r = l.itemAtIndex(39)`.
        - Then clear the error and the cooldown.
     10. **Restore:**
         - `panel.workerBusy=false`;
         - `panel.close()`;
         - build the zoom fixture exactly as before;
         - `stage=11`.

   Check: `python3 tests/qml-smoke.py` prints `QML_CHECKS_PASSED` in both
   scenarios.

   Traps:
   - The quickshell watchdog is `interval: 45000`, and the subprocess timeout
     is `timeout=60`. If the added stages push past them, raise them to
     `75000` and `90`, and record that as a deviation.
   - `zRequests` is captured in the first `zstep`. `workerBusy=true` must be
     reset before the zoom fixture opens, or the zoom stages hang.
   - `keyClick` needs the panel focused, as in the zoom stages.

4. **Docs and version.**
   - `README.md`: in the section describing the panel, one sentence saying
     that errors show in a line under the search box, with the key that
     fixes them.
   - `manifest.json`: set `"version"` to `"1.1.1"`.

   Check: the full test set below.

## Tests

```bash
node tests/polling.cjs && node tests/model.cjs && python3 -m unittest discover -s tests && python3 tests/qml-smoke.py
```

All pass, and the smoke test prints `QML_CHECKS_PASSED` for the `fresh` and
`managed` scenarios.

Review: a fresh Opus agent, given only this plan path and `git diff`, and
Codex's read-only review of the diff.

Release, after the PR merges:
- tag `v1.1.1`;
- nixarchy pin bump PR;
- the `omarchy-edge` workflow;
- nixos_config lock bump;
- `just p620` from `~/.config/nixos` on `main`, after announcing on the bus;
- the manual check from the spec.

p510 stays on 1.0.0, as the owner decided.

## Rollback

Revert the PR's merge commit and release `v1.1.2`, or point the nixarchy pin
back at `b055ffb` (v1.1.0). No data or config format changes.
