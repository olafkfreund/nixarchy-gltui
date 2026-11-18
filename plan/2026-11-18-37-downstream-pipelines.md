---
status: approved
issue: 37
spec: spec/2026-11-18-37-downstream-pipelines.md
coders:
  1: codex   # helper boundary: validation, 404 mapping, URL/id parsing
  2: codex   # scheduler lifecycle: seeding, pruning, route switch, merges
  3: codex   # row building, stage order, failure navigation
  4: coder   # two QML guards and the smoke fixture
  5: coder   # docs, help text, version
reviewers:
  - codex    # fresh diff review against this plan (agy is out of use, #2748)
---

# Plan: Show downstream and child pipelines as nested rows

## Decisions (from the approved spec)

- Status-only `»` rows inside the bridge's stage; no downstream jobs, no
  recursion. Bridges refresh every 15 s, only for the selected, inspected,
  expanded run, never while closed, in watch mode or in background checks.
- **Endpoint:** task kind `"bridges"` with `route` ∈ {`"bridges"`
  (default), `"trigger_jobs"`}: `projects/<repo>/pipelines/<run>/<route>?per_page=100&page=<n>`.
  `/bridges` is deprecated since GitLab 19.2 in favour of `/trigger_jobs`
  (introduced 19.2); older servers only have `/bridges`.
- **404 on a bridges-kind request** → `errorType: "route"` (not
  `permission`). The helper never retries itself. The scheduler restarts
  that one task with `route: "trigger_jobs"` as a new counted request; on
  success `s.bridgeRoute = "trigger_jobs"` for later tasks (reset with the
  host); a `route` error on `trigger_jobs` is handled as `permission` for
  that pipeline only, and the host preference stays.
- **`bridge(row)`** = `job(row)` + `downstream`: `None` unless
  `downstream_pipeline` is an object; else `{id, iid, project_id,
  parent_project_id, status: state(raw), conclusion: raw, ref, sha, url,
  project}`. `iid`, `project_id` and `parent_project_id` (from
  `row["pipeline"]["project_id"]`) are kept only as non-negative ints, else
  `None`. `project`: path before `/-/pipelines/` in `web_url`, only when the
  URL's host equals the task host and `project_path()` accepts it, else
  `""`. `sha`: same 40/64-hex rule as `pipeline()`, else `""`. `url` as given.
  Sorted by id, paginated with `nextPage` like jobs.
- **Storage** on `s.details[repo:run]`: `bridges`, `bridgesAt`,
  `bridgesError`, `bridgesUnavailable`. All writes merge: jobs success keeps
  the four bridge fields and clears its own `error`/`unavailable`; jobs
  permission error keeps them; bridge writes keep every jobs field.
- **Finality:** run completed, jobs final (`finalAttempt` as today, or jobs
  unavailable), bridges fetched, every bridge completed with downstream null
  or completed (`manual`/`scheduled` downstreams count as completed).
- **Errors:** bridges `permission` → `bridgesError`, `bridgesUnavailable`,
  `bridgesAt=now`; jobs and `r.blocked` untouched. Network → existing retry
  path plus `bridgesError` (cached bridges stay); success clears it. `auth`,
  `setup`, `rate` unchanged (global).
- **Rows:** `stages()` gets jobs and bridges together, sorted by id. A
  bridge row: `kind: "trigger"`, depth 3, key `runKey + ":bridge:" + id`,
  `title` `"» " + name`, `subtitle` (downstream: `"child"` only when both
  project ids are valid and equal, else `project` or `"another project"`,
  then `" · #" + (iid || id) + " · " + shortRef(ref)`; no downstream:
  `"downstream not created or unavailable"`), `status` (downstream ?
  `state(downstream)` : the bridge's, with the allowed-to-fail rule),
  `info` via `infoText`: status · `"trigger " + duration` · ago(completed),
  `url` downstream url else bridge `html_url`, `sha` downstream sha else
  parent's, `repo`/`run` the parent's. Stage status and counts use the
  bridge's own status and `allow_failure`.
- `bridgesError` → one `message` row "Downstream pipelines: " + error after
  the stages. "Loading jobs…" while `!detail || !detail.jobs` (and no jobs
  error). `nextFailure()` also stops on failed `trigger` rows.
- Panel: `t` on a trigger row → "Job logs are not available for a trigger
  row"; `w` → "Watch the parent pipeline row instead". `o`/`y`/`Shift+Y`
  unchanged.
- Version 1.12.0.

## Steps

1. **`gitlab.py`, `tests/test_gitlab.py`** (codex).
   - `page_endpoint` (`gitlab.py:125-151`): accept `"bridges"`, validate run
     id as for jobs and `route` ∈ {bridges, trigger_jobs} (missing →
     bridges; anything else → `ValueError`).
   - `read_page` (`:252-319`): for kind bridges, HTTP 404 →
     `errorType "route"`, error "GitLab has no trigger jobs route"; data via
     `bridge()`, sorted by id, `nextPage` like jobs.
   - `bridge(row, host)` next to `job()` (`:232`), per Decisions.
   - Tests: bridges endpoint for both routes; missing route → bridges;
     invalid route and bad run id → `ValueError`; 404 → `route` for bridges
     only (jobs 404 still permission); `bridge()`: null/non-object
     downstream → `None`; `iid`/`project_id`/`parent_project_id` kept as
     ints or `None` (negative, string, missing); project parsed from
     `web_url`; foreign host or invalid path → `""`; bad sha → `""`.
   → verify: `python3 -m unittest discover -s tests`.
   Traps: never echo URLs or response text into errors; keep 404 →
   permission for every other kind.

2. **`Polling.js`, `tests/polling.cjs`** (codex).
   - `create()`/`resetHost()`: `bridgeRoute:"bridges"`.
   - `seed()` (`:177-184`): split the jobs guard (`detail.unavailable` no
     longer `return`s the repo callback); add the bridges task per
     Decisions; future due → `wake`. Task carries `route: s.bridgeRoute`.
   - Pruning (`:138-140`): bridges deleted under the jobs condition.
   - `mergeRuns()` (`:252`): attempt change restarts a bridges task too.
   - `manual()` (`:122-125`): restart bridges with jobs; clear
     `bridgesUnavailable`/`bridgesError`.
   - `complete()`: `route` error handling per Decisions; bridges permission
     and network errors; last page merges `bridges`, `bridgesAt`,
     `bridgesError:""`, and sets `s.bridgeRoute` when the task's route was
     `trigger_jobs`; jobs success (`:398`) and jobs permission (`:331`)
     merge per Decisions. The reply validity check (`:303-304`) treats
     bridges as a list kind.
   - `next()` (`Polling.js:225`): copy `route` onto the emitted request for
     bridges tasks (`request.route = t.route`).
   - Tests, one each: seeded only for the selected, inspected, expanded run;
     15 s cadence and the future due reaches `wakeAt`; stops when final;
     keeps going while a downstream runs after the parent finished; a
     `manual` downstream stops it; jobs unavailable but bridges still
     seeded; permission error leaves jobs and `blocked` alone; network error
     sets `bridgesError`, success clears it; route error restarts that task
     and the emitted request has `route: "trigger_jobs"` (counted in
     `s.requests`); its success sets `s.bridgeRoute`; a second route error is
     a permission error for that pipeline only and a later readable pipeline
     still requests `/bridges`; navigation or collapse during pagination
     drops the task; a rerun between pages restarts it; both arrival orders
     (jobs then bridges, bridges then jobs) keep both field sets; jobs
     completion after a bridges permission error keeps
     `bridgesUnavailable`; jobs permission error → `r` → jobs success clears
     `error`/`unavailable` and keeps bridge fields; `r` restarts bridges;
     no bridges task while closed or in watch-only mode; a 30-minute
     scenario inspecting a parent with a running child prints its bridge
     request count (about 120); the existing realistic scenario stays 471.
   → verify: `node tests/polling.cjs` all pass, 0 fail.
   Traps: ES5 only; every exported writer sets `s.wakeAt=0`; `ensure()`
   keeps an existing task's due time; use `restart()` for immediate reruns.

3. **`PipelinesModel.js`, `tests/model.cjs`** (codex).
   - `rows()` (`:258-288`): stages from jobs + bridges sorted by id; trigger
     rows; bridges error row; loading check per Decisions.
   - `infoText()`: `trigger` branch.
   - `nextFailure()` (`:294`): include `trigger`.
   - Tests, one each: trigger row for a child (equal project ids), another
     project (path), unknown project (`"another project"`), both ids
     missing (not "child"), null downstream (bridge status and
     "downstream not created or unavailable"); `#iid` used, `#id` when iid
     is missing; url/sha fallbacks; stage order and done/total with jobs
     and bridges interleaved by id; a details entry with only bridges still
     shows "Loading jobs…"; `bridgesError` row; trigger keys distinct from
     job keys with the same id; `nextFailure` reaches a failed trigger row
     under a successful stage.
   → verify: `node tests/model.cjs` passes.
   Depends on step 2's details fields (`bridges`, `bridgesError`).
   Traps: ES5 only (QML `.import`); add any new field the delegate reads to
   `shownFields`.

4. **`PipelinesPanel.qml`, `tests/qml-smoke.py`** (coder).
   - `trace()` (`:252-253`), `toggleWatch()` (`:175-176`): trigger guards.
   - Smoke fake helper (`tests/qml-smoke.py:33-45`): answer kind `bridges`
     with one bridge in stage `test` (downstream running, other project).
   - The async block at `tests/qml-smoke.py:1676-1699`: its gate must wait
     for both `details[...].jobs` and `details[...].bridges` (bridges can
     create the entry first). Then expand stage `test`, find the `trigger`
     row, select it, press `t` and `w`, and check the two notices. Keep the
     existing lint-row checks working (rows shift by one).
   → verify: `python3 -c "import ast,sys; ast.parse(open('tests/qml-smoke.py').read())"`.
   Traps: do **not** run `tests/qml-smoke.py`, quickshell or `notify-send`
   on the host; the lead runs the smoke test in a microVM.

5. **`README.md`, `keybindings.sh`, `manifest.json`** (coder).
   - `README.md:302`: reword the limit per the spec's Docs section; add
     `»` trigger rows where pipeline rows are described.
   - `keybindings.sh --print` help: one line for `»` rows.
   - `manifest.json`: 1.12.0.
   - Wording for the limit: "Downstream and child pipelines show as `»`
     rows inside the trigger job's stage, with their status. Their own jobs
     are not shown. The times on a `»` row are the trigger job's. A
     downstream waiting in manual or scheduled stops refreshing until you
     press `r`."
   → verify: `bash keybindings.sh --print | grep -n '»'`.
   Steps 4-5 follow steps 2-3.

## Tests

```bash
set -o pipefail
python3 -m unittest discover -s tests
node tests/model.cjs
node tests/polling.cjs | tee /tmp/polling37.out
nix build --no-link .#checks.x86_64-linux.plugin
```

Expected: all pass; the realistic scenario still 471; the new
inspected-parent scenario about 120 bridge requests.

Then (lead): `tests/qml-smoke.py` in a fresh microVM
(`nixarchy vm create gltui-37 --template nixarchy-desktop`, run within a
minute of boot); a fresh Codex diff review and an Opus review given only
this plan and `git diff`.

## Deviations

From the final Codex and Opus reviews:

- **Finality** also requires a bridges snapshot taken after the parent
  finished (`bridgesAttempt`, set like `finalAttempt`). Otherwise a manual
  trigger started just before the parent finished could leave a stale
  "not created" row that never refreshes.
- `manual`/`scheduled` checks dropped from finality: the helper already
  normalises them to status `completed`; the test now uses that shape.
- `bridge()` treats a URL `urlsplit` cannot parse as no project, instead of
  failing the whole page.
- A `route` error on `trigger_jobs` uses the text "Pipeline unavailable or
  read_api scope missing".
- A trigger row with an empty downstream URL falls back to the bridge's job
  URL. Its sha stays the downstream's (possibly empty), not the parent's.
- `e` help text names `»` rows.
- Kept as is: bridges errors set the panel-wide error strip, like jobs
  errors.

## Rollback

Revert the PR commits. No config or state file format changes.
