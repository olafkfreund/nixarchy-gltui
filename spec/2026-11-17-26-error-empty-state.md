---
status: draft
issue: 26
intent: intent/2026-11-17-26-error-empty-state.md
---

# Spec: Keep errors visible and make the empty state honest

## Design

### 1. Two pure functions in `PipelinesModel.js`

Both take plain values and return a string. QML only binds to them, and
`tests/model.cjs` tests them.

```js
// What to do about the current error, or "" when no action helps.
function errorHint(error, catalogueError, stopped, filtering)
// The text of the empty list.
function emptyText(error, hint, cooldownText, discoveryComplete, repoCount, filter)
```

**`errorHint`** picks the advice from state the panel already has.

| Condition | Hint |
|---|---|
| The shown error is the project-list error (`error === catalogueError`, not empty) | `press R to reload projects` (in search: `press Esc, then R`) |
| Polling stopped for a login or setup error (`polling.auth`) | `then press r` (in search: `press Esc, then r`) |
| Anything else | `""` (the error retries by itself) |

The helper's messages already say what to fix:
- "Authenticate with glab auth login" (`gitlab.py:181,207`);
- "Install glab (GitLab CLI)" (`gitlab.py:236`);
- "GitLab helper returned invalid data; see the shell log"
  (`PipelinesPanel.qml:214`).

So the error text stays as it is, and the hint only adds the key to press.
`polling.auth` is set for both `auth` and `setup` errors (`Polling.js:218`),
and `r` clears it (`Polling.manual`, `Polling.js:51-53`). This gives the
per-cause advice the intent asks for without adding polling state, and
without tracking `errorType`. `r` does not reach the panel while the search box has focus. Outside the
box, Esc clears a filter or closes the panel (`PipelinesPanel.qml:298-300`).
So with `filtering` true the hints say "press Esc, then r" and "press Esc,
then R". With `filtering` false they say "then press r" and "press R to
reload projects".

**`emptyText`** returns the first match of the approved order:

1. `error`: `error + (hint ? " — " + hint : "")`
2. `cooldownText`: the pause text
3. `!discoveryComplete`: `"Still discovering projects… no matches so far"`
   when a filter is set, otherwise `"Discovering projects…"`
4. `repoCount === 0`: `"No projects found on this account"`
5. otherwise: `"No projects or pipelines match “" + filter + "”"`

Step 5 is reached with no filter only if every project row is hidden. The
model does not do that today, but the old wording stays as the fallback
(`"No matching projects or pipelines"`).

### 2. An error strip in `PipelinesPanel.qml`

A new `Text` (`id: errorStrip`) goes between the search box and the
hairline. It is the "strip" option decided in the intent.
- **When it shows:** `visible: root.error !== "" || root.cooldownText !== ""`.
  When hidden, it takes no space, because the `Column` skips invisible items.
- **What it says:** the error with its hint, then the pause, joined with `·`.
  When there is both an error and a pause, both are shown.
- **Style:**
  - colour `Commons.Color.urgent`;
  - font size `root.zf(Style.font.caption)`;
  - `wrapMode: Text.Wrap`, capped at two lines with `maximumLineCount: 2`
    and `elide: Text.ElideRight`;
  - `textFormat: Text.PlainText`, because errors can contain server text.
- **The list:** its height already comes from `y`, so it shrinks by
  itself.

The search placeholder (`PipelinesPanel.qml:355-357`) stops showing the
error and the pause. It keeps the hint and progress text: "Search
projects…", "Activity checked N/M…" and "Discovering projects… N found".
Its colour is always `Commons.Color.menu.text`.

The empty-list `Text` (`PipelinesPanel.qml:429-435`) binds `text` to
`Model.emptyText(...)`. It gets the following:
- `width: parent.width` with side padding;
- `wrapMode: Text.Wrap` and `horizontalAlignment: Text.AlignHCenter`;
- `textFormat: Text.PlainText`;
- `Commons.Color.urgent` when it shows an error, `menu.text` otherwise.

The footer does not change. It already shows the pause instead of the key
hints (`PipelinesPanel.qml:444`).

Two read-only test hooks are added next to the existing ones
(`PipelinesPanel.qml:68-73`): `errorItem: errorStrip` and
`emptyItem: <the empty Text>`.

## Alternatives rejected

- **Show the error in the footer instead of a strip.** The footer is the
  only place the keys are listed, and the intent chose the strip.
- **Track `errorType` in polling state for advice by cause.** The intent
  rules out new polling state. The helper's messages already name the fix,
  and `polling.auth` / `catalogueError` are enough to pick the key to press.
- **Keep the error in the placeholder, and also show it while typing.** A
  placeholder and typed text cannot share one line.
- **Compute the texts inline in QML.** Pure functions can be unit-tested in
  `tests/model.cjs` with no running shell, and the cases are many.

## Risks

- **Layout shift:** the strip pushes the list down when an error appears.
  This is acceptable: errors are rare and need attention. The list keeps
  the cursor row in view, because the list height is bound to `y`.
- **Long server messages:** the strip is capped at two lines, with an
  ellipsis.
- **Zoom (#22):** the strip's font uses `zf`, so it scales. The zoom smoke
  stages have no error, so the strip stays hidden and their measurements do
  not change. The cooldown fixture does show the strip, though, so the
  stages that check vertical sizes must be re-checked (see Verification).
- **Hosts:** a panel-only change. It reaches p620 and razer through the
  usual release → nixarchy → nixos_config chain. p510 stays on 1.0.0, as
  the owner decided.

## Verification

- `node tests/model.cjs`: new cases for `errorHint` (the project-list
  error, a stop in and out of the search box, an error that retries by
  itself) and for `emptyText`, covering each of the five steps and the
  order between them:
  - an error beats a pause;
  - a pause beats loading;
  - a project-list error during unfinished discovery shows the error, not
    loading;
  - loading with a filter says "no matches so far";
  - discovery finished with no repos;
  - discovery finished, with a filter and no match.
- `node tests/polling.cjs`, `python3 -m unittest`: unchanged, still pass.
- `python3 tests/qml-smoke.py`: one new stage, on the cooldown fixture so no
  request starts. It sets an auth stop and an error on `panel.polling`,
  calls `adopt()`, types text into the search box with `keyClick`, and
  checks:
  - `errorItem.visible` and its text contain both the error and the hint
    `Esc, then r`;
  - the placeholder does not contain the error;
  - with a filter that matches nothing, `emptyItem.text` is the error, not
    "no matches".

  It then clears the error and checks the strip shows only the pause. The
  existing zoom stages still pass; their "cooldown text shows" check now
  finds the pause in the strip and the footer.
- Manual check on p620 after deploy: log out of `glab`, open the panel, and
  check that the login error and hint stay visible while you type a
  search.
