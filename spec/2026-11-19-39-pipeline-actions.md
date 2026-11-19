---
status: approved
issue: 39
intent: intent/2026-11-19-39-pipeline-actions.md
---

# Spec: Retry, cancel, play and trigger pipelines from the panel

## Design

### Decisions carried from the intent

The approved intent's recommendations are the decisions:

1. All four actions ship: retry, cancel, play, new pipeline. Play is for
   single manual jobs only.
2. A new pipeline runs on the selected pipeline's exact ref with GitLab's
   defaults. Not on merge-request pipelines. No typed ref, no variables.
3. The setting is `"actions": true` in the plugin's `shell.json` entry.
4. The selected row decides the target (table below). `»`, project, stage,
   more and message rows offer nothing.
5. One key per action: `a` retry, `c` cancel, `x` play, `n` new pipeline.
6. One `y` confirms every action. Esc cancels. Enter never confirms, and
   auto-repeat is ignored.
7. No scope probe. The `api` scope is named only when GitLab says
   `insufficient_scope`.
8. Writes skip the 60-a-minute page budget, but run one at a time, at
   least one second after the last request start, and are refused (not
   queued) during a cooldown.

### What each key does

The row's `status` is already mapped and has no raw GitLab status, so a key
resolves the raw object first: a pipeline with `Polling.runFor(polling,
row.repo, row.run)` (`Polling.js` line 29), a job by `id` from
`polling.details[row.repo + ":" + row.run].jobs`. `conclusion` is GitLab's
raw status (`gitlab.py` lines 232, 243). If the raw object is gone, the key
says "Select the row again" and does nothing.

| Key | Row | Action | Offered when raw `conclusion` is | Request |
| --- | --- | --- | --- | --- |
| `a` | pipeline | `retry-pipeline` | `failed`, `canceled` | `POST projects/:id/pipelines/:pipeline/retry` |
| `a` | job | `retry-job` | `failed`, `canceled` | `POST projects/:id/jobs/:job/retry` |
| `c` | pipeline | `cancel-pipeline` | `created`, `waiting_for_resource`, `preparing`, `pending`, `running`, `scheduled` | `POST projects/:id/pipelines/:pipeline/cancel` |
| `c` | job | `cancel-job` | the same list | `POST projects/:id/jobs/:job/cancel` |
| `x` | job | `play-job` | `manual` | `POST projects/:id/jobs/:job/play` |
| `n` | pipeline | `new-pipeline` | any, if the raw `ref` is set, does not start with `refs/merge-requests/`, and `source` is not `merge_request_event` | `POST projects/:id/pipeline?ref=<ref>` |

- These are GitLab's documented operations (Pipelines API: retry, cancel,
  create; Jobs API: retry, cancel, run). Success is 201 for retry
  pipeline, create pipeline, retry job and cancel job, 200 for cancel
  pipeline and play job; the helper accepts any 2xx. Retrying a pipeline
  retries its failed and canceled jobs.
- The status lists are this panel's conservative policy, not GitLab's
  full rules. GitLab also lets you retry a successful job and cancel a
  manual one; both are left out on purpose (the intent scopes retry to
  failed or canceled jobs).
- Legacy detached merge-request pipelines carry the source branch as
  `ref`, so the `refs/merge-requests/` prefix alone does not catch them;
  `source` does.
- A key that is not offered says why, for example "Only a failed or
  canceled pipeline can be retried", "Only a manual job can be played",
  "Merge-request pipelines cannot be started from the panel". It never
  opens a confirmation.
- `a`, `c`, `x`, `n` are free in navigation mode (`PipelinesPanel.qml`
  lines 628-651). In search editing they stay text.

### Setting

- `configure()` (`PipelinesPanel.qml` line 370) reads
  `entry.actions === true` into a new `actionsOn` property. Anything else,
  including a missing key, is off. The file is watched (lines 561-567), so
  turning it on or off applies without a restart.
- With the setting off, the four keys only say
  `Actions are off: set "actions": true for this plugin in shell.json`.
- **The helper checks the setting itself.** The new `act` mode in
  `gitlab.py` reads `$HOME/.config/omarchy/shell.json` (the path the panel
  watches, line 562), finds the `olafkfreund.gitlab-pipelines` entry, and
  refuses with `errorType="disabled"` unless `actions` is `true` and the
  entry's host (default `gitlab.com`) equals the task's host. A stale panel
  or a hand-run helper cannot write with the setting off.

### Helper: a closed write table in `gitlab.py`

- `main()` (line 369) gets a third mode, `act`, with one JSON argument:
  `{"action", "host", "repo", "run", "job", "ref", "source", "requestId"}`.
  `job` is required for job actions, `run` for pipeline actions, `ref` and
  `source` only for `new-pipeline`. The `shell.json` gate and all
  validation run before `request()` is called.
- `act` refuses `new-pipeline` when the task's `source` is
  `merge_request_event`, as a second check behind the panel.
- `write_endpoint(task)` maps the action to a fixed path, never to text from
  the task. It validates like `page_endpoint` (lines 127-157):
  `host_name`, `project_path`, a positive int `requestId`, and the numeric
  ID check (lines 140-142) lifted into a small `numeric_id(value, label)`
  used for both pipeline and job IDs. An unknown action raises
  `ValueError("Invalid action")`.
- **The ref goes in the URL**, encoded with `quote(ref, safe="")`, as
  `projects/<id>/pipeline?ref=<encoded>`. GitLab documents `ref` as a query
  parameter on this POST. There is no `-f`, `-F` or `--input`: `glab` then
  sends an empty JSON body (`{}`), so nothing the user or GitLab supplied is
  in the body and nothing is read from a file. The ref must be a string of 1 to 255 characters
  with no control characters, and must not start with
  `refs/merge-requests/`.
- `request()` (lines 113-124) gets a `method` parameter. For writes the
  argument list is
  `["glab", "api", "--hostname", host, "--include", "--method", "POST", endpoint]`.
  Host pinning, the 25 s child timeout and the argument-list `Popen` stay.
- The rate-limit header block of `read_page` (lines 305-316) is lifted into
  `limits(headers, result)` and called from both paths, not copied.
- `pipeline()` (line 222) gains `"ref"`: the raw `row["ref"]` if it is a
  string that passes the ref check above, else `""`; and `"source"`: the
  raw `row["source"]` if it is a string matching `[a-z_]{1,40}`, else `""`. `head_branch` stays the
  sanitised display text. The write uses `ref`; the confirmation shows
  `head_branch`.
- The module docstring (line 1) becomes "GitLab pipeline data and a closed
  set of pipeline and job actions, using glab's existing authentication."

Reply: `{requestId, action, httpStatus, ok, error, errorType, retryAt,
remaining, resetAt, created}`. `created` is `{id, iid}` for a new pipeline
or a retried job, when GitLab returns it, else `null`.

| Condition | errorType | Text |
| --- | --- | --- |
| 2xx | none, `ok: true` | none; the panel writes the success text |
| setting off or host mismatch in `shell.json` | `disabled` | "Actions are off in shell.json" |
| 429, `remaining == 0`, `retry-after`, "rate limit" (the test at line 325) | `rate` | "GitLab rate limit" |
| 401, or "auth login" on stderr with no stdout | `auth` | "Authenticate with glab auth login" |
| 403 whose body `error` or `message` says `insufficient_scope` | `scope` | "Needs a token with the api scope" |
| any other 403, and 400, 404, 409, 422 | `refused` | "GitLab refused: " + GitLab's message |
| 3xx | `refused` | "GitLab redirected the request; the project may have moved" |
| `glab` missing | `setup` | "Install glab (GitLab CLI)" |
| timeout, `glab` exit with no HTTP reply, unreadable reply, 5xx | `unknown` | "Outcome unknown; check GitLab before retrying" |

- GitLab's message can be a string or an object of lists
  (`{"message": {"base": ["..."]}}`). The helper joins the strings it finds,
  runs them through `plain()` (line 204) and cuts them to 120 characters.
- The write path never uses `permission`. Only the read path's
  `permission` marks a project blocked (`Polling.js` lines 351-358).
- `unknown` covers every case where GitLab's answer was not read. A killed
  `glab` does not prove nothing happened.
- `main()` keeps its 90 s alarm (line 388) and echoes `requestId` on errors,
  as `page` does. A validation error before any request is `setup`
  (nothing was sent).

### Panel: `PipelinesModel.js`

Pure functions, tested in `tests/model.cjs`:

- `actionFor(key, row, raw)` returns `{action}` or `{reason}` from the
  table above.
- `describe(action, repo, raw, run)` returns `{confirm, done}`. The
  confirmation names the action, the target (pipeline number, name and
  ref; for a job also its name and job ID, since job names repeat), the
  project, the effect and the keys. Name and ref are cut to 30 characters;
  the project path is not cut. Examples:
  - `Retry pipeline #42 build (main) in group/app? y yes · Esc no`
  - `Cancel job deploy (job 1234) of #42 in group/app? Cannot be undone. y yes · Esc no`
  - `Play manual job deploy (job 1234) of #42 in group/app with its default variables? y yes · Esc no`
  - `Start a new pipeline on main in group/app with default variables? y yes · Esc no`
  - done: `Retry requested: group/app #42 build (main)`. "Requested", since
    GitLab only accepted it.
- `actionReply(stdout, code, requestId)`: like `reply()` (line 2) for
  writes. Empty stdout with code 127 is `setup` "python3 not found"
  (nothing was sent); empty stdout with any other code, a wrong
  `requestId`, or unparsable text is `unknown`.

### Panel: `PipelinesPanel.qml`

New state: `actionsOn`, `confirm` (null or a pinned target), `actionBusy`,
`actionId`, `actionHost`, `actionCommand` (default
`["python3", helper, "act"]`, a test hook like `traceCommand`, line 45).

- **Pinned target.** On an offered key the panel stores
  `{action, host, repo, run, job, ref, text, done}`: strings copied from
  the raw object, not a row key or index. Polling can reorder the rows;
  the confirmation still sends exactly what it named.
- **Confirmation keys.** While `confirm` is set, the key handler (line
  613) handles it first and swallows every key: `y` without modifiers and
  not auto-repeat confirms; Esc clears it; others do nothing. Escape does
  not clear the filter or close the panel then. `/` is swallowed too, so
  search cannot start, and the action keys are only wired in navigation
  mode, so a confirmation cannot open while searching.
- **Cleared by** `close()` (line 184), a host change in `configure()`
  (line 376), and `actionsOn` turning false. Each of these also cancels a
  confirmed action that is still waiting to start (below).
- **Host epoch.** `configure()` increments a `hostEpoch` counter whenever
  the host changes. `polling` is not a stable identity: `adopt()` copies
  it (line 414) and a host change replaces it (line 384).
- **Footer.** The footer text becomes
  `confirm ? confirm.text : notice || cooldownText || hint`
  (line 836). While `confirm` is set the footer wraps instead of eliding
  (`wrapMode: Text.Wrap`, `elide: Text.ElideNone`, line 840), so the
  whole confirmation is visible however long the project path is, at the
  smallest zoom and panel width too. The footer's `Accessible.name`
  follows `hint.text`, so a screen reader gets the confirmation. With `actionsOn`, `listHint` gains
  `a/c/x/n act` after `w watch`.
- **Local gates before sending** (no request):
  - `actionBusy`: "An action is already running".
  - `now < polling.cooldown`: "GitLab paused until HH:MM; try again then"
    (refused, not queued).
  - `actionsOn` false or `host !== confirm.host`: the confirmation is
    dropped with "Actions are off" or "Host changed; nothing was sent".
  - Less than one second since `max(polling.lastStarted, polling.writeAt)`:
    the send waits for the rest of that second (a one-shot `Timer`).
- **Confirming consumes the confirmation.** `y` moves `confirm` into
  `pendingAction` and clears `confirm` in the same handler, so a second `y`
  finds nothing to confirm. `actionBusy` is true from that moment. Right
  before starting `actionProc`, every gate is checked again, including the
  one-second spacing (a read may have started during the wait). Close,
  setting off or a host change clears `pendingAction` and stops the timer;
  nothing is sent.
- **Its own process.** `actionProc` is a separate `Process`. It does not
  use `requestProc`, `workerBusy` or `Polling.flight`, so it can run while
  a read is in flight. `close()` does not stop it (it stops `requestProc`,
  line 193); the helper's own 25 s and 90 s limits still apply. A failed
  start is caught the way `pinsLoad` does (lines 505-512) with an
  `actionStarted` flag, and reported as `setup` "python3 not found".
- **Result.** The panel matches `requestId` against `actionId`. Every
  result is reported, and when its `hostEpoch` differs from the current
  one it names its host ("on gitlab.example.org: Retry requested …").
  Polling is updated (`noteWrite`, `touch`) only when the epoch still
  matches; a close and reopen on the same host keeps the epoch, so it still
  applies. Then:
  - shown with `notify(text, 10000)`: `notify` (line 242) gets an optional
    duration, and `noticeTimer` (line 520) uses it, default 2000;
  - success shows `describe().done`, plus `· refresh waits until HH:MM` if a
    cooldown holds the refetch back, plus `· new pipeline #N` when
    `created.iid` is set;
  - failures show the helper's text in `Color.urgent`, as errors do;
  - if the panel is closed when the result arrives, it is kept in
    `missedAction` (one string, the latest result). `open()` shows it with
    `notify(missedAction, 10000)` after `showMissed()` (line 152), so it
    keeps its duration and is not joined with watch notices. That covers
    the unknown outcome too.
- **Refresh after success**, through a new `Polling.touch(s, repo, run,
  now)`. It reuses `restart()` (`Polling.js` lines 68-72): for a task in
  flight, `restart()` sets `t.restart`, and `complete()` then keeps the
  reply's rate-limit handling but drops its data and starts the task again
  (line 332). So a read that overlapped the write never publishes
  pre-action state, never restores `summaryAt`, and never reaches
  `settle()` with it. `touch()`:
  - `ensure(s, "run", repo, run, "interactive", now)` (line 58), then
    `restart()` it (which sets `due = now`, or flags it when in flight);
  - `delete r.summaryAt`, and `restart()` the project's `summary` task if
    one exists, so the next `seed` re-reads the project's pipelines and a
    new pipeline appears;
  - if the pipeline is expanded (`s.expanded[repo + ":" + run]`), `ensure`
    and `restart()` its `jobs` task, from page one, so a retried or played
    job shows its new state.
  It stays an ordinary polling request: it counts toward the budget, waits
  for the gap and the cooldown.
- **Watches.** No action calls `Polling.watch`. An existing watch is left
  alone; a cancel ends it the normal way when the refetch sees the
  pipeline finished (`settle`, line 46). A retried pipeline can be watched
  once the refetch shows it unfinished.
- `status()` (line 196) adds `actionsOn`, `confirm` (its text or "") and
  `actionBusy` for the smoke test.

### Panel: `Polling.js`

- The cooldown block of `complete()` (lines 326-331) moves into
  `cool(s, reply, now)`, called from `complete()` and from a new
  `noteWrite(s, reply, now)`. A write reply with `retryAt`, 429 or
  `remaining === 0` pauses polling like a read. `noteWrite` changes nothing
  else: not `s.error`, `s.auth`, a project's `blocked` or `error`, `tasks`
  or `starts`.
- A small `writeStarted(s, now)` records `s.writeAt = now` when
  `actionProc` starts, and `next()` (line 218) waits one second after
  `s.writeAt` as it does after `starts` (line 223). Writes do not enter
  `s.starts`, so they do not count toward 60 a minute.
- `touch()` as above.

### Docs and version

- `README.md`:
  - intro (line 3) and Requirements (line 10): the panel can retry,
    cancel, play and start pipelines when actions are on; that needs a
    token with `api`. `read_api` still works for everything else.
  - Settings (lines 131-148): the `actions` key, off by default.
  - Authentication (lines 150-164): `api` for actions; role and project
    rules (normally Developer, subject to protected branches, protected
    environments and the project's cancel restriction).
  - Keyboard (lines 166-193): `a`, `c`, `x`, `n` and `y` / Esc.
  - A new "Actions" section: what each key does on which row, the
    confirmation, the result texts, unknown outcomes, and what is not
    offered (merge-request pipelines, `»` rows, manual stages, variables).
  - Refresh and errors (line 288): writes skip the 60-a-minute limit and
    may run beside one read, wait one second after a request start, are
    refused during a cooldown, and an unknown outcome is never retried.
    Line 298 ("Closing the panel cancels the helper") gets the exception:
    a confirmed action is not cancelled by closing; it finishes and its
    result shows on the next open.
- `keybindings.sh`: four key lines and one for `y` / Esc.
- `manifest.json`: 1.14.0. `flake.nix`: no change (no new runtime file).

## Alternatives rejected

- **A typed ref or variables for a new pipeline or play.** Needs an input
  flow and validation for little gain; `glab ci run` and the GitLab UI do
  it (intent question 2).
- **An action menu on one key.** More UI and more keys inside it; four
  free letters do the job (question 5).
- **The panel alone enforcing the setting.** A stale panel, or the helper
  run by hand, could still write. The helper reads `shell.json` itself.
- **Passing the ref with `-f ref=...`.** It works, but puts a
  GitLab-supplied value through `glab`'s field parsing. The encoded query
  string keeps the argument list fixed and the body empty (`{}`).
- **Reusing `requestProc` and `Polling.flight`.** A write would be dropped
  by `complete()` after a close or generation change (line 319), and
  `close()` kills `requestProc`.
- **Queueing a write until a cooldown ends.** It could run much later
  against a changed pipeline (intent, Codex finding 5).
- **Probing the token's scope.** Costs a request and is unreliable for
  project and group tokens (question 7).

## Risks

- **Real side effects.** A wrong target would retry, cancel or deploy the
  wrong thing. The pinned target, the helper's ID validation and the
  setting check in the helper are the guard; tests cover a reorder while a
  confirmation is open.
- **`insufficient_scope` detection.** If GitLab words it differently on a
  self-managed version, the user gets the generic "GitLab refused: …" with
  GitLab's own text, which still explains it.
- **Pipeline cancel returns 200 whatever the state**, so "Cancel
  requested" can show for a pipeline that had just finished. The refetch
  shows the real state.
- **The `ref` query string on POST.** Documented by GitLab for create
  pipeline; if a self-managed version rejected it, the reply is a 400 shown
  as refused, nothing else breaks.
- **The helper reading `shell.json`.** If the file is unreadable or
  invalid, `act` refuses with `disabled`. Reads never touch it.
- **No host change outside the deploy.** p620 and razer get 1.14.0 on
  deploy; p510 is not touched. With the setting off (the default),
  nothing users see changes beyond the docs and the key messages.

## Verification

- `python3 -m unittest discover -s tests`: `write_endpoint` for each
  action; rejected IDs; refs (control characters, too long,
  `refs/merge-requests/`), and refs with `&`, `#`, `%`, `+`, `/` and
  Unicode round-tripping exactly through the encoding; `source`
  (`merge_request_event` refused); the exact `glab` argument list with
  `--method POST` and no `-f`; the `shell.json` gate (missing, off, other
  host, bad JSON) never calling `request()`; each row of the reply table;
  the real `insufficient_scope` body (`error`, `error_description`,
  `scope`) vs another 403; nested message arrays; non-JSON failures; a 2xx
  with `remaining: 0` (success plus a cooldown); `created`; and
  `pipeline()["ref"]` keeping a raw ref that `plain()` would change.
- `node tests/model.cjs`: `actionFor` for every key and row kind and the
  status lists, including an MR pipeline with a plain branch ref and
  `source: merge_request_event`, and a successful job refused; `describe`
  texts and cuts; `actionReply` (127, other codes, wrong ID).
- `node tests/polling.cjs`: `touch` (new task, existing backed-off task;
  an overlapping run lookup, summary and paginated jobs snapshot each
  restarted without publishing their data; a watched pipeline not settled
  from the stale reply); `noteWrite` cooldown without touching
  `blocked`/`error`/`auth`; the one-second gap after `writeAt`; writes not
  in `starts`.
- `tests/qml-smoke.py`, new stage with a fake `actionCommand`: setting off
  message; each key on an allowed and a refused row; confirmation in the
  footer; Esc cancels; Enter and held `y` do not confirm; repeated `y`
  sends once; rows reordered while confirming still send the pinned
  target (the fake records its argument); a host change before sending
  cancels; a host change after sending (A→B, and A→B→A) reports the
  result with its host and leaves B's polling alone; cooldown refuses; two
  writes in a row and a read during the wait keep one second apart;
  closing during the wait sends nothing; success text and `touch` effect;
  `scope`, `refused` and `unknown` texts; a result after close shown on
  reopen for ten seconds; `/` swallowed while confirming; a long nested
  project path wraps fully at the smallest zoom.
- `nix build .#checks.x86_64-linux.plugin` and
  `nix build ./ci#checks.x86_64-linux.qml-smoke -L` (headless VM, passes on
  p620; the CI job runs it on the PR).
- Not tested live: no request is ever sent to a real GitLab by the tests.
  A manual check on a scratch project with the owner's token is optional
  and only with the owner's go-ahead.
