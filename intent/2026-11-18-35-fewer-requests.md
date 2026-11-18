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
| 408 | idle projects' running list (137 × every 10 minutes) | `Polling.js:131-139`, interval `600000` at `:133` |
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
  ceiling (proposed: 10 → 20 → 40 → 60 minutes). Finding a running
  pipeline, selecting the project, a manual refresh, or a changed
  `last_activity_at` resets it to 10 minutes.
- **The catalogue is refreshed while open,** every 5 minutes (2 pages for 137
  projects, about 12 requests per 30 minutes). A project whose
  `last_activity_at` moved since its last check is checked next, ahead of
  its back-off. A push to a dormant project is then seen within about 5
  minutes, sooner than the 10 minutes it takes today.
- **Queued lookups back off** the same way while the pipeline stays
  queued: 15 s, doubling up to a ceiling (proposed: 5 minutes). A pipeline
  that leaves the queue is still found by the existing paths (the running
  list, the selected summary, or a lookup).
- **What does not change:**
  - the selected project's refresh (10 s activity, 60 s summary), pins
    (60 s), running projects (15 s), watches (30 s) and job logs (5 s);
  - the budget rules (60 pages a minute, 1 s between starts, one in
    flight) and the error and cooldown handling;
  - archived and CI-disabled projects stay unpolled.
- **Measured before and after.** The simulation gains a realistic scenario
  (137 projects with spread-out `last_activity_at`, 30 queued pipelines)
  and reports requests by kind. The PR shows both tables. Target: the idle
  scenario drops from 713 to under 400, and queued lookups drop by at
  least half.
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
3. **`last_activity_at` is coarse.** I believe GitLab updates it at most
   once an hour, and API-triggered or scheduled pipelines do not touch it
   (to verify in the spec). So a dormant project's scheduled pipeline is seen within the ceiling
   (up to 60 minutes) rather than 10. I recommend accepting that: pin a
   project to keep it at 60 seconds.
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
