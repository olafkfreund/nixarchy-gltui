---
status: draft
issue: 7
intent: intent/2026-09-24-7-finish-gitlab-port.md
---

# Spec: Finish the GitLab port

## Design

Defaults for the intent's open questions (the intent was approved without
answers; change them here if needed):

1. **Data field names stay.** Only the misleading comment changes. Renaming
   `run_attempt`, `display_title`, `html_url`, `head_branch` and `run_number`
   touches `actions.py`, `Polling.js`, `ActionsModel.js`, `ActionsPanel.qml`
   and most tests. That's a lot of churn for names users never see, and the
   #1 spec approved them.
2. **`keybindings.sh` stays.** Folding it into `menu.py` saves one small file
   and changes the menu entry commands users may already have registered.
3. **New names:** `PipelinesPanel.qml`, `PipelinesModel.js`, `gitlab.py`.

Changes, all behaviour-neutral:

- **User-facing text.** "Workflow helper" → "GitLab helper" in
  `ActionsModel.js:3` and `ActionsPanel.qml:167,169`; update the assertion in
  `tests/model.cjs:54`.
- **Comment.** `actions.py:123` becomes "Field names are shared with the panel
  model and scheduler; `conclusion` keeps GitLab's status." (no "GitHub").
- **Renames** with `git mv`, so history follows:
  - `ActionsPanel.qml` → `PipelinesPanel.qml`
  - `ActionsModel.js` → `PipelinesModel.js`
  - `actions.py` → `gitlab.py`
  - `tests/test_actions.py` → `tests/test_gitlab.py`

  Update every reference: `manifest.json:13` (`"panel"`), `flake.nix:18-21`
  (`runtimeFiles`), the QML import (`:8`) and helper path (`:38`),
  `tests/model.cjs:6`, the import and three `subprocess` calls in the Python
  test, and `tests/qml-smoke.py` (the `required` list, the copy list, the fake
  helper's file name, the `ActionsPanel {}` type at `:57`, and the temp
  prefix `actions-qml-` → `pipelines-qml-`). The fake helper keeps its body.
- **Dead and duplicated code:**
  - `Polling.js`: move the shared sort + "keep 10 completed or expanded" code
    (`:137-139` and `:218-220`) into one `trimRuns(s, r, runs)` that sets
    `r.runs`. Both call sites keep their own inputs (`union(r.runs, incoming)`
    and `union(t.all, keep)`).
  - `Polling.js:221`: delete `r.history=true`; nothing reads it.
  - `ActionsPanel.qml`: delete `repositories` (`:17`, `:139`) and use
    `repos.length` at `:63`, `:273`, `:306`. The `:63` debug JSON keeps its
    `repositories` key name.
  - `ActionsPanel.qml:32`: delete `loading`; `tests/qml-smoke.py` reads
    `workerBusy` instead (`:121`, `:128`).
  - `ActionsPanel.qml:38`, `:192`: one `function localPath(name)` for the
    `decodeURIComponent(Qt.resolvedUrl(...))` expression, used for both helpers.

## Alternatives rejected

- **Rename the data fields too.** See decision 1; it can be its own issue if
  wanted.
- **Keep the old file names and only fix text.** It leaves the "Actions"
  confusion the intent names as a problem.
- **Rename `Polling.js` or `menu.py`.** Their names are already neutral.
- **Read the plugin id from `root.manifest.id`** (`ActionsPanel.qml:123`).
  `manifest` defaults to `null` (`:14`) and the smoke test doesn't set it, so
  the literal id would be needed as a fallback anyway. Nothing gained.

## Risks

- **Installed plugin paths change.** The plugin id and `shell.json` keys stay,
  and omarchy loads the panel from `manifest.json`, so a normal
  `omarchy plugin update` picks up the new names. A copy installed by hand
  with a stale manifest would break. The manifest and files ship together, so
  this isn't expected.
- **Rebase with PR #8.** #8 edits `ActionsPanel.qml`. Implement after #8 is
  merged, and rebase this branch first, so `git mv` carries #8's changes.

## Verification

- `nix flake check` passes. Its runtime-files check proves the renamed files
  ship.
- `python3 tests/qml-smoke.py` and `python3 tests/qml-smoke.py ./result` print
  `QML_CHECKS_PASSED`.
- `omarchy plugin validate "$(readlink -f result)"` exits 0.
- `grep -rni github --exclude-dir=.git --exclude-dir=intent --exclude-dir=spec --exclude-dir=plan --exclude=flake.lock .`
  lists only `flake.nix:4` and the README sibling link.
- `grep -rn 'Workflow\|ActionsPanel\|ActionsModel\|actions\.py\|r\.history\|root\.repositories\|loading' --exclude-dir=.git --exclude-dir=intent --exclude-dir=spec --exclude-dir=plan .`
  → no output.
- `git log --follow gitlab.py` shows the history from before the rename.
