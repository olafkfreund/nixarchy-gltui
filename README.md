# GitLab Pipelines for Omarchy

A flat, keyboard-driven Quickshell popup for GitLab projects → pipelines → stages → jobs, hosted inside `omarchy-shell`. It can also retry, cancel, play and start pipelines when you turn actions on. It discovers every project you are a member of, including nested groups, and lists projects with running pipelines first. It uses the current Omarchy menu colours, fonts, spacing, border and corner radius, and follows the theme font size (`[font] base-size`). There are no buttons, and no background daemon, database or token storage.

It is the GitLab sibling of [nixarchy-ghtui](https://github.com/olafkfreund/nixarchy-ghtui) (GitHub Actions), with the same design and behaviour. Both plugins can be installed side by side.

## Requirements

- Omarchy shell with the panel plugin contract and `qs.Commons` / `qs.Ui` components.
- [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use, or with an environment token (see [Authentication](#authentication)). The token needs the `read_api` scope, and the `api` scope if you turn on [actions](#actions), which write to GitLab.
- Python 3, `xdg-open` for the browser shortcut, `wl-copy` (wl-clipboard) for the copy keys, and a terminal that `xdg-terminal-exec` can start with a command (Omarchy's terminals can) for the log key. `notify-send` (libnotify) for watch notifications.

On NixOS, missing dependencies belong in your declarative configuration. Do not install them with pacman or an imperative Nix profile.

## Install

Make sure your running session matches the installed Omarchy generation first. If you rebuilt since login, log out and back in.

### Git installation

```sh
omarchy plugin add https://github.com/olafkfreund/nixarchy-gltui.git --enable
```

To add the separate bar widget, link its directory beside the panel plugin, then place it on the bar:

```sh
ln -s "$HOME/.config/omarchy/plugins/olafkfreund.gitlab-pipelines/bar-widget" "$HOME/.config/omarchy/plugins/olafkfreund.gitlab-pipelines-bar"
omarchy bar put olafkfreund.gitlab-pipelines-bar
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

The panel package supports `x86_64-linux` and `aarch64-linux` and contains only the plugin files. Adding it to `environment.systemPackages` does not register it with Omarchy. The Nixarchy module validates the package and links it into your plugin directory. Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab`'s stored login or an environment token (see [Authentication](#authentication)).

The flake also exposes `packages.<system>.bar` for the separate widget. Declaring that package as a nixarchy plugin and placing it on the bar is follow-up work; the panel's `default` package does not include it.

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

## Bar widget

The separate bar widget shows `●N` running pipelines and `✕N` failed projects. A failed project is one whose latest finished pipeline the panel has seen failed. Left click anywhere on the widget to toggle the panel.

Project counts are from the last project read; the tooltip shows that time. Watched pipelines can update the running count while the panel is closed. With several hosts, the widget sums the running and failed counts of every working or rate-limited host that has loaded counts, and adds one tooltip line per host (`<host>: ●N ✕M`, `paused until HH:MM`, `stopped — <reason>`, or `no data`). A stopped or paused host does not hide the other hosts' counts; the widget shows stopped only on a configuration error or when no host is working or paused, and rechecks at the earliest per-host pause deadline.

| State | Bar | Meaning |
| --- | --- | --- |
| No data | Dimmed GitLab glyph | Open the panel to load counts. |
| Ready | Glyph and nonzero counts; urgent colour when projects failed | The tooltip shows the host (or `<first> +N`), both counts and the last project read time. |
| Stopped | Urgent glyph and `!` | The tooltip names the configuration, login or project-list error. Open the panel to fix it. |
| Rate limited | Dimmed glyph and the last counts | The tooltip shows when GitLab polling resumes. The widget rechecks at that time. |

## Projects

No project list is needed. Opening the popup fetches every page of `GET /projects?membership=true`: the projects you are a direct or inherited member of, including nested groups. Projects are scanned in order of most recent activity. The list is refreshed every 5 minutes while the panel is open. Archived projects, and projects with CI/CD disabled, stay searchable but are not polled.

Press **/** and type a project path, description, pipeline name, branch or status (or a host name when more than one host is configured). Use **↑ / ↓** while typing to select a result, then **Enter** to expand it. **Tab** finishes editing without expanding. Projects with running pipelines move to the top as activity is discovered. Projects not yet checked say **not checked**, and the header shows scan progress. A project row's icon is the latest finished pipeline the panel has seen for it, on any branch, from selecting the project or from a pipeline seen running or queued, and the row says `last <status> <age>`, for example `0 running · last failed 2h ago · checked 3m ago`. Running pipelines and errors take precedence. Projects never selected and never seen running stay `·`, and a project with no pipelines says **no pipelines**. A newer pipeline that starts and finishes between idle checks is not seen until you select the project.

The catalogue and known activity stay in memory between openings. After five minutes, reopening refreshes the catalogue. **Shift + R** refreshes it immediately.

### Self-managed GitLab and settings

The default host is `gitlab.com`. For a self-managed instance, add `host` to this plugin's entry in `~/.config/omarchy/shell.json` (the first entry with `"id": "olafkfreund.gitlab-pipelines"` is read). Add `"actions": true` to turn on [actions](#actions); anything else leaves them off. You can also add `projects`, a list of project paths that are shown before discovery finishes; it does not limit discovery. `pinned` lists projects that sort first and are checked about every minute (see [Pinned projects](#pinned-projects)).

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

Keep any other keys already in that entry. Each host must be authenticated with `glab auth login --hostname gitlab.example.org` (or reachable by an environment token, see [Authentication](#authentication)). Browser links only open URLs on the row's configured host.

### Several hosts

To show up to 4 GitLab hosts in one panel, add a non-empty `hosts` array to the plugin entry. When `hosts` is present and non-empty, it replaces the top-level `host`, `actions`, `projects` and `pinned` keys (`"hosts": []` falls back to the top-level keys). Each item must be an object with a valid `host` string (`hostname` or `hostname:port`), and can set its own `actions`, `projects` and `pinned`:

```json
{
  "plugins": [
    {
      "id": "olafkfreund.gitlab-pipelines",
      "hosts": [
        {
          "host": "gitlab.com",
          "pinned": ["me/site"]
        },
        {
          "host": "gitlab.example.org",
          "actions": true,
          "projects": ["group/subgroup/project"],
          "pinned": ["group/project"]
        }
      ]
    }
  ]
}
```

- **Validation and cap.** Every item in `hosts` is validated first; a malformed `hosts` value or any invalid `host` entry stops all polling and actions with a configuration error. Duplicate hosts (compared case-insensitively, including the port) are dropped after the first. At most 4 hosts are kept; extra hosts are ignored, logged once, and named in a notice (`Ignored hosts: …; at most 4 are shown`) the next time the panel opens.
- **Rows and header.** Projects from all hosts share one list, sorted globally with pinned and running projects first. Each project and merge-request row shows a dimmed host label after its title, search matches the host name, and the header shows `N projects on K hosts`.
- **Independent state, shared read slot.** Each host has its own project list, merge requests, pins, rate-limit pause, auth stop, error line, and 60-requests-per-minute budget (at least one second between request starts on that host). All hosts share the panel's single in-flight read slot across the 3-1-1 schedule (interactive, active, background), cycling round-robin per urgency group so a busy host cannot starve background discovery on another. Because only one read runs at a time, a slow or unreachable host can delay the other hosts by up to one 25-second request timeout per turn until its error backoff grows.
- **Refresh.** **r** refreshes the selected row's host (every host when no row is selected); **Shift + R** refreshes every host.
- **Changing the host list.** Adding or removing a host in `shell.json` starts or drops only that host; removing a host ends its watches with a notification, cancels any unsent action for it, and keeps its request-budget history for 60 seconds in case it is re-added. Switching between one host and several hosts clears open rows, saved view filters and the cursor while keeping loaded project data.

### Authentication

The plugin uses your existing `glab` login and never reads, extracts or stores a token. A personal, group or project access token works if it has `read_api`; [actions](#actions) need `api`, and your role and the project's rules must allow them (normally Developer, subject to protected branches, protected environments and the project's cancel restriction). If a project is missing, confirm that `glab api projects?membership=true` lists it with the same login, then press **Shift + R**.

**Environment tokens.** `glab` prefers a token from the environment over its stored login: `GITLAB_TOKEN`, then `GITLAB_ACCESS_TOKEN`, then `OAUTH_TOKEN`, the first one set wins. It needs the same `read_api` scope. `glab` only sends such a token to some hosts: the default host (`GITLAB_HOST`), the host in `GITLAB_REPO`, and hosts already in its configuration. `glab config --help` has the full rules. With several hosts configured, `glab` will send an environment token to every host in `hosts` that is also in `glab`'s configuration (plus the default host), which may authenticate the wrong account or send a token to another instance; prefer per-host `glab auth login --hostname …` when using more than one host. The panel names its host only on the command line, so for any other host run `glab auth login --hostname …` once. Setting `GITLAB_HOST` for the whole session also works for a single host, but then every `glab` command in that session uses that host, and fails in repositories whose remotes do not match it.

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
| Enter / Space / → / l | Expand or collapse a project, pipeline or stage; on a merge request, jump to its pipeline |
| ← / h | Collapse, or move to parent |
| Page Up / Down, Home / End | Move through long lists |
| / | Filter projects and pipelines |
| ↑ / ↓ while filtering | Select a search result |
| Enter while filtering | Expand selected result and resume navigation |
| Tab while filtering | Resume navigation without expanding |
| Esc | Clear filter, then close |
| m | Switch between projects and My merge requests |
| r | Refresh the selected project and expanded pipeline (on its host) |
| Shift + R | Rediscover projects from GitLab (all configured hosts) |
| o | Open the selected project, pipeline or job on GitLab |
| y | Copy the selected row's GitLab URL |
| Shift + Y | Copy the pipeline's commit SHA |
| p | Pin or unpin the selected project |
| t | Open the selected job's log in a terminal |
| w | Watch or stop watching the selected pipeline |
| a | Retry the selected failed or canceled pipeline or job (actions on) |
| c | Cancel the selected running or queued pipeline or job (actions on) |
| x | Play the selected manual job (actions on) |
| n | Start a new pipeline on the selected pipeline's branch or tag (actions on) |
| y / Esc | While a confirmation shows: confirm or cancel the action |
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

When `origin` is on one of the panel's configured hosts (matched by hostname, ignoring port), the filter is restricted to that host until you edit the search text (if two configured hosts share the same hostname on different ports, both are searched). A remote on a host not shown by the panel shows a notice instead of filtering, and a filter without a host searches every configured host. Only `origin` is read.

## Pinned projects

- **p** pins or unpins the selected project (any row inside it) on its host.
- Pinned projects sort first and show `★`.
- Pins made with **p** are stored per host in `$XDG_STATE_HOME/omarchy-gitlab-pipelines/pinned.json` (default `~/.local/state/…`). The panel never writes `shell.json`.
- `pinned` in `shell.json` (at the top level or in a `hosts` entry) also pins; those cannot be unpinned with **p** (`Pinned in shell.json`).
- At most 10 apply per host: `shell.json` pins first, then **p** pins in the order made. Extra saved pins stay saved and apply again when room is made; **p** at the cap says `At most 10 pins`.
- A pin only shows when the account can see the project.
- An unreadable or invalid `pinned.json` is never overwritten; the panel says `Pins not saved: …`. Fix or delete the file.

## Watching a pipeline

- **w** watches or stops watching the selected pipeline (its row, or any stage or job row inside it). Watched pipelines show `◉`.
- A pipeline counts as finished when GitLab reports `success`, `failed`, `canceled` or `skipped`; `manual` and `scheduled` ones can be watched. A pipeline that stops at a manual job is not finished: its watch stays until the job runs or the 6 hours pass.
- A desktop notification (`notify-send`) is sent when it finishes, naming the project, number, ref and result (and `on <host>` when several hosts are configured). The watch then ends. Notifications follow the desktop's do-not-disturb setting: while notifications are silenced, they are not shown.
- At most 5 watches across the panel (shared across all configured hosts). A watch ends 6 hours after **w**, with a notification.
- While the panel is closed, only watched pipelines are checked, about every 30 seconds on a healthy server, within the same request limits. Nothing is checked once the last watch ends.
- A permission error or a deleted pipeline ends that watch. A sign-in problem while closed ends all watches on that host with one notification. Network errors are retried.
- Changing `host`, removing a host from `hosts`, restarting the shell or logging out ends the affected watches (the last two silently).
- A notification that cannot be sent shows in the footer the next time the panel opens.

## My merge requests

**m** switches the panel between projects and your open merge requests, and back. The panel reopens in the last view until the shell restarts. Each view keeps its own search text and selected row.

- **What is listed.** Open merge requests you created, newest update first, at most 50 across all projects per host (listed in host order when several hosts are configured). When there are more on a host, its last row says `N more on GitLab` (or `more on GitLab` when the count is unknown, with ` · <host>` when several hosts are configured); **o** opens your merge request dashboard on that host and **y** copies its link. It is read from the list, not the project catalogue, so projects outside your project list appear too.
- **Rows.** Each row shows `project !number title`, with `Draft · ` first for drafts, a dimmed host label when several hosts are configured, and the source branch below. The status is the merge request's head pipeline. A row is in one of four states: a pipeline (status icon), `no pipeline`, `pipeline hidden` (GitLab does not show pipelines of that project to you), or `unavailable` (no access to the merge request). Rows not yet looked up say `not checked`. A row not refreshed within its target below adds `checked 2m ago`. Search matches title, project, branch and status (and the host when several hosts are configured).
- **Keys.** **Enter**, **→**, **l** or **Space** jumps to the pipeline; **o** and **y** use the merge request's link (`No link` if it is not on the row's host); **r** refreshes the list and every row on the selected row's host, and **Shift + R** refreshes across all hosts. **p t w e a c x n**, **Shift + Y** and **←** / **h** only say `Not on a merge request; press Enter for its pipeline`. Navigation, search, help, zoom and **q** work as usual.
- **Jump.** Enter switches to the projects view with an empty filter, expands the project and pipeline on that host, and selects the pipeline. It needs the pipeline's project in your project list on that host and not archived or CI-disabled; otherwise the footer says `Project not in your list; o opens the merge request`. Other refusals: `No pipeline yet`, `Pipeline hidden`, `Not checked yet`, `Merge request unavailable; o opens it`.
- **Fork pipelines.** A merge request from a fork shows the pipeline of its head, which can belong to the fork's project. Jump follows that project, so it is refused when the fork is not in your project list.
- **Cost.** The view makes no calls while it is off. Selected-project refreshes pause while it is on.

## Actions

Actions write to GitLab, so they are off for a host until you set `"actions": true` in this plugin's entry (or in that host's entry in `hosts`) in `~/.config/omarchy/shell.json` (see [settings](#self-managed-gitlab-and-settings)). They need a token with the `api` scope; `read_api` is not enough. While they are off for the selected row's host, **a**, **c**, **x** and **n** only show `Actions are off: set "actions": true for this plugin in shell.json`, and the helper refuses writes for that host too.

| Key | On | Does | When |
| --- | --- | --- | --- |
| a | pipeline | Retry the pipeline | failed or canceled |
| a | job | Retry the job | failed or canceled |
| c | pipeline or job | Cancel it | created, waiting for resource, preparing, pending, running or scheduled |
| x | job | Play the job | manual |
| n | pipeline | Start a new pipeline on its branch or tag | any status, except merge-request pipelines |

Only a pipeline row or a job row offers an action, judged by the status GitLab reported, not the icon. When a key does not apply to the row, the footer says why, for example `Only a failed or canceled job can be retried`.

- **Confirm.** Every action first shows a question in the footer, for example `Retry pipeline #7 CI (main) in group/project? y yes · Esc no` (adding `on <host>` when several hosts are configured). Plain **y** sends it; **Esc** sends nothing. Every other key is ignored while the question shows, and Shift + Y or a held key does not confirm. The question names the project, pipeline, job and branch, and a cancel adds `Cannot be undone.`
- **Sent as shown.** The action is sent to the row and host you confirmed, even if the list re-sorts meanwhile. Changing `host`, removing that host, turning actions off for it or closing the panel before it is sent cancels it. One action runs at a time, and it starts at least one second after the last GitLab request on that host.
- **Result.** The footer shows the outcome for 10 seconds, for example `Retry requested: pipeline #7 CI (main) in group/project` (with `on <host>` when several hosts are configured), and the pipeline refreshes at once (after a rate-limit pause, the text adds `· refresh waits until HH:MM`). A new pipeline adds `· new pipeline #N`. A result that arrives after you closed the panel shows when you open it again; one that arrives after a host change, or a failed action when several hosts are configured, starts with `on <host>:`.
- **Failures.** `GitLab rate limit` (polling on that host pauses too), `Authenticate with glab auth login`, `Needs a token with the api scope`, `GitLab refused: <reason>` (permissions, a state that changed, a protected branch), `Install glab (GitLab CLI)`. `Outcome unknown; check GitLab before retrying` means the request may have reached GitLab (timeout, server error, unreadable reply): look at the pipeline before pressing the key again.
- **Not offered.** Merge-request pipelines (a new pipeline cannot be started from them), `»` trigger rows, stage rows, whole manual stages, pipeline variables (new and played jobs use their defaults), retrying a successful job, and cancelling a manual job.

## Refresh and errors

While open, one scheduler fetches a single API page at a time across all configured hosts. Selecting a project waits 250 ms before fetching its missing or stale data, so rapid navigation does not trigger requests for every project you pass.

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
| Merge-request list | 60 seconds while the merge-request view is on |
| Selected merge request | 10 seconds while its pipeline is unfinished, otherwise 60 seconds |
| Other merge requests | 30 seconds while unfinished, otherwise 10 minutes (also when the list shows a newer update); unchecked ones first |

A project whose last activity changes in the project list is checked next. GitLab updates that time at most once an hour, and scheduled pipelines may not change it, so a short pipeline on an idle project can start and finish without being shown as running. Pin a project to check it every minute.

A queued pipeline on a project you are not viewing is looked up every 15 seconds at first, backing off to every 5 minutes while it stays queued.

Request slots are shared as follows:

- Three slots serve selected data, one serves projects with running pipelines, then idle pinned projects, and one serves background discovery. Spare slots serve pins before background work. Under a busy schedule (the selected project plus several running projects) idle pins wait. With several hosts, the panel rotates through the same five-slot pattern and picks round-robin within the earliest ready group across hosts.
- Actions are the exception: they do not count toward the page limit or the request starts, but one starts only a second after the last request on its host, and it can run while a read is in flight. All other paths, including manual refresh, have a per-host limit of 60 pages per rolling minute and at least one second between request starts on that host, and share one request in flight across the panel.
- Full summaries cover every unfinished status (`running`, `pending`, `created`, `waiting_for_resource`, `preparing`) plus the ten most recent pipelines.
- `manual` and `scheduled` pipelines appear in history but do not count as running.
- Merge-request lookups are background work: under sustained selected or running-project load they still get one request in every five.

When a running pipeline disappears from the running list, the panel fetches its final status rather than assuming success. A finished pipeline's jobs are fetched once and reused until you refresh, or until the pipeline is retried: GitLab updates a retried pipeline's `updated_at`, and that triggers a new fetch.

When a watched pipeline finishes while the panel is closed, its final lookup updates the running count if it was still counted. A run already removed from GitLab's activity total is not subtracted again.

GitLab's `Retry-After` and `RateLimit-Reset` headers pause all work on that host. A rate limit without a deadline starts with a one-minute wait and backs off up to fifteen minutes. Network and server errors back off the affected resource from five seconds up to five minutes. Permission failures leave that project unavailable until the panel reopens or you refresh (`r` or `R`). Authentication failures pause polling on that host until you retry or reopen. Manual refresh never bypasses a server cooldown.

Errors and pauses show under the search box (one line per stopped or paused host, prefixed with the host name when several hosts are configured), with the key that fixes them: `r` after a login or setup stop, `R` after a project-list failure (press Esc first if the search box has focus). A host that fails after loading keeps its cached rows while the other hosts continue updating.

Closing the panel cancels the helper and its `glab` child, except an action already sent, which finishes (see [Actions](#actions)). While the panel is closed, only watched pipelines are polled (see [Watching a pipeline](#watching-a-pipeline)). Each request times out after 25 seconds and shares your account's GitLab API quota with other tools.

## Known limits

- **Downstream pipelines**: downstream and child pipelines show as `»` rows inside the trigger job's stage, with their status. Their own jobs are not shown. The times on a `»` row are the trigger job's. A downstream waiting in manual or scheduled stops refreshing until you press `r`.
- **My merge requests**: capped at 50 per host (the rest are one link away); a project outside your project list on that host cannot be jumped into; `pipeline hidden` relies on GitLab leaving the pipeline field out of the reply for users who cannot read pipelines.
- **Stage order** follows job creation. Pipelines built with `needs:` can show a stage later than the GitLab UI does.
- **Pipeline durations** in lists start at creation time, so they include queue time until the pipeline is looked up individually.
- **Bar counts** stay at their last project read while the panel is closed, except for watched pipelines. Failed projects cover only pipelines the panel has seen. Two shells on the same Wayland display share one status file.

## Checks

Run from the repository root:

```sh
python3 -m unittest discover -s tests -v
node tests/model.cjs
node tests/polling.cjs
node tests/bar.cjs
python3 tests/qml-smoke.py
```

The flake runs the Python, model, polling and bar suites without a graphical session or live GitLab requests:

```sh
nix flake check
nix build .#default
omarchy plugin validate "$(readlink -f result)"
python3 tests/qml-smoke.py ./result
```

Build the widget package separately with `nix build .#bar --no-link`.

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

Rows expose a list-item role and a name (title, kind, pinned/watched, status, and `on <host>` when several hosts are configured), the list and search box have names, and the footer exposes its current text, for screen readers and automation.

## Development process

Changes follow an **intent → spec → plan** workflow. Each task has one slug, `YYYY-MM-DD-<issue>-<slug>`, shared by `intent/`, `spec/` and `plan/`. Each file carries `status: draft | approved`, and each approval is its own commit. No implementation starts before the plan is approved, and review checks the diff against the plan.

## Remove

- **Git installation:** `omarchy plugin remove olafkfreund.gitlab-pipelines`.
- **Nix installation:** remove the declarative plugin entry and rebuild.

Remove `olafkfreund.gitlab-pipelines-bar` from the bar layout and remove its `~/.config/omarchy/plugins/olafkfreund.gitlab-pipelines-bar` link as well. For a declarative installation, remove its widget entry from your configuration and rebuild.

Then remove both keybindings, and the `apps.gitlab-pipelines` and `learn.gitlab-pipelines-keybindings` menu entries.
