---
status: draft
issue: 21
author: olafkfreund
---

# Intent: Fix correctness bugs found in the 2026-11-16 review

## Problem

A read-only review on `main` at `c8b79e6` (v1.0.0) by Codex and a Fable
planning agent found nine ways the panel crashes, shows wrong data, or wastes
requests. Items 1 and 9 were re-checked by hand. Codex reproduced items 2–5
and 7 in memory. Items 6 and 8 were found by reading the code.

1. **A valid stage name crashes the panel.** `stages()` groups jobs in a plain
   `{}` (`PipelinesModel.js:43`). Stage names `constructor`, `toString` or
   `__proto__` match inherited properties, and `.push` throws. The throw
   happens inside `receivePage()` before `workerBusy` is cleared
   (`PipelinesPanel.qml:219-220`). That is expected to stop all polling until
   the panel reopens, but nobody has seen it happen in the running panel.
2. **Changing the host mixes data from two GitLab servers.** `configure()`
   changes `host` (`PipelinesPanel.qml:125`) but keeps the polling state, which
   is keyed only by project and pipeline (`Polling.js:9`). The panel goes on
   showing the old host's projects and jobs, and sends the old project paths and
   pipeline IDs to the new host.
3. **A refused project list is retried every second, forever.** A 403 or 404
   on the catalogue request deletes the task (`Polling.js:185-189`). Because
   `discover` stays true, `seed()` recreates the task straight away
   (`Polling.js:61`), with no backoff.
4. **Queued pipelines can stay queued forever.** Projects that are not
   selected are only checked for `status=running` (`Polling.js:71`), and only
   running pipelines that disappear get a follow-up (`Polling.js:153`). A
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
8. **Job lists are never freed.** `s.details` (`Polling.js:239`) keeps every
   pipeline's job list after the pipeline or project leaves the model. Because
   the manifest sets `keepLoaded: true`, memory grows for the whole shell
   session.
9. **A broken `menu.managed` symlink is ignored.** `menu.py:63` uses
   `Path.exists()`, which returns false for a dangling link. The approved spec
   `spec/2026-09-19-4-menu-managed-license.md:23` says a broken marker still
   counts.

## Proposed outcome

- Any stage name groups and renders, and an exception while the panel builds
  its rows cannot leave the request worker stuck as busy.
- After a host change the panel shows only the new host's data, and no
  request that started for the old host is accepted.
- A refused project list stops discovery until the user refreshes or the
  existing backoff runs out. It shows the error and is not retried every second.
- A cached queued pipeline eventually reaches its real final status, even
  while its project is not selected.
- The project's running count and sort order come from GitLab's total, not
  from the number of cached rows.
- `waiting_for_callback` is unfinished everywhere: job state, stage status and
  progress.
- A stage that ran and has only allowed failures shows a distinct status (not
  "skipped"), and those jobs are still visible as failed.
- Job lists are dropped when their pipeline or project leaves the retained
  model, unless that pipeline is expanded or inspected.
- A dangling `menu.managed` link turns menu registration off.
- Each item has a regression test in the existing suites (`tests/model.cjs`,
  `tests/polling.cjs`, `tests/test_gitlab.py`, `tests/test_menu.py`).

## Affected users and systems

- Anyone running the plugin. It is user-level only: no NixOS host changes and
  no p510 builds.
- Files: `PipelinesModel.js`, `Polling.js`, `PipelinesPanel.qml`, `gitlab.py`,
  `menu.py`, and the tests listed above.
- The GitHub sibling `nixarchy-ghtui` probably has items 1, 3, 5 and 7 too. It
  is out of scope here, but should be checked afterwards.

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
   proposal is `success` plus a warning marker, which matches GitLab's
   "passed with warnings". The alternative is a new `warning` status.
2. **Item 4:** how should queued pipelines on projects that are not selected
   be reconciled? Option (a) is one `run` lookup per cached queued pipeline,
   using the existing 15 s follow-up. Option (b) also checks
   `status=pending` in the background scan, which costs one more request per
   project. The proposal is (a), because it adds no requests while nothing is
   queued.
3. **Scope:** should all nine items ship in one PR, or should items 1–3 (crash,
   wrong host, retry loop) ship first as a 1.0.1 patch?
