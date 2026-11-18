---
status: approved
issue: 35
spec: spec/2026-11-18-35-fewer-requests.md
coders:
  1: codex   # small tricky scheduler logic (levels, resets) with Node tests
  2: codex   # tricky scan lifecycle (periodic type, wake, hints bypassing the background rule)
  3: codex   # tricky run-lookup state that must survive union() and be cleared in four places
  4: coder   # the measurement scenario, README wording and version, following existing patterns
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Cut API requests for accounts with many idle projects

Self-contained. Branch `perf/35-fewer-requests`, based on `3510922`
(v1.9.0). Line numbers are for that commit; match on the quoted code.
Only `Polling.js`, `tests/polling.cjs`, `README.md` and `manifest.json`
change. No QML, model or helper change. The spec names only the first
three. `manifest.json`'s version bump (1.10.0) is added here because every
release carries one, as in #32 to #34. It changes no behaviour.

## Approved decisions (from the spec)

### A. Idle back-off

- **Constant:** `var IDLE=[600000,1200000,2400000,3600000];`, next to
  `WATCH_CAP` (`Polling.js:3`).
- **Field:** `r.idle`, an index into `IDLE`, undefined until the
  project's first running-list result.
- **Interval** (`Polling.js:133`, `pinned ? 60000 : 600000`): `600000`
  becomes `IDLE[r.idle||0]`. Other intervals are unchanged.
- **`start(r,now)`:** `var a=now-Date.parse(r.lastActivity)`. If `a` is
  not finite, return 0. Under 86400000 → 0; under 604800000 → 1; else 3.
- **In `activity()`** (`Polling.js:241-261`), after `r.active` is set:
  - `r.active>0 || r.repo===s.selected` → `r.idle=0`;
  - `r.idle===undefined` → `r.idle=start(r,now)`;
  - else `r.idle=Math.min(3,r.idle+1)`.

  Then `delete r.hinted`.
- **Run lookup** (`Polling.js:316-319`): after `r.active` is set, if
  `r.active>0`, set `r.idle=0`.
- **`select()`** (`Polling.js:78-83`): when `s.selected!==repo` and the
  new repo exists, set its `idle=0`.
- **`manual(s,now,false)`** (`:96-98`): set `r.idle=0` on the selected
  repo.
- **`manual(s,now,true)`** (`:95`): set `idle=0` on every repo.

### B. Periodic catalogue refresh and hints

- **New state in `create()`:** `periodic:false`.
- **Starting a periodic scan.** In `seed()`, just before
  `if (s.discover) ensure(s, "catalogue", …)` (`Polling.js:120`):
  - if `!s.discover && s.catalogueComplete && !s.catalogueError`:
    - when `now>=s.catalogueAt+300000`: set `s.discover=true` and
      `s.periodic=true`;
    - otherwise: `wake=Math.min(wake,s.catalogueAt+300000)`. `wake` is
      declared at `:108`, before this point.
- **During a scan,** no extra wake is added. The catalogue task's due time
  is folded in by the existing loop at `:160`.
- **`open()`** (`:63-69`): replace the condition at `:67` with
  `if (!s.catalogueError) s.discover=true;` and set `s.periodic=false`.
  Every reopen is then a full refresh that clears `blocked`, as the spec
  says, including within 5 minutes of the last scan. This costs one scan
  (2 pages for 137 projects) per opening. A catalogue permission error
  still stops discovery until `R`.
- **`manual(s,now,true)`:** set `s.periodic=false`. If
  `s.tasks[key("catalogue")]` exists, `restart(s,thatTask,now)`, so the
  upgraded scan starts again from page 1. `restart` already handles a
  task in flight (`:58-62`).
- **Merge** (`Polling.js:327-331`), for an existing repo:
  - before `Object.assign`, set
    `var changed=existing.lastActivity && repo.lastActivity && existing.lastActivity!==repo.lastActivity && existing.activityAt!==undefined`;
  - then `Object.assign(existing,repo)`;
  - if `!s.periodic`: `existing.blocked=false; existing.error="";` as
    today;
  - if `changed`: `existing.idle=0; existing.hinted=true;`.
- **Scan completion** (`:341`): also `s.periodic=false`.
- **`seed()` ordering** (`:123`): the sort puts `hinted` repos first
  (`(b.hinted?1:0)-(a.hinted?1:0)`), then orders by `activityAt` as today.
- **Hinted background repo** (`:131-139`): when `r.hinted` and the group
  is `"background"`:
  - its check is due now: `ensure(…, now)`;
  - it is admitted even if `backgroundQueued`. It does not change an
    existing task's due time. If the hinted repo's own task is waiting out
    an error retry, that deadline holds;
  - setting `backgroundQueued=true` still happens, so non-hinted repos
    wait as today.
- **Hints on pinned, running or selected repos:** they only reset `idle`;
  their intervals already apply.

### C. Queued lookup back-off

- **New state in `create()`:** `queued:{}`, keyed `repo+":"+run`, with a
  level 0–5.
- **Delay helper:** `function queuedDelay(s,r,run)`. It returns
  `Math.min(300000,15000*Math.pow(2,s.queued[r.repo+":"+run.id]||0))` when
  all of these hold:
  - `run.status==="queued"`;
  - `!run.awaitingFinal`;
  - `r.repo!==s.selected`;
  - `!s.watches[r.repo+":"+run.id]`.

  Otherwise it returns `15000`.
- **Using it** (`Polling.js:147-148`): `age(run.followupAt,15000)`
  appears **three** times: the condition, the task's due time and the
  wake. Compute `var due=age(run.followupAt,queuedDelay(s,r,run));` once
  and use it in all three.
- **Raised:** in `complete()`'s run branch (`:313-318`), after
  `mergeRuns`. If `resolved.status==="queued"`, set
  `s.queued[id]=Math.min(5,(s.queued[id]||0)+1)`; otherwise
  `delete s.queued[id]`. Here `id=t.repo+":"+t.run`.
- **Cleared:**
  - in `mergeRuns()` (`Polling.js:218-229`), for every incoming run whose
    `status!=="queued"`. This covers summary pages (`:332`), activity
    results and lookups through one path;
  - in `activity()`, for every dropped id (`:255`);
  - in `trimRuns` next to `delete s.details[…]` (`:234`);
  - in the catalogue completion, for ids whose repo is in `gone`, next to
    the details loop (`:337`);
  - in `select()`, for keys of the newly selected repo.
- **Errors** do not raise the level; the task's error back-off (`:302`)
  applies.
- **Shared task key:** `ensure()` keeps an existing task's due time
  (`:48-55`). A watch added during a lookup's error retry waits for that
  retry. Do not add minimum-deadline merging.

### D. Measurement

- **`scenario({duration, queued})`** in `tests/polling.cjs`, modelled on
  the scratch script `scenario.cjs` (the baseline numbers came from
  there):
  - 137 repos `org/r${i}`;
  - `lastActivity` = `new Date(-age(i)).toISOString()`, where
    `age(i)` is `i<5 ? DAY/4 : i<20 ? 3*DAY : 60*DAY`;
  - org/r0 selected at time 0, 1 s responses, steps of 250 ms;
  - a catalogue of two pages;
  - with `queued`, after the first complete catalogue, runs
    `{id:1000+i,status:'queued',conclusion:'pending',run_attempt:1}` on
    `org/r${i+1}` for `i<queued`, then `s.wakeAt=0`. Run lookups reply
    with the same queued run.

  It counts requests by kind (activity split by group) and prints
  them.
- **Baseline (in a comment):** realistic 30 min 713 (idle 408);
  realistic 2 h 2830 (idle 1632); queued 30 min 1800 (lookups 1413).
- **Assertions:**
  - realistic 30 min total `<500`;
  - realistic 2 h background activity `<653`;
  - queued 30 min `run` `<707`.

### E. README and version

- **`README.md:125`:** after "Projects are scanned in order of most
  recent activity." add "The list is refreshed every 5 minutes while the
  panel is open."
- **`README.md:277`:** replace the row with
  `| Idle projects | 10 minutes, backing off to 60 while nothing runs (projects inactive for a week start at 60) |`.
  Add `| Project list | 5 minutes while open |`.
- **Under the table:**
  - "A project whose last activity changes in the project list is
    checked next. GitLab updates that time at most once an hour, and
    scheduled pipelines may not change it, so a short pipeline on an idle
    project can start and finish without being shown as running. Pin a
    project to check it every minute.";
  - "A queued pipeline on a project you are not viewing is looked up
    every 15 seconds at first, backing off to every 5 minutes while it
    stays queued."
- **`README.md:289`:** "until the next catalogue or manual refresh"
  becomes "until the panel reopens or you refresh (`r` or `R`)".
- **`manifest.json`:** version `1.10.0`.

## Steps

1. **Idle back-off (decisions A)** in `Polling.js`. Add tests to
   `tests/polling.cjs`:
   - progression 10 → 20 → 40 → 60 for a recent repo;
   - an old repo starts at 60, a three-day-old one at 20;
   - a running result resets to 0, and so does the run lookup with
     `r.active>0`;
   - selecting then deselecting before the 250 ms debounce resets to 0;
   - `r` resets the selected repo, `R` resets all;
   - `resetHost` drops `idle` and `hinted`.

   → verify with `node tests/polling.cjs`.
   Traps:
   - every exported writer sets `s.wakeAt=0`;
   - ES5 only (no arrow functions, `let` or template strings in
     `Polling.js`);
   - the existing `simulation()` assertions (`tests/polling.cjs:136-150`)
     must still pass (their assertions are at `tests/polling.cjs:136-143`).
     The repos there have no `lastActivity`, so they start at 0.
2. **Periodic catalogue and hints (decisions B).** Tests:
   - the periodic scan starts at `catalogueAt+300000` and `wakeAt` equals
     that before;
   - no periodic scan after a catalogue permission error, and no reopen
     scan either;
   - a reopen within 5 minutes of a complete scan (not overdue) starts a
     full scan that clears `blocked`;
   - the periodic merge keeps `blocked`; `open()` and `R` clear it,
     including an overdue `R`, an overdue reopen, and `R` mid-pagination
     (restarted at page 1);
   - a changed `lastActivity` sets `hinted` and `idle=0`;
   - a hinted repo is admitted while another background task waits out
     an error retry, and that task's `due` is unchanged;
   - the hint clears on the next activity result;
   - during a catalogue page retry, `s.seeds` grows only a bounded amount
     (for example under 10 over the retry wait).

   → verify with `node tests/polling.cjs`.
   Traps:
   - `seeds` is test-only;
   - closed mode (`next()` with `!s.opened`) must not start catalogue
     scans: `seed()` runs only while open (`Polling.js:181`), so keep the
     change inside `seed()`.
3. **Queued back-off (decisions C).** Tests:
   - the delays 15 s, 30 s, 60 s, 120 s, 240 s, 300 s, 300 s;
   - 15 s for watched, selected and `awaitingFinal` runs;
   - the level clears when the lookup returns a running run, on trim, on
     catalogue removal (then the reintroduced run starts at 15 s), and on
     selection;
   - a completed run from a summary page that stays cached (not trimmed)
     clears its level, including after a lookup in flight during
     selection returned queued;
   - with a queued run backing off at 5 minutes, `s.seeds` stays bounded
     over the wait, and the lookup fires at the backed-off time, not 15 s;
   - a watch added during a lookup's error retry waits for the retry. A
     watch added during an ordinary queued back-off wait is looked up on
     its own 30 s schedule;
   - `resetHost` drops `s.queued`.

   → verify with `node tests/polling.cjs`.
   Traps:
   - run ids are numbers in `r.runs` and strings in `t.run`, so key with
     `String`;
   - the #34 closed-mode tests must still pass.
4. **Measurement, README and version (decisions D, E).**
   → verify with `node tests/polling.cjs`, `node tests/model.cjs`,
   `python3 -m unittest discover -s tests` and
   `nix build .#checks.x86_64-linux.plugin`.
   Traps:
   - keep the README table format;
   - don't change the other rows.

After each step the lead reviews the diff, reruns the check, and commits.

## Tests

- `node tests/polling.cjs`: all old and new tests pass. The scenario
  prints the after tables, which go in the PR next to the baseline.
- `node tests/model.cjs` and `python3 -m unittest discover -s tests`:
  unchanged and passing.
- `nix flake check`, or at least
  `nix build .#checks.x86_64-linux.plugin`.
- **Mutation checks by the lead:** revert each new rule one at a time and
  confirm a test fails:
  - the start level, the `activity()` level step, and the run-lookup reset;
  - the `select()` reset, and the `r` and `R` resets;
  - the scan type chosen at start, the periodic `blocked` guard, the
    reopen full scan, and `R` restarting a scan;
  - the hint flag, the hint ordering, the hint bypass, and the hint clear;
  - the wake guard;
  - the queued delay in each of its three uses, the raise, and each of
    the four clears (`mergeRuns`, dropped, trim, catalogue removal) plus
    the selection clear.
- **No microVM smoke test:** no QML changes. If one becomes necessary, it
  runs in a fresh microVM only.
- **Review:** a fresh Codex review (`codex review --base` the
  plan-approve commit, outside the warm review member, so its context is
  independent), then a fresh Opus review given only this plan and the diff.

## Rollback

Revert the PR, or pin nixarchy and nixos_config back to v1.9.0
(`35109222`). No state or config migrates. The new fields live only in
memory.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
confirmed that the six spec review fixes are carried over, the ES5 and
`wakeAt` rules fit, and closed mode is untouched. Its findings, all
confirmed and folded in:
1. **Reopen within 5 minutes (confirmed, reproduced by Codex):** this
   left projects blocked, because `open()` starts a scan only when it is
   overdue. Every reopen now scans unless a catalogue permission error
   stopped discovery.
2. **Completed summary runs kept queued counters (confirmed):** they are
   now cleared in `mergeRuns()`, the shared path.
3. **Three delay expressions, not two (confirmed):** the plan now
   computes the due time once and uses it for all three.
4. **Version bump outside the spec's file list:** kept and called out
   above as a release step with no behaviour change. It needs your
   explicit OK through plan approval.
5. **Missing checks (confirmed):** host reset of `hinted`, a mutation check
   for every new rule, and a watch added during a queued back-off wait.

It also corrected the simulation assertion range (`:136-143`) and asked
for a fresh-context Codex review of the code.
