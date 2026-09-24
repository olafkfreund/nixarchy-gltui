---
status: approved
issue: 7
author: olafkfreund
---

# Intent: Finish the GitLab port

## Problem

The plugin was ported from the GitHub Actions panel (nixarchy-ghtui), and
parts of the old identity are still visible or misleading:

- **The approved spec is not met.** `spec/2026-09-18-1-gitlab-pipelines.md`
  says every GitHub label and error message changes, and its verification
  greps for `github` expecting only the sibling link and the flake URL. Today:
  - users see "Workflow helper returned…" errors (`ActionsModel.js:3`,
    `ActionsPanel.qml:167,169`; asserted in `tests/model.cjs:54`);
  - `actions.py:123` has a comment about "GitHub-shaped fields", which fails
    the grep.
- **File names say "Actions".** `ActionsPanel.qml`, `ActionsModel.js` and
  `actions.py` read as GitHub Actions to anyone opening the repo or the
  installed plugin.
- **Small dead or duplicated code** from the port:
  - the same trim-runs block twice (`Polling.js:137-139`, `:218-220`);
  - `r.history` written and never read (`Polling.js:221`);
  - `repositories` and `loading` in `ActionsPanel.qml` only repeat `repos`
    and `workerBusy`;
  - a repeated local-path expression (`ActionsPanel.qml:38`, `:192`);
  - the plugin id hard-coded in the QML (`:123`) although `root.manifest.id`
    holds it.

## Proposed outcome

- No user-facing text mentions workflows or GitHub; the spec's `github` grep
  passes.
- Source files have GitLab-appropriate names, and the manifest, flake,
  tests and README refer to them.
- The listed dead and duplicated code is gone, with no change in behaviour.

## Affected users and systems

- Files: `ActionsPanel.qml`, `ActionsModel.js`, `actions.py`, `Polling.js`,
  `manifest.json` (entry point), `flake.nix` (`runtimeFiles`), `tests/*`,
  `README.md`.
- Installed users: the plugin id and `shell.json` keys stay the same, so an
  update needs no config change.

## Constraints

- No behaviour change: polling, data, keys and the menu stay the same.
- Keep the plugin id `olafkfreund.gitlab-pipelines` and the `shell.json` keys.
- Leave menu registration as #4/#5 decided (the `menu.managed` marker).
- Land after PR #8, which edits `ActionsPanel.qml`. It merges cleanly with
  `main` today, but a rename right after would make #8 painful to rebase.
- Must pass `nix flake check`, the QML smoke test and `omarchy plugin
  validate`.

## Open questions

1. **Data field names.** The helper still returns GitHub-shaped keys
   (`run_attempt` holds a timestamp, `display_title` holds the commit SHA,
   also `html_url`, `head_branch`, `run_number`). Rename them to GitLab or
   neutral names in this task, or leave them and only fix the comment?
2. **`keybindings.sh`.** It only prints the key list. Fold it into `menu.py`
   (one file fewer), or keep it?
3. **New file names.** Proposed: `PipelinesPanel.qml`, `PipelinesModel.js`,
   `gitlab.py`. Other preferences?
