---
status: approved
issue: 34
spec: spec/2026-11-18-34-watch-pipeline.md
coders:
  1: codex   # tricky scheduler state machine (closed mode, settle, generations, errors) with many simulation tests
  2: coder   # small pure model helpers and row field with Node tests
  3: coder   # QML wiring following the existing Process/notice/key patterns
  4: coder   # README, keybindings.sh and version, tied to steps 1-3 wording
  5: coder   # smoke-test stages, following the existing T/K-step pattern
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Watch a pipeline and get notified when it finishes

Self-contained. Branch `feat/34-watch-pipeline`, based on `fe0d6d0`
(v1.8.0). Line numbers are for that commit; match on the quoted code.

## Approved decisions (from the spec)

### Scheduler (`Polling.js`)

- **Constants:** `var WATCH_CAP=5, WATCH_TTL=21600000, WATCH_EVERY=30000;`
  and `var FINISHED=["success","failed","canceled","skipped"];`.
- **`create()`** gains `watches:{}, events:[]`. `resetHost()` is
  unchanged: it builds from `create()`, so it drops them.
- **`finished(run)`:** `!!run && FINISHED.indexOf(run.conclusion)>=0`.
- **`watch(s, repo, run, now)`** (an exported writer, so `s.wakeAt=0`):
  - `var id=repo+":"+run`;
  - if `s.watches[id]`: delete it and return `"unwatched"`;
  - `var r=runFor(s,repo,run)`: none → `"missing"`; `finished(r)` →
    `"finished"`; `Object.keys(s.watches).length>=WATCH_CAP` → `"cap"`;
  - else `s.watches[id]={repo:repo, run:String(run), number:r.run_number, ref:r.head_branch||"", until:now+WATCH_TTL, checkedAt:0}`
    and return `"watching"`.
- **`kept(s,r,run)`** (`Polling.js:183`) also returns true when
  `s.watches[r.repo+":"+run.id]`.
- **`settle(s, now)`:** for each key of `s.watches` in `Object.keys`
  order, with `w` its value:
  - `now>=w.until` → push `{type:"expired", watch:w}` and delete;
  - else `!repoFor(s,w.repo)` → push `{type:"unavailable", watch:w}` and
    delete;
  - else `var run=runFor(s,w.repo,w.run)`; if `finished(run)` → push
    `{type:"finished", watch:w, conclusion:run.conclusion}` and delete;
  - otherwise keep.

  If anything was pushed or deleted, set `s.wakeAt=0`.
- **`seedWatches(s, now)`:** returns the earliest next-check time.
  - For each watch `w` with no `run` task in flight:
    - `var at=w.checkedAt+WATCH_EVERY`;
    - if `now>=at`, `ensure(s,"run",w.repo,w.run,"active",at)` and set
      that task's `group="active"`;
    - otherwise `wake=Math.min(wake,at)`.
  - Return `wake`.
- **`seed()`:**
  - in its first loop (the one that deletes tasks), skip the
    blocked-project and orphan deletions for a `run` task whose
    `t.repo+":"+t.run` is watched. The orphan case is reached only after
    `settle()` has ended a watch whose project is gone;
  - after the project loop, `wake=Math.min(wake,seedWatches(s,now))`.
- **`next(s, now)`** (`Polling.js:128`) becomes:

  ```js
  function next(s, now) {
      settle(s, now);
      var watching = Object.keys(s.watches).length > 0;
      if ((!s.opened && !watching) || s.flight || s.auth || now < s.cooldown) return null;
      // … the existing starts/budget lines, unchanged …
      s.clock=now;
      if (s.opened) { if (now>=s.wakeAt) seed(s,now); }
      else {
          Object.keys(s.tasks).forEach(function(id) { var t=s.tasks[id];
              if (t.kind!=="run" || !s.watches[t.repo+":"+t.run]) delete s.tasks[id]; });
          seedWatches(s,now);
      }
      // … the existing due/sort/slot pick, unchanged …
  }
  ```

  (`s.auth` still blocks, but `settle()` has already run, so expiry
  fires.)
- **`open(s, now)`:** after `s.generation++`, add
  `if (s.flight) s.flight.generation=s.generation;`.
- **`close(s)`:** after the existing lines, if `s.auth` and any watch
  exists, push `{type:"auth", count:N}`, set `s.watches={}`, and set
  `s.wakeAt=0`.
- **`complete(s, reply, now)`** (`Polling.js:209`):
  - **Guard:** `!s.opened` becomes
    `(!s.opened && !Object.keys(s.watches).length)`. The other checks
    stay.
  - **Error branch:**
    - for a `run` task whose `t.repo+":"+t.run` is watched, set that
      watch's `checkedAt=now` first;
    - `permission` on it → push `{type:"unavailable", watch}`, delete the
      watch, then the existing handling;
    - `auth` / `setup` while `!s.opened` → after `s.auth=true`, push
      `{type:"auth", count}` and set `s.watches={}`.
  - **Success:** a `run` task sets its watch's `checkedAt=now`.
  - **`settle(s, now)`** runs before every `return true` on the success
    path. That includes the next-page return, the summary-phase return,
    the `run` branch and the final return. Use a small wrapper or call it
    at each return.
  - **Jobs only while open:** in the `run` branch, the
    `ensure(s,"jobs",…)` (`Polling.js:254-255`) gains `s.opened &&`; so
    does the one in `mergeRuns()` (`Polling.js:171-172`).

### Model (`PipelinesModel.js`)

- `rows(repos, expanded, details, filter, now, pinned, watched)`:
  - `watched` missing means `{}`;
  - run rows gain `watched: !!watched[repo.repo + ":" + run.id]`;
  - `"watched"` joins `shownFields`.
- `watchNotice(code, repo, number)` returns exactly:
  - `watching` → `Watching #<number> in <repo>`;
  - `unwatched` → `Stopped watching #<number>`;
  - `finished` → `Pipeline already finished`;
  - `cap` → `At most 5 watched pipelines`;
  - `missing` → `Select a pipeline to watch`.
- `watchMessage(event, oldHost, newHost)` → `{summary, body}`, with
  `w = event.watch` and `n = event.count`. `pipelines` reads `pipeline`
  when `n === 1`. A `host` event is `{type:"host", count}`, with the hosts
  passed as arguments.

  | `event.type` | summary | body |
  |---|---|---|
  | `finished`, conclusion `success` | `Pipeline passed` | `<w.repo> #<w.number> · <w.ref>` |
  | `finished`, `failed` / `canceled` / `skipped` | `Pipeline failed` / `Pipeline canceled` / `Pipeline skipped` | same |
  | `expired` | `Stopped watching a pipeline` | `<w.repo> #<w.number>: still running after 6 hours` |
  | `unavailable` | `Pipeline unavailable` | `<w.repo> #<w.number>` |
  | `auth` | `GitLab sign-in needed` | `Stopped watching <n> pipelines. Run glab auth login.` |
  | `host` | `Stopped watching <n> pipelines` | `The panel now uses <newHost>, not <oldHost>.` |

  When `w.ref` is empty, the body drops ` · <ref>`.

### Panel (`PipelinesPanel.qml`)

- **Properties:**
  - `readonly property bool watching: Object.keys(polling.watches || {}).length > 0`;
  - `property var notifyCommand: ["notify-send", "--app-name=GitLab Pipelines"]`;
  - `property var notifyQueue: []`, `property var missedNotices: []`,
    `property bool notifyStarted: false`;
  - `property var watched: ({})`, recomputed in `adopt()` from
    `polling.watches` keys.
- **`rebuild()`:** pass `watched` as the new last `Model.rows` argument.
- **Pump timer** (`:504`):
  `Timer { interval: root.opened ? 100 : 1000; running: root.opened || root.watching; repeat: true; onTriggered: root.pump() }`.
- **`pump()`:**
  - `if (workerBusy || (!opened && !watching)) return`;
  - after `var request = Polling.next(polling, Date.now())`, call
    `if (polling.events.length) { drainEvents(); adopt() }` before the
    `if (!request) return`.
- **`receivePage()`:** after a `Polling.complete(…)` that returns true,
  `drainEvents()` before `adopt()`. Also handle a `false` return the same
  way, which costs nothing.
- **`close()`:** after `Polling.close(polling)`,
  `if (polling.events.length) { drainEvents(); adopt() }`.
- **`drainEvents()`:**
  - for each event, `var m = Model.watchMessage(e, host, host)`;
  - append `{summary, body}` to `notifyQueue` (copy and reassign);
  - set `polling.events = []`;
  - `sendNext()`.
- **`sendNext()`:**
  - if `notifyProc.running` or the queue is empty, return;
  - shift the first message into `notifyProc.message`;
  - `notifyStarted=false`;
    `notifyProc.command = notifyCommand.concat([m.summary, m.body])`;
    `running=true`.
- **`notifyProc`:**
  - `property var message`;
  - `onStarted: root.notifyStarted = true`;
  - `onExited(code)`: if `code !== 0`, call `root.missed(message)`; then
    `Qt.callLater(root.sendNext)`;
  - `onRunningChanged`: if not running and not `notifyStarted`, call
    `root.missed(message)` and `Qt.callLater(root.sendNext)`.
  - `missed(m)` appends `m.summary + ": " + m.body` to `missedNotices`.
- **`showMissed()`:**
  - if `missedNotices.length`, `notify(missedNotices.join(" · "))` and
    clear the list;
  - called at the end of `open()`, after the `pinsError` line (`:120`);
  - also at the end of `markConfigured()`, after the queued `applyOpen()`
    loop.
- **`configure()`:** in the host-change branch, before
  `polling = Polling.resetHost(polling)`:
  - `var n = Object.keys(polling.watches || {}).length`;
  - if `n`, queue `Model.watchMessage({type:"host", count:n}, host, configuredHost)`
    and call `sendNext()`.
- **`toggleWatch()`:**
  - no `current`, or `current.kind === "repo"` → notice
    `Select a pipeline to watch`;
  - otherwise:
    `var code = Polling.watch(polling, current.repo, current.run, Date.now())`;
    `var r = (polling.repos.filter(function(x){return x.repo===current.repo})[0] || {}).runs || []`;
    `var run = r.filter(function(x){return String(x.id)===current.run})[0]`;
    `notify(Model.watchNotice(code, current.repo, run ? run.run_number : current.run))`;
    `adopt()`.
- **Key:** in the `plain` chain, after `t`:
  `else if (plain && event.key === Qt.Key_W && !shift) root.toggleWatch()`.
- **Delegate title:** add
  `(modelData.kind === "run" && modelData.watched ? "◉ " : "")` after the
  arrow, next to the pin mark.
- **`listHint`:** insert `w watch  ` after `t log  `.

### Docs and version

- `README.md`, as the spec's part 4:
  - Requirements line `:11`: add `` `notify-send` (libnotify) for watch notifications``;
  - `:50`: `pkgs.libnotify pkgs.wl-clipboard` joins `home.packages`;
  - Keyboard table: `| w | Watch or stop watching the selected pipeline |`
    after `t`;
  - a new section "Watching a pipeline", after "Pinned projects", saying:
    - **w** watches or stops watching the selected pipeline (its row, or
      any stage or job row inside it); watched pipelines show `◉`;
    - a pipeline counts as finished when GitLab reports `success`,
      `failed`, `canceled` or `skipped`; `manual` and `scheduled` ones can
      be watched;
    - a desktop notification (`notify-send`) is sent when it finishes,
      naming the project, number, ref and result; the watch then ends;
    - at most 5 watches; a watch ends 6 hours after **w**, with a
      notification;
    - while the panel is closed, only watched pipelines are checked, about
      every 30 seconds on a healthy server, within the same request
      limits; nothing is checked once the last watch ends;
    - a permission error or a deleted pipeline ends that watch; a sign-in
      problem while closed ends all watches with one notification; network
      errors are retried;
    - changing `host`, restarting the shell or logging out ends all
      watches (the last two silently);
    - a notification that cannot be sent shows in the footer the next time
      the panel opens;
  - `:280`: the sentence about polling while closed, replaced;
  - the refresh table: the `Watched pipelines` row.
- `keybindings.sh`: `w → Watch or stop watching the selected pipeline`
  after the `t` line.
- `manifest.json`: `"version": "1.9.0"`.

## Steps

1. **`Polling.js`, `tests/polling.cjs`: the scheduler.** Per "Scheduler".
   Tests (use the existing `response()` helper; drive `next()` and
   `complete()` with fake clocks):
   - `watch()` returns each code: `watching`, `unwatched`, `missing`,
     `finished` for each of the four conclusions, and `cap` at 5. A
     `manual` and a `scheduled` run can be watched.
   - Closed with no watches: `next()` returns `null`.
   - Closed with two watches: `next()` returns only `run` requests, each
     for a watched id (assert `repo` and `run`). They come about every
     30 s per watch, and never as a catalogue, activity, summary or jobs
     request, even with an expanded selection.
   - **Closed-mode filter (mutation c):** with two watches, close, then put
     an unrelated due task (`ensure(s,"activity","x/y","","active",0)`)
     into `s.tasks`, and a `run` task for a third, unwatched run. Over the
     next requests, only the two watched ids are requested.
   - A `run` reply while closed, with an expanded selected run, queues no
     jobs task.
   - A finish seen in an activity list, then in a lookup, gives one event.
   - **Trim (mutation a):** a watched run sits behind ten newer completed
     runs on the same project, and its lookup returns `failed`: one
     `finished` event.
   - **Wake (mutation b):** open, with only idle, discovered projects whose
     activity was just checked. After a watched lookup completes at `t`, a
     request for it is returned at `t+30000`, and `s.wakeAt` is at most
     `t+30000`.
   - Expiry at `until`, with `s.cooldown` in the future and with
     `s.auth=true`: `next()` queues the `expired` event. Closing and
     opening before `until` does not move it.
   - Errors on a watched lookup:
     - `permission` → one `unavailable` event, and only that watch is
       gone;
     - `auth` while closed → one `auth` event with `count` 2, and all are
       gone;
     - `auth` while open → the watches stay;
     - `network` → the watch stays, and the task keeps its `failures`.
   - `close()` with `s.auth` and one watch gives one `auth` event.
   - Open during a closed-mode flight: `complete()` accepts the reply, and
     `s.flight` is null afterwards. Close during an open-mode flight: the
     reply returns `false`.
   - The catalogue drops a watched project → `unavailable`.
   - A blocked project with a watched lookup in network backoff: after
     `seed()`, the task still has its `due` and `failures`.
   - A finish seen on an intermediate summary phase gives one event.
   - `resetHost()` drops watches.
   - A watched run whose job is retried (still `running`) stays watched.
   - Once the last watch ends while closed, every later `next()` returns
     `null`.

   Check: `node tests/polling.cjs >/dev/null && node tests/model.cjs >/dev/null`.

   Traps:
   - ES5 only.
   - Every exported writer sets `s.wakeAt=0`.
   - Do not change the slot rotation, the budget or the pinned group.
   - Closed mode must never start anything but a watched `run`.
   - Keep the existing tests unchanged.

2. **`PipelinesModel.js`, `tests/model.cjs`:** per "Model". Tests: the
   `watched` field and its `syncRows` update, each `watchNotice` code, and
   each `watchMessage` type including the singular and plural counts.

   Check: as step 1. Traps: ES5; `JSON.stringify` comparisons.

3. **`PipelinesPanel.qml`:** per "Panel".

   Check: steps 1-2 checks, then the microVM smoke run.

   Traps:
   - `drainEvents()` must be called after `next()`, `complete()` and
     `close()`.
   - `adopt()` after events, so `watching` updates.
   - `w` only in the plain chain.
   - Do not change the open-panel pump interval (100 ms).

4. **`README.md`, `keybindings.sh`, `manifest.json`:** per "Docs".

   Check: `bash keybindings.sh --print | grep -c 'Watch or stop watching'`
   prints 1, and the full test set passes.

5. **`tests/qml-smoke.py`:** new `esteps` immediately before the
   `// Restore: no pins, empty state file.` step (`:1307`). `workerBusy`
   is true there, so the real pump does nothing.
   - W1-W8 drive the scheduler directly: get a request with
     `Polling.next(panel.polling, Date.now())`, then feed a reply with
     `panel.receivePage(JSON.stringify(reply), request)`. W10 goes through
     the real pump.
   - `notifyCommand` = `["sh","-c",'for a in "$@"; do echo "$a"; done >> "' + notifyOut + '"; exit 0',"sh"]`,
     where `notifyOut = Quickshell.env("XDG_STATE_HOME") + "/notify" + n + ".out"`
     is a fresh file per check. A `FileView` keeps old text otherwise:
     see #33's Deviations. The script has no backslashes, because the QML
     sits inside a Python string.
   - **W1:** fixture with an unfinished run on a project, plus a finished
     one. `w` on the run row: notice `Watching #… in …`, and
     `entries[i].watched` is true. Again: `Stopped watching #…`.
   - **W2:** `w` on a stage or job row of that run watches it; `w` on the
     project row gives `Select a pipeline to watch`; `w` on the finished
     run gives `Pipeline already finished`.
   - **W3:** cap. Add 5 watches directly with `Polling.watch` on 5
     unfinished runs, then press `w` on a sixth: `At most 5 watched
     pipelines`. Clear `panel.polling.watches` and call `adopt()`.
   - **W4:** closed finish.
     - Watch one run and close the panel.
     - Check `panel.watching` is true.
     - Get a request from `Polling.next()` with a clock past 30 s. It must
       be `kind:"run"` for that run.
     - Feed a reply whose run has `conclusion:"success"` and
       `status:"completed"`.
     - Wait until the notify file holds `Pipeline passed`, and until
       `!panel.watching`.
   - **W5:** missed notifications.
     - With a failing `notifyCommand` (`["sh","-c","exit 1","sh"]`):
       - watch, close, and feed a finished reply;
       - **wait until `panel.missedNotices.length === 1`** and the notify
         process is idle;
       - then `panel.open('{"filter":"x"}')`: `notice` contains
         `Pipeline passed`;
       - clear the filter.
     - With a missing command (`["gltui-no-such-binary"]`): two watches
       finish. Wait until `missedNotices.length === 2`: each failed start
       is recorded once, and the queue goes on to the second.
     - Before every change of `notifyCommand` or the output file, wait
       until the notify process is idle and `notifyQueue` is empty.
   - **W6:** expiry.
     - Watch a run on a visible row, set the watch's `until` to
       `Date.now()-1`, and close.
     - Call `panel.pump()` with `workerBusy=false` and
       `panel.polling.cooldown` far in the future.
     - The notify file holds `Stopped watching a pipeline`, and `watching`
       is false.
     - Reopen: that run row's `watched` is false. Calling `pump()` again
       while closed does not change `panel.polling.requests`.
     - Set `workerBusy=true` again.
   - **W7:** auth on close.
     - Watch, then set `panel.polling.auth=true` and call `panel.close()`.
     - The notify file holds `GitLab sign-in needed`.
     - Reopen, and clear `auth`.
   - **W8:** host change. Watch, then `cfg("gitlab.other.org")`: the notify
     file holds `Stopped watching 1 pipeline`. Restore
     `cfg("gitlab.example.org")`.
   - **W10:** through the real pump and fake helper.
     - **Harness:** the fake `gitlab.py`'s `run` branch:
       - returns the run with `status:"completed"` and
         `conclusion:"success"` when `root / 'run-done'` exists;
       - sleeps 1.5 s first when `root / 'run-delay'` exists.
     - Pass both paths as the environment variables `RUN_DONE` and
       `RUN_DELAY`, and toggle them with the existing `sh()` helper.
     - Restore the real polling: `panel.polling=Polling.create()`, repos
       `zRepos()` with the fake's run on `one/sub/repo`,
       `catalogueComplete=true`, `discover=false`.
     - Set `workerBusy=false`, watch run 7, and close. Create `run-done`
       and set the watch's `checkedAt` to 0.
     - Wait until the notify file holds `Pipeline passed`, `!watching`,
       `!workerBusy` and `polling.flight===null`.
     - Then a second watch with `run-delay`: open the panel while the
       delayed lookup is in flight. The reply is still accepted and the
       flight clears. No request starts while closed afterwards.
     - Never clear `flight` by hand.
     - Set `workerBusy=true` at the end.
   - **W9:** Ctrl/Alt/Meta/Shift + W change nothing. `w` in the search box
     types into the filter. The footer hint holds `w watch`, and
     `helpText` holds `Watch or stop`.
   - **Restore**, after waiting for an idle notify process and an empty
     queue: default `notifyCommand`, `polling.watches={}`, `events=[]`,
     `filterText=""`, `adopt()`.

   Check: the microVM smoke run gives `passed=2 rc=0 binding_loop=0`.

   Traps:
   - **Never run the smoke test on the host desktop.**
   - The default `notifyCommand` must never run in the smoke test.
   - If the run nears the 120 s watchdog, raise it with the 140 s
     subprocess timeout and record it in Deviations.

## Tests

```bash
node tests/polling.cjs && node tests/model.cjs && python3 -m unittest discover -s tests
```

**QML smoke test, in the microVM only.** Start a fresh VM and run the
smoke test right after boot. An idle VM locks its screen, and every
`keyClick` then fails.

```bash
nixarchy vm create gltui-34 --template nixarchy-desktop
nixarchy vm run --detach gltui-34
```

Wait about 50 s, then create
`~/.local/state/nixarchy/microvm/gltui-34/share/run-smoke.sh`:

```sh
#!/bin/sh
cd /mnt/host/repo || exit 1
{ python3 tests/qml-smoke.py; echo "rc=$?"; } > /mnt/host/smoke.out 2>&1
touch /mnt/host/smoke.done
```

Each run, from the repo root:

```sh
share=~/.local/state/nixarchy/microvm/gltui-34/share
rm -rf "${share:?}/repo" && mkdir "$share/repo" && git ls-files -co --exclude-standard -z | xargs -0 tar -c | tar -x -C "$share/repo"
rm -f "$share/smoke.done" "$share/smoke.out"
echo '[{"tool":"launch","args":{"argv":["sh","/mnt/host/run-smoke.sh"],"timeout":2,"generation":"@generation"}}]' \
  | ~/.claude/skills/ai-mirror/mirror-vm gltui-34 - --out /tmp/gltui-34-shots >/dev/null 2>&1
for i in $(seq 1 70); do [ -f "$share/smoke.done" ] && break; sleep 5; done
echo "passed=$(grep -c QML_CHECKS_PASSED "$share/smoke.out") $(grep -o 'rc=[0-9]*' "$share/smoke.out" | tail -1) binding_loop=$(grep -c 'binding loop' "$share/smoke.out")"
grep 'CHECK FAILED' "$share/smoke.out"
```

Expected: `passed=2 rc=0 binding_loop=0`.

**Mutation checks:**
- **Locally:**
  - (a) remove watched runs from `kept()`: the trimmed-result test fails;
  - (b) drop the `seedWatches` term from `seed()`'s wake: the `wakeAt` test
    fails;
  - (c) remove the closed-mode task filter in `next()`: the closed-mode
    filter test fails.
- **In the VM:** (d) remove `drainEvents()` from `close()`: W7 fails.

**Acceptance in the microVM (lead):**
- `notify-send` from the panel reaches the VM's notification daemon.
- Run `notify-send --app-name="GitLab Pipelines" "Pipeline passed" "g/p #1 · main"`
  there.
- A screenshot shows the notification.

```bash
nix build .#checks.x86_64-linux.plugin --no-link
```

**Review:** a fresh Opus agent, given only this plan and the diff, and
Codex's read-only review of the diff.

**Release, after the PR merges:**
- Tag `v1.9.0`, then open the nixarchy pin bump PR.
- In nixos_config, bump the gltui URL in `flake.nix` (`:81-83`) and run
  `nix flake lock`.
- Before any deploy, compare the running p620 generation with a main
  build (`nix store diff-closures`). `just razer` switches p620 too.
- Switch p620, then razer, announcing on the bus first.
- p510 is left alone.

## Rollback

Revert the merge commit and release a patch, or pin the previous tag in
nixarchy. Nothing persists: watches are memory only.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
confirmed the `next()` rewrite, the seeding order, the flight re-tag, the
completion guard, the permission ordering and the notify callback
pattern. Its findings, which I checked and folded in above:
- `settle()` read an unbound `run`: it is now assigned first;
- W5 could reopen before the failure was recorded: it now waits for
  `missedNotices`, and every command change waits for an idle queue;
- the smoke test only fed replies by hand: W10 goes through the real pump
  and fake helper with a finished and a delayed reply, and never clears
  the flight by hand;
- mutation (c) had no trigger: the closed-mode filter test injects an
  unrelated task and an unwatched lookup, and asserts request identity;
- the plan pointed to the spec for texts and tests: the notice and
  notification tables, the README section and the scheduler checklist are
  now copied in;
- W6 checks the row mark and that no request starts afterwards; W5 covers
  failed starts for two queued notifications.

## Deviations

- **Step 3, test hook:** `readonly property bool notifyBusy: notifyProc.running`
  was added, so the smoke test can wait for an idle notify process.
- **Step 3, `receivePage()`:** it now drains events and calls `adopt()`
  whether or not `complete()` accepts the reply, the plan's "handle a
  `false` return the same way". A rejected reply costs one extra rebuild.
- **Step 5:** W9 runs right after W3, against the key fixture. The fake
  helper reads `RUN_DONE` and `RUN_DELAY` from its environment. W4-W8
  feed replies with a clock 31 s later each time, to clear the 30 s and
  1 s limits.
- **Results:** the smoke test passed on the first VM run
  (`passed=2 rc=0 binding_loop=0`). Codex reported that mutations (a)-(c)
  each fail `polling.cjs`. Mutation (d), removing the drain from
  `close()`, fails W7 in the VM.
- **Review fixes (Opus; Codex found nothing):**
  - a `setup` error while closed (a crashed helper, invalid output) is now
    retried like a network error. Before, it ended every watch with a
    misleading "sign in" notification. Only `auth` ends all watches. This
    narrows the plan's "auth / setup while closed" rule;
  - a reply whose request id matches but that is no longer wanted (no
    watches left, or another generation) now clears `s.flight`; before, the
    scheduler could wait on it forever;
  - the retry test now feeds GitLab's raw `running` and `pending`
    statuses. As written it passed whatever `finished()` did;
  - notification bodies escape `&`, `<` and `>`, since daemons may read
    markup and git allows those characters in branch names;
  - the README says a pipeline stopped at a manual job keeps its watch
    until the job runs or the 6 hours pass;
  - both new scheduler tests fail when their fix is removed, and the smoke
    test passed again in a fresh VM;
  - accepted, not changed: closing resets a watched lookup's network
    backoff; a notification that fails while open is shown at the next
    opening; open-mode seeding moves a selected project's watched lookup
    to the `active` group.
- **Acceptance:** in the VM, `notify-send --app-name="GitLab Pipelines"`
  returned 0 but showed nothing at first, because notification silencing
  (do not disturb) was on. After `omarchy-toggle-notification-silencing`,
  the notification "Pipeline passed / g/p #1 · main" appeared. The README
  now says notifications follow the do-not-disturb setting.
