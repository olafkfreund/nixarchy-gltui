---
status: draft
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
  - else `finished(runFor(s,w.repo,w.run))` → push
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
- `watchNotice(code, repo, number)`: the strings in the spec (part 2).
- `watchMessage(event, oldHost, newHost)` → `{summary, body}`.
  - Summaries: `Pipeline passed`, `Pipeline failed`, `Pipeline canceled`,
    `Pipeline skipped`, `Stopped watching a pipeline`,
    `Pipeline unavailable`, `GitLab sign-in needed`, and
    `Stopped watching N pipeline(s)` for `host`.
  - Bodies: as in the spec. `pipeline(s)` reads `pipeline` when the count
    is 1.
  - A `host` event is `{type:"host", count}`, with the hosts passed as
    arguments.

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
  - a new section "Watching a pipeline", after "Pinned projects";
  - `:280`: the sentence about polling while closed, replaced;
  - the refresh table: the `Watched pipelines` row.
- `keybindings.sh`: `w → Watch or stop watching the selected pipeline`
  after the `t` line.
- `manifest.json`: `"version": "1.9.0"`.

## Steps

1. **`Polling.js`, `tests/polling.cjs`: the scheduler.** Per "Scheduler".
   Tests: every case in the spec's Verification for `polling.cjs`. Use the
   existing `response()` helper and drive `next()` / `complete()` with
   fake clocks.

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
   - Drive the scheduler directly: get a request with
     `Polling.next(panel.polling, Date.now())`, then feed a reply with
     `panel.receivePage(JSON.stringify(reply), request)`. Set
     `panel.polling.flight=null` and the clock as needed.
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
   - **W5:** a failing `notifyCommand` (`["sh","-c","exit 1","sh"]`).
     - Watch, close, and feed a finished reply.
     - Then `panel.open('{"filter":"x"}')`: `notice` contains
       `Pipeline passed`.
     - Clear the filter.
   - **W6:** expiry. Watch, set the watch's `until` to
     `Date.now()-1`, close, and call `panel.pump()` with
     `workerBusy=false` and `panel.polling.cooldown` far in the future.
     The notify file holds `Stopped watching a pipeline`, and `watching`
     is false. Set `workerBusy=true` again.
   - **W7:** auth on close.
     - Watch, then set `panel.polling.auth=true` and call `panel.close()`.
     - The notify file holds `GitLab sign-in needed`.
     - Reopen, and clear `auth`.
   - **W8:** host change. Watch, then `cfg("gitlab.other.org")`: the notify
     file holds `Stopped watching 1 pipeline`. Restore
     `cfg("gitlab.example.org")`.
   - **W9:** Ctrl/Alt/Meta/Shift + W change nothing. `w` in the search box
     types into the filter. The footer hint holds `w watch`, and
     `helpText` holds `Watch or stop`.
   - **Restore:** default `notifyCommand`, `polling.watches={}`, `events=[]`,
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
    test fails.
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

## Deviations

None yet.
