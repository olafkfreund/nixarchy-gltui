---
status: draft
issue: 32
author: olafkfreund
---

# Intent: Pin projects so they are checked first

## Problem

On an account with many projects, the panel checks idle projects only
about every 10 minutes (`Polling.js`, `seed()`, the `600000` interval;
README "Refresh and errors"). It also takes one idle project at a time in
the background queue. The few projects the user cares about wait in that
same rotation:

- **A pipeline can start unseen.** A pipeline started in a favourite
  project shows only when that project's turn comes, up to about 10
  minutes later, unless the user selects it.
- **The list order ignores them.** Rows are ordered by running-pipeline
  count only (`PipelinesModel.js:181`). A favourite idle project sits
  anywhere among hundreds.
- **There is no way to mark a project as important,** either in config or
  from the keyboard.

## Proposed outcome

- **Pinned projects sort first** in the list: pinned before unpinned. Within
  each part, today's order applies (running count, then the catalogue's
  order). A small pin mark, `★`, on the project row shows it is pinned.
- **Pinned projects are polled ahead of the background rotation:**
  - An idle pinned project's activity is checked every 60 seconds, not
    every 10 minutes.
  - It is checked as soon as the panel opens, before unpinned idle
    projects.
  - It does not wait behind the one-at-a-time background queue.
  - A pinned project with running pipelines keeps today's 15-second
    cadence. A selected project keeps its own, faster rules.
- **The request budget stays as it is:** 60 pages a minute, one request in
  flight, and one second between starts.
  - The number of pins is capped at 10. Their extra load is then at most
    10 activity checks a minute, about a sixth of the budget.
  - Pinning an 11th project shows a notice, and does not pin.
- **`p` pins or unpins the selected project** (on a project row, or any
  row inside it). It confirms in the footer notice (#29), for example
  `Pinned group/project`.
- **Pins persist** across panel reopen and shell restart.
- **Two sources, both applied:**
  - **Config:** a `pinned` list in the plugin's `shell.json` entry, next to
    `host` and `projects`, for declarative setups.
  - **Key:** pins made with `p` are stored by the panel in its own state
    file, one list per host, under `~/.local/state/`. The panel never
    writes `shell.json`.
  - A project pinned in `shell.json` cannot be unpinned with `p`. The
    notice says `Pinned in shell.json`.
- **Bad entries are ignored:** invalid project paths in either source are
  skipped, using the same path check as `projects` (`PipelinesPanel.qml`,
  `configure()`).
- **The README** documents the `pinned` setting, the `p` key, the state
  file, the cap and the new refresh row. The key list (`keybindings.sh`)
  and footer help gain `p`.

## Affected users and systems

- **Files:**
  - `Polling.js`: the pinned interval, group and order;
  - `PipelinesModel.js`: the sort and the pin mark;
  - `PipelinesPanel.qml`: the `p` key, state-file load and save, and the
    config `pinned` setting;
  - `README.md` and `keybindings.sh`;
  - the tests: `tests/polling.cjs`, `tests/model.cjs` and
    `tests/qml-smoke.py`.
- **A new file:** the state file under `~/.local/state/`. It holds only
  project paths, per host, and no secrets.
- **Hosts:** it ships through the usual chain to p620 and razer. p510
  stays on its current version.

## Constraints

- No new GitLab endpoints, and no request beyond the existing budget rules.
  Pins only change when, and in which group, the existing activity check
  runs.
- `Polling.js` stays pure and testable without Qt. Pins are passed in as
  data, not read from files.
- The panel must not write `shell.json`. The shell and Home Manager own it
  (README: `menu.managed`, the Nix notes).
- The state-file write must not lose pins: write a whole file atomically,
  and ignore a corrupt or missing file, which means no key-made pins.
- Pinning works for projects not yet discovered: a config pin for a path
  still in discovery is applied when the project appears.
- Smoke tests run in the microVM only, never on the host desktop.

## Open questions

1. **Key:** I recommend `p`. It is free (#29 took `?`, `y`, `g`, `q`,
   `e`), and it reads as "pin".
2. **Interval:** I recommend 60 seconds for idle pinned projects. That is
   six times as often as the 10 minutes in the issue, and well inside the
   budget at 10 pins.
3. **Cap:** I recommend 10 pins in total across both sources. If
   `shell.json` alone lists more, the first 10 apply and the rest are
   ignored, with one console warning.
4. **Where key-made pins live:** I recommend a state file, for example
   `~/.local/state/omarchy-gitlab-pipelines/pinned.json`, keyed by host.
   The alternative, writing `shell.json`, would race with the shell's own
   writes and break Home-Manager-managed files.
5. **Pin mark:** I recommend `★` before the project name, in the title's
   colour. A filled star is a common "favourite" sign, and the font set
   already renders the status glyphs from #25. It is display only: search
   does not match `★`.
