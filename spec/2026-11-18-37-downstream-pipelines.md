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
self-managed servers have no `trigger_jobs`. So:

- New task kind `"bridges"` in `page_endpoint` (`gitlab.py:125-151`), same
  validation as `jobs` (numeric run id): `{base}/{run}/bridges?per_page=100&page={n}`.
- In `read_page`, a `bridges` reply with HTTP 404 is retried once with
  `{base}/{run}/trigger_jobs?per_page=100&page={n}` (the parent pipeline is
  readable, so a 404 here means the route is gone). Only when that also
  fails does the normal error mapping apply.
  `shortcut: one extra request per page after /bridges is removed; switch
  the order once the oldest supported server has trigger_jobs.`
- `bridge(row)` = `job(row)` plus `downstream`: `None` when
  `downstream_pipeline` is null, else
  `{id, status: state(raw), conclusion: raw, ref, sha, url, project}`.
  `downstream_pipeline` has no project id or path (docs example: `id`,
  `sha`, `ref`, `status`, `created_at`, `updated_at`, `web_url`), so
  `project` is parsed from `web_url`: the path before `/-/pipelines/`, only
  when the URL's host is the task host and `project_path()` accepts it, else
  `""`. `sha` follows the same 40/64-hex rule as `pipeline()`; `url` is kept
  as given (the panel's `browsable()` pins the host before opening).
- Replies sorted by id and paginated with `nextPage`, like `jobs`.

### Scheduling (`Polling.js`)

- Bridges are stored on the existing details entry:
  `s.details[repo:run].bridges` (list), `.bridgesAt`, `.bridgesError`,
  `.bridgesUnavailable`. Every existing deletion of a details entry (rerun,
  trim, dropped runs, removed projects) also clears them. The jobs
  completion (`Polling.js:398`) keeps the three bridge fields when it
  replaces the entry.
- In `seed()`, next to the jobs task (`Polling.js:177-184`), for the
  selected, inspected, expanded run only: a `"bridges"` task, group
  `interactive`, due `age(detail.bridgesAt, 15000)`, unless
  `bridgesUnavailable`, or **final**: the run is completed, its jobs are
  final (`finalAttempt` as today), bridges were fetched, and every bridge
  is completed with its downstream either null or completed. A downstream
  in `manual` or `scheduled` counts as completed (it waits for a person or
  a time); `r` refreshes it.
- `manual()` (`r`) restarts the bridges task with the jobs task and clears
  `bridgesUnavailable`.
- Pages accumulate in `t.items` like jobs; on the last page
  `bridges=t.items, bridgesAt=now, bridgesError=""`.
- Errors: `permission` sets `bridgesError` and `bridgesUnavailable` and
  `bridgesAt=now`, leaving jobs and `r.blocked` alone (unlike other kinds,
  `Polling.js:330`); other errors take the existing retry path.
- Never seeded while closed, in watch-only mode or for background checks:
  `seed()` runs only while open, and the task exists only under the
  inspected condition.

### Rows (`PipelinesModel.js`)

- `stages()` gets `jobs.concat(bridges)`, so a bridge sits in its stage and
  counts towards the stage's status and `done/total`, as in GitLab.
- A bridge (an item with a `downstream` key) becomes a row of
  `kind: "trigger"` at depth 3 under its stage:
  - `title`: `"» " + bridge name`;
  - `subtitle`: downstream ? (`project === parent repo` or `""` →
    `"child"`, else the project path) + `" · #" + id + " · " +
    shortRef(ref)` : `"downstream not created or unavailable"`;
  - `status`: downstream ? `state(downstream)` : the bridge's status
    (allowed-to-fail rule as for jobs);
  - `info` (via `infoText`): status · `"trigger " + duration(bridge)` ·
    `ago(bridge.completed_at)`;
  - `url`: downstream url, else the bridge's `html_url`; `sha`: downstream
    sha, else the parent's; `repo`/`run`: the parent's, so selecting the row
    keeps the parent inspected.
- A `bridgesError` adds one `message` row under the run
  ("Downstream pipelines: " + error), after the stages; cached bridges stay.
- Row key: `runKey + ":bridge:" + id`, distinct from job keys.

### Panel (`PipelinesPanel.qml`)

- `trace()` (`:252-253`): a `trigger` row says "Job logs are not available
  for a trigger row".
- `toggleWatch()` (`:175-176`): a `trigger` row says "Watch the parent
  pipeline row instead".
- `o`, `y`, `Shift+Y` work unchanged through `url` and `sha`.

### Docs

`README.md:302` limit becomes: downstream pipelines show as `»` rows with
their status; their own jobs are not shown, and trigger rows show the
trigger job's times. Help text lists `»`. `manifest.json` → 1.12.0.

## Alternatives rejected

- **`/trigger_jobs` first:** fails on servers before 19.2; doubles every
  request there.
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
- **Requests:** at most one page every 15 s while a pipeline with
  unfinished bridges is inspected; none otherwise.
- QML: two message strings; smoke test in the microVM.

## Verification

- `tests/test_gitlab.py`: bridges endpoint and validation; 404 fallback to
  `trigger_jobs` (and no fallback for other statuses); `bridge()` parsing:
  null downstream, child vs other project, foreign host → `""`, bad sha.
- `tests/polling.cjs`: bridges seeded only for the inspected expanded run;
  15 s cadence; stops when final; keeps going while a downstream runs
  after the parent finished; manual downstream stops; permission error
  leaves jobs and `blocked` alone; `r` restarts; jobs completion keeps
  bridges; not seeded closed or in watch mode; a scenario: 30 minutes
  inspecting a parent with a running child → about 120 bridge requests;
  existing scenarios unchanged (471).
- `tests/model.cjs`: trigger row fields for child, multi-project, null
  downstream; stage counts include bridges; bridges-only details still say
  "Loading jobs…"; error row; key uniqueness.
- `tests/qml-smoke.py` in a fresh microVM: a trigger row appears, `t` and
  `w` show their messages.
- `nix build .#checks.x86_64-linux.plugin`; fresh Codex and Opus reviews.
