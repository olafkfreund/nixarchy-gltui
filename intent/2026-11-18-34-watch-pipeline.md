---
status: draft
issue: 34
author: olafkfreund
---

# Intent: Watch a pipeline and get notified when it finishes

## Problem

The panel shows pipelines only while it is open. To learn when a long
pipeline finishes, the user has to keep the panel open, or reopen it now
and then, or watch the GitLab page. `gh run watch`, CatLight and Glance
all notify when a run they follow ends. This is the biggest workflow the
panel lacks.

The README promises "Nothing is polled while the panel is closed"
(`README.md:280`): closing cancels every request (`Polling.close()`
clears all tasks), and the pump timer runs only while open
(`PipelinesPanel.qml:504`). Watching needs a narrow exception to that
promise, decided here.

## Proposed outcome

- **`w` watches or unwatches the selected pipeline:** on a pipeline row,
  or any stage or job row inside it. In the search box `w` still types.
  The footer notice confirms (`Watching #123 in group/project`, `Stopped
  watching #123`).
- **What "finished" means:** GitLab's own status (the `conclusion` field,
  `gitlab.py:226`) is `success`, `failed`, `canceled` or `skipped`. Every
  other status can be watched, including `manual` and `scheduled`, which
  the panel otherwise files as completed (`gitlab.py:186-189`). `w` on a
  finished pipeline says `Pipeline already finished`.
- **What is watched:** one pipeline id on one host and project, until its
  first finished status is seen. A job retried before then just keeps the
  watch going; a new pipeline (a new id) needs its own `w`.
- **A watch is session state, not a cached row.** It keeps the project,
  pipeline number, ref and deadline itself. It survives closing and
  reopening, filtering, selection changes, and the pipeline dropping out
  of the rows the panel fetched (a partial activity page or a summary
  snapshot can drop a running pipeline today, `Polling.js:194-201,283-284`).
  While the panel is open, a watched pipeline is checked directly whenever
  the rows it was fetched with do not show it.
- **Watched pipelines show a mark** on their row, so the user can see what
  is being followed.
- **A desktop notification** (`notify-send`) is sent when a watched
  pipeline finishes: it names the project, the pipeline number and ref,
  and the result (passed, failed, canceled, skipped). The watch then ends.
  Seeing the finish twice (in a list and in a lookup) sends one
  notification. Several watches finishing together each get one.
- **If a notification cannot be sent** (`notify-send` missing or failing),
  the watch still ends, and the next time the panel opens its footer says
  which pipeline finished and how. Nothing retries a finished watch.
- **The exception to "nothing is polled while closed":**
  - while the panel is closed, only watched pipelines are checked: one
    request per watched pipeline (the existing single-pipeline lookup,
    `GET …/pipelines/:id`), no catalogue, activity or job requests;
  - each watched pipeline is checked about every 30 seconds while closed.
    That is a target for a healthy service: request time (up to 25 s),
    queueing, error backoff and server cooldowns can delay it;
  - **cap:** at most 5 watched pipelines at once; `w` on a sixth says
    `At most 5 watched pipelines`;
  - **expiry:** a watch ends 6 hours after `w`, with a notification saying
    so. Reopening does not extend it, and it runs out on time even during
    an error backoff or a server cooldown;
  - when the last watch ends while the panel is closed, no further
    request starts;
  - the same budget rules as today (60 pages a minute, one request in
    flight, one second between starts, server cooldowns) apply open or
    closed;
  - **errors:**
    - an authentication or setup error stops all polling today
      (`Polling.js:129,229`). While closed it ends **all** watches, with
      one notification asking the user to sign in with `glab`;
    - a permission error or a missing pipeline (403, 404) ends only that
      watch, with a notification saying it is unavailable;
    - network and server errors keep the watch, with the existing
      backoff;
  - **host change:** changing `host` in `shell.json` ends every watch, with
    one notification naming the old host. Watches never move to another
    host, and replies for the old host are ignored, as today;
  - in closed mode a pipeline lookup does nothing else: it queues no job,
    summary or activity request (today a finished lookup can queue jobs for
    an expanded selection, `Polling.js:254-255`).
- **While the panel is open,** watched pipelines are refreshed as running
  pipelines are today, and finish notifications are still sent.
- **The 10 requests a minute** with 5 watches is nominal traffic, not a
  hard maximum: error retries follow the existing backoff.
- **The README** replaces "Nothing is polled while the panel is closed"
  with the exception above, and documents `w`, the cap, the expiry and
  the notification. `keybindings.sh`, the help and the footer gain `w`.

## Affected users and systems

- **Files:** `Polling.js` (watched set, a closed-panel mode), the model
  (the mark), `PipelinesPanel.qml` (`w`, the closed-panel timer,
  notifications), `README.md`, `keybindings.sh`, the tests.
- **Requirements:** `notify-send` (libnotify). The README's Requirements
  and the Nix example gain it.
- **API use:** at most 5 requests every 30 seconds while closed, about 10
  a minute; less with fewer watches. It shares the user's GitLab quota.
- **Hosts:** p620 and razer through the usual chain. p510 stays on its
  current version.

## Constraints

- No new GitLab endpoint: the single-pipeline lookup already exists
  (`gitlab.py`, kind `run`).
- No daemon, service or file outside the shell: watching lives in the
  panel, which the manifest keeps loaded (`"keepLoaded": true`). A shell
  restart ends all watches (see question 4).
- `Polling.js` stays pure and testable without Qt.
- Read-only, as the plugin is.
- Smoke tests run in the microVM only. They must not send real desktop
  notifications; they swap the notify command, as copy swaps `wl-copy`.

## Open questions

1. **Key:** I recommend `w` ("watch"), as the issue says. It is free.
2. **Closed-panel interval:** I recommend 30 seconds. A pipeline's end is
   then noticed within about half a minute, at about 10 requests a minute
   with 5 watches.
3. **Cap and expiry:** I recommend 5 pipelines and 6 hours. Long
   pipelines on self-managed runners can take hours; 6 hours covers them
   without leaving a forgotten watch polling all day.
4. **Persistence:** I recommend keeping watches in memory only. A shell
   restart (or logout) ends them silently, and the README says so.
   Persisting them would mean a
   state file and resuming polls at login, which goes beyond a "narrow
   exception".
5. **Auto-watch:** none. Only pipelines the user marks with `w` are
   watched; for example, not "every pipeline I started".
6. **Notification action:** I recommend plain notifications, with no
   "open in browser" button. Actions need a notification daemon that
   supports them and a running process to receive the click.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
confirmed the problem (`close()` clears tasks, the pump runs only while
open), that `w` is free, that `keepLoaded` keeps the panel alive, and
agreed with all six recommendations. Its findings, which I checked in the
code and folded in above:
- an authentication error stops the whole scheduler, so it now ends all
  watches; 403 and 404 end one; network errors keep it; expiry runs
  regardless;
- running pipelines can drop out of fetched rows, so a watch is its own
  session state, checked directly when the rows do not show it, with one
  notification per finish;
- a host change now ends all watches, with one notification;
- "finished" is defined on GitLab's raw status, since `manual` and
  `scheduled` map to `completed` (`gitlab.py:186-189`); retries keep the
  watch, a new pipeline id needs a new one;
- a missing or failing `notify-send` falls back to a notice at the next
  opening; `notify-send` joins the Requirements;
- the 30 s and 10-a-minute figures are targets, not bounds; closed mode
  starts nothing but the watched lookups, and nothing after the last watch
  ends.
