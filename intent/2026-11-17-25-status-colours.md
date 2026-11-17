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
  `✕`, the same as a job that breaks the pipeline. A stage whose jobs all
  succeeded or failed-but-allowed is shown as success (`stageStatus`,
  `PipelinesModel.js:38`). So the job row and its stage disagree, and nothing
  says "failed, but allowed". Job rows also drop `allow_failure`
  (`PipelinesModel.js:112-113`).
- **Manual, skipped and scheduled jobs look the same at a glance.** All three
  get `−` in the plain text colour (`PipelinesModel.js:24`,
  `PipelinesPanel.qml:228`). Only the small status word in the info column
  (`PipelinesPanel.qml:468`) tells a manual job waiting for someone to press
  play from a job that will never run.
- **Skipped jobs are as loud as the rest.** They have the same weight as jobs
  that ran.
- **Queued states fall back to `○`.** That covers `created`, `pending`,
  `waiting_for_resource` and `preparing`, so queued work looks like an unknown
  state.

## Proposed outcome

Every status maps to one of these groups. Within a group, rows look the same.
The icon is the signal that always differs; colour reinforces it where the
theme's palette allows.

| Group | Statuses | What the user sees |
|---|---|---|
| Running | `running`, `canceling` | its own running icon, distinct from success |
| Success | `success` | `✓` |
| Failed (blocking) | `failed` without `allow_failure`, repo `error`, `unavailable` | `✕`, the urgent colour |
| Allowed failure | `failed` with `allow_failure` | its own warning icon (for example `!`), and "allowed to fail" in the info column |
| Manual | `manual` | `▶`, so it reads as "waiting for you" |
| Scheduled | `scheduled` | its own clock-like icon, not `−` |
| Queued | `created`, `pending`, `waiting_for_resource`, `preparing`, `waiting_for_callback`, `awaiting final status`, the "Loading jobs…" row (`queued`) | its own waiting icon, not the unknown `○` |
| Skipped | `skipped` | `−`, dimmed |
| Canceled | `canceled` | `⊘`, unchanged |
| Neutral | repo rows with nothing running (`neutral`) | unchanged |
| Unknown | anything else | `○`, unchanged |

- **Icons are the guarantee.** Every group above has a different icon in every
  theme.
- **Colours reinforce, where the palette allows.** Running and success should
  differ in colour, but the shell's `accent` and `foreground` can be equal in
  some themes (`Commons/Color.qml:19-21`). There, only the icon separates them,
  and that is accepted.
- **Dimmed** means reduced opacity on the whole row's status icon and info
  text, not only a muted colour, which can fall back to `foreground`.
- **Selected row:** in every group, the icon and info text stay visible on the
  selected row's background.
- Stages and pipelines keep their existing status rules (`stageStatus`), and
  show the result with this same mapping.
- The colours follow the current Omarchy theme, so they change with it.
- Tests cover every status in the table: its icon and its colour.

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
   icons as the main signal. As the table says, colour is a bonus, not a
   guarantee.
2. **Allowed-failure text:** should the info column say "allowed to fail", or
   show only the icon? I recommend the text, with the duration kept after it.
   It costs a few characters and removes the doubt.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It confirmed
the problems and agreed with both recommendations. Its findings, which I
checked in the code and folded in above:
- the table left out `scheduled`, `waiting_for_callback`, `canceling`,
  "awaiting final status", "unavailable", and the repo and loading-row
  statuses;
- option (a) cannot guarantee that running and success differ in colour, so
  icons are now the guarantee;
- "indistinguishable" overstated the problem, because the info column
  prints the status word;
- one line reference was wrong, and the stage claim was too broad.
