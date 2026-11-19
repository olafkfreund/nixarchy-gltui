---
status: draft
issue: 40
author: olafkfreund
---

# Intent: A "my merge requests" view

## Problem

The panel is organised by project. To see how your own open merge requests
are doing, you have to remember which projects they are in, find each
project, expand it, and pick the merge-request pipeline out of the list by
its `!N` branch. Issue #40 asks for a view like gh-dash's home view: your
open merge requests, each with its latest pipeline status, switched to with
a key.

Today the plugin has no merge-request data at all:

- **The panel has one view.** `Model.rows` (`PipelinesModel.js` line 229)
  builds the project → pipeline → stage → job tree from `polling.repos`.
  There is nothing to switch to.
- **The helper cannot read merge requests.** `page_endpoint`
  (`gitlab.py` line 138) accepts six read kinds (`catalogue`, `activity`,
  `summary`, `jobs`, `bridges`, `run`) and builds only project, pipeline and
  job URLs. Anything else raises `ValueError`.
- **Merge requests show only as a pipeline's ref.** A merge-request
  pipeline's ref is `refs/merge-requests/N/head`, shown as `!N`
  (`shortRef`, `PipelinesModel.js` line 150). The panel does not know the
  title, author, draft state or target branch, and only sees such a
  pipeline when it polls that project.
- **Polling is per project.** The scheduler (`Polling.js`) fetches one page
  at a time for the selected project, projects with running pipelines, pins
  and background discovery, within 60 pages a minute, one second between
  starts and one request in flight (README "Refresh and errors"). A new
  view must fit inside that budget, not add a second scheduler.
- **Your merge requests can be anywhere.** The catalogue is
  `projects?membership=true` (`gitlab.py` line 147). A merge request you
  opened in a project you are not a member of (a fork-based contribution, or
  a project you can only report to) is not in the catalogue.
- **Most letter keys are taken**: `r R o y Y p t w g G e q a c x n ? /
  j k h l` (`PipelinesPanel.qml` lines 755-779; README "Keyboard"). Tab is
  used only while the search box has focus (line 817).
- **The list API probably lacks pipeline status.** GitLab's
  `GET /merge_requests` returns your merge requests across projects, but, as
  far as the docs show, the list response has no pipeline field; the head
  pipeline comes from the single merge request (`head_pipeline`) or its
  pipelines list. The spec confirms this against GitLab's API docs, because
  it decides how many requests the view costs.

The sister plugin has the same request open (nixarchy-ghtui #63, "PR checks
view"), not yet designed, so there is no decision to copy.

## Proposed outcome

When this is done, from the open panel and with the keyboard only:

- **One key switches** between the projects view and a "my merge requests"
  view, and back. The header says which view is shown. The projects view is
  unchanged when you return: what you expanded, filtered and selected is
  still there.
- **The view lists your open merge requests** on the configured host, newest
  activity first, across every project, including projects outside the
  catalogue. Each row shows the project, `!N`, the title, the source branch,
  a draft mark, and the status of its latest pipeline with the same icons and
  colours as pipeline rows (or "no pipeline").
- **The status stays current while you look.** An unfinished pipeline's
  status refreshes about as often as a running project's does today; a
  finished one is not refetched until it changes or you refresh.
- **It works like the rest of the panel.** `↑ ↓ j k g G`, Page Up/Down and
  Home/End move; `/` filters by title, project, branch and status; `o` opens
  the merge request on GitLab; `y` copies its URL; `r` refreshes the view;
  `?` shows the keys; `q` and Esc close as today. Keys that make no sense on
  a merge-request row say so in the footer instead of doing nothing.
- **From a merge request to its pipeline.** One key takes you from a
  merge-request row to its latest pipeline in the projects view, expanded and
  selected, where watching, logs and actions already work (open question 4).
- **Empty, loading and error states are clear**: "No open merge requests",
  a loading line, and the same error strip and hints as the projects view
  (auth, rate limit, network).
- **No cost while you do not use it.** The view fetches nothing until you
  first switch to it, and nothing while the panel is closed. Its requests go
  through the same scheduler and limits as every other read, and a rate
  limit pauses it like any other read.
- **Docs**: the README (keyboard, refresh and errors, known limits) and the
  `keybindings.sh` sheet list the key and the view.

## Affected users and systems

- **Everyone with the plugin installed** gets one new key and one new view;
  nothing changes until they press it.
- **Token scope**: `read_api` is enough to list merge requests and their
  pipelines. No new scope.
- **Files**: `gitlab.py` (new read kinds and a merge-request row parser),
  `Polling.js` (scheduling the view's reads), `PipelinesModel.js` (rows for
  the view), `PipelinesPanel.qml` (view switch, header, keys, footer),
  `keybindings.sh`, `README.md`, `manifest.json` (1.15.0), and tests under
  `tests/` (unit, model, polling and the QML smoke test in the headless VM).
- **Rate limits**: the view's requests share the account's API quota and the
  panel's 60-pages-a-minute budget with project polling.
- **Hosts**: p620 and razer get it on the 1.15.0 deploy. p510 is not
  touched.

## Constraints

Kept as they are:

- **No daemon, database or token storage**; `glab`'s login signs every
  request.
- **Keyboard-first and theme-native.** No buttons, no tabs drawn as
  widgets; the view uses the existing row styles and icons.
- **One scheduler and one budget.** No second polling loop; the README's
  request limits stay true for the new reads.
- **A closed set of read endpoints.** The new merge-request URLs are built
  by `page_endpoint` from validated values only; nothing typed reaches
  `glab` as an option or a path.
- **GitLab text is untrusted (#15).** Titles, branch names and author names
  go through `plain()` and are drawn as plain text.
- **One configured host.** The view lists merge requests on the host the
  panel already uses.
- **Opt-in actions stay as they are.** The view adds no new writes; actions
  stay on pipeline and job rows, behind the `actions` setting.
- **No new runtime dependency.**

## Open questions

Recommendations follow the owner's earlier "use recommendations that make
sense".

1. **Which merge requests?** (a) Only those you opened
   (`scope=created_by_me`). (b) Also those where you are a reviewer.
   (c) Also those assigned to you.
   *Recommendation: (a) now, as the issue says ("your open MRs"). A
   "review requested" list is a natural follow-up, filed as its own issue
   with its own key or section, so this one stays small.*
2. **How many?** *Recommendation: the first page of 50, ordered by
   `updated_at`, with "N more on GitLab" when there are more, like the
   unfinished-pipeline lists (#15). Open merge requests you authored rarely
   exceed that.*
3. **Which key switches the view?** *Recommendation: `m` ("merge
   requests"), free today, toggling between the two views. Tab stays the
   search field's key. The spec confirms `m` is not used by the shell or the
   sheet.*
4. **What does Enter do on a merge-request row?** (a) Jump to its latest
   pipeline in the projects view (switch view, expand the project and the
   pipeline, select it). (b) Expand the pipeline's stages and jobs inside
   the merge-request view. (c) Nothing; use `o`.
   *Recommendation: (a). It reuses the existing pipeline, job, watch, log
   and action rows instead of a second tree, so `t`, `w` and `a/c/x/n` work
   on a merge request's pipeline with no new code. A merge request in a
   project outside the catalogue gets that project added as a row, as a
   configured `projects` entry is today.*
5. **How is the pipeline status fetched?** (a) One request per merge
   request for its head pipeline, scheduled like a project's activity: the
   selected row first, unfinished pipelines every 15 seconds, finished ones
   only when the list says the merge request changed. (b) Only the list,
   with the status taken from pipelines the panel already polled for that
   project, and "not checked" otherwise.
   *Recommendation: (a), capped by the existing budget. (b) costs nothing
   but leaves most rows "not checked", which defeats the issue. The spec
   picks the endpoint and confirms the list response has no usable
   pipeline field.*
6. **How often is the list itself refreshed?** *Recommendation: on first
   switch, then every 60 seconds while the view is shown, and on `r`. Not
   while the projects view is shown or the panel is closed.*
7. **Does the projects view keep polling while the merge-request view is
   shown?** *Recommendation: yes, at its background rates only (the
   "selected project" rates follow the selected row, and in this view no
   project row is selected), so returning shows current data. Watches keep
   their 30-second rate either way.*
8. **Is the view remembered?** *Recommendation: the panel reopens in the
   view it was closed in, until the shell restarts, like the zoom. No state
   file.*
