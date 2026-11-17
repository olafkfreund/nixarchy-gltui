---
status: approved
issue: 25
intent: intent/2026-11-17-25-status-colours.md
---

# Spec: Tell pipeline and job states apart at a glance

## Design

### 1. One status → group table in `PipelinesModel.js`

A new pure function, `group(status)`, returns one of the intent's eleven
groups. `icon(status)` (`PipelinesModel.js:19-26`) becomes a lookup on that
group. QML picks colour and opacity from the group, so there is one table and
no second list of status names in QML.

| Group | Statuses | Icon | Colour (shell palette) | Opacity |
|---|---|---|---|---|
| `running` | `running`, `canceling` | `●` | `menu.text` | 1 |
| `success` | `success` | `✓` | `accent` | 1 |
| `failed` | `failed`, `error`, `unavailable` | `✕` | `urgent` | 1 |
| `allowed` | `allowed to fail` | `!` | `urgent` | 0.6 |
| `manual` | `manual` | `▶` | `accent` | 1 |
| `scheduled` | `scheduled` | `◷` | `menu.text` | 1 |
| `queued` | `created`, `pending`, `waiting_for_resource`, `preparing`, `waiting_for_callback`, `queued`, `awaiting final status` | `◌` | `menu.text` | 1 |
| `skipped` | `skipped` | `−` | `muted` | 0.5 |
| `canceled` | `canceled` | `⊘` | `menu.text` | 1 |
| `neutral` | `neutral` | `·` | `menu.text` | 1 |
| `unknown` | anything else | `○` | `menu.text` | 1 |

**Icon choices:**
- **Neutral repo rows change from `−` to `·`.** The approved intent says both
  "neutral: unchanged" and "every group has a different icon", and with
  skipped keeping `−` those two conflict. The icon guarantee is the stronger
  requirement, so the neutral (idle) repo row gets a middle dot. This is the
  one place the spec departs from the intent's table, and it needs the
  owner's OK at spec approval.
- `◷` moves from running to scheduled, where a clock fits.
- Running gets `●`, solid for "active now".
- Queued gets `◌`, a dotted, empty circle for "not started".

I checked every glyph in the table against the panel's fonts:
`fc-list :charset=<code>` finds each one in the installed JetBrains Mono and
FiraCode Nerd fonts. `⏱` and `⏲` are not in them, so they are not used.

**Colours:** these follow approved option (a), the shell palette only.
- `accent` marks "good" (`success`) and "your turn" (`manual`).
- `urgent` marks failure.
- The allowed failure is `urgent` at 0.6 opacity, so it is weaker than a
  blocking failure. It also has its own icon, `!`.
- In themes where `accent` equals `menu.text`, running and success still
  differ by icon (`●` against `✓`), as the intent accepts.

### 2. Allowed failures reach the row

In `rows()` (`PipelinesModel.js:111-114`), a job whose `conclusion` is
`failed` and whose `allow_failure` is true gets the status
`"allowed to fail"` instead of `state(job)`. Other jobs are unchanged.

The info column already shows `status + " · " + info`
(`PipelinesPanel.qml:468`). So the row reads "allowed to fail · 1m 2s",
which keeps the duration as the intent requires. `gitlab.py` already sends
`allow_failure` (`gitlab.py:161`).

Stage and pipeline statuses keep their rules (`stageStatus`,
`PipelinesModel.js:33-40`). They only get the new icons and colours.

### 3. QML uses the group

- `statusColor(status)` (`PipelinesPanel.qml:225-229`) becomes a switch on
  `Model.group(status)` that returns the colour column above.
- A new `statusOpacity(status)` returns the opacity column.
- In the row delegate, the status icon (`statusIcon`) and the info `Text` bind
  `opacity: root.statusOpacity(modelData.status)`.
- The title and subtitle are not dimmed, so the name stays readable.
- The selected-row colours (`menu.selectedText` for the title) do not change.
  The status icon and info keep their group colour on the selected
  background, `menu.selectedBackground`.
- **What "readable" means here:** the selected background is themeable
  (`Commons/Color.qml:105`, foreground at 8% alpha by default). So the
  guarantee is limited to this: no group's icon or info goes below 0.5
  opacity, and selection never changes a row's status colour or opacity.
  Contrast against a user's custom selected background is the theme's
  responsibility, as it is for every other text in the panel.

## Alternatives rejected

- **Read `green` and `yellow` from the theme's `colors.toml`:** rejected in
  the intent (option b).
- **Keep `◷` for running and use `◴` for scheduled:** the two quarter-clock
  glyphs look nearly the same at caption size.
- **Hard-code hex colours:** breaks themes, and the intent rules it out.
- **A separate `allow_failure` row field, so the status stays `failed`:** the
  info column would still print "failed", and QML would need two inputs per
  row. A distinct status string keeps one input, and the info word is right.
- **Dim the whole skipped row:** the job name gets harder to read, and that
  name is what you scan for.

## Risks

- **Habit:** running changes from `◷` to `●`. This is a one-time visual
  change, mentioned in the README and the release notes.
- **Glyph width:** `●`, `◌` and `▶` can be wider than `✓` in some fonts. The
  icon `Text` has a fixed width (`root.zs(Style.space(18))`), so a wide glyph
  can overflow but cannot move the columns. This gets checked in a microVM
  screenshot.
- **Search:** job status words are not searched (only run states are,
  `PipelinesModel.js:73`), so "allowed to fail" changes nothing there.
- **Hosts:** a panel-only change. It ships through the usual chain to p620 and
  razer, and p510 stays on 1.0.0.

## Verification

- `node tests/model.cjs`:
  - every status in the table maps to its group and icon;
  - an unlisted status (`"frobnicated"`) is `unknown` / `○`;
  - all eleven groups have different icons;
  - `rows()` gives an allowed-failure job the status `allowed to fail`, and
    its info is still the duration;
  - a blocking failed job stays `failed`;
  - a stage whose only failure is allowed is still `success`.
  - Existing assertions that change:
    - `tests/model.cjs:45` (the allowed-failure job row "stays failed") now
      expects `allowed to fail`;
    - the old icon expectations at `tests/model.cjs:55-59` are replaced by
      the table above.
- `node tests/polling.cjs` and `python3 -m unittest discover -s tests`: pass,
  unchanged.
- `tests/qml-smoke.py`, run in the `nixarchy-desktop` microVM only:
  - **Colour and opacity per group:** `panel.statusColor(s)` and
    `panel.statusOpacity(s)` match the table, compared with `Qt.colorEqual`
    against `Commons.Color.*`.
  - **A real delegate:** the fake helper's job list gains one job:
    `{'id':10,'name':'lint','stage':'test','status':'completed','conclusion':'failed','allow_failure':True}`.
    That keeps the two-stage count the existing check expects
    (`tests/qml-smoke.py:453`). The "jobs arrive" check
    (`tests/qml-smoke.py:452`) changes from 2 to 3. The job gets
    `started_at` and `completed_at`, so its duration shows. The steps:
    1. Add `"one/sub/repo:7:stage:test": true` to the existing expansion map
       (`tests/qml-smoke.py:438-440`) and rebuild.
    2. Find the `lint` row and move the cursor onto it, which selects it and
       scrolls it into view.
    3. Wait for its delegate.
    4. Check that the row's status is `allowed to fail`, its info contains a
       duration, and the delegate's status icon text is `!`.
    5. Check that the icon's `color` and `opacity`, and the info's, equal
       `statusColor` / `statusOpacity` for that status while the row is
       selected.
  - **Selected rows of every group:** a fixture stage has one row per group:
    repo rows for `neutral` and `error`, and run rows for every other group.
    It moves the cursor onto each row in turn. On each selected row, the
    delegate's icon and info `color` / `opacity` must match
    `statusColor` / `statusOpacity`, and the opacity must be at least 0.5.
- **Manual, in the microVM:** a screenshot of the panel with a fixture holding
  one row per group, to check the glyphs and columns by eye.
