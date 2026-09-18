---
status: approved
issue: 1
spec: spec/2026-09-18-1-gitlab-pipelines.md
---

# Plan: Port the GitHub Actions panel to GitLab pipelines

## Approved decisions (from the spec)

- **Source.** Copy the runtime files, tests and flake from `nixarchy-ghtui` at
  `26eb11a`. Leave out its `intent/`, `spec/`, `plan/`, `.git` and README
  (this repo has its own README). The GitLab adapter lives in `actions.py`,
  and the JS keeps consuming GitHub-shaped fields.
- **Identity.**
  - Plugin id `olafkfreund.gitlab-pipelines`, name "GitLab Pipelines",
    version `0.1.0`, namespace `omarchy-gitlab-pipelines`.
  - Menu keys `apps.gitlab-pipelines` and `learn.gitlab-pipelines-keybindings`.
  - Shortcuts Super+Alt+P (toggle) and Super+Ctrl+Alt+P (keybindings).
    Super+Alt+G is Omarchy's "Move active window out of group".
- **CLI.** `glab api --hostname <host> --include <endpoint>`. The `host` comes
  from the request JSON, defaults to `gitlab.com`, and must match
  `^[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]+)?$`.
- **Project path.** `path_with_namespace` with two or more segments of
  `[A-Za-z0-9_.-]+`. No `.`, `..` or leading `-` segment. Sent as
  `quote(path, safe="")`. No numeric ids are stored.
- **Endpoints** (`per_page=100&page=N` unless noted):

  | kind | endpoint |
  | --- | --- |
  | catalogue | `projects?membership=true`, with no `order_by` (gitlab.com returns 500 for `last_activity_at`) |
  | activity | `projects/:p/pipelines?status=running` |
  | summary `recent` | `projects/:p/pipelines?per_page=10`, not paginated |
  | summary phase | `projects/:p/pipelines?status=<phase>` |
  | run | `projects/:p/pipelines/:id` |
  | jobs | `projects/:p/pipelines/:id/jobs?include_retried=false` |

- **Normalisation.** Only the fields the UI uses are returned.
  - Catalogue row: `{repo, description, url, lastActivity, archived, disabled}`,
    where `disabled` is `builds_access_level == "disabled"`.
  - Pipeline:
    - `id`, `run_number` (`iid`), `html_url` (`web_url`), `head_branch` (`ref`),
      `display_title` (`sha[:8]`).
    - `name`: the pipeline `name`, else `source` with `_` replaced by a space,
      else "Pipeline".
    - `run_started_at`: `started_at`, else `created_at`.
    - `updated_at`.
    - `status`: `running` and `canceling` become `in_progress`. `created`,
      `waiting_for_resource`, `preparing` and `pending` become `queued`.
      Everything else becomes `completed`, including `manual` and `scheduled`.
    - `conclusion`: the raw GitLab status.
    - `run_attempt`: `updated_at` when the pipeline is completed, otherwise `"active"`.
  - Job: `{id, name, stage, status, conclusion, allow_failure, started_at,
    completed_at, html_url}`, sorted by `id` ascending.
- **Pagination.** `X-Next-Page` must be empty or exactly `page + 1`.
- **Errors.**
  - `RateLimit-Remaining`, `RateLimit-Reset` (epoch seconds) and `Retry-After` are read.
  - HTTP 429 or a "rate limit" message is `rate`.
  - HTTP 401, or stderr containing `auth login`, is `auth` ("Authenticate with glab auth login").
  - HTTP 403 and 404 are `permission` ("Project unavailable or read_api scope missing").
  - Anything else is `network`.
- **Batch modes removed.** `summary`, `jobs`, `repositories` and `activity` go,
  along with `pages`, `runs`, `summary`, `repositories_page`, `activity` and `api`.
  Only `page` remains.
- **`Polling.js` changes.**
  - `phases` becomes `["recent","running","pending","created","waiting_for_resource","preparing"]`,
    and the `"in_progress"` phase check becomes `"running"`.
  - When the catalogue completes, projects are sorted by `lastActivity` descending.
  - `invalidateJobs` only acts on an attempt mismatch when the old run was `completed`.
- **Model.**
  - Jobs are grouped by `stage` in order of first appearance.
  - Stage rows sit at depth 2, with info "done/total jobs · duration". Job rows
    sit at depth 3 and use the job's `html_url`.
  - Stage status is chosen in this order: running (includes canceling) → failed
    without `allow_failure` → pending (created, pending, preparing,
    waiting_for_resource) → canceled → success → manual if every job is manual,
    otherwise skipped.
  - Icons: ✓ success. ✕ failed. ◷ running or canceling. ⊘ canceled.
    − skipped, manual or scheduled. ○ anything else.
  - The repo row URL is `url + "/-/pipelines"`.
- **Panel.**
  - `configure()` reads `host` and the `projects` hint list from the plugin's `shell.json` entry.
  - `pump()` adds `host` to each request.
  - `openBrowser()` only opens URLs that start with `https://<host>/`.
  - `failed` is shown as urgent.
  - The footer reads "o GitLab".
- **Menu.** The legacy root/System migration is deleted from `menu.py` and its tests.
- **Known limits (accepted).** No downstream (bridge) pipelines. Stage order
  follows job creation. List durations start at `created_at` until the pipeline
  is looked up individually. No license is added.

## Steps

Each step is one commit on `feat/1-gitlab-pipelines`. Tests are ported in the
same step as the code they cover, so every commit is green.

1. **Copy.** From `../nixarchy-ghtui` at `26eb11a`, copy these files unchanged:
   `actions.py`, `Polling.js`, `ActionsModel.js`, `ActionsPanel.qml`,
   `menu.py`, `menu.example.json`, `keybindings.sh`, `bindings.example.lua`,
   `manifest.json`, `flake.nix`, `flake.lock` and `tests/`. Commit this as
   "chore: import nixarchy-ghtui 26eb11a".
   → Verify with `python3 -m unittest discover -s tests`, `node tests/model.cjs`
   and `node tests/polling.cjs`, which should pass as the unchanged baseline.
2. **Identity.** Update `manifest.json`, `menu.example.json`,
   `bindings.example.lua`, `keybindings.sh` (new chords and GitLab wording),
   and `menu.py` (keys, temp-file prefix, error prefix, and deleting the legacy
   migration in `registered_menu`). Update `test_menu.py` to match: delete the
   migration tests, and change `test_comments_strings_and_custom_entries` to
   check that comments and custom entries survive when defaults are added.
   → Verify with `python3 -m unittest tests.test_menu -v` and
   `bash keybindings.sh --print`. Check `hyprctl binds` again for P conflicts.
3. **`actions.py`.** Rewrite it to the decisions above: host and path validation,
   endpoints, normalisers, `X-Next-Page`, `RateLimit-*`, the error map, and
   `glab` in `request()`. Delete the batch modes. Rewrite `tests/test_actions.py`
   using GitLab-shaped fixtures that cover:
   - nested paths and bad paths or hosts
   - every status mapping
   - `run_attempt`
   - `X-Next-Page` values: valid, missing, and wrong-page (which raises)
   - rate, auth, permission and network errors
   - `recent` ignoring pagination
   - trimmed fields, so no `user` or `runner` data leaks
   - cancellation reaping a fake `glab` in `page` mode
   - a missing `glab` returning a JSON error in `page` mode

   → Verify with `python3 -m unittest tests.test_actions -v`.
4. **`Polling.js`.** Change the phases, the `running` check, the catalogue sort
   and `invalidateJobs`. In `tests/polling.cjs`, change the summary status
   `in_progress` to `running`, and add assertions for two things: the catalogue
   is ordered by `lastActivity`, and a completed→completed attempt change
   invalidates jobs while active→completed does not.
   → Verify with `node tests/polling.cjs`. The simulation budgets must still beat the baseline.
5. **`ActionsModel.js`.** Add stage grouping and aggregation, the GitLab
   icon names, the repo URL from `url` and the "jobs" wording. Update
   `tests/model.cjs` to cover:
   - the stage and job hierarchy
   - each aggregation rule, including `allow_failure`
   - the icon set
   - filtering by pipeline name and branch

   → Verify with `node tests/model.cjs`.
6. **`ActionsPanel.qml`.** Change the id, labels, namespace, `host` handling,
   the `projects` hint list with the nested regex, the `pump()` request host,
   the `openBrowser` host check, the colour names and the footer. Update
   `tests/qml-smoke.py`:
   - new ids and menu keys
   - a fake helper returning stage-grouped job fixtures under a `group/sub/project` path
   - a check that jobs arrive, replacing the steps check

   → Verify with `python3 tests/qml-smoke.py` in the graphical session.
7. **Flake.** Rename the package to `nixarchy-gltui-${version}`, update the id
   assertion, the description and the smoke-test error message, and relock with
   `nix flake lock` only if the lock needs it.
   → Verify with `nix flake check`, `nix build .#default`,
   `omarchy plugin validate "$(readlink -f result)"` (the validator rejects the `result` symlink itself; deviation recorded in step 7) and `python3 tests/qml-smoke.py ./result`.
8. **README.** Replace "in development" with the full documentation, at the
   level of the GitHub README:
   - requirements
   - both install routes, migration and updates
   - shortcuts
   - menus
   - projects and the `host` setting
   - authentication (`read_api`)
   - keys
   - refresh targets and errors
   - checks
   - removal
   - known limits

   → Verify by reviewing the text. A grep for GitHub references should find
   only the sibling link and the flake URL.
9. **Live read-only check** with the real `glab` login. Symlink the checkout
   into `~/.config/omarchy/plugins/olafkfreund.gitlab-pipelines`, run
   `omarchy plugin enable`, and open it with
   `omarchy-shell shell toggle olafkfreund.gitlab-pipelines '{}'`. Confirm that:
   - projects are listed
   - a pipeline expands to stages and jobs
   - `o` opens GitLab
   - there are no `glab api` processes after closing

   Record the results in the PR. The Hyprland binding is only added to
   `~/.config/hypr/bindings.lua` with your go-ahead.
10. **PR.** Push the branch and open a PR that links the intent, spec and plan,
    lists the verification results, and says "Closes #1".

## Tests

```sh
python3 -m unittest discover -s tests -v   # all Python tests pass
node tests/model.cjs                       # prints "Model: … passed"
node tests/polling.cjs                     # prints all "Polling: … passed" lines
python3 tests/qml-smoke.py                 # prints QML_CHECKS_PASSED (fresh and managed menus)
nix flake check                            # succeeds offline
nix build .#default && omarchy plugin validate "$(readlink -f result)"
python3 tests/qml-smoke.py ./result
```

No test makes a live GitLab request. Step 9 is the only live check, and it only reads.

## Rollback

- Before merge: close the PR and delete `feat/1-gitlab-pipelines`. `main` only
  contains the README.
- After a local test install: `omarchy plugin remove olafkfreund.gitlab-pipelines`,
  or remove the symlink. Then remove the `apps.gitlab-pipelines` and
  `learn.gitlab-pipelines-keybindings` menu entries and any added bindings.
- Nothing touches the GitHub plugin, the host NixOS configuration or GitLab data.
