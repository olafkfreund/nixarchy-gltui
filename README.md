# GitLab Pipelines for Omarchy

A flat, keyboard-driven Quickshell popup for GitLab projects → pipelines → stages → jobs, hosted inside `omarchy-shell`. It discovers every project you are a member of, including nested groups, and lists projects with running pipelines first. It uses the current Omarchy menu colours, fonts, spacing, border and corner radius, and follows the theme font size (`[font] base-size`). There are no buttons, and no background daemon, database or token storage.

It is the GitLab sibling of [nixarchy-ghtui](https://github.com/olafkfreund/nixarchy-ghtui) (GitHub Actions), with the same design and behaviour. Both plugins can be installed side by side.

## Requirements

- Omarchy shell with the panel plugin contract and `qs.Commons` / `qs.Ui` components.
- [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use, or with an environment token (see [Authentication](#authentication)). The token needs the `read_api` scope.
- Python 3, `xdg-open` for the browser shortcut, `wl-copy` (wl-clipboard) for the copy keys, and a terminal that `xdg-terminal-exec` can start with a command (Omarchy's terminals can) for the log key. `notify-send` (libnotify) for watch notifications.

On NixOS, missing dependencies belong in your declarative configuration. Do not install them with pacman or an imperative Nix profile.

## Install

Make sure your running session matches the installed Omarchy generation first. If you rebuilt since login, log out and back in.

### Git installation

```sh
omarchy plugin add https://github.com/olafkfreund/nixarchy-gltui.git --enable
```

### Nix flake installation

This route is for an existing NixOS configuration with Nixarchy and its Home Manager module already enabled for your user. Add this input to your `flake.nix`:

```nix
inputs.gitlab-pipelines = {
  url = "github:olafkfreund/nixarchy-gltui";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

Pass `inputs` to your modules through `specialArgs` in `nixpkgs.lib.nixosSystem`, keeping any other arguments:

```nix
specialArgs = { inherit inputs; };
```

Import a NixOS module like this one, replacing `YOUR_USER`:

```nix
{ inputs, ... }:
{
  home-manager.users.YOUR_USER = { pkgs, ... }: {
    programs.nixarchy.plugins."olafkfreund.gitlab-pipelines".src =
      inputs.gitlab-pipelines.packages.${pkgs.stdenv.hostPlatform.system}.default;
    home.packages = [ pkgs.glab pkgs.python3 pkgs.xdg-utils pkgs.bash pkgs.libnotify pkgs.wl-clipboard ];
  };
}
```

The package supports `x86_64-linux` and `aarch64-linux` and contains only the plugin files. Adding it to `environment.systemPackages` does not register it with Omarchy. The Nixarchy module validates the package and links it into your plugin directory. Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab`'s stored login or an environment token (see [Authentication](#authentication)).

Build and activate through NixOS, replacing `HOST`, then enable the plugin once in the running session (or use **Setup → Plugins**):

```sh
nixos-rebuild build --flake .#HOST
sudo nixos-rebuild switch --flake .#HOST
omarchy plugin enable olafkfreund.gitlab-pipelines
```

Use `nixos-rebuild`, not `home-manager switch`, with this integration.

### Migrating an existing Git checkout

Nixarchy refuses to replace an existing real plugin directory. Before switching to the declarative installation:

1. Check `git status` in `~/.config/omarchy/plugins/olafkfreund.gitlab-pipelines` and preserve any local work.
2. Close the panel.
3. Move the checkout to a backup **outside** `~/.config/omarchy/plugins/`.
4. Rebuild, and confirm the managed plugin opens.

### Updates and rollback

- **Git installation:** `omarchy plugin update olafkfreund.gitlab-pipelines`.
- **Nix installation:** update only this input and rebuild:

  ```sh
  nix flake update gitlab-pipelines
  nixos-rebuild build --flake .#HOST
  sudo nixos-rebuild switch --flake .#HOST
  ```

  To roll back, restore the previous `flake.lock` and rebuild. Do not use Git pull or the plugin updater on a store-managed link.

### Keyboard shortcuts

| Chord | Action |
| --- | --- |
| **Super + Alt + P** | Open or close GitLab Pipelines |
| **Super + Ctrl + Alt + P** | GitLab Pipelines keybindings |

Super + Alt + G is Omarchy's *Move active window out of group*, so P (pipelines) is used instead. Before adding the shortcuts, check `omarchy menu keybindings --print` for conflicts. Then add the lines from `bindings.example.lua` to `~/.config/hypr/bindings.lua`. If Home Manager owns that file, change its declarative source instead. Validate with `hyprctl reload` followed by `hyprctl configerrors`.

You can also open the panel directly:

```sh
omarchy-shell shell toggle olafkfreund.gitlab-pipelines '{}'
```

## Omarchy menus

Enabling the plugin registers two menu entries:

- **Apps → GitLab Pipelines**, also found by searching for gitlab, pipelines or ci.
- **Learn → GitLab Pipelines keybindings**, a searchable reference for every panel control.

Registration runs once when the enabled panel loads. It preserves comments and customisations in `~/.config/omarchy/extensions/omarchy-menu.jsonc` and never duplicates or rewrites unchanged entries.

A `menu.managed` file beside `menu.py` turns registration off entirely: the panel then leaves
the menu alone and writes nothing. nixarchy ships that marker, because it declares both rows
itself.

If that file is a symlink or read-only (for example, managed by Nix), declare the entries from `menu.example.json` in your host configuration instead. Automatic registration leaves managed or malformed files untouched and logs an error; the panel still works through its shortcut. After fixing a writable file, retry with:

```sh
python3 ~/.config/omarchy/plugins/olafkfreund.gitlab-pipelines/menu.py register
```

## Projects

No project list is needed. Opening the popup fetches every page of `GET /projects?membership=true`: the projects you are a direct or inherited member of, including nested groups. Projects are scanned in order of most recent activity. The list is refreshed every 5 minutes while the panel is open. Archived projects, and projects with CI/CD disabled, stay searchable but are not polled.

Press **/** and type a project path, description, pipeline name, branch or status. Use **↑ / ↓** while typing to select a result, then **Enter** to expand it. **Tab** finishes editing without expanding. Projects with running pipelines move to the top as activity is discovered. Projects not yet checked say **not checked**, and the header shows scan progress. A project row's icon is the latest finished pipeline the panel has seen for it, on any branch, from selecting the project or from a pipeline seen running or queued, and the row says `last <status> <age>`, for example `0 running · last failed 2h ago · checked 3m ago`. Running pipelines and errors take precedence. Projects never selected and never seen running stay `·`, and a project with no pipelines says **no pipelines**. A newer pipeline that starts and finishes between idle checks is not seen until you select the project.

The catalogue and known activity stay in memory between openings. After five minutes, reopening refreshes the catalogue. **Shift + R** refreshes it immediately.

### Self-managed GitLab and settings

The default host is `gitlab.com`. For a self-managed instance, add `host` to this plugin's entry in `~/.config/omarchy/shell.json`. You can also add `projects`, a list of project paths that are shown before discovery finishes; it does not limit discovery. `pinned` lists projects that sort first and are checked about every minute (see [Pinned projects](#pinned-projects)).

```json
{
  "plugins": [
    {
      "id": "olafkfreund.gitlab-pipelines",
      "host": "gitlab.example.org",
      "projects": ["group/subgroup/project"],
      "pinned": ["group/project"]
    }
  ]
}
```

Keep any other keys already in that entry. The host must be authenticated with `glab auth login --hostname gitlab.example.org` (or reachable by an environment token, see [Authentication](#authentication)). Browser links only open URLs on the configured host. One host is shown at a time.

### Authentication

The plugin uses your existing `glab` login and never reads, extracts or stores a token. A personal, group or project access token works if it has `read_api`. If a project is missing, confirm that `glab api projects?membership=true` lists it with the same login, then press **Shift + R**.

**Environment tokens.** `glab` prefers a token from the environment over its stored login: `GITLAB_TOKEN`, then `GITLAB_ACCESS_TOKEN`, then `OAUTH_TOKEN`, the first one set wins. It needs the same `read_api` scope. `glab` only sends such a token to some hosts: the default host (`GITLAB_HOST`), the host in `GITLAB_REPO`, and hosts already in its configuration. `glab config --help` has the full rules. The panel names its host only on the command line, so for any other host run `glab auth login --hostname …` once. Setting `GITLAB_HOST` for the whole session also works, but then every `glab` command in that session uses that host, and fails in repositories whose remotes do not match it.

The variable must be in the environment the Omarchy shell was started with. Exporting it in a terminal does not change a running shell.

If the panel keeps asking you to authenticate although `glab auth status` looks fine, check for a stale environment token. In a terminal, compare with all three cleared, using the panel's host in place of `gitlab.example.org`:

```bash
env -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN glab api --hostname gitlab.example.org user
```

If that works, the stale token is in the session's environment. `omarchy-restart-shell` starts the shell through Hyprland, so the shell gets Hyprland's environment: remove the variable where your session sets it, then log out and back in. Keep tokens out of world-readable files and the Nix store.

## Keyboard

| Key | Action |
| --- | --- |
| ↑ / ↓ or k / j | Select a row |
| Enter / Space / → / l | Expand or collapse a project, pipeline or stage |
| ← / h | Collapse, or move to parent |
| Page Up / Down, Home / End | Move through long lists |
| / | Filter projects and pipelines |
| ↑ / ↓ while filtering | Select a search result |
| Enter while filtering | Expand selected result and resume navigation |
| Tab while filtering | Resume navigation without expanding |
| Esc | Clear filter, then close |
| r | Refresh the selected project and expanded pipeline |
| Shift + R | Rediscover projects from GitLab |
| o | Open the selected project, pipeline or job on GitLab |
| y | Copy the selected row's GitLab URL |
| Shift + Y | Copy the pipeline's commit SHA |
| p | Pin or unpin the selected project |
| t | Open the selected job's log in a terminal |
| w | Watch or stop watching the selected pipeline |
| g / G | First or last row |
| e | Next failed pipeline, stage, job or `»` row |
| ? | Show or hide this help in the panel |
| q | Close the panel, or the help |
| Ctrl + = / Ctrl + + | Make the panel larger |
| Ctrl + - | Make it smaller |
| Ctrl + 0 | Reset the size |

`e` only looks at rows already shown, and never opens a pipeline.

Searching keeps the rows you opened open, and a project that matches only through one of its pipelines opens by itself. Left closes such a project for that search, and clearing the search restores what you had opened.

The zoom multiplies the theme's `[font] base-size`, ranges from 75% to 200%, and resets when the shell restarts.

Icons accompany the GitLab status:

| Icon | Status |
| --- | --- |
| ● | running, canceling |
| ✓ | success |
| ✕ | failed, error, unavailable |
| ! | allowed to fail |
| ▶ | manual |
| ◷ | scheduled |
| ◌ | created, pending, waiting_for_resource, preparing, waiting_for_callback, queued, awaiting final status |
| − | skipped |
| ⊘ | canceled |
| · | neutral |
| ○ | anything else |

Merge-request pipelines show `!N` for their branch. Times count up live, and finished rows say how long ago they ended. Failed jobs show the failure reason and the queue time, and project rows say when they were last checked and show the latest known pipeline as `last <status> <age>`.

Running is now `●` and scheduled is `◷`. A failed job that is allowed to fail shows `!` with "allowed to fail", and skipped jobs are dimmed.

Stage status follows GitLab's rules, in this order:

1. Running, if any job in the stage is running.
2. Otherwise failed, if a job failed that is not `allow_failure`.
3. Otherwise pending, then canceled, then success.

`»` rows are trigger jobs and show their downstream pipeline's status; `t` and `w` do not apply to them (use the parent pipeline row for `w`). Stage rows show completed/total jobs. Press **t** on a job to follow its log in a terminal (`glab ci trace`), or **o** to open it on GitLab. If the terminal launcher fails within two seconds, the panel stays open and says `Could not open a terminal`. A terminal that fails later is not reported by the panel; errors after the terminal opens show in that window.

## Open on the current repository

Add an alias to your shell:

```bash
alias glp='python3 ~/.config/omarchy/plugins/olafkfreund.gitlab-pipelines/menu.py open'
```

`glp` in a checkout opens the panel on its `origin` project, and `glp group/project` opens it filtered on any text. For scripts:

```bash
omarchy-shell shell summon olafkfreund.gitlab-pipelines '{"filter":"group/project"}'
```

A remote on a different host than the panel's shows a notice instead of filtering. Only `origin` is read.

## Pinned projects

- **p** pins or unpins the selected project (any row inside it).
- Pinned projects sort first and show `★`.
- Pins made with **p** are stored per host in `$XDG_STATE_HOME/omarchy-gitlab-pipelines/pinned.json` (default `~/.local/state/…`). The panel never writes `shell.json`.
- `pinned` in `shell.json` also pins; those cannot be unpinned with **p** (`Pinned in shell.json`).
- At most 10 apply: `shell.json` pins first, then **p** pins in the order made. Extra saved pins stay saved and apply again when room is made; **p** at the cap says `At most 10 pins`.
- A pin only shows when the account can see the project.
- An unreadable or invalid `pinned.json` is never overwritten; the panel says `Pins not saved: …`. Fix or delete the file.

## Watching a pipeline

- **w** watches or stops watching the selected pipeline (its row, or any stage or job row inside it). Watched pipelines show `◉`.
- A pipeline counts as finished when GitLab reports `success`, `failed`, `canceled` or `skipped`; `manual` and `scheduled` ones can be watched. A pipeline that stops at a manual job is not finished: its watch stays until the job runs or the 6 hours pass.
- A desktop notification (`notify-send`) is sent when it finishes, naming the project, number, ref and result. The watch then ends. Notifications follow the desktop's do-not-disturb setting: while notifications are silenced, they are not shown.
- At most 5 watches. A watch ends 6 hours after **w**, with a notification.
- While the panel is closed, only watched pipelines are checked, about every 30 seconds on a healthy server, within the same request limits. Nothing is checked once the last watch ends.
- A permission error or a deleted pipeline ends that watch. A sign-in problem while closed ends all watches with one notification. Network errors are retried.
- Changing `host`, restarting the shell or logging out ends all watches (the last two silently).
- A notification that cannot be sent shows in the footer the next time the panel opens.

## Refresh and errors

While open, one scheduler fetches a single API page at a time. Selecting a project waits 250 ms before fetching its missing or stale data, so rapid navigation does not trigger requests for every project you pass.

| Data | Refresh target |
| --- | --- |
| Inspected unfinished pipeline's jobs | 5 seconds |
| Selected project activity | 10 seconds |
| Other projects with running pipelines, pinned or not | 15 seconds |
| Selected full pipeline summary | 60 seconds |
| Idle pinned projects | 60 seconds |
| Idle projects | 10 minutes, backing off to 60 while nothing runs (projects inactive for a week start at 60) |
| Project list | 5 minutes while open |
| Watched pipelines | 30 seconds, also while the panel is closed |

A project whose last activity changes in the project list is checked next. GitLab updates that time at most once an hour, and scheduled pipelines may not change it, so a short pipeline on an idle project can start and finish without being shown as running. Pin a project to check it every minute.

A queued pipeline on a project you are not viewing is looked up every 15 seconds at first, backing off to every 5 minutes while it stays queued.

Request slots are shared as follows:

- Three slots serve selected data, one serves projects with running pipelines, then idle pinned projects, and one serves background discovery. Spare slots serve pins before background work. Under a busy schedule (the selected project plus several running projects) idle pins wait.
- All paths, including manual refresh, share a limit of 60 pages per rolling minute, at least one second between request starts, and one request in flight.
- Full summaries cover every unfinished status (`running`, `pending`, `created`, `waiting_for_resource`, `preparing`) plus the ten most recent pipelines.
- `manual` and `scheduled` pipelines appear in history but do not count as running.

When a running pipeline disappears from the running list, the panel fetches its final status rather than assuming success. A finished pipeline's jobs are fetched once and reused until you refresh, or until the pipeline is retried: GitLab updates a retried pipeline's `updated_at`, and that triggers a new fetch.

GitLab's `Retry-After` and `RateLimit-Reset` headers pause all work. A rate limit without a deadline starts with a one-minute wait and backs off up to fifteen minutes. Network and server errors back off the affected resource from five seconds up to five minutes. Permission failures leave that project unavailable until the panel reopens or you refresh (`r` or `R`). Authentication failures pause polling until you retry or reopen. Manual refresh never bypasses a server cooldown.

Errors and pauses show in a line under the search box, with the key that fixes them: `r` after a login or setup stop, `R` after a project-list failure (press Esc first if the search box has focus).

Closing the panel cancels the helper and its `glab` child. While the panel is closed, only watched pipelines are polled (see [Watching a pipeline](#watching-a-pipeline)). Each request times out after 25 seconds and shares your account's GitLab API quota with other tools.

## Known limits

- **Downstream pipelines**: downstream and child pipelines show as `»` rows inside the trigger job's stage, with their status. Their own jobs are not shown. The times on a `»` row are the trigger job's. A downstream waiting in manual or scheduled stops refreshing until you press `r`.
- **Stage order** follows job creation. Pipelines built with `needs:` can show a stage later than the GitLab UI does.
- **Pipeline durations** in lists start at creation time, so they include queue time until the pipeline is looked up individually.

## Checks

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
node tests/model.cjs
node tests/polling.cjs
python3 tests/qml-smoke.py
```

The flake runs the Python, model and polling suites without a graphical session or live GitLab requests:

```sh
nix flake check
nix build .#default
omarchy plugin validate "$(readlink -f result)"
python3 tests/qml-smoke.py ./result
```

Node is only used by the tests. The QML check needs a graphical session, Quickshell and `OMARCHY_PATH`. It runs against a fake API in a temporary configuration, without installing the plugin.

### Testing

The QML check also runs in CI, inside a NixOS VM with a real nixarchy session:

```bash
nix build ./ci#checks.x86_64-linux.qml-smoke -L
```

This boots a VM, so it needs KVM, and `nix flake check` does not run it. To move the nixarchy version it tests against:

```bash
nix flake update nixarchy --flake ./ci
```

### Accessibility

Rows expose a list-item role and a name (title, kind, pinned/watched, status), the list and search box have names, and the footer exposes its current text, for screen readers and automation.

## Development process

Changes follow an **intent → spec → plan** workflow. Each task has one slug, `YYYY-MM-DD-<issue>-<slug>`, shared by `intent/`, `spec/` and `plan/`. Each file carries `status: draft | approved`, and each approval is its own commit. No implementation starts before the plan is approved, and review checks the diff against the plan.

## Remove

- **Git installation:** `omarchy plugin remove olafkfreund.gitlab-pipelines`.
- **Nix installation:** remove the declarative plugin entry and rebuild.

Then remove both keybindings, and the `apps.gitlab-pipelines` and `learn.gitlab-pipelines-keybindings` menu entries.
