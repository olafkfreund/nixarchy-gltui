---
status: draft
issue: 37
intent: intent/2026-11-18-37-downstream-pipelines.md
---

# Spec: Show downstream and child pipelines as nested rows

Approved answers: status-only rows, 15 s cadence, inside the stage,
endpoint checked here.

## Design

### Endpoint (`gitlab.py`)

GitLab's Jobs API docs (checked 2026-11-18) list
`GET /projects/:id/pipelines/:pipeline_id/trigger_jobs`, introduced in 19.2,
and say `/bridges` is deprecated in 19.2 ("Use `trigger_jobs` instead").
Deprecated REST routes are removed only in a major release, and older
self-managed servers have no `trigger_jobs`.

- New task kind `"bridges"` in `page_endpoint` (`gitlab.py:125-151`), same
  validation as `jobs` (numeric run id), with a `route` field that must be
  `"bridges"` (default) or `"trigger_jobs"`:
  `{base}/{run}/{route}?per_page=100&page={n}`.
- A `bridges` reply with HTTP 404 maps to `errorType: "route"` instead of
  `permission`; the helper never retries itself. The scheduler decides (see
  below), so every HTTP request goes through its accounting, spacing and
  cooldown.
- `bridge(row)` = `job(row)` plus `downstream`: `None` when
  `downstream_pipeline` is not an object, else
  `{id, iid, project_id, parent_project_id, status: state(raw), conclusion:
  raw, ref, sha, url, project}`. GitLab's `PipelineBasic` serializer
  exposes `iid` and `project_id` (the docs' example omits them), so both are
  kept when they are non-negative integers, else `None`.
  `parent_project_id` comes from the bridge's `pipeline.project_id` (same
  rule). `project` is parsed from `web_url`: the path before
  `/-/pipelines/`, only when the URL's host is the task host and
  `project_path()` accepts it, else `""`. `sha` follows the 40/64-hex rule
  of `pipeline()`; `url` is kept as given (the panel's `browsable()` pins the
  host before opening).
- Replies sorted by id and paginated with `nextPage`, like `jobs`.

### Scheduling (`Polling.js`)

- **Storage** on the existing details entry `s.details[repo:run]`: four
  fields `bridges` (list), `bridgesAt`, `bridgesError`,
  `bridgesUnavailable`. Whole-entry deletions (rerun via `invalidateJobs`,
  trim, dropped runs, removed projects, host reset) clear them too. Every
  write merges instead of replacing: jobs success (`Polling.js:398`) and
  jobs permission error (`:331`) keep the four bridge fields; bridge success
  and errors keep every jobs field.
- **Route:** `s.bridgeRoute` (initially `"bridges"`, reset with the host in
  `resetHost`). A `route` error on `bridges` switches it to `"trigger_jobs"`
  and restarts the task as a new, counted request. A `route` error on
  `trigger_jobs` is handled as `permission`.
- **Seeding**, in `seed()` (`Polling.js:177-184`): the jobs part and the
  bridges part are guarded separately (the existing `return` on
  `detail.unavailable` becomes a guard around the jobs part only). For the
  selected, inspected, expanded run, a `"bridges"` task, group
  `interactive`, due `age(detail.bridgesAt, 15000)`, unless
  `bridgesUnavailable` or **final**: the run is completed, its jobs are final
  (`finalAttempt` as today, or jobs unavailable), bridges were fetched, and
  every bridge is completed with its downstream null or completed. A
  downstream in `manual` or `scheduled` counts as completed; `r` refreshes
  it. A future due time goes into `wake`.
- **Pruning** (`Polling.js:138-140`): bridges tasks are deleted under the
  same condition as jobs tasks (not selected, not inspected or collapsed).
- **Rerun** (`mergeRuns`, `Polling.js:252`): an attempt change restarts a
  pending bridges task like the jobs task.
- `manual()` (`r`, `Polling.js:122-125`) restarts the bridges task with the
  jobs task and clears `bridgesUnavailable` and `bridgesError`.
- Pages accumulate in `t.items` like jobs; on the last page
  `bridges=t.items, bridgesAt=now, bridgesError=""`.
- **Errors:** `permission` sets `bridgesError`, `bridgesUnavailable`,
  `bridgesAt=now`, and leaves jobs and `r.blocked` alone (`Polling.js:330`
  blocks the project for other kinds). Network errors take the existing
  retry path and also set `bridgesError` (cached bridges stay). `auth`,
  `setup` and `rate` keep their global handling.
- Never seeded while closed, in watch-only mode or for background checks:
  `seed()` seeds per-repo tasks only while open, and only under the
  inspected condition.

### Rows (`PipelinesModel.js`)

- `stages()` gets `jobs.concat(bridges)` **sorted by id**, so stages keep
  creation order and a bridge sits in its stage, counting towards the
  stage's status and `done/total` with the bridge's own status and
  `allow_failure`, as in GitLab.
- A bridge (an item with a `downstream` key) becomes a row of
  `kind: "trigger"` at depth 3 under its stage:
  - `title`: `"» " + bridge name`;
  - `subtitle`: downstream ? (`project_id` and `parent_project_id` equal →
    `"child"`; else the parsed `project`, or `"another project"` when it is
    `""`) + `" · #" + (iid || id)` + `" · " + shortRef(ref)` :
    `"downstream not created or unavailable"`;
  - `status`: downstream ? `state(downstream)` : the bridge's status
    (allowed-to-fail rule as for jobs);
  - `info` (via `infoText`): status · `"trigger " + duration(bridge)` ·
    `ago(bridge.completed_at)`;
  - `url`: downstream url, else the bridge's `html_url`; `sha`: downstream
    sha, else the parent's; `repo`/`run`: the parent's, so selecting the row
    keeps the parent inspected.
- `bridgesError` adds one `message` row under the run
  ("Downstream pipelines: " + error), after the stages; cached bridges stay.
- The "Loading jobs…" row is shown while `!detail || !detail.jobs` (a
  details entry can hold only bridges), unless the entry has a jobs error.
- Row key: `runKey + ":bridge:" + id`.
- `nextFailure()` (`PipelinesModel.js:294`) also stops on failed `trigger`
  rows.

### Panel (`PipelinesPanel.qml`)

- `trace()` (`:252-253`): a `trigger` row says "Job logs are not available
  for a trigger row".
- `toggleWatch()` (`:175-176`): a `trigger` row says "Watch the parent
  pipeline row instead".
- `o`, `y`, `Shift+Y` work unchanged through `url` and `sha`.

### Docs

`README.md:302` limit becomes: downstream pipelines show as `»` rows with
their status; their own jobs are not shown; trigger rows show the trigger
job's times; a downstream waiting in `manual` or `scheduled` stops
refreshing until `r`. Help text lists `»`. `manifest.json` → 1.12.0.

## Alternatives rejected

- **`/trigger_jobs` first:** costs a 404 probe on every server before 19.2.
- **Fallback inside the helper:** a hidden second HTTP request outside the
  scheduler's accounting, spacing and cooldown.
- **Expand into downstream jobs:** needs numeric project ids at the helper
  and more polling; follow-up issue (approved answer 1).
- **Separate "Downstream" group:** GitLab's graph places bridges in their
  stage (approved answer 3).
- **Bridges with every 5 s jobs refresh:** about 360 requests per 30
  minutes inspecting vs 120 (approved answer 2).
- **A separate `s.bridges` map:** needs a new panel property and model
  argument; the details entry already has the right lifetime.

## Risks

- **Stage status changes** for stages with bridges (they now count). That
  matches GitLab, but a stage could flip from success to failed.
- **Before the first jobs reply** a details entry may exist with bridges
  only; the model's "Loading jobs…" check must test `detail.jobs`, not
  `detail`.
- **Requests:** one bridges snapshot (one page unless over 100 bridges)
  every 15 s while a pipeline with unfinished bridges is inspected, plus one
  counted 404 probe per host session once `/bridges` is removed; none
  otherwise. Retries back off as for jobs.
- QML: two message strings; smoke test in the microVM.

## Verification

- `tests/test_gitlab.py`: bridges endpoint, `route` validation; 404 →
  `route` error for bridges only; `bridge()` parsing: null downstream,
  `iid`/`project_id`/`parent_project_id` kept or `None`, project from
  `web_url`, foreign host → `""`, bad sha.
- `tests/polling.cjs`: bridges seeded only for the inspected expanded run;
  15 s cadence and the due time reaches `wakeAt`; stops when final; keeps
  going while a downstream runs after the parent finished; manual
  downstream stops; jobs unavailable but bridges still seeded; permission
  error leaves jobs and `blocked` alone; network error sets `bridgesError`,
  success clears it; route error switches to `trigger_jobs` as a counted
  request, then a second route error is a permission error; navigation or
  collapse during pagination drops the task; rerun between pages restarts
  it; both arrival orders keep jobs and bridges fields; jobs completion
  after a bridges permission error keeps `bridgesUnavailable`; `r`
  restarts; not seeded closed or in watch mode; a scenario: 30 minutes
  inspecting a parent with a running child counts about 120 bridge
  requests; existing scenarios unchanged (471).
- `tests/model.cjs`: trigger row fields for child, multi-project, unknown
  project, null downstream; stage order and counts with bridges
  interleaved by id; bridges-only details still say "Loading jobs…"; error
  row; key uniqueness; `nextFailure` reaches a failed trigger row under a
  successful stage.
- `tests/qml-smoke.py` in a fresh microVM: a trigger row appears; `t` and
  `w` show their messages.
- `nix build .#checks.x86_64-linux.plugin`; fresh Codex and Opus reviews.
