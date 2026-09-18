---
status: draft
issue: 1
intent: intent/2026-09-18-1-gitlab-pipelines.md
---

# Spec: Port the GitHub Actions panel to GitLab pipelines

## Design

Copy the runtime files, tests and flake from
[nixarchy-ghtui](https://github.com/olafkfreund/nixarchy-ghtui) at `26eb11a`.
Change only what GitLab requires. **`actions.py` translates GitLab replies into
the shape the JS already consumes**, so `Polling.js` and `ActionsModel.js` keep
their scheduling and row logic, and their existing tests stay meaningful.

Identity: plugin id `olafkfreund.gitlab-pipelines`, name "GitLab Pipelines",
version `0.1.0`, layer namespace `omarchy-gitlab-pipelines`, menu keys
`apps.gitlab-pipelines` and `learn.gitlab-pipelines-keybindings`, and shortcuts
Super+Alt+P (toggle) and Super+Ctrl+Alt+P (keybindings). Every
`github-actions` string, label and error message changes accordingly.

### `actions.py`: GitLab helper

All requests go through `glab api --hostname <host> --include <endpoint>`. The
live check on 2026-09-18 showed that `glab` prints the same `HTTP/x` status line,
headers, blank line and body as `gh`, so `request()` and `http_reply()` stay.

**Host:** each request JSON carries `host`, which defaults to `gitlab.com`. It is
validated as a DNS hostname with an optional port (`^[A-Za-z0-9.-]+(:[0-9]+)?$`,
no leading `-`).

**Project path:** `repo` is `path_with_namespace`. It must have two or more
segments matching `[A-Za-z0-9_.-]+`, with no `.`, `..` or leading `-` segment. It
is sent URL-encoded (`quote(path, safe="")`), which GitLab accepts as `:id`. No
numeric ids are stored.

**Endpoints** (`per_page=100&page=N` unless noted):

| kind | endpoint |
| --- | --- |
| catalogue | `projects?membership=true` (no `order_by`: `last_activity_at` returned HTTP 500 after about 15 s on gitlab.com) |
| activity | `projects/:p/pipelines?status=running` |
| summary `recent` | `projects/:p/pipelines?per_page=10` (not paginated) |
| summary phase | `projects/:p/pipelines?status=<phase>` |
| run | `projects/:p/pipelines/:id` |
| jobs | `projects/:p/pipelines/:id/jobs?include_retried=false` |

**Normalised output.** Only the fields the UI uses are returned, which also
drops GitLab's large nested `commit`, `runner` and `user` objects.

- Catalogue row: `{repo, description, url: web_url, lastActivity: last_activity_at,
  archived, disabled: builds_access_level == "disabled"}`.
- Pipeline:
  - `id`, `run_number: iid`, `html_url: web_url`, `head_branch: ref`,
    `display_title: sha[:8]`.
  - `name`: the pipeline `name`, else `source` with `_` replaced by a space, else "Pipeline".
  - `run_started_at`: `started_at` if present, otherwise `created_at`.
  - `updated_at`.
  - `status`: the scheduler value. `running` and `canceling` become
    `in_progress`. `created`, `waiting_for_resource`, `preparing` and
    `pending` become `queued`. Everything else is `completed`, including
    `manual` and `scheduled`, as the intent requires.
  - `conclusion`: the raw GitLab status, used for display.
  - `run_attempt`: `updated_at` when the pipeline is `completed`, otherwise
    `"active"`. A retried job changes a finished pipeline's `updated_at`, which
    is how a rerun is detected.
- Job: `{id, name, stage, status (same mapping), conclusion (raw),
  allow_failure, started_at, completed_at: finished_at, html_url: web_url}`.
  They are sorted by `id` ascending so that stages appear in creation order.

**Pagination:** the `X-Next-Page` header must be empty or exactly `page + 1`.
Anything else is an error, which replaces the `Link` URL check.

**Rate limits:** `RateLimit-Remaining`, `RateLimit-Reset` (epoch seconds) and
`Retry-After`. HTTP 429 or a "rate limit" message is `errorType: rate`. 401, or
stderr containing `auth login`, is `auth` ("Authenticate with glab auth login").
403 and 404 are `permission` ("Project unavailable or read_api scope missing").

**Removed from `actions.py`:** the legacy batch modes `summary`, `jobs`,
`repositories` and `activity`, and their helpers `pages`, `runs`, `summary`
and `repositories_page`. The panel only calls `page`. Removing them means one
code path to port instead of two.

### `Polling.js`

- `phases` = `["recent","running","pending","created","waiting_for_resource","preparing"]`,
  and the `phases[t.phase]==="in_progress"` check becomes `"running"`.
- Catalogue completion sorts `s.repos` by `lastActivity` descending instead of
  API order, so recently active projects are scanned first, as with GitHub's
  `pushed` order.
- `invalidateJobs`: an attempt mismatch only invalidates cached jobs when the old
  run was `completed`. Without this, the `"active"` → `updated_at` switch at
  completion would flash "Loading jobs…".

The scheduler, limits, back-off and cooldowns are otherwise unchanged.

### `ActionsModel.js`: pipeline → stage → job

The job cache stays flat. `rows()` groups `detail.jobs` by `stage`, in order of
first appearance, and emits:

- A **stage** row at depth 2, in place of the GitHub job row. Its `info` is
  "done/total jobs · duration".
- Its **job** rows at depth 3, in place of step rows. Each links to the job's `web_url`.

Stage status is chosen in this order:

1. Any `running` or `canceling` job → `running`.
2. Otherwise, any failed job without `allow_failure` → `failed`.
3. Otherwise, any queued job (`created`, `pending`, `preparing`, `waiting_for_resource`) → `pending`.
4. Otherwise, any `canceled` job → `canceled`.
5. Otherwise, any `success` job → `success`.
6. Otherwise, `skipped`, or `manual` if every job is `manual`.

Icons and colours use GitLab names:

| Icon | Statuses |
| --- | --- |
| ✓ | `success` |
| ✕ | `failed` |
| ◷ | `running`, `canceling` |
| ⊘ | `canceled` |
| − | `skipped`, `manual`, `scheduled` |
| ○ | anything else |

The repo row URL is `url + "/-/pipelines"`, taken from the catalogue.

### `ActionsPanel.qml`

- Plugin id, labels and namespace change.
- `configure()` reads `host` and the start-up hint list `projects`, both from the
  plugin's `shell.json` entry. The hint list is validated with the nested-path regex.
- `pump()` adds `host` to each request.
- `openBrowser()` only opens URLs that start with `https://<host>/`.
- `statusColor` treats `failed` as urgent, and `running` and `success` as accent.
- The footer reads "o GitLab".

### Menu, keys, flake, docs

- **`menu.py`:** uses the new menu keys and plugin path. The GitHub-specific
  legacy root/System migration is deleted, because this plugin has no legacy entries.
- **`menu.example.json`, `bindings.example.lua`, `keybindings.sh`:** new text and chords.
- **`flake.nix`:** package `nixarchy-gltui-<version>`, and the id check uses the new
  id. The runtime file list is unchanged.
- **`README.md`:** completed to the level of the GitHub README, including
  authentication (`read_api`), the `host` setting, refresh targets and removal.
- **Not copied:** GitHub's `intent/`, `spec/` and `plan/` history.

### Tests

The four suites and the QML smoke test are ported to GitLab-shaped fixtures.
The new cases cover:

- endpoint building, nested-path and host validation
- status and field normalisation
- `X-Next-Page` handling
- `RateLimit-*` parsing
- stage grouping and aggregation
- attempt-based invalidation
- activity sorting in the catalogue

`nix flake check` runs all of them offline.

## Alternatives rejected

- **Numeric project ids through the scheduler.** This adds a second key to
  every request and row. URL-encoded paths work as `:id` and keep the display
  name as the key. After a project rename, the old path returns 404 until a
  catalogue refresh, which is the same as a GitHub repo rename today.
- **Translating GitLab statuses in JS.** That spreads GitLab knowledge across
  three files. Keeping it in `actions.py` leaves the scheduler untouched.
- **GraphQL.** It can return pipelines, stages and jobs in one query. But it has
  its own cost-based limits and cursor pagination, so it would mean rewriting
  `Polling.js` and its fairness tests.
- **Grouping stages in `actions.py`.** Jobs arrive paginated. A stage can span
  pages, and the scheduler merges pages by `id`, so stages would split. Grouping
  after merge, in the model, avoids that.
- **`glab ci list` / `glab ci view`.** These give formatted output with no
  headers, so the plugin could not read rate limits or pagination.
- **One plugin that supports both GitHub and GitLab.** The intent asks for a
  separate plugin that runs alongside the GitHub one. Two backends in one helper
  would double the configuration and tests.

## Risks

- **Downstream pipelines** (trigger/bridge jobs, `/bridges`) are not shown.
  Only the parent pipeline's own jobs appear. Add them if you ask for them.
- **Stage order** follows job creation. Pipelines built with `needs:` (DAG) can
  create jobs out of stage order, and a stage could then appear later than in
  the GitLab UI. This affects display only.
- **Durations in the pipeline list** start at `created_at`, so they include
  queue time until the single-pipeline lookup supplies `started_at`.
- **Heavy catalogue pages:** full project objects are about 5 KB each. Accounts
  with many memberships download more on each discovery, which runs at most
  every 5 minutes while open.
- **Self-managed hosts** can have rate-limit headers turned off. Then only 429
  or `Retry-After` pauses the scheduler, and the local 60-requests-per-minute
  ceiling still applies.
- **Shortcut conflicts:** Super+Alt+P is free on this desktop (checked with
  `hyprctl binds` on 2026-09-18). Other desktops must check before adding it.
- **Hosts:** none change. P620 and Razer consume the plugin later.

## Verification

- `python3 -m unittest discover -s tests -v`, `node tests/model.cjs` and
  `node tests/polling.cjs` pass. They include the new GitLab cases listed under Tests.
- `nix flake check` and `nix build .#default` succeed, and
  `omarchy plugin validate ./result` passes.
- `python3 tests/qml-smoke.py` and `python3 tests/qml-smoke.py ./result` pass
  in the graphical session.
- **Live read-only check** against gitlab.com with the existing `glab` login:
  - the catalogue lists the account's projects
  - a pipeline expands to stages and jobs
  - `o` opens the correct GitLab page
  - closing the panel stops `glab` processes (`pgrep -f 'glab api'` is empty)
- `grep -ri 'github' --exclude-dir=.git` finds only intended references: the
  sibling plugin link and the flake URL.
