---
status: draft
issue: 21
intent: intent/2026-11-16-21-review-correctness.md
---

# Spec: Fix correctness bugs found in the 2026-11-16 review

## Design

The intent was approved with its proposals as the answers: item 7 shows
`success` (no warning marker), item 4 uses per-pipeline lookups (option a),
all thirteen items ship in one PR as 1.0.1, and `waiting_for_callback` is not
added to the polled pipeline filters.

One correction to the intent: the catalogue refresh is **Shift+R**
(`PipelinesPanel.qml:271-272`, README "Shift + R"), not `r`. Plain `r`
refreshes the selected project. Item 3 below uses Shift+R.

Line numbers are for `8445d25`. The numbers follow the intent's items.

1. **Stage names** (`PipelinesModel.js:43`). `byName = Object.create(null)`.
   Only bracket access is used on it, so nothing else changes. The other plain
   maps are keyed by numeric ids or by prefixed row keys (`repo:…`,
   `<repo>:<id>:…`), which cannot collide with `Object.prototype`.
   **Worker release** (`PipelinesPanel.qml:162-166`, `:218-222`). Move the body of
   `onExited` into `function finishRequest(text, code)`, which calls
   `receivePage` inside `try { … } finally { workerBusy = false }`.
   `failedToStart()` calls `receivePage` the same way. Any exception while
   building rows is then still logged by QML, and the next pump can run.
2. **Host change** (`PipelinesPanel.qml:126`, `Polling.js`). New
   `Polling.resetHost(s)` returns `create()` with `opened`, `starts` and
   `serial` copied over and `generation` set to `s.generation + 1`. The request
   budget is ours, not the server's, so it carries over. The cooldown and
   `rateFailures` belong to the old server and are dropped. `configure()` calls
   it only when `configured !== host`, before assigning `host`. In the same
   branch it also clears `expanded`, `details`, `updated` and `error`, and sets
   `cursor = 0`. An in-flight old-host reply fails the generation check in
   `complete()` (`Polling.js:168`) and is dropped. Its process exit still
   releases the worker through item 1. Because `repos` is now empty, the
   existing "configured projects" branch at `:128-129` applies to the new host.
3. **Refused catalogue** (`Polling.js:185-189`). In the permission branch, when
   `t.kind === "catalogue"`, set `s.discover = false` and keep `s.error`.
   Projects already known keep polling. Discovery resumes on Shift+R
   (`manual(…, true)` sets `discover`), or on reopen, because the catalogue is
   still incomplete (`open()`, `:27`).
4. **Queued pipelines** (`Polling.js` `seed`, `:81-83`). Before the follow-up
   check, a cached run that is `queued`, has no `followupAt`, has no
   `lookupError`, and belongs to a project that is not selected gets
   `followupAt = now`. The existing condition then looks it up 15 s later,
   and every 15 s after that while it stays queued, in the `active` group.
   Lookups stop when it becomes `in_progress` (the activity check takes over) or
   `completed`, or after a permission error (`lookupError`). The selected
   project needs none of this, because its summary already polls the queued
   statuses every 60 s.
5. **Running total** (`Polling.js:162`, `:205`). `activity()` records
   `r.activeFromTotal = typeof total === "number" && total >= 0`. The `run`
   branch recomputes `r.active` from cached rows only when `!r.activeFromTotal`.
   GitLab's total already excludes a pipeline that left the running list, so
   no correction is needed. The fallback when GitLab sends no total
   (`tests/polling.cjs:149-156`) is unchanged.
6. **`waiting_for_callback`**. Add it to `QUEUED` in `gitlab.py:19`, so jobs
   and pipelines map to `queued`. Add it to the pending list in `stageStatus()`
   (`PipelinesModel.js:36`). `PHASES` and `Polling.js:2` are unchanged
   (open question 4).
7. **Allowed failures** (`PipelinesModel.js:38`). The success check becomes
   "any `success`, or any `failed` job with `allow_failure`". The order is
   unchanged, so running, blocking failure, pending and canceled still win.
   Job rows keep their own `failed` status.
8. **Job list pruning** (`Polling.js`). New `prune(s)` deletes each
   `s.details` key whose `<repo>:<id>` no longer names a retained run
   (`runFor` returns nothing). `complete()` calls it after the trims: a
   summary's final phase, a finished catalogue, and `activity()`. An expanded
   or inspected run is never trimmed (`kept()`, `:143-145`), so its jobs stay.
9. **Dangling marker** (`menu.py:63`). Use
   `os.path.lexists(Path(__file__).with_name('menu.managed'))`, which is true
   for a broken link.
10. **Job snapshot attempt** (`Polling.js:233-240`). On each jobs page reply,
    read the run's current `run_attempt`. On page 1, store it as `t.attempt`.
    On a later page, if it differs from `t.attempt`, reset the task
    (`page = 1`, `items = []`, `attempt` cleared, `due = now`) and publish
    nothing. On the last page, set `finalAttempt` to `t.attempt` only if the run
    is `completed` with `run_attempt === t.attempt` and every job is completed.
    Otherwise it is `0`, as today. Only one request is ever in flight, so the
    only window for a change is between page replies, which this check covers.
    Offset paging that skips a job is not fixed: GitLab offers no stable
    snapshot for this endpoint. It is listed under Risks.
11. **Manual refresh** (`Polling.js:38-48`). New `restart(s, t, now)` sets
    `due = now` and `failures = 0`. When `t` is not in flight, it also sets
    `page = 1`, `phase = 0` and `items = all = []`. `manual()` calls it on the
    summary and jobs tasks that `ensure()` returns. A task in flight keeps its
    page state, so its reply still matches its phase. `next()` still enforces
    the server cooldown and the request budget.
12. **Selection sync** (`PipelinesPanel.qml:144`). The guard becomes "the
    highlighted row's `repo`/`run` differ from `polling.selected`/`inspected`",
    and calls `selectionChanged(false)` in that case. Project rows have no
    `run`, so they compare as `""`. `select()` keeps its 250 ms debounce for a
    project change.
13. **Idle scheduling** (`Polling.js` `seed`, `next`). `seed()` records
    `s.wakeAt`: the earliest future time any branch would act. That covers
    `stableAt`, `summaryAt + 60000`, `activityAt + interval`,
    `followupAt + 15000`, `jobsAt + 5000`, and every existing task's `due`.
    `next()` skips `seed()` while `now < s.wakeAt`. Every function that changes
    scheduler input sets `s.wakeAt = 0`: `open`, `select`, `manual`,
    `complete`, `resetHost`, and the panel's `configure` when it sets
    `polling.repos`. As a safety net against a missed path, `wakeAt` is capped
    at `now + 60000`. An idle panel therefore sorts the catalogue at most once
    a minute instead of ten times a second.

## Alternatives rejected

- **Item 1: a `hasOwnProperty` check or a `Map`.** `Object.create(null)` is
  one token and works in QML's V4 and in Node.
- **Item 2: keying all polling state by host.** It is larger and only needed
  for several hosts at once, which is out of scope (L5 in the review).
- **Item 3: retrying a refused catalogue with backoff.** A 403 or 404 on
  `/projects?membership=true` is a token or scope problem, and retrying cannot
  fix it.
- **Item 4: option (b), polling `status=pending` in background scans.** It
  costs a request per project per scan, and cannot see a pipeline that leaves
  the pending list without ever being seen running.
- **Item 10: keyset pagination for jobs.** GitLab's jobs endpoint does not
  support it.
- **Item 13: throttling `seed()` to once a second.** That still does steady
  idle work, which the intent rules out.

## Risks

- **Item 4 request cost.** A non-selected project with many cached queued
  pipelines (up to 100 per status from an earlier summary) gets one lookup each
  per 15 s. These run in the `active` group, which the 3:1:1 slot rotation
  limits to about one request in five, so interactive work is not starved.
  They can still delay other active projects. The plan's test asserts the
  interactive share.
- **Item 13 stall.** A missed invalidation would delay scheduling by up to the
  60 s cap. The existing request-cadence tests in `tests/polling.cjs` (15 s
  active, 10 s selected, 5 s jobs) catch a stall longer than the cadence.
- **Item 10 restart loop.** A run whose `run_attempt` changed on every page
  would never finish. The attempt only changes on retry or completion, so this
  needs a pipeline retried more than once a second.
- **Item 2 on the first load.** Startup configure moves from the default
  `gitlab.com` to the configured host. The state is empty at that point, so
  the reset has no visible effect.
- **The GitHub sibling** keeps these bugs until it is ported separately.
- No host or NixOS impact: user-level plugin files only.

## Verification

All checks run in `nix flake check`, which runs `tests/test_*.py`,
`tests/model.cjs` and `tests/polling.cjs`. `tests/qml-smoke.py` runs locally
in a graphical session, as before.

| Item | Test | Proves |
| --- | --- | --- |
| 1 | `model.cjs`: jobs in stages `constructor`, `toString`, `__proto__` group into three stages | Grouping |
| 1 | `qml-smoke.py`: put a run whose detail makes `Model.rows` throw, call `finishRequest`, then check `workerBusy` is false and a later pump starts a request | Worker release |
| 2 | `polling.cjs`: `resetHost` with a flight: the old reply is rejected, `repos`/`details` are empty, `starts` is kept, `cooldown` is 0 | Isolation |
| 2 | `qml-smoke.py`: configure host A, add repos, configure host B: only B's configured projects are listed, and `expanded` is empty | Panel reset |
| 3 | `polling.cjs`: catalogue 403: no catalogue request in the next 10 s, `error` set, other activity continues; `manual(…, true)` resumes | No loop |
| 4 | `polling.cjs`: a cached queued run on a non-selected project gets a `run` request within 15 s; it stops once the run is completed; it stops after `lookupError` | Reconciliation |
| 5 | `polling.cjs`: activity `total: 250`, then a run lookup: `active` stays 250. Existing `total: -1` test unchanged | Total kept |
| 6 | `test_gitlab.py`: a `waiting_for_callback` job maps to `queued`. `model.cjs`: a stage with one is `pending` | Mapping |
| 7 | `model.cjs`: a stage with only an allowed failure is `success`, and the job row is `failed` | Status |
| 8 | `polling.cjs`: a run trimmed from the recent ten, and a project dropped from the catalogue, both lose their `details`; an expanded run keeps it | Pruning |
| 9 | `test_menu.py`: a dangling `menu.managed` symlink leaves the menu file untouched | Marker |
| 10 | `polling.cjs`: change `run_attempt` between page 1 and page 2: the task restarts, and no `finalAttempt` is set for the newer attempt | Snapshot |
| 11 | `polling.cjs`: after a network error pushes `due` out by 5 min, `manual()` makes the summary due now with `failures` 0; a task in flight keeps its `phase` | Refresh |
| 12 | `qml-smoke.py`: the selected run is trimmed while its project stays: `polling.inspected` follows the highlighted row | Sync |
| 13 | `polling.cjs`: idle state, 50 calls to `next()` with nothing due: `seed` runs at most once (counted via `wakeAt`); `select()` triggers it again | Idle cost |

Release: bump `version` in `manifest.json` to 1.0.1 (the flake reads it).
