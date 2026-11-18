---
status: approved
issue: 32
spec: spec/2026-11-18-32-pinned-projects.md
coders:
  1: codex   # small tricky scheduler logic (groups, slots, orphan cleanup) with simulation tests
  2: codex   # pure model rules with exact edge cases (cap, union, toggle branches) and Node tests
  3: codex   # file-safety code (atomic write, refusal rules, modes) with unittest
  4: coder   # QML wiring following the existing Process/notify/key patterns
  5: coder   # README, keybindings.sh and version bump, tied to steps 1-4 wording
  6: coder   # smoke-test stages, following the existing esteps pattern
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Pin projects so they are checked first

Self-contained. Branch `feat/32-pinned-projects`, based on `b91ba77`
(main after #31; v1.6.0 code). Line numbers are for that commit; match on
the quoted code.

## Approved decisions (from the spec)

### Scheduler (`Polling.js`)

- `create()` gains `pinned:{}`. `resetHost()` is unchanged: it starts from
  `create()`, so a host change clears the pins until the panel sets them.
- **New exported writer `pin(s, names)`:**
  - `s.wakeAt=0`;
  - `s.pinned` = a new map, `name → true`, for each entry in `names`;
  - if `!s.catalogueComplete`: for each name with no `repoFor(s,name)`,
    push `{repo:name}` onto `s.repos`. After the catalogue is complete,
    nothing is added.
- **`seed()`, first loop** (`Polling.js:68-76`, the one that skips the
  flight): after the `blocked` check, also delete a task with a non-empty
  `t.repo` whose `repoFor(s,t.repo)` is missing. Catalogue tasks have
  `repo:""` and are kept.
- **`seed()`, interval and group** (`Polling.js:89-90`):

  ```js
  var pinned = !selected && !(r.active > 0) && !!s.pinned[r.repo];
  var interval = selected ? 10000 : r.active > 0 ? 15000 : pinned ? 60000 : 600000;
  var group = selected ? "interactive" : r.active > 0 ? "active" : pinned ? "pinned" : "background";
  ```

  The `backgroundQueued` rule stays for `group==="background"` only.
- **`next()`** (`Polling.js:123-128`): the rotation array stays. Replace
  the pick with:

  ```js
  var group = ["interactive","interactive","interactive","active","background"][s.slot % 5];
  var order = group === "active" ? ["active","pinned"] : [group];
  var t;
  order.concat(["interactive","active","pinned","background"]).some(function(g) {
      t = due.filter(function(x) { return x.group === g })[0]; return !!t });
  ```

  The `due` sort (due, then order) is unchanged.
- **Accepted limit:** while interactive and running tasks are due at every
  start, `pinned` gets no start. Tested, not fixed.

### Model (`PipelinesModel.js`)

- `validProject(name)`: `typeof name === "string"` and
  `/^[A-Za-z0-9_.][A-Za-z0-9_.-]*(\/[A-Za-z0-9_.][A-Za-z0-9_.-]*)+$/`
  and not `/(^|\/)\.\.?(\/|$)/`. This is the check at
  `PipelinesPanel.qml:242`; that line then uses `Model.validProject`.
- `pins(config, saved)` → `{names, config}`:
  - a non-array argument counts as `[]`;
  - `names`: `config` then `saved`, valid entries only, first occurrence
    kept, cut to 10;
  - `config`: map of the valid config entries (all of them, even past 10).
- `togglePin(repo, config, saved)` → `{saved, notice}`, `saved` a new array
  or `null`. With `p = pins(config, saved)`:
  1. `p.config[repo]` → `{null, "Pinned in shell.json"}`;
  2. `repo` in `p.names` → `saved` without `repo`,
     `"Unpinned " + repo`;
  3. `p.names.length >= 10` → `{null, "At most 10 pins"}`;
  4. else → `saved` without `repo`, then `repo` appended,
     `"Pinned " + repo`.

  Non-array `saved` counts as `[]`.
- `rows(repos, expanded, details, filter, now, pinned)`:
  - `pinned` missing → `{}`;
  - sort: `(!!pinned[b.repo]) - (!!pinned[a.repo]) || (b.active||0) - (a.active||0)`;
  - the repo row gains `pinned: !!pinned[repo.repo]`;
  - `shownFields` gains `"pinned"`.

### State file (`gitlab.py`)

- `state_path()`: `base = os.environ.get("XDG_STATE_HOME", "")`; if not
  `os.path.isabs(base)`, `base = os.path.expanduser("~/.local/state")`.
  Returns `Path(base) / "omarchy-gitlab-pipelines" / "pinned.json"`.
- `read_state(path)` → `{"version": 1, "hosts": {...}}`:
  - `FileNotFoundError` → `{"version": 1, "hosts": {}}`;
  - other `OSError` → `ValueError("Cannot read pinned.json")`;
  - not JSON, not a dict, `version != 1`, `hosts` not a dict, or a host's
    value not a list → `ValueError("pinned.json is not valid")`.
- `pins(task)`:
  - `task` must be a dict; `host = host_name(task.get("host")).lower()`;
  - **load** (no `"save"` key): `read_state`, return
    `{"pins": [n for n in hosts.get(host, []) if valid]}`, valid meaning
    `project_path` does not raise;
  - **save**: `task["save"]` must be a list of strings that each pass
    `project_path`, else `ValueError("Invalid pins")`. Duplicates are
    dropped, order kept. Then `read_state` (an error stops here, nothing
    written), set `hosts[host]`, and write:
    - `path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)`;
    - `tempfile.mkstemp(dir=path.parent, prefix=".pinned-", suffix=".json")`,
      `os.fchmod(fd, 0o600)`, write `json.dumps(state, indent=2)`, flush,
      `os.fsync`, close, `os.replace(tmp, path)`;
    - on any exception, unlink the temp file if it exists, and raise
      `ValueError("Cannot write pinned.json")` for an `OSError`;
    - return `{"pins": list}`.
- `main()`: `choices=("page","pins")`. For `pins`: no alarm, no signal
  handlers needed; `print(json.dumps(pins(json.loads(args.request))))`
  and return 0; on `ValueError` (JSON errors included) print
  `{"error": str(exc)}` and return 1. The `page` path is unchanged.
- No lock (one panel per session, one save at a time).

### Panel (`PipelinesPanel.qml`)

- **Properties:** `configPins: []`, `savedPins: []`, `pinsLoaded: false`,
  `pinsError: ""`, `pinned: ({})`, `pinsLoadHost: ""`,
  `pinsLoadStarted: false`, `pinsQueue: ({})` (host → list),
  `pinsSaveStarted: false`, `sessionPins: ({})` (host → the latest list
  set with `p` in this session), and `pinsCommand: ["python3"]`, the
  launcher prefix for both pin Processes (a test hook, like
  `copyCommand`).
- **`configure(text)`:**
  - in the host-change branch (`configuredHost !== host`), also set
    `savedPins = []` and `pinsLoaded = false`;
  - the `projects` filter uses `Model.validProject`;
  - read `configPins = entry && Array.isArray(entry.pinned) ? entry.pinned : []`;
    if more than 10 pass `validProject`,
    `console.warn("GitLab Pipelines: only the first 10 pins apply")`;
  - after `host = configuredHost`, if the host changed, call `loadPins()`;
  - at the end of the `try`, call `applyPins()`. `markConfigured()` stays
    last.
- **`markConfigured()`:** after `configured = true`, call `applyPins()`.
- **`applyPins()`:** return if `!configured`. Else
  `var p = Model.pins(configPins, savedPins)`; set `pinned` to a map of
  `p.names` (`name → true`); `Polling.pin(polling, p.names)`; `adopt()`.
- **`rebuild()`:** pass `pinned` as the new last argument of `Model.rows`.
- **`loadPins()`:** if `pinsLoad.running`, return (its exit handler
  reloads). Else set `pinsLoadHost = host`, `pinsLoadStarted = false`,
  command `pinsCommand.concat([helper, "pins", JSON.stringify({host: host})])`,
  `running = true`. `Component.onCompleted` calls it once.
- **`pinsLoad` Process:** stdout `StdioCollector`.
  - `onStarted: root.pinsLoadStarted = true`;
  - `onExited: function(code) { root.finishPinsLoad(code, output.text) }`;
  - `onRunningChanged: if (!running && !root.pinsLoadStarted) root.finishPinsLoad(127, "")`;
  - `finishPinsLoad(code, text)`:
    - if `pinsLoadHost !== host`: `loadPins()` and return;
    - parse `text` inside `try`; success needs `code === 0` and
      `Array.isArray(reply.pins)`; then `savedPins = reply.pins`;
    - in every case, if `sessionPins[host]` is set, `savedPins` is that
      list instead: this session's own edits win over the file, so a
      return to a host whose save is still pending or running never
      reloads older pins;
    - else `savedPins = []` and
      `pinsError = "Pins not loaded: " + (reply && reply.error || "helper failed")`;
    - `pinsLoaded = true`; `applyPins()`.
  - A failed start and a later `exited` must not both finish: guard with
    `pinsLoadStarted`, as `requestProc` does.
- **`open()`:** after `applyOpen`/queue, `if (pinsError) { notify(pinsError); pinsError = "" }`.
- **`togglePin()`:**
  - `if (!current) return`;
  - `if (!pinsLoaded) { notify("Pins are still loading"); return }`;
  - `var r = Model.togglePin(current.repo, configPins, savedPins); notify(r.notice)`;
  - if `r.saved`: `savedPins = r.saved`, `sessionPins[host] = r.saved`
    (copy the map and reassign), `applyPins(); savePins(host, r.saved)`,
    then `list.positionViewAtIndex(cursor, ListView.Contain)` so the moved
    row stays visible.
- **`savePins(h, names)`:** `pinsQueue[h] = names` (copy the map and
  reassign); `nextSave()`.
- **`nextSave()`:** if `pinsSave.running`, return. Take the first key of
  `pinsQueue`, remove it, set `pinsSaveStarted = false`, command
  `pinsCommand.concat([helper, "pins", JSON.stringify({host: h, save: names})])`,
  `running = true`.
- **`pinsSave` Process:** same started/failed-start pattern. On finish:
  success needs exit 0 and `Array.isArray(reply.pins)`; else
  `notify("Pins not saved: " + (reply && reply.error || "helper failed"))`.
  Then `nextSave()`.
- **Key:** in the `plain` chain, after the `e` branch:
  `else if (plain && event.key === Qt.Key_P && !shift) root.togglePin()`.
- **Delegate title:** after the arrow,
  `(modelData.kind === "repo" && modelData.pinned ? "★ " : "")`.
- **Text:** header `" · running first · "` → `" · pinned and running first · "`;
  `listHint` inserts `p pin  ` after `y/Y copy  `.

### Docs

- **`README.md`:**
  - "Self-managed GitLab and settings" (`:131-147`): the JSON example gains
    `"pinned": ["group/project"]`, and the sentence about `projects` gains
    one on `pinned` (pinned projects sort first and are checked about every
    minute; see Pinned projects);
  - new section "Pinned projects" after "Open on the current repository":
    - `p` pins or unpins the selected project (any row inside it);
    - pinned projects sort first and show `★`;
    - pins made with `p` are stored per host in
      `$XDG_STATE_HOME/omarchy-gitlab-pipelines/pinned.json` (default
      `~/.local/state/…`); the panel never writes `shell.json`;
    - `pinned` in `shell.json` also pins; those cannot be unpinned with `p`
      (`Pinned in shell.json`);
    - at most 10 apply: `shell.json` pins first, then `p` pins in the order
      made; extra saved pins stay saved and apply again when room is made;
      `p` at the cap says `At most 10 pins`;
    - a pin only shows when the account can see the project;
    - an unreadable or invalid `pinned.json` is never overwritten; the
      panel says `Pins not saved: …`; fix or delete the file;
  - "Refresh and errors" table: new row `| Idle pinned projects | 60 seconds |`
    before the 10-minute row; the running row becomes "Other projects with
    running pipelines, pinned or not";
  - the slot paragraph: the running-pipelines slot also serves idle pinned
    projects, after running ones; spare slots serve pins before background
    work; under a busy schedule (the selected project plus several running
    projects) idle pins wait;
  - "Keyboard" table: `| p | Pin or unpin the selected project |` after
    Shift + Y.
- **`keybindings.sh`:** after the Shift + Y line:
  `p → Pin or unpin the selected project`.
- **`manifest.json`:** `"version": "1.7.0"`.

## Steps

1. **`Polling.js` and `tests/polling.cjs`: the scheduler.** Per
   "Scheduler". New tests (use the existing `polling.create/open/seed/next`
   helpers in the file):
   - an idle pin is due 60 s after `activityAt`, not before; an idle
     unpinned project after 600 s;
   - two idle pins and two idle unpinned projects, all due: both pins are
     queued, only one `background` activity task is;
   - a running project (`active:1`) and an idle pin both due: the
     `active`-slot start takes the running one;
   - saturation: selection with expanded jobs always due, 10 pins, 3
     running projects, discovery on; over 100 starts, `background` gets at
     least one start in every five, and the total stays within
     60 a minute;
   - the accepted limit: with interactive and active always due, no
     `pinned` start; once active is empty, the next active-slot start is a
     pin;
   - a selected pin gets a `summary` and no `activity` task;
   - `pin()` seeds `{repo}` for unknown names while the catalogue is
     incomplete, not after; `pinned` is replaced, not merged;
   - reopen (`close` then `open`) 30 s after a pin's check does not queue
     it; 61 s after does;
   - orphan: a seeded pin with a queued activity task in retry
     (`failures:1`) is removed when a catalogue without it completes and
     `seed()` runs; a task in flight is not removed.

   Check: `node tests/polling.cjs >/dev/null && node tests/model.cjs >/dev/null`.

   Traps: ES5 in `Polling.js` (no `let`, arrows or `includes`). Every
   exported writer sets `s.wakeAt=0`. Do not change the rotation array or
   the budget code.

2. **`PipelinesModel.js` and `tests/model.cjs`: the model.** Per "Model".
   Tests:
   - `validProject`: `g/p` and `a.b/c_d-e` pass; `p`, `/g/p`, `g/../p`,
     `g/./p`, `g//p`, `g/p q`, `3` fail;
   - `pins`: config then saved order, duplicates across sources removed,
     invalid entries dropped, cap at 10 with 12 inputs, config map holds
     all valid config entries, non-arrays count as `[]`;
   - `togglePin`: each of the four branches with exact `saved` and
     `notice`; a saved pin beyond the cap (8 config + 3 saved) gives
     `At most 10 pins`; re-pinning moves to the end;
   - `rows`: pinned before unpinned, then running count; ties keep input
     order; `pinned` true/false on repo rows; missing argument works;
     filter `★` returns no rows;
   - `syncRows` updates a row whose only change is `pinned`.

   Check: as step 1.

   Traps: ES5 only. Compare `vm` objects through `JSON.stringify`
   (`tests/model.cjs:45-46`).

3. **`gitlab.py` and `tests/test_gitlab.py`: the state file.** Per "State
   file". New `PinsTest` class, each test with a temporary
   `XDG_STATE_HOME` (`patch.dict(os.environ, ...)`):
   - load: absent file → `[]`; valid file → that host's list, invalid
     entries dropped; host matched lower-case;
   - load: unreadable (chmod 000; skip if running as root) →
     `Cannot read pinned.json`; invalid JSON, `[]`, `version: 2`, a host
     value `"x"` → `pinned.json is not valid`;
   - save: keeps other hosts' lists; lower-cases `Gitlab.Example.org:8443`
     and keeps the port; removes duplicates; file mode 0600, new directory
     mode 0700;
   - save refuses an invalid or unreadable file and leaves it byte for
     byte unchanged;
   - a patched failing `os.replace` leaves the old file unchanged and no
     `.pinned-*` temp file;
   - bad host, `save` not a list, `save: ["bad"]` → `ValueError`;
   - `XDG_STATE_HOME` empty or relative → `~/.local/state/...` under a
     patched `HOME`;
   - `main()` with `pins`: prints `{"pins": [...]}` and returns 0; on error
     prints `{"error": ...}` and returns 1; invalid JSON request → error.

   Check: `python3 -m unittest discover -s tests`.

   Traps: never touch the real `~/.local/state`: every test patches
   `XDG_STATE_HOME` or `HOME`. Keep the `page` path and its alarm
   unchanged.

4. **`PipelinesPanel.qml`: the panel.** Per "Panel".

   Check: steps 1-3 checks, then the microVM smoke run (Tests). Existing
   smoke checks must pass unchanged, apart from the header and `listHint`
   strings if a check quotes them (update those, and say so).

   Traps:
   - `applyPins()` must do nothing before `configured`, so `configure()`
     seeds `projects` first (`PipelinesPanel.qml:240`).
   - Ignore a load result for another host, then reload.
   - Do not change `requestProc`, `toggle()`, the search field, or
     `configure()`'s host validation and reset beyond the lines above.
   - `p` is in the `plain` chain only: Ctrl/Alt/Meta + P must do nothing new.

5. **`README.md`, `keybindings.sh`, `manifest.json`.** Per "Docs".

   Check: the full test set, and
   `bash keybindings.sh --print | grep -c 'Pin or unpin'` prints 1.

   Traps: keep table formats; the version is `1.7.0`.

6. **`tests/qml-smoke.py`: the pin checks.**
   - **Harness:**
     - before starting `quickshell`, write
       `home/.local/state/omarchy-gitlab-pipelines/pinned.json` with
       `{"version":1,"hosts":{"gitlab.com":["zz/saved"]}}`. The startup host
       is `gitlab.com` (no `shell.json`), so the startup timer
       (`tests/qml-smoke.py:828-831`) can check, after a `waitUntil` on
       `pinsLoaded` in the first new step, that `savedPins` is
       `["zz/saved"]`: a real load from the file.
     - a shared helper at the test item's top level (next to `waitUntil`,
       `:273`):
       `function cfg(h, extra) { panel.configure(JSON.stringify({plugins:[Object.assign({id:"olafkfreund.gitlab-pipelines",host:h}, extra || {})]})) }`.
       Remove the local `cfg` in O9 (`:861`) so O9 uses the shared one
       unchanged in behaviour.
     - a delay switch for pin requests: the fake's `pins` branch sleeps
       1.5 s first when the file `root / 'pins-delay'` exists. Tests
       create and remove it with a `Process` (`touch`/`rm`); pass its path
       into QML as an environment variable `PINS_DELAY`.
     - add `'XDG_STATE_HOME': str(home / '.local/state')` to the `env` of
       the `quickshell` call (`tests/qml-smoke.py:1096`). The theme path
       already lives under `home`, so nothing else moves.
     - the fake `gitlab.py`: as its first lines, if `sys.argv[1] == 'pins'`,
       load the real helper with `importlib` from the source path (format
       the path into the fake's text with `repr`), then
       `sys.exit(real.main())`. The API fake stays as it is for `page`.
   - **New `esteps`,** inserted immediately before the final `estep` (the
     one that sets `panel.workerBusy=false` and calls `panel.close()`).
     `workerBusy` is already true there, so no API request starts.
     Synchronous checks grouped in one function; waits use `waitUntil`
     (`:273`) in their own steps.
     - **P1. Fixture:** `cfg` with `pinned:["o/gamma"]` on
       `gitlab.example.org`; repos `o/alpha` (`active:1`), `o/beta`,
       `o/gamma`, `o/delta`, all `checked`; wait until `pinsLoaded`.
     - **P2. Config pin sorts first:** `entries[0].key` is `repo:o/gamma`,
       its row text in the list starts with `▸ ★ `; `entries[1]` is
       `o/alpha` (running).
     - **P3. `p` pins:** cursor on `o/delta`, `pressKey(Qt.Key_P)`: notice
       `Pinned o/delta`, `entries[1].key` is `repo:o/delta`, cursor still
       on `o/delta`; wait until the state file
       (`XDG_STATE_HOME/omarchy-gitlab-pipelines/pinned.json`, read with a
       `FileView` or `Process` `cat`) holds `"o/delta"` under
       `gitlab.example.org`.
     - **P4. `p` unpins:** `p` again on `o/delta`: notice
       `Unpinned o/delta`; wait until the file no longer holds it.
     - **P5. Config pin:** `p` on `o/gamma`: notice `Pinned in shell.json`.
     - **P6. Cap:** `cfg` with 10 valid config pins; `p` on an unpinned
       project: `At most 10 pins`. Restore `cfg` with `["o/gamma"]`.
     - **P7. Ctrl+P:** does not change pins or notice.
     - **P8. Save failure:** make the state directory read-only
       (`Process` `chmod 500`), `p` on `o/beta`: wait for a notice starting
       `Pins not saved:`; restore `chmod 700`.
     - **P9. Distinct lists:** on `gitlab.example.org`, pin `o/beta`
       (`p`) and wait until the file holds `["o/beta"]` there. `cfg`
       `gitlab.other.org`, wait until `pinsLoaded`, set repos
       `three/repo` (checked), pin it, wait until the file holds
       `["three/repo"]` for `gitlab.other.org` and still `["o/beta"]`
       for `gitlab.example.org`.
     - **P10. Host change during a save:** create `pins-delay`. On
       `gitlab.other.org` unpin `three/repo` (save starts, delayed); at
       once `cfg` `gitlab.example.org`, wait until `pinsLoaded`, pin
       `o/delta` (queued). Remove `pins-delay`. Wait until the file holds
       `[]` for `gitlab.other.org` and `["o/beta","o/delta"]` for
       `gitlab.example.org`.
     - **P11. Stale reload (A→B→A):** create `pins-delay`. On
       `gitlab.example.org` unpin `o/delta` (delayed save). `cfg`
       `gitlab.other.org` then at once `gitlab.example.org`. Wait until
       `pinsLoaded`: `savedPins` is `["o/beta"]` (the session list), not
       the file's older `["o/beta","o/delta"]`. Remove `pins-delay`;
       wait until the file holds `["o/beta"]`.
     - **P12. Order at start, both ways:** with the catalogue incomplete
       (`panel.polling.catalogueComplete=false`):
       - config first: `panel.configured=false`, `panel.polling.repos=[]`,
         `savedPins=["o/beta"]`, `applyPins()` (does nothing: `pinned`
         unchanged), then `cfg` with `projects:["o/alpha"]`: both
         `o/alpha` and `o/beta` are in `polling.repos`;
       - load last: `panel.configured=false`, `panel.polling.repos=[]`,
         `savedPins=[]`, `cfg` with `projects:["o/alpha"]`, then
         `panel.finishPinsLoad(0, '{"pins":["o/gamma2"]}')` with
         `pinsLoadHost` equal to `host`: `polling.repos` holds `o/alpha`
         and `o/gamma2`.
     - **P13. Failed start:** `panel.pinsCommand=["/nonexistent-python"]`;
       `panel.pinsLoaded=false`; `panel.loadPins()`: wait until
       `pinsLoaded` and `pinsError` starts `Pins not loaded:`. Then `p`
       on an unpinned project: wait for a notice starting
       `Pins not saved:`. Restore `pinsCommand=["python3"]` and clear
       `pinsError`.
     - **P14. Text:** `footerHint` contains `p pin`; wait until `helpText`
       contains `Pin or unpin`.
     - **Restore:** `cfg("gitlab.example.org")` with no pins, clear the
       state file through a save of `[]`, wait until done, `adopt()`.

   Check: the microVM smoke run gives `passed=2 rc=0 binding_loop=0`.

   Traps:
   - **Never run `tests/qml-smoke.py` on the host desktop.**
   - The smoke runs two scenarios (`fresh`, `managed`) in separate temp
     dirs; the state file is per scenario.
   - If the run nears the 90 s watchdog, raise it together with the 110 s
     subprocess timeout, and record it in Deviations.

## Tests

```bash
node tests/polling.cjs && node tests/model.cjs && python3 -m unittest discover -s tests
```

**QML smoke test, in the microVM only.** Never on the host desktop.

1. Start the VM:
   ```bash
   nixarchy vm create gltui-32 --template nixarchy-desktop
   nixarchy vm run --detach gltui-32
   ```
   Wait about 45 s.
2. Create `~/.local/state/nixarchy/microvm/gltui-32/share/run-smoke.sh`:
   ```sh
   #!/bin/sh
   cd /mnt/host/repo || exit 1
   { python3 tests/qml-smoke.py; echo "rc=$?"; } > /mnt/host/smoke.out 2>&1
   touch /mnt/host/smoke.done
   ```
3. Each run, from the repo root:
   ```sh
   share=~/.local/state/nixarchy/microvm/gltui-32/share
   rm -rf "${share:?}/repo" && mkdir "$share/repo" && git ls-files -co --exclude-standard -z | xargs -0 tar -c | tar -x -C "$share/repo"
   rm -f "$share/smoke.done" "$share/smoke.out"
   echo '[{"tool":"launch","args":{"argv":["sh","/mnt/host/run-smoke.sh"],"timeout":2,"generation":"@generation"}}]' \
     | ~/.claude/skills/ai-mirror/mirror-vm gltui-32 - --out /tmp/gltui-32-shots >/dev/null 2>&1
   for i in $(seq 1 70); do [ -f "$share/smoke.done" ] && break; sleep 5; done
   echo "passed=$(grep -c QML_CHECKS_PASSED "$share/smoke.out") $(grep -o 'rc=[0-9]*' "$share/smoke.out" | tail -1) binding_loop=$(grep -c 'binding loop' "$share/smoke.out")"
   grep 'CHECK FAILED' "$share/smoke.out"
   ```
   Expected: `passed=2 rc=0 binding_loop=0`.
4. **Mutation checks, in the VM copy only:** (a) drop `"pinned"` from the
   active-slot order in `next()`: `polling.cjs` fails; (b) drop the pinned
   term from the `rows()` sort: `model.cjs` and P2 fail; (c) remove the
   `configured` guard in `applyPins()`: P12 fails; (d) drop the
   `sessionPins` check in `finishPinsLoad`: P11 fails.
5. Afterwards: `nixarchy vm stop gltui-32`, then, when stopped,
   `nixarchy vm rm gltui-32`.

Also build the flake checks:

```sh
nix build .#checks.x86_64-linux.plugin .#checks.x86_64-linux.menu-verbs --no-link
```

**Review:** a fresh Opus agent, given only this plan and `git diff`, and
Codex's read-only review of the diff (`codex review --base <approve-plan sha>`).

**Release, after the PR merges:** tag `v1.7.0`; nixarchy pin bump PR;
lock nixos_config's `nixarchy-gltui` node (locked fields only, each count
1); switch p620 with its live overrides, then razer, announcing on the bus
first; check `manifest.json` is 1.7.0 and no units failed. p510 is left
alone.

## Rollback

Revert the merge commit and release a patch, or pin the previous tag in
nixarchy. The state file is only read by this feature; leaving it behind
is harmless, and deleting `~/.local/state/omarchy-gitlab-pipelines/`
removes all key pins.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It
confirmed the scheduler snippets (it ran the `next()` pick in memory), the
seed grouping, the orphan cleanup, the model rules, `shownFields` and the
state-file steps. Its findings, which I checked and folded in above:
- returning to a host while its save is pending could reload older pins:
  the session's own lists (`sessionPins`) now win over the file, with a
  test (P11);
- `cfg` was local to O9 and host-only: a shared `cfg(host, extra)` helper;
- P13 set a command that `loadPins()` overwrote: a `pinsCommand` prefix
  hook, and `pinsLoaded` is reset first;
- the race tests used empty lists and no save race: distinct lists, a
  controlled delay, a host change during a save, both start orders, and
  a real load from a pre-written file;
- the flake command was split over two lines.

## Deviations

- **Step 4, lead fix:** `finishPinsLoad`'s host-mismatch reload and
  `finishPinsSave`'s `nextSave()` run through `Qt.callLater`, so a new
  start never happens inside the old Process's exit handler while it may
  still report `running`.
- **Step 6, smoke delay on saves only:** the fake sleeps for `save`
  requests, not loads. A delayed load would let the save finish first, and
  P11 would prove nothing.
- **Step 6, P8 gets two extra steps:** the failed save leaves `o/beta`
  pinned in memory only; after `chmod 700` it is unpinned again before P9
  pins it.
- **Step 6, P12 clears `sessionPins` first,** or P11's session list would
  override the injected load; P12 and P13 also restore
  `catalogueComplete` and the project fixture.
- **Step 6, startup check:** the first `savedPins` loaded while the host is
  still `gitlab.com` is recorded by a `Connections` handler and asserted in
  P1, because the 1 s startup timer changes the host before a step could
  wait on it.
- **Step 6, watchdog message:** the timeout line now also prints the
  current `ei` step index, to find a stuck step.
- **Tests, flake:** this repo's flake has only the `plugin` check, and it
  builds. `menu-verbs` is a nixarchy check; it is built in the pin bump.
- **Tests, VM:** a VM left idle locks its screen (DPMS off, then a
  password prompt), and every `keyClick` then fails, on `main` too. The
  VM was recreated and the smoke run started right after boot.
