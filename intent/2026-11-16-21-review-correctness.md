---
status: approved
issue: 21
author: olafkfreund
---

# Intent: Fix correctness bugs found in the 2026-11-16 review

## Problem

Two read-only reviews on `main` at `c8b79e6` (v1.0.0), each by Codex and a
Fable planning agent, found thirteen ways the panel crashes, shows wrong data,
or wastes requests. Items 1 and 9 were re-checked by hand. Codex reproduced
items 2–5, 7, 10 and 11 in memory. Items 3, 6–8 and 10–13 were confirmed by
reading the code at `8445d25`; none of the code they touch changed in #20.

1. **A valid stage name crashes the panel.** `stages()` groups jobs in a plain
   `{}` (`PipelinesModel.js:43`). Stage names `constructor`, `toString` or
   `__proto__` match inherited properties, and `.push` throws. The throw
   happens inside `receivePage()` before `workerBusy` is cleared
   (`PipelinesPanel.qml:220-221`). `pump()` refuses work while `workerBusy` is
   true (`:152`), and neither closing nor reopening the panel clears it, so
   polling is expected to stop until the shell restarts. Nobody has seen it
   happen in the running panel.
2. **Changing the host mixes data from two GitLab servers.** `configure()`
   changes `host` (`PipelinesPanel.qml:126`) but keeps the polling state, which
   is keyed only by project and pipeline (`Polling.js:9`). The panel goes on
   showing the old host's projects and jobs, and sends the old project paths and
   pipeline IDs to the new host.
3. **A refused project list is retried every second, forever.** A 403 or 404
   on the catalogue request deletes the task (`Polling.js:185-189`). Because
   `discover` stays true, `seed()` recreates the task straight away
   (`Polling.js:61`), with no backoff.
4. **Queued pipelines can stay queued forever.** Projects that are not
   selected are only checked for `status=running` (`gitlab.py:74`), and only
   running pipelines that disappear get a follow-up (`Polling.js:82-83`,
   `:153`). A
   pending pipeline that is cancelled, or that starts and finishes between two
   scans, stays "pending".
5. **The running count gets overwritten with a smaller one.** Looking up a
   single pipeline replaces GitLab's `X-Total` running count with the number of
   cached rows (`Polling.js:205`). In Codex's test, 250 running became 99, which
   changes both the sort order and the project badge.
6. **`waiting_for_callback` counts as finished.** It is missing from the
   unfinished statuses (`gitlab.py:18-19`), so `state()` maps it to
   `completed`. This affects job progress counts and the cache's "final"
   check.
7. **A stage whose only failures are allowed shows as "skipped".**
   `stageStatus()` (`PipelinesModel.js:33-40`) ignores allowed failures but
   then needs a real success to report anything other than skipped.
8. **Job lists are not freed.** `s.details` (`Polling.js:239`) keeps a
   pipeline's job list after the pipeline is trimmed or its project leaves the
   catalogue (`Polling.js:139-144`, `:220-225`); only an attempt change drops
   one. Because
   the manifest sets `keepLoaded: true`, memory grows for the whole shell
   session.
9. **A broken `menu.managed` symlink is ignored.** `menu.py:63` uses
   `Path.exists()`, which returns false for a dangling link. The approved spec
   `spec/2026-09-19-4-menu-managed-license.md:23` says a broken marker still
   counts.
10. **A job list can be saved as final while it mixes two attempts.** Job
    pages are fetched one per second, and a summary can run between them. When
    the last page arrives, the whole list is stamped with the pipeline's
    *current* `run_attempt` (`Polling.js:238-240`). If a retry started
    mid-fetch, earlier pages belong to the old attempt, yet the list counts as
    final and is never fetched again. Codex reproduced this. `run_attempt` is a
    local stand-in (`"active"` while unfinished, else `updated_at`,
    `gitlab.py:154`) and job pages carry no attempt, so only a change the
    scheduler *observes* can be detected. Offset paging while jobs are retried
    may also skip jobs (`gitlab.py:73`); that is unverified against GitLab.
11. **Pressing `r` does not cut short a retry wait.** `manual()` calls
    `ensure()`, which for an existing task only changes its group
    (`Polling.js:22`). After repeated network errors the task's own backoff
    (up to five minutes) still applies, so a refresh can do nothing visible.
12. **Polling can follow a row that is no longer highlighted.** When a reply
    removes the selected pipeline (for example, it is trimmed from the recent
    ten) while its project remains, the rebuild moves the cursor, but `adopt()`
    only reselects if the selected *project* has vanished
    (`PipelinesPanel.qml:144`). Filtering already reselects (`:39-42`). The
    scheduler then keeps polling the old project or pipeline at interactive
    priority while another row is highlighted.
13. **The scheduler re-sorts every project ten times a second while idle.**
    Once a second has passed since the last request, each 100 ms pump calls
    `seed()`, which copies and sorts the whole catalogue even when nothing is
    due (`Polling.js:63`). With thousands of memberships this is steady
    UI-thread work for no request.

## Proposed outcome

- Any stage name groups and renders, and an exception while the panel builds
  its rows cannot leave the request worker stuck as busy.
- After a host change the panel shows only the new host's data, and no
  request that started for the old host is accepted.
- A refused project list stops discovery until the user presses `r` (the
  catalogue refresh). It shows the error and is not retried on its own.
- A cached queued pipeline that leaves the queued lists is looked up within
  one follow-up interval (15 s, subject to the request budget), even while its
  project is not selected. Follow-ups stop on a final status or a permanent
  lookup error.
- The project's running count and sort order come from GitLab's total when
  GitLab sends one. When it sends none, the existing cached-count fallback
  stays (`tests/polling.cjs:149-156`).
- `waiting_for_callback` is unfinished everywhere: job state, stage status and
  progress.
- A stage that ran and has only allowed failures shows a distinct status (not
  "skipped"), and those jobs are still visible as failed.
- Job lists are dropped when their pipeline or project leaves the retained
  model, unless that pipeline is expanded or inspected.
- A dangling `menu.managed` link turns menu registration off.
- An attempt change observed during paging discards the pages fetched so far
  and restarts the fetch. A mixed or stale list never receives the newer
  attempt's final marker.
- `r` makes the selected project eligible at once and clears its network-error
  backoff. A multi-page summary in progress restarts from page one. The request
  budget and a server rate-limit cooldown still apply.
- The scheduler always polls the project and pipeline under the cursor,
  keeping the existing 250 ms selection debounce.
- An idle open panel does not copy or sort the catalogue while no task is due.
- Each item has a regression test in the existing suites (`tests/model.cjs`,
  `tests/polling.cjs`, `tests/test_gitlab.py`, `tests/test_menu.py`). Items 1,
  2 and 12 cross into QML and are also checked in `tests/qml-smoke.py`.

## Affected users and systems

- Anyone running the plugin. It is user-level only: no NixOS host changes and
  no p510 builds.
- Files: `PipelinesModel.js`, `Polling.js`, `PipelinesPanel.qml`, `gitlab.py`,
  `menu.py`, and the tests listed above.
- The GitHub sibling `nixarchy-ghtui` probably has items 1, 3, 5, 7 and
  10–13 too. It is out of scope here, but should be checked afterwards.

## Constraints

- The plugin stays read-only and daemon-free, with no token storage, and
  nothing is polled while it is closed. This task changes no design rule.
- No new runtime dependencies.
- Keep the existing request budget: one request in flight, one per second, 60
  per minute.
- Keep the field names shared by `gitlab.py`, the model and the scheduler,
  because the GitHub sibling uses the same ones.
- The UI and workflow recommendations from the same review (status colours,
  error and empty states, keys, log tail, "my pipelines", actions,
  watch-and-notify) are out of scope. They get their own issues and intents.

## Open questions

1. **Item 7:** what should a stage with only allowed failures show? The
   proposal is `success`, with the failed jobs still shown as failed. A warning
   marker is presentation and goes to the UI issue. The alternative is a new
   `warning` status.
2. **Item 4:** how should queued pipelines on projects that are not selected
   be reconciled? Option (a) is one `run` lookup per cached queued pipeline,
   using the existing 15 s follow-up. Option (b) also checks
   `status=pending` in the background scan, which costs one more request per
   project. The proposal is (a), because it adds no requests while nothing is
   queued, and (b) alone cannot catch a pipeline that leaves the pending list
   without ever being seen running.
3. **Scope:** should all thirteen items ship in one PR, or should items 1–3
   (crash, wrong host, retry loop) ship first as a 1.0.1 patch? The proposal
   is one PR released as 1.0.1, because most items are local changes. Items 10
   and 12 need design work in the spec, and can move to a follow-up if the spec
   shows they are larger.
4. **Item 6:** should `waiting_for_callback` also be added to the pipeline
   status filters the scheduler polls (`Polling.js:2`)? The proposal is no,
   only to the job and stage handling, until it is confirmed that the
   pipelines endpoint accepts it as a `status` value. An unknown value would
   fail every summary. If it is added later, `Polling.js:2` and the helper's
   own list (`gitlab.py:15`, `:77-78`) must change together.
