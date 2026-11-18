---
status: draft
issue: 35
author: olafkfreund
---

# Intent: Cut API requests for accounts with many idle projects

## Problem

An open panel on an account with many projects spends most of its
requests on projects where nothing happens. The existing simulation
(`tests/polling.cjs:102`) covers 137 idle projects, one selected project and
30 minutes with the panel open. It makes **713 requests**:

| Requests | What | Where |
| --- | --- | --- |
| 408 | idle projects' running list (136 non-selected × 3: a first check, then every 10 minutes) | `Polling.js:131-139`, interval `600000` at `:133` |
| 168 | the selected project's full summary (6 status pages every minute) | `Polling.js:126`, `phases` at `:2` |
| 135 | the selected project's running list (every 10 s) | `Polling.js:133` |
| 2 | the project catalogue | `Polling.js:120` |

Over half the traffic checks idle projects, and every idle project costs
the same however long it has been dormant. The catalogue already returns
each project's `last_activity_at` (`gitlab.py:248`). It is used only to
sort, and it is never refreshed while the panel stays open (`Polling.js:67`
refreshes it only on open, after 5 minutes).

Queued pipelines (#21) add a lookup every 15 s for each queued pipeline on a
project that is not selected (`Polling.js:145-148`): about 58 requests a
minute with 30 queued, for pipelines that often wait for a runner for a
long time.

All of this shares the user's GitLab API quota with their other tools.

## Proposed outcome

- **Idle projects back off.** Each running-list check that finds nothing
  running lengthens that project's next interval, from 10 minutes up to a
  ceiling (proposed: 10 → 20 → 40 → 60 minutes). A project whose
  `last_activity_at` is already old starts further along: active within a
  day starts at 10 minutes, within a week at 20, older at 60. Finding a
  running pipeline, selecting the project, a manual refresh, or a changed
  `last_activity_at` resets it to 10 minutes.
- **The catalogue is refreshed while open,** every 5 minutes (2 pages for 137
  projects, about 12 requests per 30 minutes). A project whose
  `last_activity_at` moved since its last check takes priority for the next
  background check, ahead of its back-off.
- **What this can and cannot see.** The idle check reads only the running
  list (`gitlab.py:146-151`), today and after this change. A pipeline that
  starts and finishes between two checks is never shown as running, at 10
  minutes today and more often at 60. `last_activity_at` is a hint, not a
  guarantee. GitLab does not update it within an hour of its previous
  update (Projects API documentation). It also misses scheduled and
  API-triggered pipelines (gitlab-org/gitlab#227877). The catalogue refresh
  speeds up only the cases it does catch. Short pipelines on idle projects
  will be missed more often than today. A project's recent history is still
  complete when it is selected, because the selected summary lists the ten
  most recent pipelines.
- **Queued lookups back off** while the pipeline stays queued: 15 s,
  doubling up to a ceiling (proposed: 5 minutes). This applies only to
  queued pipelines on non-selected projects that are not watched and not
  awaiting their final status. Watches (30 s) and final-status lookups
  keep their current timing. A pipeline
  that leaves the queue is still found by the existing paths (the running
  list, the selected summary, or a lookup).
- **What does not change:**
  - the selected project's refresh (10 s activity, 60 s summary), pins
    (60 s), running projects (15 s), watches (30 s) and job logs (5 s);
  - the budget rules (60 pages a minute, 1 s between starts, one in
    flight) and the error and cooldown handling;
  - archived and CI-disabled projects stay unpolled.
- **Measured before and after.** The simulation gains a realistic scenario
  (137 projects with spread-out `last_activity_at`, a few recently active)
  and a queued scenario (30 queued pipelines on non-selected projects). It
  reports requests by kind for the first 30 minutes and for a 2-hour
  session. The PR shows both tables. Targets:
  - first 30 minutes, realistic spread: from 713 to under 500. The first
    check of every project (136) and the selected project's traffic (303)
    stay, so this window cannot drop much further;
  - 2-hour session: idle running-list checks drop by at least 60 %;
  - queued scenario: lookups drop by at least half.
- **The README's refresh table** gains the back-off and the catalogue
  refresh.

## Affected users and systems

- **Files:** `Polling.js` (intervals, catalogue refresh, back-off state on
  each repo and run), `tests/polling.cjs` (the scenarios and the counts),
  `README.md`. No change to `gitlab.py`, the panel or the model is
  expected.
- **Users:** fewer requests against their quota. A dormant project's first
  pipeline after a quiet spell may show up later than today (see
  question 3).
- **Hosts:** p620 and razer through the usual chain. p510 stays on its
  current version.

## Constraints

- No new endpoint or helper mode. Only data the panel already fetches.
- `Polling.js` stays pure and testable in Node.
- Freshness for what the user is looking at (selected, pinned, running,
  watched, inspected jobs) must not get worse.
- Smoke tests, if any are needed, run in the microVM only.

## Open questions

1. **Back-off ceiling for idle projects:** I recommend 60 minutes, with the
   5-minute catalogue refresh as the fast path.
2. **Queued back-off ceiling:** I recommend 5 minutes.
3. **Missed short pipelines on idle projects.** With a 60-minute ceiling, a
   pipeline that starts and finishes between checks on an idle project is
   missed more often than at 10 minutes. The catalogue hint narrows this
   gap but does not close it. I recommend accepting it: the selected
   summary still shows the history, and pinning a project checks it every
   60 seconds. Pinning samples more often; it does not guarantee that a
   short pipeline is seen.
4. **Batching through GraphQL** (one query for the running pipelines of
   many projects) would cut idle checks the most. It needs a new helper
   mode and GraphQL complexity limits checked against gitlab.com and
   self-managed instances. I recommend leaving it out of this issue and
   filing it separately if the numbers above are not enough.
5. **The selected summary's 6 pages a minute** (168 requests) are left as
   they are: they serve the project the user is looking at. Fetching the
   four rarely-used statuses (`pending`, `created`, `waiting_for_resource`,
   `preparing`) less often would save about 90 more. I recommend leaving
   it out.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
reproduced 713 = 408 + 168 + 135 + 2 and confirmed the line references.
Its findings, which I checked and folded in above:
- **Target (confirmed):** the under-400 target was unreachable in a
  30-minute window. In Codex's experiment, removing every repeat idle check
  still left 442 requests. The targets are now split into a first-30-minute
  window and a 2-hour session, and old projects start at a longer interval.
- **Discovery promise (confirmed):** the draft promised that pipelines
  would be "seen". The idle check reads only running pipelines, so short
  ones can be missed. The outcome and question 3 now say so. The hourly
  `last_activity_at` throttle is in GitLab's Projects API documentation.
  The scheduled-pipeline gap rests on gitlab-org/gitlab#227877; Codex could
  not verify current behaviour for every trigger and version.
- **Queued back-off scope (confirmed):** it is restricted to unwatched,
  non-selected queued runs that are not awaiting their final status
  (`Polling.js:145-148`).
- **For the spec:**
  - changed projects must take priority for the single background slot
    (`Polling.js:122-140`);
  - the catalogue refresh must wake the scheduler, keep its permission-stop
    and retry handling, and keep cached projects on partial or failed
    snapshots;
  - host reset clears the new state;
  - back-off counters must survive `union()` replacing run objects.
- **Open questions:** Codex agrees with 1, 2, 4 and 5. It disagreed with
  the old wording of 3 ("seen within the ceiling"), which is now
  rewritten.
