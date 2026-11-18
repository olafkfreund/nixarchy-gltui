---
status: draft
issue: 35
intent: intent/2026-11-18-35-fewer-requests.md
---

# Spec: Cut API requests for accounts with many idle projects

## Design

All changes are in `Polling.js`, `tests/polling.cjs` and `README.md`. No
change to `gitlab.py`, the model or the panel.

### 1. Idle back-off

- **New constant:** `IDLE=[600000,1200000,2400000,3600000]` (10, 20, 40, 60
  minutes).
- **New field on each repo:** `r.idle`, an index into `IDLE`.
  - It is undefined until the project's first running-list result.
  - The repo object survives catalogue refreshes (`Object.assign` at
    `Polling.js:329`). `resetHost()` drops it with the repos.
- **Where the interval is chosen:** the background interval at
  `Polling.js:133` becomes `IDLE[r.idle||0]` instead of `600000`.
  - Undefined `r.idle` keeps today's first check: `activityAt` is
    undefined, so the check is due at once.
  - The selected (10 s), running (15 s) and pinned (60 s) intervals are
    unchanged.
- **Updated in `activity()`** (`Polling.js:241-261`), after `r.active` is
  set:
  - `r.idle=0` if `r.active>0` or the project is selected;
  - else, if `r.idle` is undefined, the start level from `lastActivity`
    (below);
  - else `Math.min(3, r.idle+1)`.

  `activity()` also runs for the selected summary's `running` phase, so
  that path is covered too.
- **Start level:** `start(r,now)` takes the age `now-Date.parse(r.lastActivity)`:

  | Age | Level | Next interval |
  | --- | --- | --- |
  | under 1 day | 0 | 10 minutes |
  | under 7 days | 1 | 20 minutes |
  | older | 3 | 60 minutes |

  A missing or unparsable `lastActivity` gives 0, today's behaviour.
- **What resets the level to 0:**
  - **finding a running pipeline:** `activity()` above, and the run lookup
    path at `Polling.js:316-319` when it leaves `r.active>0`;
  - **selecting the project:** `select()` sets `r.idle=0` on the newly
    selected repo, even if no request completes before it is deselected.
    The `activity()` rule above keeps it at 0 while selected. After
    deselection the next background check is 10 minutes after the last
    one;
  - **manual refresh `r`:** sets `r.idle=0` on the selected project in
    `manual()`;
  - **`R` (catalogue refresh):** sets `r.idle=0` on every repo;
  - **a changed `lastActivity`:** see section 2.

### 2. Catalogue refresh while open, with a change hint

- **Periodic refresh.** In `seed()`, before the catalogue `ensure` at
  `Polling.js:120`: if `!s.discover`, `s.catalogueComplete`,
  `!s.catalogueError` and `now>=s.catalogueAt+300000`, then set
  `s.discover=true` and `s.periodic=true`. The refresh type is chosen only
  when a scan starts, and it holds through pagination and retries.
  - **Wake:** while `!s.discover`, `seed()` folds `s.catalogueAt+300000`
    into its `wake`, so a sleeping scheduler wakes for the next scan. Once a
    scan is under way, only the catalogue task's own due time counts, so a
    page retry does not keep `wakeAt` in the past.
  - **`open()` and `R`:** they set `s.discover=true` and `s.periodic=false`,
    as a full refresh that clears `blocked`. An overdue reopen is therefore
    a full refresh: `discover` is already set, so `seed()` does not mark it
    periodic.
  - **`R` during a periodic scan:** it also restarts the catalogue task from
    page 1 (`restart()`), so every page of the upgraded scan clears
    `blocked`.
- **Pagination and errors:** unchanged. The catalogue task keeps its own
  pages, and `ensure` is keyed, so no second task starts mid-scan.
  - Network and server errors retry with the task's back-off
    (`Polling.js:301-305`).
  - A permission error sets `catalogueError` and stops discovery
    (`:296`), and that also stops the periodic refresh.
  - Partial or failed snapshots keep cached repos, as today. Repos are
    removed only when the scan completes (`:334-339`).
- **Merge** (`Polling.js:327-331`): compare before `Object.assign`. If
  `existing.lastActivity` and `repo.lastActivity` are both non-empty and
  differ, and `existing.activityAt` is defined, set `existing.idle=0` and
  `existing.hinted=true`. During a periodic refresh (`s.periodic`) the merge
  keeps `existing.blocked` and `existing.error`. Otherwise a 403 project
  would be retried every 5 minutes; README line 289 keeps its meaning.
  `s.periodic` is cleared when the scan completes.
- **Priority in `seed()`:**
  - the repo sort (`Polling.js:123`) puts `hinted` repos first, then
    orders by `activityAt` as today;
  - a hinted background repo's check is due now, not at
    `activityAt+interval`;
  - **Hinted repos bypass the one-background-task rule** (`:122`, `:134`).
    A queued background task may be waiting out an error retry
    (`:139-140`, `:302`), and a hint must not wait behind it. That task
    keeps its own retry deadline. Hints are bounded by the projects whose
    `lastActivity` changed in one scan.
  - `activity()` clears `r.hinted`. A failed hinted check keeps the hint,
    and the task's own error back-off applies.
- **Hints for pinned, running or selected repos:** their intervals are
  already 60 s or less, so the hint only resets `idle`.

### 3. Queued lookup back-off

- **New state:** `s.queued={}`, keyed `repo+":"+run`, holding a level 0–5.
  - **Why not on the run:** `complete()` replaces run objects through
    `union()` and `Object.assign({},data,…)` (`Polling.js:315`, `:202-209`),
    so a counter on the run would be lost.
  - `resetHost()` drops it (fresh `create()`).
- **Delay:** `Math.min(300000, 15000*Math.pow(2, level))`, so 15 s, 30 s,
  1, 2, 4, then 5 minutes.
- **Which runs:** the delay applies only when all of these hold:
  - `run.status==="queued"`;
  - `!run.awaitingFinal`;
  - the project is not selected;
  - the run is not watched.

  Every other follow-up keeps 15 s at `Polling.js:147-148`. Watched runs
  keep their own 30 s timer (`seedWatches`, `:163-170`).
  - **Shared task key:** both paths share the `run` task key. `ensure()`
    on an existing task changes only its group and keeps its due time
    (`Polling.js:48-55`), as today.
  - **Watched during a retry wait:** if a watch is added while that task
    is waiting out an error retry, the watch waits for the retry. The
    network back-off is not bypassed.
  - **Watched during a queued back-off wait:** if no task exists yet,
    `seedWatches` creates one on its 30 s schedule.
- **Raised:** in `complete()`'s run branch, when the lookup returns a run
  that is still `queued`: `s.queued[id]=Math.min(5,(s.queued[id]||0)+1)`.
- **Cleared:**
  - when a lookup or a list shows the run is not queued;
  - when the run is dropped in `trimRuns` (next to the `s.details`
    cleanup at `:234`), or in `activity()`'s dropped runs (`:255`);
  - when the catalogue scan removes its project (next to the details
    cleanup at `:335-338`);
  - when the project becomes selected (the selected summary covers it).
- **Errors** keep the task's own error back-off (`:302`). An error does not
  raise the level.

### 4. Measurement

`tests/polling.cjs` gains a `scenario()` simulation alongside the
existing `simulation()`:
- 137 projects: 5 active within a day, 15 within a week, 117 older;
- org/r0 selected, 1 s responses;
- an optional 30 queued pipelines on non-selected projects, whose lookups
  keep returning queued.

It prints requests by kind and asserts the targets. The existing
`simulation()` and its assertions stay.

Baseline on `main` (3510922), measured with this scenario:

| Scenario | Total | Idle checks | Queued lookups |
| --- | --- | --- | --- |
| Realistic, first 30 min | 713 | 408 | 0 |
| Realistic, 2 h | 2830 | 1632 | 0 |
| 30 queued, 30 min | 1800 (budget cap) | 90 | 1413 |

Targets:
- realistic first 30 minutes under 500;
- realistic 2 hours: idle checks under 653 (60 % fewer);
- queued 30 minutes: lookups under 707 (half).

The catalogue refresh adds about 12 requests per 30 minutes and is
counted.

### 5. README

- **The refresh table** (`README.md:270-278`): "Previously checked idle
  projects | 10 minutes" becomes "Idle projects | 10 minutes, backing off
  to 60 (projects inactive for a week start at 60)". A new row: "Project
  list | 5 minutes while open". A note on queued back-off goes under the
  table.
- **A sentence on the trade-off:** a short pipeline on an idle project can
  start and finish unseen; pin a project to check it every minute.
- **Line 125** ("Projects are scanned in order of most recent activity")
  gains "and the list is refreshed every 5 minutes while open".
- **Line 289** ("until the next catalogue or manual refresh") becomes
  "until the panel reopens or you refresh (`r` or `R`)". The periodic
  refresh keeps a 403 project blocked.

## Alternatives rejected

- **Skip a project whose `last_activity_at` is unchanged.** GitLab updates
  it at most once an hour, and it misses scheduled and API-triggered
  pipelines (intent, question 3). Used only as a hint that speeds up a
  check.
- **GraphQL batching.** It needs a new helper mode and complexity limits
  per host. Deferred by intent question 4.
- **Fewer summary phases for the selected project.** Deferred by intent
  question 5.
- **`updated_after` on the running list.** It filters results but still
  costs one request per project.
- **A per-project `status=pending` list in place of per-run lookups.** It
  is one request per project rather than per run, but it changes the
  lookup path from #21 and still polls. Back-off is smaller and meets the
  target.

## Risks

- **Short pipelines missed more often on idle projects.** Accepted in the
  intent (question 3); the README says so.
- **The catalogue hint scan** costs 2 pages every 5 minutes for 137
  projects, more on large accounts (1 page per 100 projects). An account
  with 2,000 projects pays 20 pages every 5 minutes, about 4 a minute.
  Accepted: it is still far below 2,000 idle checks every 10 minutes.
- **Periodic refresh and `blocked`:** if the merge cleared `blocked`, 403
  projects would loop. The `s.periodic` guard prevents it, and a test
  covers it.
- **Queued counters leaking:** cleared on not-queued, trim, selection and
  host reset; a test covers the trim.
- **No host-level risk:** the change is in a QML plugin's JS. A bad
  release reverts with the pin. Hosts: p620 and razer; p510 untouched.

## Verification

- `node tests/polling.cjs`: all existing tests pass, plus new cases:
  1. back-off progression 10 → 20 → 40 → 60 for a recent project; an old
     project starts at 60; a three-day-old one at 20;
  2. a running result resets to 0; selection resets; `r` resets the
     selected project; `R` resets all;
  3. the periodic catalogue refresh starts 5 minutes after the last
     complete scan, wakes the scheduler, and does not start after a
     permission error;
  4. a changed `lastActivity` sets `hinted` and puts the repo first. A
     hinted repo is admitted while another background task waits out an
     error retry, and that task keeps its deadline. The hint is cleared by
     the next check;
  5. a periodic refresh keeps `blocked`. An open or `R` refresh clears it,
     including an overdue `R`, an overdue reopen, and `R` during a
     periodic scan's pagination;
  5a. `seed()` runs a bounded number of times during a catalogue page
     retry (the wake is not stuck in the past);
  5b. selecting a backed-off project and deselecting it before the
     debounce resets its level to 0;
  6. queued back-off: 15 s, 30 s … 5 minutes; not applied to watched,
     selected or `awaitingFinal` runs; reset when the run starts running;
     cleared on trim and on project removal (remove, then reintroduce: the
     lookup starts again at 15 s). A watch added during a lookup's error
     retry waits for the retry;
  7. host reset clears `idle`, `hinted` and `s.queued`;
  8. the scenario targets above.
- `python3 -m unittest discover tests` and `node tests/model.cjs`
  unchanged.
- `nix flake check` (the plugin check runs the suites).
- No QML change, so no microVM smoke test is needed. If the panel code is
  touched after all, the smoke test runs in a fresh microVM.
- Each new rule has a mutation check: revert the rule and confirm that a
  test fails.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
reproduced the baseline tables. Its model of the design estimates:

| Scenario | Total | Idle checks | Queued lookups |
| --- | --- | --- | --- |
| Realistic, 30 min | 471 | 155 | 0 |
| Realistic, 2 h | 1542 | 295 | 0 |
| 30 queued, 30 min | 737 | 155 | 270 |

All three targets are within reach. Its findings, all confirmed against
the code and folded in above:
1. **Refresh type (confirmed, reproduced by Codex):** `seed()`
   re-marked a scan as periodic after `R` or an overdue reopen. The type is
   now chosen only when a scan starts, and `R` restarts a periodic scan.
2. **Selection reset (confirmed):** it lived in `activity()`, so a quick
   select and deselect left a 60-minute level. It now happens in
   `select()`.
3. **Hint behind a failed task (confirmed):** a hint could wait behind
   another task's error retry. Hints now bypass the one-background rule.
4. **Wake stuck in the past (confirmed):** the wake during a scan kept
   `wakeAt` expired. It now counts only before a scan starts.
5. **Queued counters on removed projects (confirmed):** they survived
   catalogue removal. They are now cleared there and in `activity()`'s
   dropped runs.
6. **"Earliest due wins" was wrong (confirmed, reproduced by Codex):**
   `ensure()` keeps an existing task's due time. The text now says so, and
   a test covers a watch added during a retry.

It also corrected two references (`:316-319`, "three-day-old"). It did
not check the README references; I checked them (`README.md:125`, `:277`,
`:289`).
