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

What GitLab offers (Pipelines API, "List pipeline trigger jobs"):
`GET /projects/:id/pipelines/:pipeline_id/bridges` returns the bridge jobs,
each with its stage, status and a `downstream_pipeline` object (`id`,
`project_id` as a number, `ref`, `sha`, `status`, `web_url`, times). The
downstream pipeline's own jobs are at
`/projects/:project_id/pipelines/:id/jobs`, keyed by the numeric project
id, which the helper does not accept today (`gitlab.py:31-36` validates a
path).

## Proposed outcome

- Under an expanded pipeline, each downstream pipeline appears as a nested
  `»` row at the bridge job's place in its stage, with the same status icon,
  colour, duration and "ago" text as other pipeline rows.
- A `»` row names what it is: child or the downstream project's path, its
  ref and number, so a multi-project pipeline is distinguishable.
- A bridge whose downstream pipeline has not been created yet (manual
  trigger, still pending) shows the bridge's own status.
- `o` and `y` on a `»` row open and copy the downstream pipeline's URL.
- While the parent is inspected, `»` rows refresh with its jobs and stop
  once everything is final, like jobs today.
- The README limit at `:302` is removed or reworded.

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
   downstreams of downstreams. Recommended: (a) first, (b) as a follow-up.
2. **Fetch cadence.** Bridges with every jobs refresh (every 5 s while
   inspected, one extra request each), or less often (for example every
   15 s, or only until all bridges are final)? Recommended: with the jobs
   refresh, stopping when the parent's jobs are final.
3. **Placement.** Inside the bridge's stage as a job-level row (matches
   GitLab's pipeline graph), or in a separate "Downstream" group after the
   stages? Recommended: inside the stage.
