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
  pipeline's ref is `refs/merge-requests/N/head`, `/merge` or `/train`,
  shown as `!N` (`shortRef`, `PipelinesModel.js` line 150). The panel does not know the
  title, author, draft state or target branch, and only sees such a
  pipeline when it polls that project.
- **Polling is per project.** The scheduler (`Polling.js`) fetches one page
  at a time for the selected project, projects with running pipelines, pins
  and background discovery, within 60 pages a minute, one second between
  starts and one request in flight (README "Refresh and errors"). A new
  view must fit inside that budget, not add a second scheduler.
- **Your merge requests can be anywhere.** The catalogue is
  `projects?membership=true` (`gitlab.py` lines 147-148). A merge request you
  opened in a project you are not a member of (a fork-based contribution, or
  a project you can only report to) is not in the catalogue. Seeding such a
  project does not help: configured `projects` are only discovery seeds
  (`PipelinesPanel.qml` line 500), and a finished catalogue drops every
  project it did not list, with its cached details (`Polling.js` lines
  416-421).
- **A fork's pipeline can live in another project.** A fork merge request's
  pipeline normally runs in the source fork; members of the parent can run
  it in the target project instead (GitLab "merge request pipelines" docs,
  forked projects). The merge request's project and its pipeline's project
  can differ.
- **Polled projects skip archived, CI-disabled and blocked projects**
  (`Polling.js` line 165).
- **Most letter keys are taken**: `r R o y Y p t w g G e q a c x n ? /
  j k h l` (`PipelinesPanel.qml` lines 755-779; README "Keyboard"). Tab is
  used only while the search box has focus (line 817).
- **The list API lacks pipeline status.** GitLab's
  `GET /merge_requests?scope=created_by_me&state=opened` returns your merge
  requests across every project you can see, but its documented fields have
  neither `pipeline` nor `head_pipeline`. The head pipeline comes from the
  single merge request (`head_pipeline`, one request each), and only when
  you may see that project's pipelines. The merge request's pipelines list
  does not document its order, so "first item" is not "latest". Status
  therefore costs one request per merge request.
- **Totals can be missing.** GitLab may omit `X-Total`; the helper already
  reports "more, count unknown" (`pipeline_total`, `gitlab.py` line 241).

The sister plugin has the same request open (nixarchy-ghtui #63, "PR checks
view"), not yet designed, so there is no decision to copy.

## Proposed outcome

When this is done, from the open panel and with the keyboard only:

- **One key switches** between the projects view and a "my merge requests"
  view, and back. The header says which view is shown. The projects view is
  unchanged when you switch back with that key: what you expanded, filtered
  and selected is still there. (Jumping to a pipeline, below, deliberately
  changes the selection.)
- **The view lists your open merge requests** on the configured host, most
  recently updated first, across every project you can see, including
  projects outside the catalogue, up to the cap in open question 2. When
  there are more, the last row says so ("N more on GitLab", or "more on
  GitLab" when GitLab gives no count). Each row shows the project, `!N`, the
  title, the source branch, a draft mark, and the status of its head
  pipeline with the same icons and colours as pipeline rows.
- **The pipeline state is never guessed.** A row says one of: the status;
  "not checked" (not fetched yet); "no pipeline" (GitLab says there is
  none); or "pipeline hidden" (GitLab gave no pipeline because you may not
  see it). A row whose status is older than its refresh target says how old
  it is.
- **The status stays current while you look, best effort.** The selected
  row is refreshed first. Unfinished pipelines are refreshed in the shared
  budget, behind selected data and projects with running pipelines, so with
  many unfinished merge requests each row refreshes less often and shows
  its age. Finished statuses are rechecked on a bounded interval, when the
  list shows the merge request changed, and on `r`, because a retried or new
  pipeline is not guaranteed to change the merge request's own timestamp.
- **It works like the rest of the panel.** `↑ ↓ j k g G`, Page Up/Down and
  Home/End move; `/` filters by title, project, branch and status; `o` opens
  the merge request on GitLab; `y` copies its URL; `r` refreshes the view;
  `?` shows the keys; `q` and Esc close as today. Keys that make no sense on
  a merge-request row say so in the footer instead of doing nothing.
- **From a merge request to its pipeline.** One key takes you from a
  merge-request row to its head pipeline in the projects view, expanded and
  selected, where watching, logs and actions already work (open question 4).
  It goes to the project that owns the pipeline, which for a fork can differ
  from the merge request's project. When that project is not in the
  projects view (not a member, archived or CI disabled), or the row has no
  pipeline, the footer says so and `o` still opens the merge request.
- **Empty, loading and error states are clear**: "No open merge requests",
  a loading line, and the same error strip and hints as the projects view
  (auth, rate limit, network).
- **A host change resets the view.** Changing `host` while the view is open
  or a fetch is running drops the old host's rows, ignores replies that
  arrive for the old host, and loads the new host's list.
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
   `updated_at`, with "N more on GitLab" (or "more on GitLab" without a
   count) when there are more, like the unfinished-pipeline lists (#15).
   Older merge requests past the cap are not shown or searchable in the
   panel; that is stated in the README's known limits.*
3. **Which key switches the view?** *Recommendation: `m` ("merge
   requests"), free today, toggling between the two views. Tab stays the
   search field's key. The spec confirms `m` is not used by the shell or the
   sheet.*
4. **What does Enter do on a merge-request row?** (a) Jump to its latest
   pipeline in the projects view (switch view, expand the project and the
   pipeline, select it). (b) Expand the pipeline's stages and jobs inside
   the merge-request view. (c) Nothing; use `o`.
   *Recommendation: (a), into the project that owns the head pipeline. It
   reuses the existing pipeline, job, watch, log and action rows instead of
   a second tree, so `t`, `w` and `a/c/x/n` work on a merge request's
   pipeline with no new code. Only projects already in the projects view
   are jumped into; for others the footer says so and `o` opens the merge
   request. Keeping a non-member project alive across catalogue refreshes is
   left out: it would change discovery for a rare case.*
5. **How is the pipeline status fetched?** (a) One request per merge
   request for its head pipeline, scheduled like a project's activity: the
   selected row first, unfinished pipelines often, finished ones
   only when the list says the merge request changed. (b) Only the list,
   with the status taken from pipelines the panel already polled for that
   project, and "not checked" otherwise.
   *Recommendation: (a), the single merge request's `head_pipeline`, in the
   existing budget: the selected row first, then unfinished pipelines at
   most every 30 seconds, behind selected data and running projects, so
   fifty unfinished merge requests cannot starve project polling; finished
   ones rechecked every 10 minutes and when the list shows a change. (b)
   costs nothing but leaves most rows "not checked", which defeats the
   issue. "Latest" means GitLab's head pipeline, whatever its kind
   (detached, merged results or merge train). The spec sets the exact rates
   and slot share.*
6. **How often is the list itself refreshed?** *Recommendation: on first
   switch, then every 60 seconds while the view is shown, and on `r`. Not
   while the projects view is shown or the panel is closed.*
7. **Does the projects view keep polling while the merge-request view is
   shown?** *Recommendation: yes. Projects with running pipelines keep their
   15-second rate and idle ones their background rates; only the "selected
   project" rates pause, because in this view no project row is selected.
   Watches keep their 30-second rate either way. The merge-request reads
   take what is left of the 60-a-minute budget.*
8. **Is the view remembered?** *Recommendation: the panel reopens in the
   view it was closed in, until the shell restarts, like the zoom. No state
   file.*
