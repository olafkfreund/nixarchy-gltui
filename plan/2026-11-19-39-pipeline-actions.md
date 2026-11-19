---
status: approved
issue: 39
spec: spec/2026-11-19-39-pipeline-actions.md
coders:
  1: codex   # helper write path: validation, encoding and error mapping, security-sensitive
  2: codex   # Polling.js touch/restart/cooldown: small tricky scheduling logic
  3: coder   # model helpers: pure functions and their tests
  4: coder   # panel wiring: state, keys, process, footer
  5: codex   # smoke stage: async steps, timing and key traps
  6: coder   # docs, key sheet, version
reviewers:
  - codex    # fresh diff review against this plan (agy is out of use, #2748)
---

# Plan: Retry, cancel, play and trigger pipelines from the panel

Work in the worktree `/mnt/code/Source-home/GitHub/nixarchy-gltui-39`,
branch `feat/39-pipeline-actions`. Line numbers are from `main` at
`3f998d0`.

## Decisions (from the approved spec)

- **Actions, keys and rows.** The raw object decides, never the mapped row
  `status`: a pipeline from `Polling.runFor(polling, row.repo, row.run)`
  (`Polling.js:29`), a job by `id` from
  `polling.details[row.repo + ":" + row.run].jobs`. `conclusion` is GitLab's
  raw status (`gitlab.py:232`, `:243`). Missing raw object → notice
  "Select the row again", nothing else.

  | Key | Row | Action | Offered when raw `conclusion` is | Request |
  | --- | --- | --- | --- | --- |
  | `a` | run | `retry-pipeline` | `failed`, `canceled` | `POST projects/:id/pipelines/:pipeline/retry` |
  | `a` | job | `retry-job` | `failed`, `canceled` | `POST projects/:id/jobs/:job/retry` |
  | `c` | run | `cancel-pipeline` | `created`, `waiting_for_resource`, `preparing`, `pending`, `running`, `scheduled` | `POST projects/:id/pipelines/:pipeline/cancel` |
  | `c` | job | `cancel-job` | the same list | `POST projects/:id/jobs/:job/cancel` |
  | `x` | job | `play-job` | `manual` | `POST projects/:id/jobs/:job/play` |
  | `n` | run | `new-pipeline` | any, raw `ref` set, not starting `refs/merge-requests/`, `source !== "merge_request_event"` | `POST projects/:id/pipeline?ref=<quote(ref, safe="")>` |

  `:id` is `quote(project_path(repo), safe="")`, as `page_endpoint` does.
  Repo, stage, trigger (`»`), more and message rows offer nothing. A key
  not offered gives a reason notice and never opens a confirmation:
  "Only a failed or canceled pipeline can be retried", "Only a failed or
  canceled job can be retried", "Only a running or queued pipeline can be
  canceled", "Only a running or queued job can be canceled", "Only a
  manual job can be played", "Merge-request pipelines cannot be started
  from the panel", "Select a pipeline or job" (other rows). Successful-job
  retry and manual-job cancel are left out on purpose.
- **Setting.** `"actions": true` in the `olafkfreund.gitlab-pipelines`
  entry of `~/.config/omarchy/shell.json`; anything else is off. Off: the
  four keys only notify
  `Actions are off: set "actions": true for this plugin in shell.json`.
- **Helper gate.** `act` mode reads `$HOME/.config/omarchy/shell.json`,
  and refuses with `errorType "disabled"` ("Actions are off in
  shell.json") unless the entry has `actions === true` and its host
  (default `gitlab.com`, compared lowercased) equals the task's host.
  Missing or invalid file → `disabled`. The gate and all validation run
  before `request()`.
- **Write request.** `["glab", "api", "--hostname", host, "--include",
  "--method", "POST", endpoint]`. No `-f`, `-F`, `--input`; `glab` sends an
  empty `{}` body. Ref: string, 1-255 chars, no char below U+0020 and no
  U+007F, not starting `refs/merge-requests/`. Job and pipeline IDs:
  digits, ≥ 1.
- **Reply** `{requestId, action, httpStatus, ok, error, errorType, retryAt,
  remaining, resetAt, created}`; `created` is `{id, iid}` from a 2xx body
  dict when present (new pipeline, retried job), else `null`.

  | Condition (checked in this order) | errorType | Text |
  | --- | --- | --- |
  | 2xx | `""`, `ok: true` | `""` |
  | rate: 429, `remaining == 0` on a non-2xx, `retryAt`, "rate limit" in message | `rate` | "GitLab rate limit" |
  | 401, or empty stdout and "auth login" in stderr | `auth` | "Authenticate with glab auth login" |
  | 403 and body `error` or `message` contains `insufficient_scope` | `scope` | "Needs a token with the api scope" |
  | other 403, 400, 404, 409, 422 and other 4xx | `refused` | "GitLab refused: " + message |
  | 3xx | `refused` | "GitLab redirected the request; the project may have moved" |
  | `FileNotFoundError` from `Popen` | `setup` | "Install glab (GitLab CLI)" |
  | timeout, nonzero exit with no HTTP reply, unparsable reply, 5xx | `unknown` | "Outcome unknown; check GitLab before retrying" |

  Message: a string, or the strings found in a dict/list body
  (`{"message": {"base": ["..."]}}`), joined with "; ", passed through
  `plain()`, cut to 120 chars. A 2xx still fills `remaining`/`resetAt`/
  `retryAt` so the panel can pause polling. The write path never returns
  `permission`.
- **Panel.**
  - New properties: `actionsOn`, `confirm` (null or target), `pendingAction`,
    `actionBusy`, `actionId`, `actionSerial`, `actionStarted`, `actionFailed`,
    `hostEpoch`, `missedAction`,
    `actionCommand` (default `["python3", helper, "act"]`).
  - Target `{action, host, epoch, repo, run, job, ref, source, text, done}`, all
    copied strings.
  - While `confirm` is set the main key handler swallows every key: plain
    `y`, not auto-repeat, confirms; Esc clears; the rest do nothing
    (including `/`, Enter, `q`).
  - `y` moves `confirm` to `pendingAction`, clears `confirm`, and sets
    `actionBusy` in one handler.
  - `close()`, a host change and `actionsOn` → false clear `confirm` and
    `pendingAction` and stop the wait timer.
  - Gates before opening a confirmation and again right before starting the
    process: `actionsOn`, the same `host` and `hostEpoch`, no cooldown ("GitLab
    paused until HH:MM; try again then"), and not `actionBusy` ("An action is
    already running"; only checked on open).
  - Spacing: if `now - max(polling.lastStarted, polling.writeAt) < 1000`,
    wait the rest with a one-shot `Timer`, then re-check every gate.
  - Separate `actionProc`. It is not stopped by `close()`.
  - The reply is matched by `requestId === actionId`. Every result is shown,
    and one from another epoch is prefixed `on <host>: `.
  - `Polling.noteWrite` and `Polling.touch` run only if the epoch matches.
  - Result: `notify(text, 10000)`, failures urgent-coloured. A result that
    arrives while closed goes to `missedAction`, shown on open with
    `notify(missedAction, 10000)` after `showMissed()`.
  - Footer: `confirm ? confirm.text : (notice || cooldownText || hint)`,
    wrapping while `confirm` is set.
- **Polling.**
  - `cool(s, reply, now)` is lifted from `complete()`.
  - `noteWrite(s, reply, now)` calls only `cool`.
  - `writeStarted(s, now)` sets `s.writeAt = now`.
  - `next()` waits 1 s after `s.writeAt`, but writes do not enter `starts`.
  - `touch(s, repo, run, now)` ensures and `restart()`s the run lookup, the
    project's `summary` task if present (and deletes `r.summaryAt`), and the
    `jobs` task if the pipeline is expanded.

## Steps

1. **Helper write path** — `gitlab.py`, `tests/test_gitlab.py`.
   - Docstring (line 1) → "GitLab pipeline data and a closed set of
     pipeline and job actions, using glab's existing authentication."
   - `numeric_id(value, label)`: lift the check at lines 140-142; use it
     in `page_endpoint` and the new code. Keep the existing error text
     "Invalid pipeline ID" for pipelines.
   - `request(endpoint, host, method=None)` (line 113): insert
     `"--method", method` before the endpoint when set. Nothing else in the
     argument list changes.
   - `limits(headers, result)`: lift lines 306-316 out of `read_page` and
     call it there; `read_page` behaviour is unchanged.
   - `pipeline()` (line 222): add `"ref"` (raw ref if `valid_ref`, else
     `""`) and `"source"` (raw if `re.fullmatch(r"[a-z_]{1,40}")`, else
     `""`). `head_branch` unchanged.
   - `ACTIONS` table (action → (needs job, path suffix)). Then
     `write_endpoint(task)`, `actions_enabled(host)` (reads the config
     path from `$HOME`), `message_text(body)` and `write_action(task)`,
     following the Decisions tables exactly.
   - `main()`: `choices=("page", "pins", "act")`. `act` uses the same alarm,
     SIGTERM and error-echo shape as `page`. A `ValueError` before any
     request gives `errorType "setup"`; `DeadlineExceeded` gives `unknown`.
   - Tests in `tests/test_gitlab.py`, mocking `request` (and `HOME` via a
     temp dir):
     - every action's endpoint and the exact argument list, with no `-f`;
     - rejected IDs, refs and actions;
     - refs with `&#%+/` and Unicode round-tripping through `unquote`;
     - the MR source refused;
     - the gate: missing, off, other host, bad JSON, with `request` never
       called;
     - every reply-table row, including the real scope body
       `{"error":"insufficient_scope","error_description":"…","scope":"api"}`,
       nested messages, non-JSON, 5xx, timeout, and a 2xx with
       `remaining: 0`;
     - `created`;
     - `pipeline()["ref"]` keeping a ref that `plain()` would change.
   - Check:

     ```bash
     python3 -m unittest discover -s tests
     ```

   - Traps: never build an endpoint from task text other than validated
     IDs and the encoded ref. The read output changes only by the two new
     pipeline fields `ref` and `source`: update the exact dictionary in
     `test_pipeline_fields_and_attempt` (`tests/test_gitlab.py:214-220`) to
     include them (`"ref": "main"`, and `"source"` from the fixture), and
     keep every other field and all read-error behaviour unchanged. Do not
     touch `pins`.
2. **Polling** — `Polling.js`, `tests/polling.cjs`.
   - `create()` gets `writeAt:0`; `resetHost` keeps `writeAt`, as it keeps
     `starts`.
   - Lift lines 326-331 into `cool(s, reply, now)`; `complete()` calls it
     in the same place.
   - Add `noteWrite(s, reply, now)` (calls `cool`, sets `s.wakeAt = 0`,
     nothing else) and `writeStarted(s, now)`.
   - In `next()` (line 223) also return null when
     `now - s.writeAt < 1000`.
   - Add `touch(s, repo, run, now)`:
     - `restart(s, ensure(s, "run", repo, run, "interactive", now), now)`;
     - if `repoFor` finds the project: `delete r.summaryAt`, and `restart`
       the summary task if `s.tasks[key("summary", repo, "")]` exists;
     - if `s.expanded[repo + ":" + run]`:
       `restart(s, ensure(s, "jobs", repo, run, "interactive", now), now)`.
   - Declare ordinary top-level functions. The QML `import` and the Node
     VM loaders (`tests/polling.cjs:17-19`, `tests/model.cjs:4-6`) expose
     them automatically. Do not add `module.exports`: it breaks QML.
   - Tests in `tests/polling.cjs`, covering the spec's polling verification
     list:
     - a new task, and an existing backed-off task due now;
     - an in-flight run, summary and paged jobs task each restarted, with
       stale data not published;
     - a watched pipeline not settled from the stale reply;
     - `noteWrite` with no change to `error`, `auth`, `blocked`, `tasks` or
       `starts`, and its cooldown;
     - the 1 s gap after `writeAt`.
   - Check:

     ```bash
     node tests/polling.cjs
     ```

   - Traps: `restart()` on an in-flight task only flags it, so
     `complete()` handles the rest. `complete()` must still apply `cool`
     before the `t.restart` return, which it does today (line 332).
3. **Model** — `PipelinesModel.js`, `tests/model.cjs`.
   - `actionFor(key, row, raw)` → `{action}` or `{reason}`. `key` is one of
     `"a"`, `"c"`, `"x"`, `"n"`.
   - `describe(action, repo, run, job)`, where `run` and `job` are raw
     objects (`job` only for job actions), returns `{confirm, done}`.
     Name and ref are cut to 30 chars with `…`; the project path is not cut.
     - Confirmation texts:
       - `Retry pipeline #<iid> <name> (<ref>) in <repo>? y yes · Esc no`
       - `Cancel pipeline #<iid> <name> (<ref>) in <repo>? Cannot be undone. y yes · Esc no`
       - `Retry job <name> (job <id>) of #<iid> in <repo>? y yes · Esc no`
       - `Cancel job <name> (job <id>) of #<iid> in <repo>? Cannot be undone. y yes · Esc no`
       - `Play manual job <name> (job <id>) of #<iid> in <repo> with its default variables? y yes · Esc no`
       - `Start a new pipeline on <ref> in <repo> with default variables? y yes · Esc no`
     - Done texts: `Retry requested: …`, `Cancel requested: …`,
       `Play requested: …`, `New pipeline requested on <ref> in <repo>`.
       The display ref is `head_branch`.
   - `actionReply(stdout, code, requestId)`:
     - empty stdout with code 127 → `{errorType: "setup", error: "python3 not found"}`;
     - empty stdout with another code, unparsable text or a wrong
       `requestId` → `unknown` with the fixed text;
     - otherwise the parsed object.
   - Tests in `tests/model.cjs`: every key × row kind and every status
     list; an MR pipeline with a plain branch ref; a successful job
     refused; the texts and cuts; `actionReply`.
   - Check:

     ```bash
     node tests/model.cjs
     ```

   - Traps: none of these may read QML state. Keep them pure.
4. **Panel** — `PipelinesPanel.qml`.
   - Properties as in Decisions.
   - In `configure()` (line 370), set `actionsOn = !!entry && entry.actions === true`.
     When `hostChanged`, also run `hostEpoch++` and `dropAction("Host
     changed; nothing was sent")`. Add `onActionsOnChanged: if (!actionsOn)
     dropAction("Actions are off")`.
   - `close()` (line 184): add `dropAction("")`. It does not touch
     `actionProc`.
   - `open()`, after `showMissed()` (line 128): `if (missedAction) {
     notify(missedAction, 10000); missedAction = "" }`.
   - `notify(t, ms)` (line 242): `noticeTimer.interval = ms || 2000`
     before the restart.
   - `startAction(key)`:
     1. gate `actionsOn`, then `actionBusy`;
     2. resolve the raw object, then `Model.actionFor`;
     3. gate the cooldown;
     4. `confirm = {…, text: d.confirm, done: d.done, epoch: hostEpoch, host: host}`.
   - `confirmAction()`:
     - `pendingAction = confirm; confirm = null; actionBusy = true; sendAction()`.
   - The task sent is built from `pendingAction` only:
     `{action, host, repo, run, job, ref, source, requestId: actionId}`,
     where `job`, `ref` and `source` are included only when the action
     needs them.
   - `sendAction()`:
     1. re-check `actionsOn`, the host and epoch, and the cooldown; on
        failure call `dropAction(reason)`;
     2. compute the wait from `max(polling.lastStarted, polling.writeAt)`;
        if it is above 0, start `actionWait` with that interval and return;
     3. otherwise `actionId = ++actionSerial`, `actionStarted = false`;
     4. set `actionProc.command = actionCommand.concat([JSON.stringify(task)])`,
        `actionProc.epoch = pendingAction.epoch`,
        `actionProc.host = pendingAction.host`,
        `actionProc.requestId = actionId`,
        `actionProc.target = pendingAction`;
     5. clear `pendingAction`, start the process, and call
        `Polling.writeStarted(polling, Date.now())`.
   - `dropAction(text)`:
     - clear `confirm` and `pendingAction`, stop `actionWait`;
     - set `actionBusy = actionProc.running`;
     - `notify(text)` if `text` is set.
   - `finishAction(code, text)` reads only the snapshot on `actionProc`
     (`target`, `epoch`, `host`, `requestId`), never `pendingAction` or
     `confirm`, because close, setting off and a host change may have
     cleared those while the process ran:
     1. compute `r = Model.actionReply(text, code, actionProc.requestId)`;
     2. set `actionBusy = false`;
     3. if `actionProc.epoch === hostEpoch`: `Polling.noteWrite(polling, r, Date.now())`,
        and on `r.ok` also `Polling.touch(polling, actionProc.target.repo, actionProc.target.run, Date.now())`,
        then `adopt(); pump()`;
     4. build the message: on success `target.done`, plus
        ` · refresh waits until HH:MM` during a cooldown, plus
        ` · new pipeline #N` when `created.iid` is set; otherwise `r.error`.
        Prefix `on <actionProc.host>: ` when the epoch differs;
     5. if `opened`, `notify(msg, 10000)` and set `actionFailed = !r.ok`;
        otherwise `missedAction = msg`.
   - `Process actionProc`: `property int epoch`, `property string host`,
     `property int requestId`, `property var target`,
     `stdout: StdioCollector`, `onStarted: actionStarted = true`,
     `onExited: finishAction(code, out.text)`, and
     `onRunningChanged: if (!running && !actionStarted) finishAction(127, "")`,
     the pattern at lines 505-512.
   - `Timer actionWait { repeat: false; onTriggered: sendAction() }`.
   - Key handler (line 613):
     - first, when `confirm` is set, call `confirmKey(event)` and return.
       `confirmKey(e)` is a plain function (so the smoke test can call it
       with an event-shaped object): it sets `e.accepted = true`; if
       `e.key === Qt.Key_Y && e.modifiers === Qt.NoModifier &&
       !e.isAutoRepeat` → `confirmAction()`; if `e.key === Qt.Key_Escape`
       → `dropAction("Nothing was sent")`; anything else does nothing.
       It must run before the existing `plain` variable (line 626), which
       allows Shift; confirmation requires no modifier at all.
     - then, in navigation mode next to `w` (line 635): plain `a`/`c`/`x`/`n`
       without shift → `startAction`.
   - Footer (line 836):
     - text `root.confirm ? root.confirm.text : (existing)`;
     - `wrapMode: root.confirm ? Text.Wrap : Text.NoWrap`;
     - `elide: root.confirm ? Text.ElideNone : Text.ElideRight` (line 840);
     - colour urgent when `actionFailed && notice`.
   - `listHint` (line 51): when `actionsOn`, insert `a/c/x/n act` after
     `w watch`. Make it a function or a ternary, since it is `readonly`.
   - `status()` (line 196): add `actionsOn`, `confirm: confirm ? confirm.text : ""`, `actionBusy`.
   - Check:

     ```bash
     nix build .#checks.x86_64-linux.plugin
     ```

     It runs the unit, model and polling tests.
   - Traps:
     - Quickshell 0.3.1 emits only `running=false` on a failed start.
     - Do not reuse `requestProc`, `workerBusy` or `Polling.flight`.
     - `polling` is reassigned by `adopt()` (line 414), so never store it.
     - The key handler at line 677 (search field) must not get the action
       keys.
     - Keep `Accessible.name: hint.text` working.
5. **Smoke stage** — `tests/qml-smoke.py`.
   - Add the action steps to the final step list, before its last step
     (the one that logs `QML_CHECKS_PASSED` and calls `Qt.quit()`,
     `tests/qml-smoke.py:221-226`). Anything after that step never runs.
     The steps set
     `panel.actionCommand` to a `sh` script that appends its last argument
     to a temp file and prints a chosen JSON reply after an optional
     delay.
   - It drives keys with `tc.keyClick`, and covers the spec's smoke list:
     - setting off; each key allowed and refused; the footer text;
     - Esc; Enter not confirming; Shift+`y` not confirming; repeated `y`
       sending once; auto-repeat tested by calling
       `panel.confirmKey({key: Qt.Key_Y, modifiers: Qt.NoModifier,
       isAutoRepeat: true, accepted: false})` (Qt Quick Test's `keyPress`
       has no auto-repeat argument), and the same object with
       `isAutoRepeat: false` confirming;
     - a reorder while confirming still sending the pinned target;
     - host change before sending; host change after sending (A→B and
       A→B→A) giving a host-prefixed result with B's polling untouched;
     - cooldown refusal; the 1 s spacing for two writes in a row and for a
       read during the wait; close during the wait sending nothing;
     - close, setting off and host change while an action is running: the
       result still arrives, from the process snapshot;
     - success text and `touch`; the `scope`, `refused` and `unknown` texts;
     - a result after close shown on reopen for 10 s; `/` swallowed;
     - long-path wrap at 75% zoom and at the narrow card width, reusing
       the width override at `tests/qml-smoke.py:202-211`: the whole
       confirmation is inside the card (`!hint.truncated`, `hint.x +
       hint.width <= card width`, the full text present), then restore the
       width binding.
   - Restore the fixture and the setting at the end, as E11 does.
   - Check: in the headless VM, not on the host desktop. Add a temporary
     `check(false, "probe")` inside the new steps once, to prove they are
     reached in both scenarios (not committed).

     ```bash
     nix build ./ci#checks.x86_64-linux.qml-smoke -L --override-input gltui path:/mnt/code/Source-home/GitHub/nixarchy-gltui-39
     ```

     It must print `QML_CHECKS_PASSED` twice.
   - Traps:
     - Never run `qml-smoke.py`, quickshell, `menu.py` or `notify-send` on
       the host desktop.
     - Auto-repeat needs a `keyPress` with `autoRepeat=true`, or a direct
       `Keys` event; `keyClick` cannot repeat.
     - Toggle the setting by calling `configure()` with a JSON string, as
       existing host tests do. Do not write the real `shell.json`.
6. **Docs and version** — `README.md`, `keybindings.sh`, `manifest.json`.
   - README:
     - intro (line 3) and Requirements (line 10): writing is possible
       when actions are on, and needs `api`;
     - settings (lines 131-148): the `actions` key;
     - Authentication (150-164): `api`, plus role and project rules —
       normally Developer, subject to protected branches, protected
       environments and the project's cancel restriction;
     - Keyboard table (166-193): `a c x n`, then `y` / Esc;
     - a new "Actions" section after "Watching a pipeline": rows, texts,
       unknown outcomes, and what is not offered;
     - "Refresh and errors": line 288's exception for writes, and line
       298's exception for closing.
   - `keybindings.sh`: four key lines and `y / Esc → Confirm or cancel an
     action`.
   - `manifest.json`: `1.14.0`.
   - Check: each new line is present, and the printed sheet and the README
     diff read correctly:

     ```bash
     for k in '^a →' '^c →' '^x →' '^n →' '^y / Esc →'; do bash keybindings.sh --print | grep -q "$k" || echo "missing $k"; done
     ```
   - Traps: README line numbers shift after edits, so anchor by heading.

## Tests

```bash
cd /mnt/code/Source-home/GitHub/nixarchy-gltui-39
python3 -m unittest discover -s tests   # OK
node tests/model.cjs                    # all pass
node tests/polling.cjs                  # all pass, 0 fail
nix build .#checks.x86_64-linux.plugin  # builds
nix build ./ci#checks.x86_64-linux.qml-smoke -L --override-input gltui path:$PWD   # QML_CHECKS_PASSED x2
```

- A deliberate `check(false, …)` in the new stage fails the VM test
  (not committed).
- The CI `qml-smoke` job passes on the PR.
- No test sends a request to a real GitLab.

## Deviations

- Step 2: `next()` waits one second after `s.writeAt` only when
  `writeAt` is set (`s.writeAt && now - s.writeAt < 1000`), so the
  default `0` never delays the first read (e.g. a test clock at 0).
- Step 3: a pipeline with no usable ref gets its own reason, "This
  pipeline has no branch or tag to start from", instead of the
  merge-request reason.

## Rollback

- Before deploy: close the PR.
- After deploy:
  - revert the squash commit and release 1.14.1, or pin nixos_config back
    to v1.13.0 (`flake.nix` lines 81-82) and switch;
  - or remove `"actions": true`, which turns every write off at the panel
    and in the helper.

The change keeps no state, so nothing needs migrating.
