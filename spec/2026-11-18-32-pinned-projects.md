---
status: approved
issue: 32
intent: intent/2026-11-18-32-pinned-projects.md
---

# Spec: Pin projects so they are checked first

## Design

Five parts: the scheduler (`Polling.js`), the model (`PipelinesModel.js`),
the state file helper (`gitlab.py`), the panel (`PipelinesPanel.qml`), and
the docs. Pins are project paths. They are applied by name, so a pin for a
project not yet discovered takes effect when the project appears.

### 1. Scheduler: a `pinned` group (`Polling.js`)

- **State:** `create()` gains `pinned:{}`, a map of project path to `true`.
  `resetHost()` starts from `create()`, so a host change clears it; the
  panel sets the new host's pins (part 4).
- **New writer:** `pin(s, names)`. Like every exported writer, it sets
  `s.wakeAt=0`.
  - It sets `s.pinned` to a map of `names`.
  - While `!s.catalogueComplete`, it appends `{repo:name}` for each name not
    in `s.repos`. Config and key pins are then checked before discovery
    reaches them. A finished catalogue stays the source of truth: its
    existing cleanup (`complete()`, the `gone` filter) drops a pinned path
    the account cannot see, as it does today for `projects`.
- **Orphan tasks:** `seed()`'s first loop also deletes a task whose `repo`
  is set but no longer in `s.repos`, unless it is in flight. Today the
  catalogue cleanup drops the project but leaves its queued tasks
  (`Polling.js:257-259`), and a failing one keeps retrying. This matters
  more once several pins are seeded, and also fixes it for `projects`.
- **`seed()`:** the activity interval and group for an unselected project
  (`Polling.js:89-90`) become:

  | Project            | Interval  | Group        |
  | ------------------ | --------- | ------------ |
  | selected           | 10 s      | `interactive`|
  | running (`active>0`), pinned or not | 15 s | `active` |
  | idle and pinned    | **60 s**  | **`pinned`** |
  | idle, not pinned   | 10 min    | `background` |

  Only `background` tasks are limited to one queued at a time
  (`backgroundQueued`), so idle pins no longer wait behind it. The selected
  project's summary still replaces its activity check (`Polling.js:85`), so
  a selected pin is never checked twice.
- **`next()`:** the slot rotation stays
  `["interactive","interactive","interactive","active","background"]`.
  - The `active` slot takes an `active` task first, else a `pinned` one.
  - The fallback order, used when the slot's own group has nothing due,
    becomes `interactive`, `active`, `pinned`, `background`.
  - So running projects go before idle pins when both are due. The
    `background` slot still serves discovery and unpinned projects once
    every five starts. Only idle pins slow down under a saturated
    schedule.
  - **Accepted limit:** if interactive and running tasks are due at every
    start, no slot reaches `pinned`, and idle pins wait until one frees up.
    That follows the approved precedence: it needs the selection plus more
    than about three running projects at once, and it lasts only while
    they keep running. The README states it, and a test pins it.
- **Open and reopen:** nothing new. `close()` clears tasks but keeps each
  project's `activityAt`, so on reopen a pin is due only if its last check
  is 60 s old or more. A pin that was never checked is due at once.

### 2. Model (`PipelinesModel.js`)

- **`validProject(name)`:** the project path check that `configure()` has
  inline today (`PipelinesPanel.qml:242`), moved here so `projects`,
  config pins and saved pins share it. `configure()` calls it.
- **`pins(config, saved)`:** returns `{names, config}`.
  - `names`: the union of `config` then `saved`, keeping only strings that
    pass `validProject`, without duplicates, cut to the first 10.
  - `config`: a map of the valid config pins.
  - Non-array input counts as `[]`.
- **`togglePin(repo, config, saved)`:** returns `{saved, notice}`. `saved`
  is the new saved list, or `null` for no change.
  - In the config map: no change, notice `Pinned in shell.json`.
  - Among the applied `names`: removed from `saved`, notice
    `Unpinned <repo>`.
  - Otherwise, if 10 names apply: no change, notice `At most 10 pins`.
    This also covers a saved pin that the cap keeps inactive.
  - Otherwise: appended to `saved` (moved to the end if it was there),
    notice `Pinned <repo>`.
- **`rows(repos, expanded, details, filter, now, pinned)`:** a new last
  argument, a map; missing means none.
  - The sort becomes pinned before unpinned, then running count. The
    existing tie order is kept, as today.
  - Project rows gain `pinned: true|false`, and `pinned` joins
    `shownFields` so a toggle updates the row in place.
  - Search is unchanged: `repoMatches` reads only the path and
    description, so `★` never matches.

### 3. State file (`gitlab.py pins`)

The helper gains a second mode, `pins`, taking one JSON argument as
`page` does.

- **Path:** `$XDG_STATE_HOME/omarchy-gitlab-pipelines/pinned.json`. When
  `XDG_STATE_HOME` is unset, empty or not absolute, `~/.local/state` is
  used (the XDG rule).
- **Format:** `{"version": 1, "hosts": {"gitlab.com": ["group/project"]}}`.
  The host key is the configured host in lower case, port kept.
- **Load:** `{"host": "<host>"}` prints `{"pins": [...]}` with that host's
  list, filtered with `project_path`.
  - An absent file prints `{"pins": []}`.
  - An unreadable file prints `{"error": "Cannot read pinned.json"}`.
  - A file that is not valid JSON or not the format above prints
    `{"error": "pinned.json is not valid"}`.
  - Exit code 0 on success, 1 on an error.
- **Save:** `{"host": "<host>", "save": [...]}` replaces that host's list.
  - It reads the file first and keeps every other host's list.
  - If the read gives an error, it does not write, and prints the same
    error as load. The panel then says `Pins not saved: <error>`. The user
    keeps the file, and can fix or remove it.
  - It validates `save` with `project_path` and caps nothing: the panel
    owns the cap, and saved pins beyond it stay inactive.
  - It creates the directory (mode 0700, checked by a test), writes a temporary file in the
    same directory, and renames it over the old file (`os.replace`), so a
    crash never leaves a partial file. The file is mode 0600.
  - Success prints `{"pins": [...]}`, the list as written.
- A bad host or a bad `save` list gives `{"error": ...}` and exit 1, with
  nothing written.
- No lock: one panel per session writes the file, and the panel never runs
  two saves at once (part 4).

### 4. Panel (`PipelinesPanel.qml`)

- **New properties:** `configPins` (from `shell.json`), `savedPins` (from
  the state file), `pinsLoaded`, and `pinned` (the `names` map from
  `Model.pins`).
- **Order at start:** pins are applied only once the panel is
  `configured`. `applyPins()` returns early before that, and
  `markConfigured()` calls it. So `configure()` seeds `projects` first
  (its `!polling.repos.length` guard, `PipelinesPanel.qml:240`), and
  `pin()` then adds only the pins not already there. A state load that
  finishes first just stores `savedPins`.
- **Config:** `configure()` reads `entry.pinned` like `projects`. A
  `pinned` value that is not an array counts as `[]`. If `shell.json` lists
  more than 10 valid pins, it logs one `console.warn`. It then calls
  `applyPins()`.
- **Load:** a `pinsLoad` Process runs `gitlab.py pins {"host":…}` at start
  and after every host change.
  - A host change first clears `savedPins` and `pinsLoaded`, then loads.
  - Each load remembers its host. A result for a host other than the
    current one is ignored, and the current host is loaded again.
  - On success it sets `savedPins` and `pinsLoaded`. On an error it sets
    `pinsLoaded`, keeps `savedPins` empty, and shows the error in the
    footer notice when the panel opens.
- **`applyPins()`:** computes `Model.pins(configPins, savedPins)`, calls
  `Polling.pin(polling, names)`, then `adopt()` so the list re-sorts.
- **The `p` key:** a `plain` (no Ctrl, Alt or Meta), unshifted `p` in the
  list.
  - Before `pinsLoaded`, it shows `Pins are still loading` and does
    nothing else.
  - Otherwise it calls `Model.togglePin(current.repo, …)` and shows the
    notice. If `saved` is not `null`, it updates `savedPins`, calls
    `applyPins()`, and saves.
  - It works on any row inside a project: run, stage, job and "more" rows
    all carry `repo`.
  - The cursor stays on the same row key after the re-sort, as for any
    rebuild.
- **Save:** a `pinsSave` Process, one save at a time.
  - Each save carries its host and list. While one runs, later saves wait
    in a queue keyed by host, keeping only the latest list per host. When
    a save exits, the next queued host is saved. A host change therefore
    never drops another host's pending pins or saves them under the wrong
    host.
  - A failed save (exit 1 or bad output) shows `Pins not saved: <error>`.
    The pin stays applied for the session.
- **Failed start:** in Quickshell 0.3.1 a process that cannot start emits
  neither `started` nor `exited` (`PipelinesPanel.qml:381`). Both new
  Processes use the same `started` flag and `onRunningChanged` check as
  `requestProc`. A failed load then counts as a load error, and a failed
  save as a save error, so `pinsLoaded` never stays false.
- **Display:** a project row with `pinned` shows `★ ` after the expand
  arrow and before the path, in the title's colour, for example
  `▸ ★ group/project`.
- **Text:** the header's `running first` becomes `pinned and running
  first`. `listHint` gains `p pin`, after `y/Y copy`.

### 5. Docs

- **`README.md`:**
  - "Projects" and "Self-managed GitLab and settings" (`:123-147`) gain `pinned` in the example and
    a sentence on it;
  - a new "Pinned projects" section covers the `p` key, the state file and
    its path, the cap and which 10 apply, `Pinned in shell.json`, and that a
    pin needs the project to be visible to the account;
  - the "Refresh and errors" table (`:241-266`) gains the row "idle pinned project:
    about every 60 s", the running row notes that it includes pins, and
    one sentence states the accepted limit under a busy schedule;
  - the "Keyboard" table (`:165-`) gains `p`.
- **`keybindings.sh`:** `p` pins or unpins the selected project.

## Alternatives rejected

- **Pins in the `active` group with a sort rank:** the same order, but a
  separate group keeps "running before idle pins" visible in the slot
  rule, and keeps the ranking out of `next()`'s due sort.
- **A sixth slot for pins:** it would take starts from the selection or
  from discovery. Sharing the `active` slot and the fallbacks takes them
  only from idle time.
- **Writing pins with Quickshell's `FileView`:** it cannot tell an absent
  file from an unreadable one in the way the rules need, and its directory
  handling is unknown here. A Python helper is testable with `unittest`,
  and `gitlab.py` already ships and runs from the panel.
- **A separate `pins.py`:** a new runtime file for the flake's
  `runtimeFiles`, for two small functions.
- **Writing `shell.json`:** ruled out in the intent.
- **Overwriting an invalid state file:** it would lose the pins in it.
  The save refuses and names the problem instead.

## Risks

- **Budget:** at most 10 extra activity checks a minute, inside the
  existing 60-a-minute limit. The `polling.cjs` tests pin the rotation, so
  a change that starves discovery fails them.
- **Re-sorting on toggle:** the pinned row moves to the top. The cursor
  follows the row key, as on any rebuild.
- **Pins not visible to the account:** dropped from the list when discovery
  finishes. They still count towards the cap. The README says so.
- **Hosts:** p620 and razer get it through the usual chain. Nothing is
  written outside the state directory. p510 stays on its current version.

## Verification

- **`tests/polling.cjs`:**
  - an idle pin is due 60 s after its last check, and an idle unpinned
    project after 10 min;
  - two idle pins are both queued, while unpinned idle projects stay one at
    a time;
  - when a running project and an idle pin are both due, the running one
    goes first;
  - a saturated schedule with 10 pins, a running project and discovery
    still starts a `background` task once every five starts;
  - a selected pin gets its summary and no activity check;
  - `pin()` seeds unknown pins before the catalogue completes, and does not
    after it;
  - reopening within 60 s of a pin's check does not queue it;
  - a catalogue that omits a seeded pin removes its queued activity task,
    including one in retry after a network error;
  - with interactive and running tasks due at every start, idle pins wait
    (the accepted limit), and they start as soon as the active slot is
    free.
- **`tests/model.cjs`:** `validProject`; `pins()` order, duplicates, invalid
  entries and the cap; `togglePin()` for every branch, including a saved
  pin beyond the cap; `rows()` puts pinned first, keeps tie order, sets
  `pinned`, and `★` search finds nothing.
- **`tests/test_gitlab.py`:** load of an absent, valid, unreadable and
  invalid file; save keeps other hosts, lower-cases the host, writes mode
  0600 atomically (a failing `os.replace` leaves the old file), refuses an
  unreadable or invalid file, and rejects a bad host or list; the
  `XDG_STATE_HOME` fallback.
- **`tests/qml-smoke.py`, in the microVM only:**
  - the harness sets `XDG_STATE_HOME` inside its temporary directory, so
    the VM user's own state is never touched;
  - the fake `gitlab.py` passes `pins` requests to the real helper's
    `pins` code and keeps the API calls fake;
  - a state load that finishes before `shell.json` still keeps the
    `projects` seeds, and the reverse order gives the same list;
  - a delayed load for host A that finishes after a switch to host B does
    not change B's pins, and a host change during a running save saves
    both hosts' lists under the right host;
  - a missing `python3` for the pins processes ends with
    `pinsLoaded` true and a save-failure notice;
  - with `pinned` in `shell.json` and a saved pin in the state file, both
    rows sort first with `★`;
  - `p` pins a row, which moves to the top, and the state file holds it;
    `p` again unpins it;
  - `p` on a config pin shows `Pinned in shell.json`;
  - `p` at the cap shows `At most 10 pins`;
  - an unwritable state directory shows `Pins not saved: …`;
  - the footer hint and the help text include `p`.
- **Mutation checks in the VM:** removing the `pinned` group from the
  `active` slot, or the sort change, makes a test fail.
- All existing tests pass, and the flake's `plugin` and `menu-verbs` checks
  build.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
confirmed the scheduler keeps the request limit, spacing and single
flight, the cap and toggle rules, `shownFields`, the search, the state
file design and the line references. Its findings, which I checked in the
code and folded in above:
- a host change could apply a late load to the wrong host, or lose or
  misfile a pending save: loads are now tagged by host, and saves queue
  per host;
- catalogue cleanup leaves queued tasks of removed projects
  (`Polling.js:257-259`, the `seed()` loop at `:68-76`): `seed()` now
  deletes them;
- a state load before `shell.json` could make `configure()` skip the
  `projects` seeds: pins apply only once configured;
- idle pins can wait indefinitely while interactive and running tasks are
  always due: accepted under the approved precedence, documented and
  tested;
- the smoke fake `gitlab.py` reads `request['kind']` (`tests/qml-smoke.py:25`)
  and the harness inherits `XDG_STATE_HOME`: the fake now passes `pins` to
  the real code, and the harness isolates the state directory;
- a failed process start emits no `exited` (`PipelinesPanel.qml:381`):
  both new Processes handle it as `requestProc` does.
