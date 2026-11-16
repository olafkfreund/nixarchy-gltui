---
status: draft
issue: 21
spec: spec/2026-11-16-21-review-correctness.md
coders:
  1: coder   # one-line mapping change plus a unit test
  2: coder   # one-line change plus a fixture test
  3: coder   # three small model edits with direct tests
  4: codex   # restart flag touches the in-flight reply path: small, tricky logic
  5: codex   # attempt-change detection inside mergeRuns: small, tricky logic
  6: coder   # catalogue refusal field: straightforward branch changes
  7: codex   # queued follow-ups plus a congestion simulation: tricky scheduling
  8: coder   # one flag and one condition
  9: coder   # pruning at two well-defined points
  10: coder  # resetHost is a constructor copy
  11: codex  # wakeAt deadline computation and invalidation: tricky logic
  12: coder  # QML wiring of steps 1-11 plus smoke checks
  13: coder  # version bump
reviewers:
  - codex    # independent read of the scheduler changes; agy omitted, out of use (#2748)
---

# Plan: Fix correctness bugs found in the 2026-11-16 review

Self-contained. Branch `fix/21-review-correctness`, based on `8445d25`.
Line numbers are for `8445d25` and shift as the steps land, so match on the
quoted code, not only on the number.

## Approved decisions (from the spec)

- Item 7: a stage with only allowed failures is `success`, and its job rows
  stay `failed`. No warning marker.
- Item 4: one `run` lookup per cached queued pipeline on non-selected projects,
  every 15 s, in the **`background`** group.
- `waiting_for_callback` goes into `QUEUED` and the stage pending list only,
  not into `PHASES` or `Polling.js:2`.
- The catalogue refresh is **Shift+R** (`manual(s, now, true)`). Plain `r` is
  `manual(s, now, false)`.
- One PR, released as 1.0.1.
- A shared `restart(s, t, now)`: when the task is not in flight, reset
  `page=1, phase=0, items=[], all=[], failures=0, due=now`. When it is in
  flight, set `t.restart=true`. `complete()` handles the flag after the
  rate-limit block and before the error branch: reset as above, clear the
  flag, discard the reply data, and return `true`.
- `wakeAt`: `seed()` computes the earliest future time any of its branches
  would act, and `next()` skips `seed()` while `now < s.wakeAt`. There is no
  periodic safety scan. Every exported writer sets `s.wakeAt = 0`.

## Corrections to the spec found while planning

- **Item 8.** The spec says every trim goes through `trimRuns()`. That is
  wrong in two places:
  - the final summary passes an already reduced list into it
    (`Polling.js:233`);
  - `activity()` drops runs directly (`:160`).

  Step 9 therefore prunes by comparing the run ids before and after, and
  covers both paths.
- **Item 6 verification.** The spec's `polling.cjs` row ("a jobs list with one
  gets no `finalAttempt`") cannot fail before the fix. `polling.cjs` sees jobs
  that `gitlab.py` has already normalized, and a fixture with
  `status:"queued"` already passes `:240`. The final-cache effect follows from
  step 1's mapping. Step 1's end-to-end helper test covers it instead.

## Repo traps (all steps)

- `Polling.js` and `PipelinesModel.js` are plain ES5-style JS. QML imports
  them, and the Node tests load them with `vm.runInContext`. Use `var` and
  `function`, with no `const`, `let`, arrow functions, modules or `?.`.
  Exported means a top-level function.
- Keep the dense house style of `Polling.js`. Don't rename existing fields:
  the GitHub sibling shares them.
- Shortcuts with a known limit get a `ponytail:` or `shortcut:` comment, as in
  the existing code.
- GitLab text is untrusted. Don't add new display paths for it.
- Don't touch `README.md` behaviour text unless a step says to.
- Never stage, commit or push from a coder or Codex. The lead commits after
  each step.

## Steps

1. **`gitlab.py:19`**, item 6a. Add `"waiting_for_callback"` to `QUEUED`.
   Leave `PHASES` (`:15`) alone. Tests in `tests/test_gitlab.py`:
   - `job()` of a row with that status gives `status == "queued"`;
   - a `jobs` page reply through the existing fake-`glab` path containing such
     a job yields a job whose `status` is not `completed`. This is what keeps
     it out of the final cache.
   → verify by `python3 -m unittest discover -s tests -v`
   Traps: none.

2. **`menu.py:63`**, item 9. Replace
   `Path(__file__).with_name('menu.managed').exists()` with
   `os.path.lexists(Path(__file__).with_name('menu.managed'))`, and add
   `import os` if it is missing. Test: extend the temporary plugin fixture at
   `tests/test_menu.py:122` with a dangling `menu.managed` symlink. Assert the
   menu file is not created or changed.
   → verify by `python3 -m unittest tests.test_menu -v`
   Traps: the test must not touch the real `~/.config`.

3. **`PipelinesModel.js`**, items 1a, 6b and 7.
   - `:43`: `byName = Object.create(null)`.
   - `:36`: add `"waiting_for_callback"` to the pending list.
   - `:38`: `if (some(jobs, ["success"]) || jobs.some(function(job) { return job.conclusion === "failed" && job.allow_failure; })) return "success";`

   Tests in `tests/model.cjs`:
   - stages named `constructor`, `toString` and `__proto__` group into three
     stages with the right jobs;
   - a stage containing a `waiting_for_callback` job is `pending`;
   - a stage with only an allowed failure is `success`, and its job row in
     `rows()` has status `failed`.
   → verify by `node tests/model.cjs`
   Traps: the rule order in `stageStatus` must not change.

4. **`Polling.js`**, the shared restart mechanism and item 11.
   - Add top-level `function restart(s,t,now)`, as in the decisions above.
   - In `complete()`, after the rate-limit block (`if (reply.errorType==="rate" || …) { … }`,
     `:174-179`) and before `var r=repoFor(s,t.repo);`: if `t.restart`,
     reset the task, `delete t.restart`, and `return true`.
   - In `manual()` (`:38-48`), call `restart(s, <task>, now)` on the task
     returned by each `ensure(s,"summary",…)` and `ensure(s,"jobs",…)`.

   Tests in `tests/polling.cjs`:
   - drive repeated network errors on a selected summary until its `due` is
     at least 5 min out, then `manual(s,now,false)`: the task is due now and
     `failures` is 0;
   - start a summary, advance it to phase ≥ 2, call `manual()` while it is in
     flight, then complete that flight: the reply's data is not merged, and
     the next summary request has `status` `recent` and `page` 1;
   - a rate-limit reply on a restarted task still sets `s.cooldown`.
   → verify by `node tests/polling.cjs`
   Traps: `ensure()` returns the existing task, so call `restart` on its
   return value. Don't clear `s.cooldown`.

5. **`Polling.js` `mergeRuns` (`:130-138`)**, item 10. For each incoming run,
   compare its `run_attempt` with the cached run's (`runFor`) **before**
   `trimRuns`. When they differ, and `s.tasks[key("jobs",r.repo,run.id)]`
   exists, call `restart(s, thatTask, s.clock || 0)`. `finalAttempt` (`:240`)
   is unchanged.

   Tests:
   - page 1 of a 2-page jobs fetch, then a summary changes the attempt from
     `t1` to `t2`, then page 2: `s.details` gets no list stamped `t2` from mixed
     pages, and the next jobs request is page 1;
   - the same with `active → t1 → active` between pages;
   - existing rerun tests (`:222-227`) still pass.
   → verify by `node tests/polling.cjs`
   Traps: `invalidateJobs` already deletes `s.details` on attempt change. Keep
   it. This step adds the task restart beside it.

6. **`Polling.js`**, item 3.
   - `create()`: add `catalogueError:""`.
   - Permission branch (`:185-189`): when `t.kind==="catalogue"`, set
     `s.discover=false; s.catalogueError=s.error;`.
   - `open()` (`:27`): set `discover` only if `!s.catalogueError`.
   - `manual()` with `catalogue` true: `s.catalogueError=""`, then set
     `discover` as now.

   Tests:
   - catalogue 403, then a successful activity reply: `catalogueError` is
     still set, and there is no catalogue request for 10 s;
   - `close`, then `open`: still no catalogue request;
   - `manual(s,now,true)`: a catalogue request follows.
   → verify by `node tests/polling.cjs`
   Traps: `s.auth` means "stopped until manual refresh" for *all* polling.
   Don't use it here.

7. **`Polling.js` `seed` (`:81-83`)**, item 4. Inside the
   `(r.runs || []).forEach(function(run) {` loop, first:
   `if (run.status==="queued" && run.followupAt===undefined && !run.lookupError && r.repo!==s.selected) run.followupAt=now;`.
   Then give the `ensure(s,"run",…)` call a group of `selected ? "interactive"`
   when selected, `"background"` when `run.status==="queued"`, and `"active"`
   otherwise.

   Tests:
   - uncongested: a queued run on a non-selected project gets a `run` request
     at 15 s ± 1 s;
   - a lookup returning `in_progress`, `completed`, or a 403 (`lookupError`)
     stops further lookups for it;
   - congested simulation, reusing the request loop at `:20-62`: 30 queued
     runs across 3 projects, 5 running projects, and one inspected jobs fetch,
     for 10 minutes. Assert ≤ 60 requests in every 60 s window, each running
     project checked at least every 16 s, and every queued run looked up at
     least once.
   → verify by `node tests/polling.cjs`
   Traps: the `backgroundQueued` limit (`:62`) applies to `activity` tasks
   only. Don't extend it to `run` tasks.

8. **`Polling.js`**, item 5.
   - `activity()` (`:162`): add
     `r.activeFromTotal=typeof total==="number" && total>=0;`.
   - `run` branch (`:205`): only recompute `r.active` when
     `!r.activeFromTotal`.

   Tests:
   - activity with `total: 250`, then a run lookup: `active` stays 250;
   - then an activity reply with no total: `active` falls back to the cached
     count;
   - the existing `total:-1` test (`:149-156`) is unchanged.
   → verify by `node tests/polling.cjs`
   Traps: none.

9. **`Polling.js`**, item 8.
   - `trimRuns()` (`:139-142`): before assigning `r.runs`, collect the ids of
     the old `r.runs`. After assigning, delete `s.details[r.repo+":"+id]` for
     each old id missing from the new `r.runs`. Diffing old against new covers
     runs the filter drops *and* runs the caller left out of `runs`. The final
     summary's `union(t.all,keep)` at `:233` is the case that matters.
   - `activity()` (`:160`): delete `s.details[r.repo+":"+id]` for each id in
     `dropped`.
   - Catalogue completion (`:222`): before filtering `s.repos`, delete the
     `s.details` keys whose `<repo>` part (text before the last `:`) is a
     removed repo.

   Tests:
   - a run dropped by an intermediate summary page loses its details;
   - so does a run dropped by a run lookup;
   - so does a completed run absent from a final summary;
   - so does a run that `activity()` drops on a partial page;
   - so do the runs of a project removed from the catalogue;
   - an expanded run beyond the recent ten keeps its details.
   → verify by `node tests/polling.cjs`
   Traps: `kept()` must still protect expanded and inspected runs. Don't prune
   in `invalidateJobs`.

10. **`Polling.js`**, item 2a. Add top-level `function resetHost(s)`. It
    returns `create()` with `opened`, `starts` and `serial` copied, and with
    `generation:s.generation+1` and `wakeAt:0`.

    Test: a flight in progress; `resetHost`; open a new-host flight via
    `next`; deliver the old reply: `complete` returns `false`. Also check that
    `repos` and `details` are empty, `starts` is kept, and `cooldown` is 0.
    → verify by `node tests/polling.cjs`
    Traps: return a new object. The panel assigns it, which notifies QML.

11. **`Polling.js`**, item 13.
    - `create()` gets `wakeAt:0` and a comment: every exported writer sets
      `s.wakeAt=0`.
    - `seed()` starts with `var wake=Infinity`. At each time threshold it
      tests (`stableAt`, `age(r.summaryAt,60000)`,
      `age(r.activityAt,interval)`, `age(run.followupAt,15000)`,
      `age(detail.jobsAt,5000)`), when the threshold is still in the future,
      it does `wake=Math.min(wake,threshold)`. After the loop it also folds in
      every remaining task's `due` when `due > now`. At the end it sets
      `s.wakeAt=wake`.
    - `next()` calls `seed` only when `now>=s.wakeAt`.
    - Set `s.wakeAt=0` in `open`, `close`, `select`, `manual`, `complete`,
      `ensure`, `activity`, `mergeRuns`, `trimRuns` and `restart`
      (`resetHost` is done in step 10).
    - Add a counter: `seeds:0` in `create()` (comment: test-only) and
      `s.seeds++` at the top of `seed`. `resetHost` gets it through
      `create()`.

    Tests:
    - idle state with nothing due: 50 calls to `next()` at increasing times
      before the next threshold run `seed` once (`s.seeds`);
    - with a pending task whose `due` is in the future and no other threshold
      sooner, `wakeAt` equals that `due`, and the task starts at that time;
    - `select()` makes it run again;
    - the existing cadence tests pass.

    Fixtures: any test that writes scheduler input directly (`s.repos`,
    `.selected`, `.inspected`, `.expanded`, `.discover`, `.runs`,
    `activityAt`, `summaryAt`) **after** a `next()` call on the same state
    must set `x.wakeAt=0` right after the write. Writes between `open()` and
    the first `next()` are safe. Lines to check: `:65-75`, `:122-126`,
    `:135-143`, `:150-156`, `:159-177`, `:184-200`, `:204-207`, `:209-214`,
    `:217-220`. Change only the ones that fail.
    → verify by `node tests/polling.cjs`
    Traps: a missed invalidation is a silent stall. If a cadence test fails,
    look for a missing `wakeAt=0` before changing any interval.

12. **`PipelinesPanel.qml`**, items 1b, 2b, 3b, 12 and 13b.
    - Add `function finishRequest(text, code)`. It calls
      `receivePage(Model.reply(text, code, requestInfo.requestId), requestInfo)`
      in `try { … } finally { workerBusy = false }`. `onExited` (`:218-222`)
      keeps its `console.warn` and then calls it. `failedToStart()`
      (`:162-166`) keeps its `console.warn` and then calls
      `finishRequest("", 127)`. Both exit paths go through the helper.
    - `configure()` (`:119-131`): if `configured !== host`, set
      `polling = Polling.resetHost(polling)`, `expanded = ({})`,
      `details = ({})`, `updated = ""`, `error = ""` and `cursor = 0`, all
      before `host = configured`. Where it sets `polling.repos`, also set
      `polling.wakeAt = 0`.
    - `adopt()` (`:140`): `error = polling.error || polling.catalogueError`.
    - `adopt()` (`:144`): replace the guard with
      `if ((current && current.repo || "") !== polling.selected || (current && current.run || "") !== polling.inspected) selectionChanged(false)`.

    Smoke checks in `tests/qml-smoke.py`:
    - **Fake helper** (`:26-30`): accept `host` in
      `('gitlab.example.org', 'gitlab.other.org')` instead of asserting one.
      For `gitlab.other.org`, return a catalogue with only `three/repo` and
      empty pipeline lists.
    - **Worker release.** Add new asynchronous stages after the existing
      ones, while the panel is open:
      - wait for an idle worker;
      - set an expanded run's detail to `{jobs: {}}`. That is a truthy
        non-array, so `stages()` throws (`PipelinesModel.js:104` only guards
        a falsy value);
      - `pump()` so a real request starts, then wait for its exit;
      - `onExited` → `finishRequest` → `receivePage` → `adopt` → `rows`
        throws. Wrap the stage in a JS `try`/`catch` and catch it by calling
        `finishRequest(pageOutput.text, 0)` yourself only if the real exit
        cannot be caught, and record which in a comment;
      - assert `!workerBusy`;
      - restore valid details, then `pump()`: assert `workerBusy` and
        `polling.flight`, so the next request started.
    - **Host change during a flight.** Another stage:
      - with a request in flight (`workerBusy`), call `configure(...)` with
        `"host":"gitlab.other.org"` and projects `["three/repo"]`;
      - assert at once: `entries` lists only `three/repo`, `expanded` is
        empty, and `polling.generation` increased;
      - wait for the old process to exit, then assert `!workerBusy` and that
        no `one/sub/repo` data reappeared;
      - configure back to `gitlab.example.org` for the remaining stages.
    - **Selection sync.** In the first-stage timer:
      - set a filter matching a selected pipeline's status;
      - change that pipeline's status in `polling.repos` so its row drops
        while the project stays, then `adopt()`;
      - assert `polling.inspected === (current && current.run || "")`;
      - then set `polling.expanded` to a sentinel object (`var mark = {}`)
        and call `adopt()` again: assert `polling.expanded === mark`. That
        shows `select()` was not called, because `select()` replaces
        `s.expanded`.
    → verify by `python3 tests/qml-smoke.py` (graphical session) and
    `nix flake check`
    Traps:
    - the smoke log scan (`:158`) fails on `TypeError`, so the intentional
      throw must be caught in JS;
    - `Color` is `Commons.Color` since #20, so don't reintroduce a bare
      `Color` import;
    - keep the 250 ms debounce.

13. **`manifest.json:5`**: `"version": "1.0.1"`. The flake reads it.
    → verify by `nix flake check`, then
    `nix build .#default && ls result/` shows the plugin files.
    Traps: no other file carries the version.

## Tests

```sh
python3 -m unittest discover -s tests -v
node tests/model.cjs
node tests/polling.cjs
python3 tests/qml-smoke.py      # graphical session only
nix flake check
```

All must pass, and each new test must fail on `8445d25`: check by running it
against `git stash` of the fix, or by reasoning recorded in the PR.

## Rollback

Every step is its own commit on `fix/21-review-correctness`. Revert the
offending commit, or the PR merge commit after release. Users on the flake
input pin back to `v1.0.0`. There is no state on disk to migrate: all polling
state is in memory.
