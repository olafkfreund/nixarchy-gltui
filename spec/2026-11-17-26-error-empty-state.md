---
status: draft
issue: 26
intent: intent/2026-11-17-26-error-empty-state.md
---

# Spec: Keep errors visible and make the empty state honest

## Design

All changes are in `PipelinesPanel.qml` and `tests/qml-smoke.py`, the scope
the intent approved. The polling, model and helper code do not change.

### 1. No error-type tracking

The hint is chosen from state the panel already has, which is
`polling.auth`, `catalogueError` and the error text, plus whether the
search box has focus. No new property is added. Reply types are not
tracked, because `Polling.complete` can replace a reply with its own setup
error (`Polling.js:206`), and a restarted request's reply is discarded
(`Polling.js:213`). So the reply the panel sees is not always the error
being shown.

### 2. Two pure functions on the panel root

These functions are on `root`, so the smoke test can call them directly
with any inputs and also check the bindings that use them.

```js
// Advice for the current error, or "" when no action is needed.
function errorHint(error, catalogueError, stopped, filtering)
// The text of the empty list.
function emptyText(error, hint, cooldownText, discoveryComplete, repoCount, filter)
```

**`errorHint`** returns the first hint that applies (`k` is `r` or `R`):

| Condition | Hint, outside the search box | Hint, inside the search box |
|---|---|---|
| The project list was refused: `error !== ""` and `error === catalogueError` | `check the token's access, then press R` | `check the token's access, then press Esc and R` |
| Stopped (`polling.auth`), and the message names neither `glab` nor `shell log` | `see the shell log, then press r` | `see the shell log, then press Esc and r` |
| Stopped (`polling.auth`), any other message | `then press r` | `then press Esc and r` |
| Anything else | `""` | `""` |

Notes on the table:
- `error === catalogueError` holds even when `polling.error` is also set,
  because a permission refusal sets both (`Polling.js:216,220`).
- `polling.auth` is set for both `auth` and `setup` errors
  (`Polling.js:218`). `r` clears it (`Polling.manual`, `Polling.js:53`), and
  only `R` clears `catalogueError` (`Polling.js:54`).
- `r` and `R` do not reach the panel while the search box has focus. Esc
  leaves the box first (`PipelinesPanel.qml:344-346`).
- **Login errors:** the helper's message already says what to fix:
  "Authenticate with glab auth login" (`gitlab.py:181,207`).
- **Setup errors:** these keep their real message:
  - "python3 not found";
  - "GitLab helper failed (exit N); see the shell log";
  - "Install glab (GitLab CLI)";
  - "GitLab helper returned invalid data", with or without "; see the shell
    log".

  "python3 not found", and the bare "invalid data" message from
  `Polling.js:206`, get "see the shell log". So does a helper `ValueError`
  (`gitlab.py:262-264`). Messages that already name `glab` or the shell log
  get only the key. Every message that sets `polling.auth` is one of our
  own fixed strings, or a helper exception message, never GitLab server
  text. So matching on `glab` and `shell log` is safe here.
- **Other errors** get no hint. Network and rate errors retry by
  themselves, and a refused single project is marked blocked on its own row
  (`Polling.js:221`); that row already shows the error. This change does not
  add recovery advice for those.

**`emptyText`** returns the first match, in the order approved in the
intent:

1. An error: `error + (hint ? " — " + hint : "")`.
2. A pause: `cooldownText`.
3. Discovery not finished:
   - with a filter: `"Still discovering projects… no matches so far"`;
   - without one: `"Discovering projects…"`.
4. Discovery finished, no projects: `"No projects found on this account"`.
5. A filter set: `"No projects or pipelines match “<filter>”"`.
6. Otherwise: `"No matching projects or pipelines"` (the old text, kept as
   a fallback; today's model never hides every row without a filter).

### 3. An error strip

A new `Text` (`id: errorStrip`) goes between the search box and the
hairline, inside the existing `Column`.

- **When it shows:** `visible: root.error !== "" || root.cooldownText !== ""`.
  A `Column` gives no space to invisible children, so the layout is
  unchanged when there is no error.
- **What it says:** the non-empty parts, joined with `" · "`:
  - the error, followed by `" — " + hint` if there is a hint;
  - the pause.

  A pause alone has no leading separator.
- **Style:**
  - colour `Commons.Color.urgent`;
  - font size `root.zf(Style.font.caption)`;
  - `wrapMode: Text.Wrap`, capped at two lines with `maximumLineCount: 2`
    and `elide: Text.ElideRight`;
  - `textFormat: Text.PlainText`.
- **Keeping the cursor in view:** the list's height already follows its
  `y` (`PipelinesPanel.qml:368`). But the list only repositions while a zoom
  settles (`PipelinesPanel.qml:373`). The strip can change the list's height
  in two ways: by appearing or disappearing, and by wrapping from one line
  to two. So it calls one function from both `onVisibleChanged` and
  `onHeightChanged`:

  ```qml
  function keepCursor() { Qt.callLater(function() {
      if (root.opened && root.cursor >= 0 && root.cursor < list.count)
          list.positionViewAtIndex(root.cursor, ListView.Contain)
  }) }
  ```

  The cursor row then stays in view when an error appears, clears, or
  grows.

### 4. Search placeholder, empty list and footer

- **Search placeholder** (`PipelinesPanel.qml:355-357`): it no longer shows
  the error or the pause. It keeps the hint and progress text: "Search
  projects…", "Activity checked N/M…" and "Discovering projects… N found".
  Its colour is always `Commons.Color.menu.text`.
- **Empty list** (`PipelinesPanel.qml:429-435`): `text` binds to
  `root.emptyText(...)`. It also gets:
  - `width: parent.width` with side padding;
  - `wrapMode: Text.Wrap` and `horizontalAlignment: Text.AlignHCenter`;
  - `textFormat: Text.PlainText`;
  - `Commons.Color.urgent` when it shows an error, `menu.text` otherwise.
- **Footer:** unchanged. It already shows the pause in place of the key
  hints (`PipelinesPanel.qml:444`).

### 5. Test hooks

Two read-only hooks join the existing ones (`PipelinesPanel.qml:68-73`):
`errorItem: errorStrip` and `emptyItem` (the empty-list `Text`).

## Alternatives rejected

- **Show the error in the footer:** the footer is the only list of keys,
  and the intent chose the strip.
- **Put the functions in `PipelinesModel.js` with unit tests:** easier to
  test, but the approved intent keeps the model unchanged. The smoke test
  calls the root functions directly instead.
- **Track `errorType`:**
  - in the polling state: the intent rules out new polling state;
  - in the panel, from each reply: wrong when `Polling.complete` replaces
    the reply, or discards it.
- **Choose all advice from the error text:** brittle for server text.
  Matching is limited to the case where polling has stopped, and every
  message in that case is our own.
- **Keep the error in the placeholder and also show it while typing:** a
  placeholder and typed text cannot share one line.

## Risks

- **Layout shift:** the strip pushes the list down when an error appears.
  This is acceptable, because errors need attention. The cursor row is
  repositioned (section 3).
- **Long messages:** the strip is capped at two lines, with an ellipsis.
- **Zoom smoke stages (#22):** the zoom fixture sets a one-hour pause
  (`tests/qml-smoke.py:365`), so the strip is visible for all zoom stages,
  and the list is one or two lines shorter. Most of those checks compare
  relative sizes. The checks that depend on the list's viewport (the cursor
  row staying contained after zoom, `tests/qml-smoke.py:168-185`) must still
  pass. If one does not, the fix is in the stage's measurement, not in
  hiding the strip.
- **Hosts:** a panel-only change. It reaches p620 and razer through the
  usual release → nixarchy → nixos_config chain. p510 stays on 1.0.0, as
  the owner decided.

## Verification

- `node tests/polling.cjs`, `node tests/model.cjs` and
  `python3 -m unittest`: unchanged, still pass.
- `python3 tests/qml-smoke.py`: new stages run before the zoom stages, on
  their own fixture with no pause. `panel.workerBusy` is set to `true`
  during these stages, so `pump()` (`PipelinesPanel.qml:188`) starts no
  request, even though projects have summary tasks due. It is reset
  afterwards. They check the following.
  - **The functions directly:** every row of the `errorHint` table, both
    inside and outside the search box, and every step of `emptyText`. That
    includes the cases where order matters:
    - an error beats a pause;
    - a pause beats loading;
    - a project-list error during unfinished discovery shows the error;
    - loading with a filter shows "no matches so far".
  - **The bindings, through the real UI:**
    - Loading: no repos, discovery unfinished; `emptyItem.text` is
      "Discovering projects…".
    - Activity still running: discovery finished with repos, some not yet
      checked. The placeholder shows "Activity checked N/M".
    - No projects: discovery finished with none.
    - No matches: a filter that matches nothing.
    - Login stop: `polling.auth` and an auth error.
      - With the search box focused but empty, `errorItem` is visible with
        the error and `Esc and r`, and the placeholder does not contain the
        error.
      - After typing with `keyClick`, the same holds, and `emptyItem.text`
        is the error, not "no matches".
    - Pause without an error: the strip shows only the pause.
    - Cursor in view: with the cursor on the last row of a full list, the
      row stays inside the viewport in two cases: when the strip appears,
      and when a pause-only strip gains a long error and wraps to two
      lines.

  The stages then restore the filter, focus, error state and fixture, so
  the existing zoom stages start as before. They wait one frame before
  checking any sizes.
- The existing zoom stages still pass with the strip visible.
- Manual check on p620 after deploy: log out of `glab`, open the panel,
  focus the search box and type. The login error and its hint stay
  visible. Press Esc and `r` after logging back in, and the list fills.
