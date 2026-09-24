---
status: approved
issue: 7
spec: spec/2026-09-24-7-finish-gitlab-port.md
---

# Plan: Finish the GitLab port

Approved decisions (from the spec):

- No behaviour change. Plugin id `olafkfreund.gitlab-pipelines` and
  `shell.json` keys stay; menu registration stays as #4/#5 left it.
- Data field names (`run_attempt`, `display_title`, `html_url`,
  `head_branch`, `run_number`) stay; only the comment in `actions.py` changes.
- `keybindings.sh`, `Polling.js` and `menu.py` keep their names.
- Renames (with `git mv`): `ActionsPanel.qml` → `PipelinesPanel.qml`,
  `ActionsModel.js` → `PipelinesModel.js`, `actions.py` → `gitlab.py`,
  `tests/test_actions.py` → `tests/test_gitlab.py`.
- "Workflow helper" → "GitLab helper" in user-facing errors.
- Cleanups: one `trimRuns` in `Polling.js`; delete `r.history`,
  `repositories`, `loading`; one `localPath(name)` in the panel.
- The plugin id literal in the panel stays (`manifest` is `null` in tests).
- Implement only after PR #8 is merged, on a rebased branch.

Line numbers below are from `main` at `b9c0f30`; after #8 they may shift by
one, so each step also names the code it changes.

## Steps

1. Gate: `gh pr view 8 --json state` is `MERGED`; then
   `git fetch && git rebase origin/main` on `chore/7-finish-gitlab-port`
   → verify `git merge-base --is-ancestor origin/main HEAD`.
2. Text and comment, before renaming so the diffs stay readable:
   - `ActionsModel.js:3`: `"Workflow helper returned no data (exit "` →
     `"GitLab helper returned no data (exit "`.
   - `ActionsPanel.qml` `receivePage`: both "Workflow helper returned…" strings
     → "GitLab helper returned…".
   - `tests/model.cjs:54`: expected string → `'GitLab helper returned no data (exit 1)'`.
   - `actions.py:123`: comment → `# Field names are shared with the panel model and scheduler; conclusion keeps GitLab's status.`

   → verify `grep -rn 'Workflow' --exclude-dir=.git --exclude-dir=intent --exclude-dir=spec --exclude-dir=plan .` is empty.
3. `Polling.js`: add
   `function trimRuns(s,r,runs) { var completed=0; r.runs=runs.sort(function(a,b) { return (a.status==="completed")-(b.status==="completed") || b.id-a.id }).filter(function(run) { return run.status!=="completed" || ++completed<=10 || s.expanded[r.repo+":"+run.id] }); }`
   Replace the three lines after `invalidateJobs(s,r,incoming);` with
   `trimRuns(s,r,union(r.runs || [],incoming));`, and the three lines after
   `var keep=…` with `trimRuns(s,r,union(t.all,keep));`. In
   `r.summaryAt=now; r.history=true;` delete `r.history=true;`
   → verify `node tests/polling.cjs` passes and `grep -c history Polling.js` = 0.
4. `ActionsPanel.qml` cleanups:
   - Delete `property var repositories: []` and the
     `repositories = repos.map(…)` line.
   - `root.repositories.length` / `repositories.length` → `root.repos.length` /
     `repos.length`. The debug JSON key `repositories:` stays.
   - Delete `readonly property bool loading: workerBusy`; in
     `tests/qml-smoke.py`, `panel.loading` → `panel.workerBusy` (2 places).
   - Add `function localPath(name) { return decodeURIComponent(Qt.resolvedUrl(name).toString().replace(/^file:\/\//, "")) }`;
     `helper` becomes `localPath("actions.py")`, and the registration command
     uses `localPath("menu.py")`.

   → verify `python3 tests/qml-smoke.py` prints `QML_CHECKS_PASSED`.
5. Commit steps 2–4 as `refactor: GitLab wording and dead code (#7)`.
6. Renames:
   `git mv ActionsPanel.qml PipelinesPanel.qml`,
   `git mv ActionsModel.js PipelinesModel.js`, `git mv actions.py gitlab.py`,
   `git mv tests/test_actions.py tests/test_gitlab.py`. Then update:
   - `manifest.json` `"panel": "PipelinesPanel.qml"`
   - `flake.nix` `runtimeFiles` (three names)
   - `PipelinesPanel.qml`: `import "PipelinesModel.js" as Model`, `localPath("gitlab.py")`
   - `tests/model.cjs:6`: `'PipelinesModel.js'`
   - `tests/test_gitlab.py`: `import gitlab`, every `actions.` module
     reference → `gitlab.`, and the three `"actions.py"` subprocess args → `"gitlab.py"`
   - `tests/qml-smoke.py`: the `required` and copy lists, the fake helper
     file `'gitlab.py'`, `PipelinesPanel { id: panel }`, temp prefix `'pipelines-qml-'`

   → verify step 7's greps, then commit as
   `refactor: rename files to GitLab names (#7)`, kept separate so
   `git log --follow` tracks the renames.
7. Checks (see Tests), then push and open a PR linking all three artifacts,
   `Closes #7`.

## Tests

- `nix flake check` → all checks passed.
- `nix build .#default && python3 tests/qml-smoke.py ./result` and
  `python3 tests/qml-smoke.py` → `QML_CHECKS_PASSED`.
- `omarchy plugin validate "$(readlink -f result)"` → exit 0.
- `grep -rni github --exclude-dir=.git --exclude-dir=intent --exclude-dir=spec --exclude-dir=plan --exclude=flake.lock .`
  → only `flake.nix:4` and the README sibling link.
- `grep -rnE 'Workflow|ActionsPanel|ActionsModel|actions\.py|import actions|r\.history|repositories = |\.loading' --exclude-dir=.git --exclude-dir=intent --exclude-dir=spec --exclude-dir=plan .`
  → no output.
- `git log --follow --oneline gitlab.py | wc -l` > 2.

## Rollback

`git revert` the two implementation commits (rename first). Installed users
update through `omarchy plugin update`; the plugin id and config are
unchanged, so reverting needs no user action.
