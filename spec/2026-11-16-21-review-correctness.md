---
status: approved
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

**Shared mechanism: a restart flag on a task.** Items 10 and 11 both need to
restart a task that may be in flight. New `restart(s, t, now)` in `Polling.js`:

- not in flight: set `page = 1`, `phase = 0`, `items = all = []`, `failures = 0`
  and `due = now`;
- in flight (`s.flight.key === t.key`): set `t.restart = true`.

In `complete()`, after the rate-limit block (`:174-179`, so a server cooldown
in that reply still applies) and before the error branch, a task with
`t.restart` is reset as above and has the flag cleared. Its reply data is
discarded, and `complete` returns `true`. The reply that was already in flight
is never read against the reset phase.

1. **Stage names** (`PipelinesModel.js:43`). `byName = Object.create(null)`.
   Only bracket access is used on it. The other plain maps are keyed by numeric
   ids or by prefixed row keys (`repo:…`, `<repo>:<id>:…`), which cannot
   collide with `Object.prototype`.
   **Worker release** (`PipelinesPanel.qml:162-166`, `:218-222`). Move the body
   of `onExited` into `function finishRequest(text, code)`, which calls
   `receivePage` inside `try { … } finally { workerBusy = false }`.
   `onExited` and `failedToStart()` both go through it, so it is the real exit
   path. An exception while building rows still propagates (and QML logs it),
   but the next pump can run.
2. **Host change** (`PipelinesPanel.qml:126`, `Polling.js`). New
   `Polling.resetHost(s)` returns `create()` with `opened`, `starts` and
   `serial` copied over and `generation` set to `s.generation + 1`. The request
   budget is ours, so it carries over. The old server's cooldown and
   `rateFailures` are dropped. `configure()` calls it only when
   `configured !== host`, before assigning `host`. In the same branch it also
   clears `expanded`, `details`, `updated` and `error`, and sets `cursor = 0`.
   An old-host reply fails the generation check in `complete()`
   (`Polling.js:168`). Its process exit still releases the worker through
   item 1. `repos` is now empty, so the configured-projects branch
   (`:128-129`) applies to the new host.
3. **Refused catalogue** (`Polling.js:185-189`). In the permission branch, when
   `t.kind === "catalogue"`, set `s.discover = false` and
   `s.catalogueError = s.error`. `s.error` is cleared by any later successful
   request (`:198`), so the refusal needs its own field. `catalogueError` is
   cleared only by `manual(…, true)` (Shift+R), which also sets `discover`, and
   by `resetHost`. `open()` (`:27`) does not set `discover` while
   `catalogueError` is set, so reopening does not retry it, as the intent
   requires. The panel shows `polling.error || polling.catalogueError`
   (`PipelinesPanel.qml:140`). Projects already known keep polling.
4. **Queued pipelines** (`Polling.js` `seed`, `:81-83`). Before the follow-up
   check, a cached run that is `queued`, has no `followupAt`, has no
   `lookupError`, and belongs to a project that is not selected gets
   `followupAt = now`. The existing condition then looks it up 15 s later and
   every 15 s while it stays queued. These lookups use the **`background`**
   group, not `active`. `next()` lends unused slots to other groups
   (`:102-105`), so queued lookups take only slots that interactive and active
   work leave free. They cannot delay running-project checks. Lookups stop when
   the run becomes `in_progress` (the activity check takes over), when it
   becomes `completed`, or after a permission error (`lookupError`). The
   selected project needs none of this: its summary polls the queued statuses
   every 60 s.
5. **Running total** (`Polling.js:162`, `:205`). `activity()` sets
   `r.activeFromTotal = typeof total === "number" && total >= 0` on every
   reply, so a later reply without a total turns it off again. The `run` branch
   recomputes `r.active` from cached rows only when `!r.activeFromTotal`.
   GitLab's total already excludes a pipeline that left the running list. The
   fallback when GitLab sends no total (`tests/polling.cjs:149-156`) is
   unchanged.
6. **`waiting_for_callback`**. Add it to `QUEUED` (`gitlab.py:19`), so jobs and
   pipelines map to `queued`. Add it to the pending list in `stageStatus()`
   (`PipelinesModel.js:36`). `PHASES` and `Polling.js:2` are unchanged (open
   question 4).
7. **Allowed failures** (`PipelinesModel.js:38`). The success check becomes
   "any `success`, or any `failed` job with `allow_failure`". The order is
   unchanged, so running, blocking failure, pending and canceled still win.
   Job rows keep their own `failed` status.
8. **Job list pruning** (`Polling.js`). Prune where runs leave the model:
   - `trimRuns()` (`:139-142`) deletes `s.details[<repo>:<id>]` for each run it
     drops. Every trim goes through it: `mergeRuns()` on summary pages and run
     lookups, the final summary phase, and `activity()`.
   - The catalogue completion (`:222`) deletes the details of every project it
     removes. Details keys are `<repo>:<id>`, and repo paths contain no `:`.

   An expanded or inspected run is never trimmed (`kept()`, `:143-145`).
9. **Dangling marker** (`menu.py:63`). Use
   `os.path.lexists(Path(__file__).with_name('menu.managed'))`, which is true
   for a broken link.
10. **Job snapshot attempt** (`Polling.js` `mergeRuns`, `:130-138`). Detect the
    change where pipeline state is merged, not at page boundaries. In
    `mergeRuns()`, for each incoming run whose `run_attempt` differs from the
    cached run's, call `restart()` on that run's jobs task if one exists. This
    catches every change the scheduler observes, including
    `active → <timestamp> → active` between two job pages. A reset task drops
    the pages fetched so far (`:211`), and the shared restart flag protects a
    page in flight. `finalAttempt` (`:240`) is unchanged: it can only be set
    by a fetch that ran with no observed change.
    Offset paging that skips a job is not fixed, because GitLab offers no
    stable snapshot for this endpoint. It is listed under Risks.
11. **Manual refresh** (`Polling.js:38-48`). `manual()` calls `restart()` on
    the summary task (and the jobs task, when it is created) that `ensure()`
    returns. A pending task becomes due now, with its backoff cleared. A
    summary in flight finishes its current request, discards that reply, and
    starts again from `recent`, page 1, as the intent requires. `next()` still
    enforces the server cooldown and the request budget.
12. **Selection sync** (`PipelinesPanel.qml:144`). The guard becomes: if
    `(current && current.repo || "") !== polling.selected` or
    `(current && current.run || "") !== polling.inspected`, call
    `selectionChanged(false)`. `select()` does not call `adopt()`, so this
    cannot loop, and a second `adopt()` with nothing changed does not call it
    again. Project rows have no `run`, so they compare as `""`. `select()`
    keeps its 250 ms debounce for a project change.
13. **Idle scheduling** (`Polling.js` `seed`, `next`). `seed()` computes
    `s.wakeAt`: the earliest future time at which any of its branches would
    act. That covers `stableAt`, `summaryAt + 60000`,
    `activityAt + interval`, `followupAt + 15000`, `jobsAt + 5000`, and every
    task's `due`. `next()` skips `seed()` while `now < s.wakeAt`. There is no
    periodic safety scan, so an idle panel does no per-project work, as the
    intent requires.
    **Invalidation contract:** every exported `Polling.js` function that writes
    scheduler input sets `s.wakeAt = 0`. Those functions are `open`, `close`,
    `select`, `manual`, `complete`, `ensure`, `activity`, `mergeRuns`,
    `trimRuns`, `restart` and `resetHost`. Direct writes from outside (the
    panel's `configure` setting `polling.repos`, and test fixtures) must set
    `wakeAt = 0` themselves. The plan lists each existing fixture that needs
    it.

## Alternatives rejected

- **Item 1: a `hasOwnProperty` check or a `Map`.** `Object.create(null)` is
  one token and works in QML's V4 and in Node.
- **Item 2: keying all polling state by host.** It is larger and only needed
  for several hosts at once, which is out of scope (L5 in the review).
- **Item 3: retrying a refused catalogue with backoff.** A 403 or 404 on
  `/projects?membership=true` is a token or scope problem, and retrying cannot
  fix it.
- **Item 4: option (b), or `active`-group lookups.** Option (b) costs a request
  per project per scan. `active` lookups would compete with running-project
  checks: 15 continuously queued pipelines would ask for the whole 60-per-minute
  budget.
- **Item 10: comparing attempts at job-page replies.** It misses a change that
  returns to the same token (`active → <timestamp> → active`).
- **Item 10: keyset pagination for jobs.** GitLab's jobs endpoint does not
  support it.
- **Item 13: throttling `seed()`, or a 60 s safety scan.** Both still do idle
  work, which the intent rules out.

## Risks

- **Item 4 latency under load.** With many queued pipelines and busy running
  projects, queued lookups wait for free slots, so reconciliation can take
  longer than 15 s. The intent allows this ("subject to the request budget").
  The simulation test bounds it.
- **Item 13 stall.** A write path that skips invalidation delays scheduling
  until the next invalidating call. The existing cadence tests in
  `tests/polling.cjs` (15 s active, 10 s selected, 5 s jobs) and the new idle
  test catch a stall. Any future exported writer must set `wakeAt = 0`; a
  comment at `create()` says so.
- **Item 10 restart loop.** The attempt only changes on retry or completion,
  so a loop needs a pipeline retried between every two job pages.
- **Item 11 extra request.** Pressing `r` during a summary wastes the reply in
  flight. That is one request, by an explicit key press.
- **Item 2 on the first load.** Startup configure moves from the default
  `gitlab.com` to the configured host. The state is empty at that point, so
  the reset has no visible effect.
- **The GitHub sibling** keeps these bugs until it is ported separately.
- No host or NixOS impact: user-level plugin files only.

## Verification

`nix flake check` runs `tests/test_*.py`, `tests/model.cjs` and
`tests/polling.cjs`. `tests/qml-smoke.py` runs locally in a graphical session,
as before. Every test below fails on `8445d25`.

| Item | Test | Proves |
| --- | --- | --- |
| 1 | `model.cjs`: jobs in stages `constructor`, `toString`, `__proto__` group into three stages | Grouping |
| 1 | `qml-smoke.py`: give a run detail that makes `Model.rows` throw, call `finishRequest` inside a JS `try`/`catch` and assert the error, restore valid data, check `workerBusy` is false and the next pump starts a request. Caught in JS, so no `TypeError` reaches the log scan (`:158`) | Worker release |
| 2 | `polling.cjs`: `resetHost` during a flight, then start a new-host flight, then deliver the old reply: it is rejected. `repos`/`details` are empty, `starts` is kept, `cooldown` is 0 | Isolation |
| 2 | `qml-smoke.py`: configure host A, add repos, configure host B during a real worker flight: only B's configured projects are listed, `expanded` is empty, and the worker is released | Panel reset |
| 3 | `polling.cjs`: catalogue 403, then a successful activity reply: `catalogueError` is kept and there is no catalogue request for 10 s; close and reopen: still none; `manual(…, true)` resumes | No loop, error kept |
| 4 | `polling.cjs`: uncongested: a queued run on a non-selected project gets a `run` request within 15 s; it stops after `in_progress`, after `completed`, and after `lookupError` | Reconciliation |
| 4 | `polling.cjs`: congested: 30 queued runs, 5 running projects and an inspected jobs fetch over 10 minutes: under 60 requests per minute, the running projects keep their 15 s cadence, and every queued run is looked up at least once | Cost bound |
| 5 | `polling.cjs`: activity `total: 250`, then a run lookup: `active` stays 250. A later activity without a total falls back to the cached count | Total kept |
| 6 | `test_gitlab.py`: a `waiting_for_callback` job maps to `queued`. `model.cjs`: a stage with one is `pending`. `polling.cjs`: a jobs list with one gets no `finalAttempt` | Mapping |
| 7 | `model.cjs`: a stage with only an allowed failure is `success`, and the job row is `failed` | Status |
| 8 | `polling.cjs`: a run dropped by an intermediate summary page, by a run lookup, and with a project removed from the catalogue each loses its `details`; an expanded run keeps it | Pruning |
| 9 | `test_menu.py` (temporary plugin fixture, `:122`): a dangling `menu.managed` symlink leaves the menu file untouched | Marker |
| 10 | `polling.cjs`: `run_attempt` changes A→B between job pages, and separately `active → <timestamp> → active`: both restart the jobs task from page 1, and no mixed list is published | Snapshot |
| 11 | `polling.cjs`: repeated errors push the summary out by 5 min, then `manual()` makes it due now with `failures` 0. `manual()` during a summary flight: that reply is discarded, and the next summary request is `recent`, page 1 | Refresh |
| 12 | `qml-smoke.py`: filter on the selected pipeline's status, then deliver a status change that drops that row while its project stays: `polling.inspected` follows the newly highlighted row; a second `adopt()` does not call `select()` again | Sync |
| 13 | `polling.cjs`: count real `seed()` calls (a test counter on `s`): with nothing due, 50 calls to `next()` run `seed` once; `select()` makes it run again | Idle cost |

Release: bump `version` in `manifest.json` to 1.0.1 (the flake reads it).
