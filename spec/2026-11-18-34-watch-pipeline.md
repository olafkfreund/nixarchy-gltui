---
status: draft
issue: 34
intent: intent/2026-11-18-34-watch-pipeline.md
---

# Spec: Watch a pipeline and get notified when it finishes

## Design

Watches are session state in the scheduler, separate from its disposable
tasks. The scheduler decides when to check them and records what
happened as events. The panel turns events into notifications and keeps
the pump running while any watch exists.

### 1. Scheduler (`Polling.js`)

**State.** `create()` gains:
- `watches:{}`, keyed `repo + ":" + run`;
- each value is `{repo, run, number, ref, until, checkedAt}`:
  - `number` and `ref` are copied from the run when the watch starts;
  - `until` is the start time plus 6 hours;
  - `checkedAt` is the time of the last lookup;
- `events:[]`, a queue the panel drains.

Two constants: `WATCH_CAP = 5`, `WATCH_TTL = 21600000` (6 h). The closed
interval is 30 s. `close()` and `open()` keep both fields. `resetHost()`
starts from `create()`, so it drops them (see the host change in part 3).

**Finished.** `finished(run)` is true when `run.conclusion` is one of
`success`, `failed`, `canceled` or `skipped`, which is GitLab's raw status
(`gitlab.py:226`). `status` cannot be used: it files `manual` and
`scheduled` as `completed` (`gitlab.py:186-189`).

**New writer `watch(s, repo, run, now)`** returns a code, and sets
`s.wakeAt=0`:
- the watch exists → delete it, return `"unwatched"`;
- `runFor(s, repo, run)` is missing → `"missing"`;
- `finished(run)` → `"finished"`;
- `WATCH_CAP` watches exist → `"cap"`;
- otherwise add it with `until = now + WATCH_TTL` and `checkedAt = 0`,
  and return `"watching"`.

**Watched runs are kept.** `kept(s, r, run)` (`Polling.js:183-184`)
also returns true for a watched run. So `trimRuns()` never drops it, even
behind ten newer completed pipelines, and a partial activity page never
drops it either (`Polling.js:194-201`). That way `settle()` always finds
the finished result that a merge just stored.

**`settle(s, now)`** runs on every successful return path of `complete()`
(intermediate summary pages and phases included, `Polling.js:267,282`)
and at the start of `next()`. For each watch, in key order:
- `now >= until` → event `{type:"expired", watch}`, delete it;
- no `repoFor(s, repo)` (the catalogue dropped the project) → event
  `{type:"unavailable", watch}`, delete it;
- `runFor` exists and `finished(run)` → event
  `{type:"finished", watch, conclusion}`, delete it;
- `runFor` missing while the project exists: the watch stays, and its next
  lookup restores the run.

The watch is deleted when its event is queued, so a finish seen both in a
list and in a lookup gives one event.

**Checks.** `seedWatches(s, now)` ensures a `run` task for each watch
whose `now >= checkedAt + 30000`:
- group `active`, the same as an unselected running project;
- `ensure()` keeps an existing task, so a task in network backoff keeps
  its `due` and `failures`.

It runs open or closed, as its own loop over the watches, not inside the
project loop. So the archived, disabled and blocked skips
(`Polling.js:90`) do not apply. While open, `seed()` calls it after its
project loop. The task's group is set to `active` last, so it wins over
an ordinary follow-up group. Each watch's next check time,
`checkedAt + 30000`, joins `seed()`'s `wake` minimum. Otherwise, with only
idle projects, `wakeAt` could sit ten minutes away and the next watch
check would wait for it. The watched pipeline is thus looked up directly
every 30 s, whether or not the fetched rows still show it.

`seed()`'s cleanup of blocked projects (`Polling.js:79-81`) skips a
watched `run` task, so a task in network backoff keeps its retry state
there too. Orphan removal for a missing project still applies after
`settle()` has ended its watch. That covers the partial-page and snapshot
cases from the intent, at the cost of a lookup that is sometimes
redundant (at most 10 a minute).

`complete()` for a `run` task sets `checkedAt = now` on its watch, for
success and error alike.

**Closed mode.** `next(s, now)`:
1. Calls `settle(s, now)` first, so expiry happens even during a
   cooldown or an auth stop.
2. Returns `null` when `!s.opened` and no watch is left.
3. The budget and cooldown checks stay as they are.
4. When closed, it calls `seedWatches()` instead of `seed()`, and picks
   only `run` tasks of watched pipelines.

`close()` keeps clearing tasks and the flight, so closed mode starts from
the watches alone.

**Generations.**
- `close()` increments `generation`, as today, so a reply to an
  open-panel request is ignored.
- `open()` also increments it. If a closed-mode lookup is in flight, it
  re-tags `s.flight.generation` with the new generation. The reply is
  then accepted rather than ignored, and the flight never sticks.
- `complete()`'s guard `!s.opened` becomes "neither open nor watching".
  The generation and request-id checks stay.

**Closed-mode side effects.** While closed, a `run` reply only merges
the run and settles. It queues no `jobs` task: the two `ensure(s,"jobs",…)`
calls in `mergeRuns()` (`Polling.js:166-167`) and in the `run` branch
(`Polling.js:254-255`) also require `s.opened`.

**Errors on a watch's `run` task.**

| Error | Today | With watches |
|---|---|---|
| `permission` (403, 404) | marks the run `lookupError` | also: event `{type:"unavailable", watch}`, delete the watch |
| `auth` / `setup` while closed | sets `s.auth` | also: one event `{type:"auth", count}`, delete all watches |
| `auth` / `setup` while open | sets `s.auth` | watches stay; the user sees the stop |
| `network` / server | backoff | watch stays |
| `rate` | cooldown | watch stays |

`close()` with `s.auth` set and watches present also emits the `auth`
event and drops them: a closed panel cannot clear the stop. The panel
drains events right after `Polling.close()` (part 3), so this event is
delivered even though the pump then stops.

### 2. Model (`PipelinesModel.js`)

- `rows(…, pinned, watched)`: `watched` is a map of `repo:run`. Run rows
  gain `watched: !!watched[repo + ":" + run.id]`, and `watched` joins
  `shownFields`.
- `watchNotice(code, repo, number)` gives the footer notice:
  - `watching` → `Watching #<number> in <repo>`;
  - `unwatched` → `Stopped watching #<number>`;
  - `finished` → `Pipeline already finished`;
  - `cap` → `At most 5 watched pipelines`;
  - `missing` → `Select a pipeline to watch`.
- `watchMessage(event)` returns `{summary, body}` for a notification:
  - `finished`: summary `Pipeline passed`, `failed`, `canceled` or
    `skipped` (`success` reads as "passed"); body
    `<repo> #<number> · <ref>`;
  - `expired`: `Stopped watching a pipeline`, body
    `<repo> #<number>: still running after 6 hours`;
  - `unavailable`: `Pipeline unavailable`, body `<repo> #<number>`;
  - `auth`: `GitLab sign-in needed`, body
    `Stopped watching <count> pipeline(s). Run glab auth login.`;
  - `host`: `Stopped watching <count> pipeline(s)`, body
    `The panel now uses <new host>, not <old host>.`

### 3. Panel (`PipelinesPanel.qml`)

- **Pump while watching.**
  - New readonly `watching`: `Object.keys(polling.watches).length > 0`.
  - The pump `Timer` (`:504`) runs `opened || watching`, with an interval
    of 100 ms when open and 1000 ms when closed.
  - `pump()` returns early only when `workerBusy`, or when neither
    `opened` nor `watching`.
  - After each `Polling.next()`, `Polling.complete()` and `Polling.close()`,
    the panel calls `drainEvents()`. When it finds events, it also calls
    `adopt()`. That reassigns `polling`, so `watching`, the pump timer and
    the row marks update even when `next()` expired the last watch and
    started no request.
- **`w`:** a plain, unshifted key in the list.
  - On a run, stage or job row (they all carry `repo` and `run`), call
    `Polling.watch(polling, current.repo, current.run, Date.now())`, then
    `adopt()`, and show `Model.watchNotice(…)`.
  - On a project row, show `Select a pipeline to watch`.
- **Run row mark:** the delegate title shows `◉ ` before a watched run's
  name, as `★ ` does for pins.
- **Notifications.**
  - `drainEvents()` moves `polling.events` into a send queue.
  - A `notifyProc` `Process` sends one at a time:
    `notifyCommand.concat([summary, body])`, where `notifyCommand`
    defaults to `["notify-send", "--app-name=GitLab Pipelines"]` and is a
    test hook.
  - Each argument is a separate element, never shell text.
  - A non-zero exit or a failed start (the `copyProc` pattern) adds the
    message to `missedNotices`. They are shown in the footer notice, joined
    by ` · `, and the list is cleared:
    - at the end of `open()`, after `applyOpen()` (which clears the
      notice for a filter payload, `PipelinesPanel.qml:125-133`) and after
      the pins error notice;
    - when the panel is not configured yet, at the end of
      `markConfigured()`, after the queued `applyOpen()` calls.
  - Nothing is resent.
- **Host change.** In `configure()`, before `Polling.resetHost()`, a
  host change with watches queues a `host` notification with the count,
  the old host and the new host.
- **`listHint`** gains `w watch` after `t log`.

### 4. Docs and version

- **`README.md`:**
  - Requirements (`:11`): add `notify-send` (libnotify) for watch
    notifications.
  - The Nix example's `home.packages` (`:50`): add `pkgs.libnotify`, and
    `pkgs.wl-clipboard`, which #29 missed.
  - Keyboard table: `| w | Watch or stop watching the selected pipeline |`.
  - A new section, "Watching a pipeline":
    - `w`, the mark, and which statuses count as finished;
    - the 5-watch cap and the 6-hour expiry;
    - the checks while closed: 30 s, a target;
    - the notifications;
    - every error case;
    - that a host change, a shell restart or a logout ends watches.
  - "Refresh and errors": `Nothing is polled while the panel is closed`
    (`:280`) becomes "While the panel is closed, only watched pipelines are
    polled (see Watching a pipeline); everything else stops." The table
    gains `| Watched pipelines | 30 seconds, open or closed |`.
- **`keybindings.sh`:** `w → Watch or stop watching the selected
  pipeline`.
- **`manifest.json`:** `1.9.0`.

## Alternatives rejected

- **Following watches only through list rows while open:** running
  pipelines can drop out of a partial page or a summary snapshot
  (`Polling.js:194-201,283-284`). A direct lookup every 30 s is simpler
  and always correct.
- **A separate timer and request path for watches:** it would bypass the
  shared budget, cooldown and single flight. Reusing `next()` keeps every
  existing rule.
- **A systemd user timer or a daemon:** the intent rules out anything
  outside the shell.
- **Persisting watches:** intent, question 4.
- **Sending notifications with `Quickshell.execDetached`:** a failure
  could not be seen, so the missed-notice fallback would be impossible.

## Risks

- **Closed-mode bugs** could leave requests running while closed. The
  tests pin that a closed panel with no watches starts nothing, and that
  closed mode only ever starts `run` lookups of watched pipelines.
- **Budget:** with 5 watches, at most about 10 extra lookups a minute,
  open or closed, inside the 60-a-minute limit.
- **Notification daemon:** without one, `notify-send` fails, and the
  fallback notice appears at the next opening.
- **Hosts:** p620 and razer through the usual chain. p510 stays on its
  current version.

## Verification

- **`tests/polling.cjs`:**
  - `watch()` codes: start, toggle off, a missing run, every finished
    conclusion (including that `manual` and `scheduled` can be watched),
    and the cap;
  - closed with no watches: `next()` returns `null`. Closed with watches:
    `next()` returns only `run` requests for watched pipelines, about every
    30 s per watch, and never a catalogue, activity, summary or jobs
    request, even with an expanded selection;
  - a `run` reply while closed queues no jobs task;
  - finish observed in a list and then in a lookup: one event;
  - a watched pipeline behind ten newer completed pipelines: its `failed`
    lookup is kept by `trimRuns()` and gives a `finished` event;
  - open with only idle, discovered projects: a watched pipeline is looked
    up again 30 s after each lookup (`wakeAt` includes it);
  - a blocked project with a watched lookup in network backoff: the task
    keeps its `due` and `failures`;
  - a finish seen on an intermediate summary page gives the event;
  - expiry fires at `until` during a cooldown and during an auth stop, and
    is not extended by close and open;
  - errors: a 403 or 404 gives `unavailable` and drops one watch; auth
    while closed gives one `auth` event and drops all; auth while open
    keeps the watches; network backoff keeps the watch and its `failures`;
  - `close()` with `s.auth` and watches gives the `auth` event;
  - open during a closed-mode flight: the reply is accepted and the flight
    clears; close during an open-mode flight: the reply is ignored;
  - the catalogue drops a watched project: `unavailable`;
  - `resetHost()` drops watches;
  - a run that is retried before finishing stays watched;
  - the last watch ending while closed: `next()` returns `null` from then
    on.
- **`tests/model.cjs`:** run rows carry `watched`; `syncRows` updates it;
  every `watchNotice` code; every `watchMessage` type.
- **`tests/qml-smoke.py`, in the microVM only:**
  - `notifyCommand` writes its arguments to a file:
    - `w` on a run row marks it `◉` and shows the notice; `w` again
      unmarks it;
    - `w` on a stage or job row watches its pipeline; `w` on a project
      row gives the notice;
    - the cap notice;
    - a finished pipeline gives `Pipeline already finished`;
  - close the panel with one watch. Feed a finished `run` reply through
    the fake helper. The notification file holds `Pipeline passed` and the
    body, and the pump timer stops once no watch is left;
  - a failing `notifyCommand`: the next `open()` shows the missed notice,
    also when opened with a filter payload;
  - expiry with no reply (set `until` in the past while closed): the
    notification is sent, the run mark goes, and the pump timer stops;
  - `close()` with an auth stop and a watch, with no request in flight:
    the `auth` notification is sent;
  - a host change with watches: the `host` notification;
  - Ctrl/Alt/Meta/Shift + W do nothing; `w` in the search box types;
  - footer and help text include `w`.
- All existing tests pass, and the flake's `plugin` check builds.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
confirmed that closed mode starts only watched lookups, that guarding
both jobs `ensure()` calls covers closed-mode side effects, that
re-tagging the flight on `open()` works, that `ensure()` keeps retry
state, and the explicit terminal statuses. Its findings, which I checked
in the code and folded in above (two it confirmed with read-only scheduler
probes):
- `trimRuns()` could drop a watched run's terminal result before
  `settle()` saw it: watched runs are now kept;
- watch checks were missing from `wakeAt`, so with idle projects the next
  check could wait ten minutes: they now join it;
- the `auth` event from `close()` was never drained: the panel drains
  after `close()`;
- an expiry inside `next()` did not refresh QML bindings: events trigger
  `adopt()`;
- the blocked-project cleanup could delete a watched task: watches seed in
  their own loop and are exempt from that cleanup;
- missed notices could be cleared while opening: they are shown after
  `applyOpen()` and after the queued opens in `markConfigured()`.
