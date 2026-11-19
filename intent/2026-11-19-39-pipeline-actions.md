---
status: draft
issue: 39
author: olafkfreund
---

# Intent: Retry, cancel, play and trigger pipelines from the panel

## Problem

The panel shows a failed, stuck or manual pipeline, but it cannot act on
it. To retry a flaky job, cancel a pipeline that is burning runner minutes,
start a manual deploy job, or run a new pipeline on a branch, you leave the
panel, open GitLab or a terminal, find the same pipeline again and act
there. Issue #39 asks for the panel to do these itself.

The owner already decided the frame (issue comment, 2026-11-17): yes, as an
opt-in; the default token scope stays `read_api`; a write fails with a
clear message when the token lacks `api`; every action asks for
confirmation; and `gitlab.py` gets a separate allowlist of the POST
endpoints it may call.

Today the plugin has no write path at all:

- **The helper can only read.** `gitlab.py` says "Read-only GitLab pipeline
  data" (line 1). Its modes are `page` and `pins` (`main`, line 368).
  `request()` runs `glab api --hostname <host> --include <endpoint>` with no
  method or body (lines 113-124), so it only sends GET requests.
- **The endpoint list is closed.** `page_endpoint` accepts six read kinds
  (`catalogue`, `activity`, `summary`, `jobs`, `bridges`, `run`, line 128)
  and builds only read URLs. Anything else raises `ValueError`.
- **Documented scope is read only.** The README requires a token with
  `read_api` (lines 10, 152, 154). A `read_api` token gets 403 on any write.
- **A 403 is read as "cannot read".** `read_page` turns 403 and 404 into
  `errorType="permission"` with "Project unavailable or read_api scope
  missing" (lines 331-332). `Polling.complete` then marks the project
  `blocked` for catalogue, activity and summary tasks (`Polling.js` line
  354) and deletes the task (line 358). A refused write must not do this,
  or one failed retry would hide the project's activity.
- **There is no setting for it.** The plugin entry in
  `~/.config/omarchy/shell.json` holds `host`, `projects` and `pinned`
  (`PipelinesPanel.qml` `configure`, lines 370-394; README lines 131-148).
  Nothing turns writes on or off.
- **The panel has no confirm step.** The footer hint is the only line that
  is always visible (`listHint`, line 51). Most letter keys are taken:
  `r R o y Y p t w g G e q ? / j k h l` (lines 629-651).
- **A cut-off write has an unknown result.** The helper kills `glab` after
  25 seconds (line 119) and the whole request after 90 (line 388). Closing
  the panel stops the running request process. For a read that is
  harmless; for a write, a killed call does not prove GitLab did nothing,
  and a blind retry could start a job twice.
- **Rows move while you look at them.** Polling rebuilds and reorders the
  list (`rebuild()` via `Model.rows`, line 211). A confirmation that points
  at "the selected row" could point at a different pipeline by the time you
  confirm.
- **The panel has no ref to trigger on.** Project rows carry no default
  branch (`project()`, `gitlab.py` lines 286-291). Pipeline rows carry
  their `ref` (`head_branch`, line 230).

The sister plugin did the same for GitHub (nixarchy-ghtui #45: rerun,
rerun failed, cancel; dispatch left out). Its owner decisions are a
starting point, not binding here: this issue differs in being opt-in and
in asking for manual jobs and new pipelines too.

## Proposed outcome

When this is done, with the setting on and a token with the `api` scope,
from the panel and with the keyboard only, you can:

- **Retry** a failed or canceled pipeline (GitLab retries its failed and
  canceled jobs), or a single failed or canceled job.
- **Cancel** a running or pending pipeline, or a single running or pending
  job.
- **Play** a manual job.
- **Trigger** a new pipeline, on a ref to be decided (open question 2).

Whichever way the open questions are answered:

- **Off by default.** With the setting off, no write key does anything but
  say how to turn actions on. The panel stays exactly as read-only as
  today, and the helper refuses write requests unless told the setting is
  on.
- **The default scope stays `read_api`.** Everything that works today
  keeps working with it. A write with a `read_api` token fails with a
  message that names the missing `api` scope, and nothing else changes: the
  project is not marked blocked and polling continues.
- **Every action asks for confirmation first**, naming the project, the
  pipeline or job, and what will happen. Nothing is sent until you confirm.
  Escape backs out.
- **The confirmation is pinned to its target.** If the list changes while
  it is open, you cannot confirm an action on a different pipeline or job.
- **The result is shown.** After you confirm, the panel says whether GitLab
  accepted the action, refused it (with the reason), or whether the outcome
  is unknown (timed out or cut off). An unknown outcome is never retried on
  its own.
- **Only sensible actions are offered.** You cannot cancel a finished
  pipeline, retry a running one, or play a job that is not manual.
- **The affected pipeline refreshes soon after**, without bypassing a
  GitLab rate-limit cooldown; if a cooldown holds it back, the panel says
  so.
- **A closed allowlist.** `gitlab.py` can send only the POST requests in a
  fixed table, separate from the read endpoints. It still cannot send an
  arbitrary request, and nothing the user types reaches `glab` as an
  option or a file path.
- **Docs.** The README (requirements, settings, authentication, keyboard,
  refresh and errors) and the `keybindings.sh` sheet list the setting, the
  keys and the `api` scope.

## Affected users and systems

- **Everyone with the plugin installed** gets the new code, but with the
  setting off nothing they see changes beyond the docs and one message on a
  write key.
- **Users who turn it on** need a `glab` login or environment token with
  `api` on that host, and at least Developer role on the project (GitLab's
  rule for retry, cancel and play; protected branches and protected
  environments can refuse more). The spec confirms these against GitLab's
  API docs.
- **Files:** `gitlab.py`, `PipelinesPanel.qml`, `PipelinesModel.js`,
  `Polling.js`, `keybindings.sh`, `README.md`, `manifest.json` (1.14.0),
  and tests under `tests/` (unit, model, polling and the QML smoke test,
  which now runs in CI from #38).
- **GitLab side effects.** Retry, play and trigger start real runner time
  and can deploy. Cancel cannot be undone.
- **Rate limits.** Writes spend the same quota as polling.
- **Hosts.** p620 and razer get it on the 1.14.0 deploy. p510 is not
  touched.

## Constraints

Kept as they are:

- **No daemon, database or token storage.** `glab`'s own login signs every
  request; the plugin never reads a token (README line 3, 152).
- **Keyboard-first and theme-native.** No buttons. Any confirm line uses
  the Omarchy theme.
- **No shell strings.** `request()` passes an argument list to `Popen`.
  Project, pipeline and job IDs are validated as today (`project_path`,
  the numeric ID check at lines 136-137); a ref, if the user picks one,
  must reach GitLab as a value only.
- **One configured host.** Writes go to the host reads use, validated by
  `host_name` (line 107).
- **GitLab text is untrusted (#15).** Names, refs and error messages shown
  in a confirmation or result go through `plain()` and are drawn as plain
  text.
- **Polling rules still hold.** No polling while closed except watches; a
  manual refresh never bypasses a server cooldown.
- **No new runtime dependency** and no new file in the package beyond what
  the spec names.

Changed by this task:

- "Read-only" is dropped from the helper and the README intro, and the
  README says the plugin can write when the setting is on.
- A write is not a read: its result, and especially its 403, is reported
  to the user, not fed into the polling error path.

## Open questions

Recommendations follow the owner's earlier "use recommendations that make
sense".

1. **Which actions ship first?** (a) Retry, cancel and play only, on
   pipelines and jobs; trigger later. (b) All four now.
   *Recommendation: (b), with trigger kept to the simple case in question 2.
   The issue asks for all four, and trigger without variables is one more
   row in the allowlist.*
2. **Trigger on which ref?** (a) The selected pipeline's ref only ("run
   again on `main`"), no typed input. (b) A typed branch or tag. (c) Also
   CI/CD variables.
   *Recommendation: (a). It needs no input field, no ref validation beyond
   what GitLab returns, and covers "run it again with the latest commit".
   Typed refs and variables stay in a terminal (`glab ci run`).*
3. **Where does the setting live?** A key in the plugin's `shell.json`
   entry, next to `host` (for example `"actions": true`), read on each
   open like the others.
   *Recommendation: yes, that key. No state file, no in-panel toggle, so it
   cannot be switched on by a stray key.*
4. **Pipeline or job, from which row?** Retry and cancel exist for both.
   *Recommendation: the row decides: on a pipeline row they act on the
   pipeline, on a job row on that job. Play only on a manual job row.
   Trigger on a pipeline row. Project, stage, `»`, more and message rows
   offer nothing.*
5. **Keys.** One key per action or one action menu?
   *Recommendation: one key each on free letters, for example `a` retry
   ("again"), `c` cancel, `x` play ("execute"), `n` new pipeline. `n` is
   then unusable as "no" in the confirmation, so the confirmation would be
   `y` / Esc. The spec fixes the letters.*
6. **How strong is the confirmation?** One `y` for all, or more for cancel
   and play (play can deploy)?
   *Recommendation: one `y` for every action, the target and effect
   spelled out, auto-repeat ignored so a held key cannot confirm twice, and
   Enter not a confirm key.*
7. **What does a `read_api` user see with the setting on?** Probe the
   token first, or try and report?
   *Recommendation: try and report. GitLab's 403 says `insufficient_scope`,
   and a probe costs a request and is unreliable for project and group
   tokens.*
8. **Does a write count toward the polling budget?**
   *Recommendation: no, but it waits for a rate-limit cooldown, and a write
   reply that shows a limit pauses polling like a read would (as ghtui #45
   did).*
