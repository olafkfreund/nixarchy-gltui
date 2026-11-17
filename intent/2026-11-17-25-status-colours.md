---
status: draft
issue: 25
author: olafkfreund
---

# Intent: Tell pipeline and job states apart at a glance

## Problem

Each row's status is shown by an icon (`Model.icon`, `PipelinesModel.js:19-26`)
and a colour (`statusColor`, `PipelinesPanel.qml:225-229`). Several states that
mean different things look the same:

- **Running and success share a colour.** Both are `Commons.Color.accent`
  (`PipelinesPanel.qml:227`). Only the small `◷` / `✓` icon tells "still going"
  from "done and green".
- **An allowed failure looks like a real failure.** A job with
  `allow_failure: true` that failed has the status `failed`, so it gets the red
  `✕`, the same as a job that breaks the pipeline. The stage above it is shown
  as success (`stageStatus`, `PipelinesModel.js:40`), so the job row and its
  stage disagree, and nothing says "failed, but allowed".
- **Manual, skipped and scheduled jobs look the same.** All three get `−` in the
  plain text colour (`PipelinesModel.js:24`). A manual job that waits for
  someone to press play is indistinguishable from a job that will never run.
- **Skipped jobs are as loud as the rest.** They have the same weight as jobs
  that ran.
- **Queued states fall back to `○`.** That covers `created`, `pending`,
  `waiting_for_resource` and `preparing`, so queued work looks like an unknown
  state.

## Proposed outcome

Each of these states has its own icon, and its colour adds meaning but is never
the only signal:

| State | What the user should see |
|---|---|
| Running | its own icon and colour, distinct from success |
| Success | `✓`, a "good" colour |
| Failed (blocking) | `✕`, the urgent colour |
| Failed but allowed | its own warning icon (for example `!`), a warning colour, and "allowed to fail" in the row's info |
| Manual | `▶`, so it reads as "waiting for you" |
| Skipped | dimmed, so rows that ran stand out |
| Queued / pending | its own "waiting" icon, not the unknown `○` |
| Canceled | `⊘`, unchanged |

- Stages and pipelines use the same mapping as jobs.
- The colours follow the current Omarchy theme, so they change with it.
- The selected row stays readable in every state.
- Tests cover the mapping from each status to its icon and colour.

## Affected users and systems

- Files: `PipelinesModel.js` (icons, and passing `allow_failure` through to
  rows), `PipelinesPanel.qml` (colours), `tests/model.cjs` and
  `tests/qml-smoke.py`. `gitlab.py` already sends `allow_failure` for jobs
  (`gitlab.py:161`), so the helper is not expected to change.
- Everyone using the panel.
- It ships through the usual chain: release, nixarchy pin bump, nixos_config
  lock bump. p620 and razer get it; p510 stays on 1.0.0.

## Constraints

- Colours come from the theme, never hard-coded hex values. Otherwise light
  themes and the user's theme choices break.
- Every state is still clear without colour (colour-blind users, monochrome
  themes): icons must differ.
- Icons must render in the menu font. Use characters already proven in this
  panel, or check new ones in the microVM.
- Smoke tests run in the `nixarchy-desktop` microVM, never on the host desktop
  (owner's request, #26).
- No new polling or helper requests.

## Open questions

1. **Where do the "good" and "warning" colours come from?** The shell's
   `Commons.Color` only exposes `foreground`, `background`, `accent`, `urgent`
   and `muted`. The theme's `colors.toml` also has `green`, `yellow`,
   `orange` and others, but the shell does not expose them.
   - **(a) Shell palette only:**
     - success `accent`;
     - running `foreground`, with its own icon;
     - allowed failure `urgent` at reduced opacity, with its own icon;
     - skipped `muted`.

     No new file reading, but warning and failure differ only by icon and
     strength.
   - **(b) Read `green` and `yellow` from the theme's `colors.toml`,** falling
     back to (a) when they are missing. Truer to "green / amber", but the panel
     then reads a theme file itself.

   I recommend **(a)**. It stays inside the shell's contract and keeps the
   icons as the main signal.
2. **Allowed-failure text:** should the info column say "allowed to fail", or
   show only the icon? I recommend the text: it costs a few characters and
   removes the doubt.
