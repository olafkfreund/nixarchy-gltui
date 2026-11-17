---
status: approved
issue: 25
spec: spec/2026-11-17-25-status-colours.md
coders:
  1: codex   # small, exact pure logic: the group table, icons and the allowed-failure row status
  2: coder   # QML colour/opacity functions and delegate bindings
  3: coder   # smoke-test stages, following the existing esteps pattern
  4: coder   # README table and version bump
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Tell pipeline and job states apart at a glance

Self-contained. Branch `feat/25-status-colours`, based on `59e6856`
(v1.1.1). Line numbers are for that commit; match on the quoted code.
`gitlab.py` and `Polling.js` must not change.

## Approved decisions (from the spec)

### The group table

This is the single source of truth.

| Group | Statuses | Icon | Colour | Opacity |
|---|---|---|---|---|
| `running` | `running`, `canceling` | `●` | `Commons.Color.menu.text` | 1 |
| `success` | `success` | `✓` | `Commons.Color.accent` | 1 |
| `failed` | `failed`, `error`, `unavailable` | `✕` | `Commons.Color.urgent` | 1 |
| `allowed` | `allowed to fail` | `!` | `Commons.Color.urgent` | 0.6 |
| `manual` | `manual` | `▶` | `Commons.Color.accent` | 1 |
| `scheduled` | `scheduled` | `◷` | `Commons.Color.menu.text` | 1 |
| `queued` | `created`, `pending`, `waiting_for_resource`, `preparing`, `waiting_for_callback`, `queued`, `awaiting final status` | `◌` | `Commons.Color.menu.text` | 1 |
| `skipped` | `skipped` | `−` | `Commons.Color.muted` | 0.5 |
| `canceled` | `canceled` | `⊘` | `Commons.Color.menu.text` | 1 |
| `neutral` | `neutral` | `·` | `Commons.Color.menu.text` | 1 |
| `unknown` | anything else | `○` | `Commons.Color.menu.text` | 1 |

### Other decisions

- **Allowed failures:** a job with `conclusion === "failed"` and
  `allow_failure` true gets the row status `"allowed to fail"`. All other
  rows keep `state(...)`. `stageStatus` and `stages` do not change.
- **Dimming:** only the status icon and the info `Text` bind
  `opacity: root.statusOpacity(modelData.status)`. The title and subtitle do
  not.
- **Selection:** it never changes a status colour or opacity. Opacity never
  drops below 0.5.
- **Icons:** every group has a different one.

## Steps

1. **`PipelinesModel.js` and `tests/model.cjs`: the group table and the
   allowed-failure status.**
   - **`group(status)`:** add it before `icon`. It returns the group name per
     the table, and `"unknown"` for anything else.
   - **`icon(status)`:** rewrite it (the function starting
     `if (status === "success") return "✓";`) as a lookup from
     `group(status)` to the icon.
   - **`rows()`:** in the job push
     (`status: state(job), info: duration(job, now)`), use
     `status: job.conclusion === "failed" && job.allow_failure ? "allowed to fail" : state(job)`.
   - **`tests/model.cjs`:**
     - replace the icon assertions (from `assert.equal(model.icon('success'), '✓');`
       through `assert.equal(model.icon('pending'), '○');`) with a loop over
       every status in the table, checking `group` and `icon`, plus
       `group('frobnicated')==='unknown'` and `icon('frobnicated')==='○'`;
     - check that the eleven icons are distinct (a `Set` of size 11);
     - change `assert.equal(allowed[3].status, 'failed', 'the job row stays failed');`
       to expect `'allowed to fail'`, keeping `allowed[2].status === 'success'`;
     - add a blocking failed job, which stays `failed`;
     - check that the allowed job's `info` equals `model.duration(job, now)`.

   Check: `node tests/model.cjs >/dev/null && node tests/polling.cjs >/dev/null`.

   Traps: keep the code ES5, because the file is loaded by QML and by Node
   `vm`. No `const`, arrows or `Set` in `PipelinesModel.js`; the tests may use
   them. The table must be built so that lookups fall through for prototype
   names: `group("constructor")` must be `"unknown"`, so use
   `Object.create(null)` or a `switch`.

2. **`PipelinesPanel.qml`: colour, opacity and delegate bindings.**
   - **`statusColor(status)`** (the function with
     `if (status === "failed" || status === "error") return Commons.Color.urgent`):
     switch on `Model.group(status)` and return the colour column.
   - **`statusOpacity(status)`:** add it next to `statusColor`; it returns the
     opacity column.
   - **Status icon:** in the delegate, the status-icon `Text` (`id: statusIcon`,
     `text: Model.icon(modelData.status)`) gets
     `opacity: root.statusOpacity(modelData.status)` and
     `objectName: "statusIcon"`.
   - **Info:** the info `Text` (`id: info`) gets the same `opacity` and
     `objectName: "statusInfo"`. The objectNames let the smoke test find
     these items inside a delegate.

   Check: `node tests/model.cjs >/dev/null && node tests/polling.cjs >/dev/null`,
   then the microVM smoke run (see Tests). It must pass unchanged at this
   point.

   Traps:
   - `Model` is the QML import name of `PipelinesModel.js`; match how
     `Model.icon` is already called.
   - Do not touch the title and subtitle `Text`s, or their selected-text
     colours.

3. **`tests/qml-smoke.py`: smoke checks.**
   - **Fake helper job list** (the line starting `elif kind=='jobs': data=[`):
     add
     `{'id':10,'name':'lint','stage':'test','status':'completed','conclusion':'failed','allow_failure':True,'started_at':'2026-01-01T00:00:00Z','completed_at':'2026-01-01T00:01:02Z'}`.
     Change `check(panel.details["one/sub/repo:7"].jobs.length===2,"jobs arrive")`
     to `===3`.
   - **The `lint` row,** in stage 1, right after the "jobs grouped into
     stages" check:
     1. Set `panel.expanded["one/sub/repo:7:stage:test"]=true`, then call
        `panel.rebuild()`.
     2. Find the entry with `kind==="job" && title==="lint"`.
     3. Check that its status is `"allowed to fail"` and its info is
        `"1m 2s"`.
     4. Move the cursor onto it with `panel.cursor=<index>` and
        `panel.selectionChanged(true)`.
     5. Scroll it into view with
        `panel.listItem.positionViewAtIndex(<index>, ListView.Contain)`.
        `selectionChanged()` does not scroll (`PipelinesPanel.qml:173-175`);
        only `move()` does (`:129-132`).

     Then a later tick (new stage or a `held()` wait):
     - `listItem.itemAtIndex(<index>)` exists;
     - its `statusIcon` child text is `"!"`;
     - `statusIcon` and `statusInfo` `color` and `opacity` equal
       `panel.statusColor("allowed to fail")` and
       `panel.statusOpacity("allowed to fail")`, using `Qt.colorEqual`.

     Find the children with a small recursive `findByName(item, name)` helper
     that walks `children`.

     Afterwards, delete the `stage:test` key from `panel.expanded` and call
     `panel.rebuild()`, so the later stages see the rows they expect.
   - **New `esteps` entries** (the #26 error-state stages run at stage 10),
     before the restore step:
     - **Colour and opacity table:** for every status in the group table,
       `Qt.colorEqual(panel.statusColor(s), <expected Commons colour>)` and
       `panel.statusOpacity(s)===<expected>`.
     - **Selected rows of every group:**
       - fixture: set `panel.polling.repos` to one repo per group, using
         `run`-less repo rows for `neutral` and `error`, and one repo with
         runs whose `conclusion` covers each other group's first status;
       - expand the repo, then `adopt()`;
       - for each row:
         - set the cursor;
         - call `panel.listItem.positionViewAtIndex(i, ListView.Contain)`;
         - wait for `itemAtIndex(i)`;
         - check that `statusIcon` / `statusInfo` `color` and `opacity` match
           the functions and are at least 0.5.

       Put the wait and the check in separate functions, as #26 did.
     - **Insertion point:** these entries go immediately before the final
       `estep`, the one that sets `panel.workerBusy=false`, closes the panel,
       rebuilds the 40-repo zoom fixture with its cooldown and sets
       `stage=11`. That step already restores everything the zoom stages
       need, so no extra restore is required.

   Check: the microVM smoke run passes, with `passed=2 rc=0 binding_loop=0`.

   Traps:
   - **Never run `tests/qml-smoke.py` on the host desktop** (owner's
     request). Use the microVM script (see Tests). Run only one copy at a
     time.
   - Run rows read `state(run)`, which is `conclusion || status`, so a run's
     `conclusion` sets its group.
   - `workerBusy=true` stays set during `esteps`, so no request starts.

4. **Docs and version.** This is release work, as in #26; it is outside the
   spec's code scope.
   - **`README.md`:** replace the icon table under "Icons accompany the GitLab
     status:" with one row per group (icon, statuses). Add one line saying
     that running is now `●` and scheduled is `◷`, that allowed failures show
     `!` with "allowed to fail", and that skipped jobs are dimmed.
   - **`manifest.json`:** `"version": "1.2.0"`, because the change is
     visible.
   - **Release notes:** the `v1.2.0` GitHub release body (written by the lead
     at release) states the running icon change (`◷` → `●`), and the new `!`,
     `▶`, `◷`, `◌` and `·` icons.

   Check: the full test set.

## Tests

```bash
node tests/polling.cjs && node tests/model.cjs && python3 -m unittest discover -s tests
```

**QML smoke test, in the microVM only.** Never on the host desktop.

1. Start the VM once:
   ```bash
   nixarchy vm create gltui-25 --template nixarchy-desktop
   nixarchy vm run --detach gltui-25
   ```
   Wait about 45 s, until `~/.local/state/nixarchy/microvm/gltui-25/vsock-cid`
   exists and omarchy's first run has finished.
2. Create the in-guest runner, `~/.local/state/nixarchy/microvm/gltui-25/share/run-smoke.sh`.
   The share is `/mnt/host` in the guest.
   ```sh
   #!/bin/sh
   cd /mnt/host/repo || exit 1
   { python3 tests/qml-smoke.py; echo "rc=$?"; } > /mnt/host/smoke.out 2>&1
   touch /mnt/host/smoke.done
   ```
3. Each run: copy the working tree in, start the runner in the guest, and
   read the result.
   ```sh
   share=~/.local/state/nixarchy/microvm/gltui-25/share
   rm -rf $share/repo && mkdir $share/repo && git ls-files -z | xargs -0 tar -c | tar -x -C $share/repo
   rm -f $share/smoke.done $share/smoke.out
   echo '[{"tool":"launch","args":{"argv":["sh","/mnt/host/run-smoke.sh"],"timeout":2,"generation":"@generation"}}]' \
     | ~/.claude/skills/ai-mirror/mirror-vm gltui-25 - --out /tmp/gltui-25-shots >/dev/null 2>&1
   for i in $(seq 1 60); do [ -f $share/smoke.done ] && break; sleep 5; done
   echo "passed=$(grep -c QML_CHECKS_PASSED $share/smoke.out) $(grep -o 'rc=[0-9]*' $share/smoke.out | tail -1) binding_loop=$(grep -c 'binding loop' $share/smoke.out)"
   grep 'CHECK FAILED' $share/smoke.out
   ```
   Expected: `passed=2 rc=0 binding_loop=0`. Run one copy at a time.
4. **Glyph check, before the PR merges** (done by the lead):
   - open the panel in the guest on a fixture with one row per group, and
     take a screenshot with `mirror-vm` (`{"tool":"screenshot"}`);
   - check that every icon renders as a glyph, not as a box, and that no
     icon overlaps the title column.
   - If one fails, swap it for a covered glyph before merging, and record
     that as a deviation.
5. Afterwards, remove the VM:
   ```bash
   nixarchy vm stop gltui-25
   ```
   When `nixarchy vm list` shows it stopped, run:
   ```bash
   nixarchy vm rm gltui-25
   ```

**Review:** a fresh Opus agent, given only this plan and `git diff`, and
Codex's read-only review of the diff.

**Release, after the PR merges:**
1. Tag `v1.2.0`.
2. Open the nixarchy pin bump PR.
3. Lock nixos_config's `nixarchy/nixarchy-gltui` node (the #3024 approach),
   unless edge has caught up.
4. Switch p620, keeping its live overrides, then razer. Announce on the bus
   first.

p510 stays on 1.0.0.

## Rollback

Revert the PR's merge commit and release `v1.2.1`, or point the pins back at
`59e6856` (v1.1.1). No data or config format changes.

## Deviations

- **Step 3, wait and check in one estep:** the selected-rows check keeps the
  wait and the check in one `estep`, with a `gPlaced` flag. The first tick
  places the cursor and scrolls, and a later tick waits for the delegate and
  checks it. The plan asked for separate functions.
- **Step 3, stage 12:** the lint row's "later tick" is a new tick-timer stage,
  `stage===12`. It runs between stage 1 and stage 2, and does the close that
  stage 1 used to do.
- **Step 3, group fixture:** the selected-rows fixture covers every group
  except `allowed`, which the lint row covers.
