---
status: approved
issue: 40
spec: spec/2026-11-19-40-my-merge-requests.md
coders:
  1: codex   # helper reads: endpoint validation, parsing untrusted MR data, error mapping
  2: codex   # Polling.js: task identity, wake deadlines, pruning, jump — small tricky scheduling logic
  3: coder   # model rows: pure functions and their tests
  4: coder   # panel wiring: view switch, per-view state, keys, jump, header, footer
  5: codex   # smoke stage: async steps, fake helper kinds, key and timing traps
  6: coder   # docs, key sheet, version
reviewers:
  - codex    # fresh diff review against this plan (agy is out of use, #2748)
---

# Plan: A "my merge requests" view

Work in the worktree `/mnt/code/Source-home/GitHub/nixarchy-gltui-40`,
branch `feat/40-my-merge-requests`. Line numbers are from `main` at
`c401700`; they shift as steps land, so anchor by function name.

## Decisions (from the approved spec)

Intent decisions: (1) only merge requests you opened; (2) the first 50 by
`updated_at`; (3) `m` toggles the view; (4) Enter jumps into the pipeline's
own project when it is in the projects view; (5) one `head_pipeline`
request per merge request, in the shared budget; (6) the list refreshes on
first switch, every 60 s while shown and on `r`; (7) project polling
continues, only the selected-project rates pause; (8) the view is
remembered until the shell restarts.

Rejected, do not build: status from already-polled pipelines; the
per-merge-request pipelines list endpoint; GraphQL; keeping non-member
projects alive for the jump; a second tree inside the merge-request view;
Tab as the switch key.

### Data flow

```mermaid
flowchart LR
  K[m key] --> V[panel view = mrs]
  V --> S[Polling.seed]
  S -->|mrs task| L[GET merge_requests]
  S -->|mr task per row| H[GET projects/:id/merge_requests/:iid]
  L --> M[s.mrs.list]
  H --> P[s.mrs.status]
  M & P --> R[Model.mrRows]
  R -->|Enter| J[Polling.jump → projects view]
```

### Helper (`gitlab.py`)

Two new read kinds in `page_endpoint` (line 138), both page 1 only:

- **`mrs`**: `merge_requests?scope=created_by_me&state=opened&order_by=updated_at&sort=desc&per_page=50`.
  Global endpoint: it covers every project the token can see, members or not
  (GitLab "List merge requests"). Its documented fields have no pipeline.
- **`mr`**: `projects/<project>/merge_requests/<iid>`, where `project` and
  `iid` are checked with `numeric_id` (line 131). Using the numeric
  `project_id` from the list avoids parsing a path out of `references`.

New parsers, next to `pipeline()` (line 251):

- **`merge_request(row)`** → `{id, iid, project_id, project, title,
  source_branch, draft, web_url, updated_at}`. `id`, `iid` and `project_id`
  must be positive ints, or the row raises `ValueError` (like `entry`).
  `project` is `references.full` without its `!iid` suffix; if
  `project_path()` refuses it, the path of `web_url` before `/-/` is tried
  the same way; else `""`. Raw text never reaches the panel as a project.
  `title` and `source_branch` go through `plain()`
  (#15). `draft` is `bool(row.get("draft") or row.get("work_in_progress"))`.
- **`mr_detail(row)`** → `{iid, project_id, pipeline, pipelineState}`:
  - `head_pipeline` key **absent** → `pipelineState: "hidden"`, `pipeline:
    null`. GitLab exposes it only to users who may read the project's
    pipelines (`API::Entities::MergeRequest`, `if: can read_pipeline`).
  - key present and `null` → `"none"`.
  - an object → `"ok"`, `pipeline` = `pipeline(head)` plus `project_id` (the
    pipeline's own project, a positive int, which for a fork can differ from
    the merge request's `project_id`). `pipeline()` already accepts GitLab's
    basic pipeline fields (`id`, `status`, `ref`, `sha`, `source`,
    `updated_at`, `web_url`); missing `started_at` leaves `run_started_at`
    as `created_at`.

`read_page` (line 418) gains the two kinds: `mrs` returns a list plus
`total = pipeline_total(headers, len(body))` (−1 = more, count unknown);
`mr` returns an object and checks that its `iid` matches the task. A 403 or
404 on either is `errorType="permission"` with "Merge request unavailable",
not the project message.

`project()` (line 317) also returns the project's numeric `id`, so the panel
can map a pipeline's `project_id` to a catalogue path.

### Scheduler (`Polling.js`)

State in `create()`: `mrView:false`, `mrSelected:""` and `mrs:{list:null,
total:0, listAt:undefined, error:"", status:{}}`, where `status` is keyed
`"<project_id>!<iid>"` → `{state:"ok"|"none"|"hidden"|"unavailable",
pipeline, at, mrUpdated}`. `resetHost` keeps `mrView` and starts `mrs` and
`mrSelected` empty; its generation bump already drops replies for the old
host (`complete`, line 338).

**Task identity.** `ensure()` (line 58) keys on kind, repo and run only, so
repo-less tasks would collide as `mr::`. The `mr` task uses `run` =
`"<project_id>!<iid>"` (key `mr::<project_id>!<iid>`) and stores `project`
and `iid` on the task; `next()` (line 250) forwards both into the request,
as it does `status` and `route`. `mrs` is the single key `mrs::`.

- **`view(s, on, now)`** sets `mrView`, clears `wakeAt`; turning it off also
  clears `mrSelected`.
- **`seed`** (line 143), only while `opened && mrView`; every deadline that
  is not yet due goes into `wake`, like the existing tasks (lines 157, 234),
  so `next()` wakes for it even with no projects and no watches:
  - `mrs` task (group `interactive`) when `now >= age(listAt, 60000)`.
  - per listed merge request, an `mr` task with its target and group:

    | Row | Group | Due |
    | --- | --- | --- |
    | selected (`mrSelected`), unchecked | `interactive` | now |
    | selected, unfinished pipeline | `interactive` | `at + 10 s` |
    | selected, anything else | `interactive` | `at + 60 s` |
    | unchecked | `background` | now |
    | unfinished pipeline | `pinned` | `at + 30 s` |
    | finished, `none`, `hidden` or `unavailable` | `background` | `at + 10 min`, or now when the list's `updated_at` differs from `mrUpdated` |

    "Unfinished" means `pipeline.status !== "completed"`, so `manual` and
    `scheduled` head pipelines count as finished (they wait on a person or a
    clock, not a runner), as they do for project activity. `unavailable` is
    retried on the 10-minute rule and on `r`, so restored access recovers.
  - Pruning: while `mrView` is off, every `mrs` and `mr` task not in flight
    is deleted; while on, every `mr` task whose key is not in the current
    list is deleted. The owner check (line 152) does not apply: they have no
    `repo`.
- **`complete`** (line 334):
  - `mrs` replaces `list` (cut to 50), sets `total`, `listAt`, `error:""`,
    and drops statuses and queued `mr` tasks of merge requests no longer
    listed.
  - `mr`: a reply for a key no longer in the list is dropped (task deleted,
    no status written). Otherwise it stores the status with `at:now` and
    `mrUpdated` from the list row, and deletes the task.
  - Errors: `rate`, `auth`, `setup` and `network` follow the existing paths
    (cooldown, stop, backoff). `permission` on `mr` stores
    `state:"unavailable", at:now` and deletes the task; on `mrs` it sets
    `mrs.error`, `listAt=now` and deletes the task, so it retries a minute
    later. No error marks a project blocked.
  - The "invalid data" check (line 342) treats `mr` like `run` (an object).
- **`manual`** (line 117) in the merge-request view restarts the `mrs` task
  and marks every listed status due now (keeping its data until the reply),
  so `r` rechecks all rows, selected first.
- **`jump(s, repo, run, expanded, now)`**: first `select(s, repo, run,
  expanded, now, true)`, so the scheduler sees the pipeline as selected and
  expanded and `trimRuns` (line 288) keeps it even when it is older than the
  ten newest finished pipelines; then `mergeRuns` adds it, then `touch`
  (line 73) fetches it in full.
- **`select`** keeps working: in the merge-request view the panel calls it
  with no repo, so selected-project rates pause (decision 7). A new
  `selectMr(s, key)` sets `mrSelected` and clears `wakeAt`.

### Model (`PipelinesModel.js`)

- **`mrRows(mrs, filter, now, host, selectedKey)`** → rows with `kind:"mr"`,
  `key:"mr:<project_id>!<iid>"`, `title` `"<project> !<iid> <title>"` (with
  `Draft · ` first when draft), `subtitle` the source branch, and `status`
  from the pipeline (`state()`), or `neutral` with `info` "not checked", "no
  pipeline", "pipeline hidden" or "unavailable".
  - Age: a checked row whose status is older than its refresh target
    (10 s selected and unfinished, 30 s unfinished, 60 s selected otherwise,
    10 min otherwise) adds "checked 2m ago".
  - `url` is the merge request's `web_url` only if `browsable(url, host)`
    (line 9), else `""`, so `o` and `y` say "No link".
  - A merge request whose `project` is `""` shows "unknown project".
  - When `total` exceeds the list, or is −1, a last `kind:"more"` row says
    "N more on GitLab" or "more on GitLab". Its `url` is
    `https://<host>/dashboard/merge_requests?scope=created_by_me&state=opened`
    (built from the configured host, so `o` opens and `y` copies it); Enter
    on it does nothing but say "Open it with o".
  - Filter matches title, project, branch and status, like `runMatches`; no
    match gives "No merge requests match" in the empty state.
- `accessibleName` (line 185) covers `mr` and `more` rows.

### Panel (`PipelinesPanel.qml`)

- `property string view: "projects"` — not reset by `close()` or `open()`,
  so the panel reopens in the last view until the shell restarts.
- **`m`** toggles the view. It is handled after the help overlay and the
  action confirmation (lines 297-300, 745-749), which keep their precedence,
  and only when the list has focus (not while filtering; `m` typed in the
  search box is text).
- **Per-view state.** Each view keeps `{filter, collapsed, key}` (filter
  text, `searchCollapsed`, selected row key) in `viewState`. Assigning
  `filterText` fires `onFilterTextChanged` (line 89), which clears
  `searchCollapsed`, resets the selection and calls `selectionChanged`. So a
  switch runs in this order: save the current view's three values; set
  `switching = true` (the handler returns early while it is set); set
  `view`; assign the saved filter; restore `searchCollapsed`; set `switching
  = false`; `rebuild(false)` selecting the saved key; `selectionChanged(true)`.
- `rebuild()` (line 225) uses `Model.mrRows` in the `mrs` view;
  `selectionChanged` calls `Polling.select(s, "", "", …)` plus `selectMr` in
  that view.
- Header (line 788): `GitLab Pipelines · N projects` or `My merge requests ·
  N open`.
- Keys on an `mr` row: `o` opens and `y` copies the merge request URL; `r`
  refreshes the list and every row's status; Enter/→/l/Space jumps.
  `p t w e a c x n Y` and ←/h say "Not on a merge request; press Enter for
  its pipeline" in the footer. Navigation, `/`, `?`, `q`, Esc and zoom are
  unchanged.
- **Jump**: find the catalogue repo whose `id` is the pipeline's
  `project_id`. If found and not archived or CI-disabled: save the
  merge-request view's state, switch to the projects view as above but with
  an empty filter, add the repo and pipeline to `expanded`, call
  `Polling.jump` with that expansion, `adopt()`, then select and scroll to
  the pipeline row (`positionViewAtIndex`). Otherwise the footer says "No
  pipeline yet", "Pipeline hidden", "Not checked yet" or "Project not in
  your list; o opens the merge request".
- Empty state: "No open merge requests" when the list is empty; "Loading
  merge requests…" before the first reply; `mrs.error` uses the existing
  error strip.
- `configure()` host change: `resetHost` resets the scheduler state; the
  panel also resets both `viewState` entries (filter, collapsed, key) but
  keeps `view`, so the new host's list loads in the same view.
- `status()` adds `view` and `mrs` (count) for the smoke test.
- `listHint` gains `m MRs`; the `mrs` view has its own short hint.

### Docs

README: keyboard table (`m`, Enter on a merge-request row), a "My merge
requests" section (what is listed, the 50 cap, states, jump rules, fork
pipelines), refresh table rows (list 60 s; unfinished 30 s best effort;
finished 10 min), known limits (cap; non-member projects cannot be jumped
into; `hidden` relies on GitLab omitting the field). `keybindings.sh` gets
`m`. `manifest.json` 1.15.0.

## Steps

1. **Helper reads** — `gitlab.py`, `tests/test_gitlab.py`.
   - `page_endpoint` (line 138): add kinds `mrs` and `mr` to the allowed
     tuple. `mrs` → the fixed `merge_requests?scope=created_by_me&state=opened&order_by=updated_at&sort=desc&per_page=50`
     (page must be 1). `mr` → `projects/{numeric_id(project)}/merge_requests/{numeric_id(iid)}`,
     reading `task["project"]` and `task["iid"]`. Keep the existing
     `requestId` and host checks for both.
   - Add `merge_request(row)` and `mr_detail(row)` after `pipeline()`
     (line 251), exactly as in Decisions › Helper. `mr_detail` reads
     `"head_pipeline" in row` for hidden vs none; for an object, run
     `pipeline(head)` and add `project_id` (positive int, else
     `ValueError`).
   - `read_page` (line 418): `mrs` → `[merge_request(r) for r in body]` and
     `result["total"] = pipeline_total(headers, len(body))`; `mr` → object,
     `mr_detail(body)` and check `str(body.get("iid")) == str(task["iid"])`,
     else `ValueError`. A 403/404 on either kind → `errorType="permission"`,
     `error="Merge request unavailable"` (before the generic 403/404
     branch). The "run" object check stays as is.
   - `project()` (line 317): add `"id"` (positive int, else `ValueError`).
     Update the existing fixtures that build projects without an id:
     the catalogue test around `tests/test_gitlab.py:409` (input rows and
     the expected parsed list) and the `project()` call around line 580.
   - Tests in `tests/test_gitlab.py` next to the existing page tests: both
     endpoints; bad `project`/`iid` (0, "1/2", "../x", bool) refused; page 2
     refused for `mrs`; `merge_request` plain-text title and branch, draft
     from `draft` and from `work_in_progress`, bad `references.full` falls
     back to the `web_url` path, both bad → `""`; `mr_detail` absent /
     `null` / object, fork `project_id`, bad `project_id` refused; `iid`
     mismatch → network error; 403 → "Merge request unavailable"; `total`
     −1 when `X-Total` is missing and `X-Next-Page` set; `project()` has `id`.
   - Check: `python3 -m unittest discover -s tests` (all pass).
   - Traps: `numeric_id` takes a string or int and rejects `True` only via
     the regex — `str(True)` is "True", so it is refused; keep it that way.
     The smoke test's fake helper (`tests/qml-smoke.py:25-48`) does not
     import these parsers; it is updated in step 5.

2. **Scheduler** — `Polling.js`, `tests/polling.cjs`.
   - Implement Decisions › Scheduler: `create()` fields, `resetHost`
     keeping `mrView`, `view()`, `selectMr()`, the `mr` task key
     `mr::<project_id>!<iid>` with `project` and `iid` on the task and
     forwarded by `next()` (line 250), the `seed` table (line 143) with every
     undue deadline added to `wake`, pruning while off and of unlisted keys
     while on, `complete` for `mrs` and `mr` (stale-key replies dropped,
     permission paths, the invalid-data check treating `mr` as an object at
     line 342), `manual` in the view, and `jump()`.
   - `Polling.js` has no exports: QML imports it as a library and
     `tests/polling.cjs` loads it with `node:vm`; new top-level functions are
     visible to both.
   - Tests: every bullet of the polling list in Tests › Required cases, each as
     its own case in `tests/polling.cjs`, using injected `now`.
   - Check: `node tests/polling.cjs` and `node tests/model.cjs` (0 fail).
   - Traps:
     - `seed()` only runs when `now >= s.wakeAt` (`next()`, line 234); a
       deadline left out of `wake` silently stalls the view.
     - `seed()` deletes tasks with a `repo` and no owner (line 152): the
       new tasks keep `repo:""`.
     - `next()` checks `s.flight` first; never delete the in-flight task in
       pruning (as existing pruning does, line 148).
     - `jump` must call `select` before `mergeRuns`, or `trimRuns`
       (line 288) drops an older finished pipeline.

3. **Model** — `PipelinesModel.js`, `tests/model.cjs`.
   - Add `mrRows(mrs, filter, now, host)` per Decisions › Model, the `more`
     row and its dashboard URL, and `mr`/`more` cases in `accessibleName`
     (line 185) and wherever `infoText`/`subtitleText` switch on `kind`.
   - `selectedKey` is the scheduler's status key `"<project_id>!<iid>"`
     (the same value as `polling.mrSelected`, without the row key's `mr:`
     prefix); it picks the selected refresh targets (10 s / 60 s) for the
     age text. Test selected and unselected thresholds.
   - Tests: the model list in Tests › Required cases.
   - Check: `node tests/model.cjs` (0 fail).
   - Traps: `browsable(url, host)` returns false without a host (line 9);
     rows must not carry an unchecked URL.

4. **Panel** — `PipelinesPanel.qml`.
   - Implement Decisions › Panel: `view`, `viewState`, `switching` guard in
     `onFilterTextChanged` (line 89), the switch order, `rebuild()` and
     `selectionChanged()` by view, header (line 788), keys and refusals in
     the list `Keys` handler (lines 755-779, after help and confirm),
     `o`/`y`/`r` on `mr` and `more` rows, the jump, empty and loading text
     (`emptyText`, line 590), host-change reset in `configure()` (line 479),
     `status()` fields, `listHint` and the view hint.
   - `copy()` and `openBrowser()` (lines 352, 599) must use the row's
     already-checked `url` for `mr`/`more` rows.
   - Call `Model.mrRows(polling.mrs, filterText, now, host, polling.mrSelected)`
     in `rebuild()`; `selectMr` gets the row key without its `mr:` prefix.
   - Check: `node tests/model.cjs`, `node tests/polling.cjs`; the QML is
     checked by step 5 in the VM.
   - Traps:
     - Never run quickshell or `tests/qml-smoke.py` on the host desktop.
     - `onFilterTextChanged` fires synchronously on assignment.
     - The confirm handler (line 297) and help handler (line 745) must keep
       their precedence; `m` in the search field is text.

5. **Smoke stage** — `tests/qml-smoke.py`.
   - Fake helper (lines 25-48) emits already-parsed `data`, bypassing the
     real parsers, so its replies are in the normalized shape:
     - `mrs`: a list of `merge_request()` entries — `!1` in `one/sub/repo`
       (`project_id` 1) and `!2` in `outside/repo` (`project_id` 99).
     - `mr`: `{iid, project_id, pipeline, pipelineState}`. For `!1`,
       `pipelineState:"ok"` and pipeline 7 with `project_id` 1. For `!2`,
       `pipelineState:"ok"` and a visible pipeline with `project_id` 99,
       which is not in the catalogue, to prove the "Project not in your
       list" refusal. Hidden and none states are covered by the Python and
       model tests.
     - The catalogue fixture rows get `id` 1 and 2. The other host returns
       `[]` for `mrs`.
   - New steps before the final `QML_CHECKS_PASSED` step, covering the smoke list in Tests › Required cases.
   - Check, in the headless VM only:

     ```bash
     nix build ./ci#checks.x86_64-linux.qml-smoke -L --override-input gltui path:/mnt/code/Source-home/GitHub/nixarchy-gltui-40
     ```

     It must print `QML_CHECKS_PASSED` twice. Add a temporary
     `check(false, "probe")` in the new steps once to prove they run (not
     committed).
   - Traps: anything after the final step never runs; restore view, filter
     and fixtures at the end, as E11 does; drive host changes with
     `configure()` JSON, never the real `shell.json`; the global QML timer
     (180 s) and the subprocess timeout (200 s) may need raising — record
     it as a deviation.

6. **Docs and version** — `README.md`, `keybindings.sh`, `manifest.json`.
   - README per Decisions › Docs: keyboard table (`m`; Enter on a
     merge-request row), a "My merge requests" section after "Watching a
     pipeline", refresh-table rows, the slot note in "Refresh and errors",
     and known limits.
   - `keybindings.sh`: `m → My merge requests (toggle)` and Enter on a
     merge request row. `manifest.json`: `1.15.0`.
   - Check: `bash keybindings.sh --print | grep -q '^m →'` and the README
     reads correctly.
   - Traps: anchor README edits by heading.

## Tests

```bash
python3 -m unittest discover -s tests
node tests/model.cjs
node tests/polling.cjs
nix build ./ci#checks.x86_64-linux.qml-smoke -L --override-input gltui path:/mnt/code/Source-home/GitHub/nixarchy-gltui-40
```

All pass; the VM build prints `QML_CHECKS_PASSED` twice. Then a fresh Codex
review against this plan and an Opus review of the diff.

### Required cases (from the spec)

- `python3 -m unittest discover -s tests`: endpoint building and validation
  for `mrs`/`mr` (bad ids refused); `merge_request` parsing (plain text,
  draft, bad project path → `""`); `mr_detail` three states and a fork
  pipeline `project_id`; `read_page` 403 → "Merge request unavailable";
  `total` −1; `project()` returns `id`.
- `node tests/polling.cjs`: nothing scheduled while `mrView` is off; list
  due at once and every 60 s; two merge requests with the same `iid` in two
  projects get two tasks and two requests carrying `project` and `iid`; with
  an empty catalogue and no watches, `wakeAt` is the next list or status
  deadline; selected unchecked row is `interactive`; unchecked rows
  `background`; unfinished rows `pinned` every 30 s, behind `active`;
  manual and scheduled head pipelines on the finished rule; finished every
  10 min and on `updated_at` change; `unavailable` retried on the 10-minute
  rule and on `manual`; list churn during a failed `mr` request deletes the
  task and drops a late reply; tasks dropped when the view turns off; `mr`
  permission → `unavailable` without blocking a repo; an old-generation
  reply is ignored after `resetHost`; `jump` keeps a pipeline older than
  the ten newest finished ones and starts its `run` task; under sustained
  `active` load background `mr` tasks still start in the one-in-five slot.
- `node tests/model.cjs`: `mrRows` titles, draft mark, states, age text for
  each refresh target, "more" row with and without a count and its URL,
  filter and no-match text, URL rejected by `browsable` on another host,
  project fallback from the URL path.
- QML smoke test, in the headless VM only:
  `nix build ./ci#checks.x86_64-linux.qml-smoke -L --override-input gltui path:<worktree>`
  with a fake helper reply for `mrs` and `mr`:
  - `m` switches, and `m` back keeps the projects cursor, filter and a
    project collapsed during search;
  - `m` typed while filtering is text; `m` during an action confirmation or
    with help open does not switch;
  - header text; no-match filter text in the merge-request view;
  - Enter jumps to the pipeline row and it is selected and visible; Enter on
    an outside project shows the footer message;
  - `p` and `a` on an `mr` row show the footer message;
  - closing and reopening keeps the view;
  - a host change during an `mr` request: old rows disappear, the old reply
    is ignored, the view stays and the new host's list loads.
- Manual on p620 after deploy: open, press `m`, check one real merge request
  and Enter into its pipeline.

## Deviations

- Step 3: the "more on GitLab" row is left out while a filter is active,
  since it does not match any query and would show under a no-match filter.
- Step 4: `emptyText` takes two more arguments (`mrView`, `mrs`);
  `rebuild` and `adopt` take an optional key to select; the "more" row gets
  the same "Not on a merge request" refusals as `mr` rows; Enter on an
  `unavailable` row says "Merge request unavailable; o opens it" (the
  spec named no text); Shift+R in the merge-request view refreshes the view
  like `r` (`manual` returns early there).
- Step 5 (lead fixes after the VM run): MR1 presses Right before Left, since
  under the `repo` filter the project is not expanded and Left only moves to
  the parent; and a first MR step waits 2 s, then clears `workerBusy`,
  because the action stages restore a saved `workerBusy` that is stale in
  the managed scenario (the request it was saved for has finished). No
  timeout change was needed: the run took about 286 s with the 180 s QML
  timer per scenario.
- Final review fixes (Codex, Opus):
  - an explicit project filter on open (`glp`, `menu.py open`) switches to
    the projects view when the merge-request view was remembered;
  - `jump` selects the pipeline by id (it stored the object) and merges a
    copy, so the merge request's cached status is not mutated by polling;
  - a reply for a merge request that left the list still applies a rate
    cooldown before it is dropped;
  - `merge_request()` keeps `updated_at` only when it is a string.
  Not taken: resetting the live filter text on a host change (the projects
  view already keeps it), and the header count above the 50 cap (the "more"
  row covers it).

## Rollback

Revert the squash commit and release the previous version; the view is
additive and stores no state, so nothing on disk needs cleaning. For a
deployed host, revert the nixos_config pin bump and switch.
