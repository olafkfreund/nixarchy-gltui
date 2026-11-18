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
  or any stage or job row inside it. A pipeline that has already finished
  cannot be watched: the notice says `Pipeline already finished`. The
  footer notice confirms (`Watching #123 in group/project`, `Stopped
  watching #123`).
- **Watched pipelines show a mark** on their row, so the user can see what
  is being followed.
- **A desktop notification** (`notify-send`) is sent when a watched
  pipeline finishes: it names the project, the pipeline number and ref,
  and the result (passed, failed, canceled, skipped). The watch then ends.
- **The exception to "nothing is polled while closed":**
  - while the panel is closed, only watched pipelines are checked: one
    request per watched pipeline (the existing single-pipeline lookup,
    `GET …/pipelines/:id`), no catalogue, activity or job requests;
  - each watched pipeline is checked about every 30 seconds while closed;
  - **cap:** at most 5 watched pipelines at once; `w` on a sixth says
    `At most 5 watched pipelines`;
  - **expiry:** a watch ends after 6 hours without the pipeline finishing,
    with a notification saying so;
  - the same budget rules as today (60 pages a minute, one request in
    flight, one second between starts, server cooldowns) apply open or
    closed;
  - an authentication or permission error ends that watch, with a
    notification, rather than retrying forever.
- **While the panel is open,** watched pipelines are refreshed as running
  pipelines are today, and finish notifications are still sent.
- **The README** replaces "Nothing is polled while the panel is closed"
  with the exception above, and documents `w`, the cap, the expiry and
  the notification. `keybindings.sh`, the help and the footer gain `w`.

## Affected users and systems

- **Files:** `Polling.js` (watched set, a closed-panel mode), the model
  (the mark), `PipelinesPanel.qml` (`w`, the closed-panel timer,
  notifications), `README.md`, `keybindings.sh`, the tests.
- **Requirements:** `notify-send` (libnotify), which Omarchy already
  provides for its own notifications.
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
   restart (or logout) ends them silently. Persisting them would mean a
   state file and resuming polls at login, which goes beyond a "narrow
   exception".
5. **Auto-watch:** none. Only pipelines the user marks with `w` are
   watched; for example, not "every pipeline I started".
6. **Notification action:** I recommend plain notifications, with no
   "open in browser" button. Actions need a notification daemon that
   supports them and a running process to receive the click.
