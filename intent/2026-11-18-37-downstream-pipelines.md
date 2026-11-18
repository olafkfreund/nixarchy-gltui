---
status: draft
issue: 37
author: olafkfreund
---

# Intent: Show downstream and child pipelines as nested rows

## Problem

A pipeline that triggers others (a `trigger:` job, called a bridge) shows
only its own jobs. The jobs request (`gitlab.py:145`,
`pipelines/:id/jobs`) does not return bridge jobs, so the bridge itself and
the pipeline it started are missing. The README lists this as a limit
(`README.md:302`).

So when a parent pipeline is green or red because of a child pipeline
(`trigger: include:`) or a pipeline in another project (multi-project,
`trigger: project:`), the panel cannot show which one or why. The user has
to open GitLab.

What GitLab offers (Jobs API, "List pipeline trigger jobs"):
`GET /projects/:id/pipelines/:pipeline_id/bridges` returns the bridge jobs
with their own stage, status and times, each with a `downstream_pipeline`
object: `id`, `iid`, numeric `project_id`, `ref`, `sha`, `status`,
`web_url`, `created_at`, `updated_at`. It has **no start/finish times and no
project path**. `downstream_pipeline` is null both when nothing has been
created yet and when the user cannot read it. Codex reports that current
docs deprecate `/bridges` in GitLab 19.2 in favour of `/trigger_jobs`; not
verified here. The
downstream pipeline's own jobs are at
`/projects/:project_id/pipelines/:id/jobs`, keyed by the numeric project
id, which the helper does not accept today (`gitlab.py:31-36` validates a
path).

## Proposed outcome

- Under an expanded pipeline, each bridge job appears in its stage as a
  nested `»` row, with the downstream pipeline's status icon and colour.
- The row names the bridge job and what it started: "child" when the
  downstream `project_id` is the parent's, otherwise the project path taken
  from its `web_url` (validated against the configured host), plus `#iid`
  and ref.
- Times: the bridge job's duration and "ago", labelled as the trigger's,
  not presented as the downstream pipeline's run time (GitLab does not
  return those for the downstream).
- No downstream pipeline: the row shows the bridge's own status and says
  "downstream not created or unavailable", because GitLab cannot tell the
  two apart. A failed bridges request shows one error row and leaves the
  parent's cached jobs as they are.
- Keys on a `»` row: `o` / `y` open and copy the downstream URL (the
  bridge's job URL when there is none); `Shift+Y` copies the downstream
  SHA; `t` and `w` say they are not available for a trigger row. Selecting a
  `»` row keeps its parent pipeline inspected.
- Refresh: bridges are fetched while the parent is inspected, until the
  parent's jobs are final **and** every downstream shown is final. A
  downstream can keep running after its parent finished.
- No bridge requests while the panel is closed, in watch mode or in
  background checks. The README limit at `:302` is reworded.
- A new polling scenario measures an inspected parent with bridges; the
  existing #35 scenarios keep their numbers.

## Affected users and systems

- `gitlab.py` (a bridges request), `Polling.js` (when bridges are fetched),
  `PipelinesModel.js` (nested rows), `PipelinesPanel.qml` (only if the row
  needs a new marker or key), `tests/`, `README.md`, `manifest.json`.
- p620 and razer through the deploy chain. p510 is left alone.

## Constraints

- Keep #35's request budget: bridges are fetched only for a pipeline the
  user has expanded, never in background checks.
- A downstream pipeline in a project the user cannot read must show a clear
  "unavailable" row, not break the parent's jobs.
- Same validation rules as today at the helper boundary (numeric ids,
  known hosts).
- UI checks in the microVM only, never on the host desktop.

## Open questions

1. **How deep?** (a) `»` rows show status only, and `o` opens GitLab; or
   (b) a `»` row expands into the downstream pipeline's stages and jobs
   (needs jobs by numeric project id and more polling); (c) also nested
   downstreams of downstreams. Recommended: (a); (b) as a follow-up issue.
2. **Fetch cadence while inspected.** Every 5 s with the jobs refresh
   (about 360 extra requests per 30 minutes of inspecting) or every 15 s
   (about 120)? Recommended: 15 s; bridges change less often than jobs.
3. **Placement.** Inside the bridge's stage (matches GitLab's pipeline
   graph), or a separate "Downstream" group after the stages? Recommended:
   inside the stage.
4. **Endpoint.** `/bridges` (works on gitlab.com and older self-managed
   servers) or `/trigger_jobs` if the deprecation is confirmed, with a
   fallback? Recommended: `/bridges`, checked against the GitLab docs in the
   spec.
