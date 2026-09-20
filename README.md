# GitLab Pipelines for Omarchy

A flat, keyboard-driven Quickshell popup for GitLab projects → pipelines → stages → jobs, hosted inside `omarchy-shell`. It discovers every project you are a member of, including nested groups, and lists projects with running pipelines first. It uses the current Omarchy menu colours, fonts, spacing, border and corner radius, with text at 1.5× theme font size. There are no buttons, and no background daemon, database or token storage.

It is the GitLab sibling of [nixarchy-ghtui](https://github.com/olafkfreund/nixarchy-ghtui) (GitHub Actions), with the same design and behaviour. Both plugins can be installed side by side.

## Requirements

- Omarchy shell with the panel plugin contract and `qs.Commons` / `qs.Ui` components.
- [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use. The token needs the `read_api` scope.
- Python 3, and `xdg-open` for the browser shortcut.

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
    home.packages = [ pkgs.glab pkgs.python3 pkgs.xdg-utils pkgs.bash ];
  };
}
```

The package supports `x86_64-linux` and `aarch64-linux` and contains only the plugin files. Adding it to `environment.systemPackages` does not register it with Omarchy. The Nixarchy module validates the package and links it into your plugin directory. Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab auth login`.

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

No project list is needed. Opening the popup fetches every page of `GET /projects?membership=true`: the projects you are a direct or inherited member of, including nested groups. Projects are scanned in order of most recent activity. Archived projects, and projects with CI/CD disabled, stay searchable but are not polled.

Press **/** and type a project path, description, pipeline name, branch or status. Use **↑ / ↓** while typing to select a result, then **Enter** to expand it. **Tab** finishes editing without expanding. Projects with running pipelines move to the top as activity is discovered. Projects not yet checked say **not checked**, and the header shows scan progress.

The catalogue and known activity stay in memory between openings. After five minutes, reopening refreshes the catalogue. **Shift + R** refreshes it immediately.

### Self-managed GitLab and settings

The default host is `gitlab.com`. For a self-managed instance, add `host` to this plugin's entry in `~/.config/omarchy/shell.json`. You can also add `projects`, a list of project paths that are shown before discovery finishes; it does not limit discovery.

```json
{
  "plugins": [
    {
      "id": "olafkfreund.gitlab-pipelines",
      "host": "gitlab.example.org",
      "projects": ["group/subgroup/project"]
    }
  ]
}
```

Keep any other keys already in that entry. The host must be authenticated with `glab auth login --hostname gitlab.example.org`. Browser links only open URLs on the configured host. One host is shown at a time.

### Authentication

The plugin uses your existing `glab` login and never reads, extracts or stores a token. A personal, group or project access token works if it has `read_api`. If a project is missing, confirm that `glab api projects?membership=true` lists it with the same login, then press **Shift + R**.

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

Icons accompany the GitLab status:

| Icon | Status |
| --- | --- |
| ✓ | success |
| ✕ | failed |
| ◷ | running, canceling |
| ○ | created, pending, preparing, waiting |
| ⊘ | canceled |
| − | skipped, manual, scheduled |

Stage status follows GitLab's rules, in this order:

1. Running, if any job in the stage is running.
2. Otherwise failed, if a job failed that is not `allow_failure`.
3. Otherwise pending, then canceled, then success.

Stage rows show completed/total jobs. Open GitLab for logs.

## Refresh and errors

While open, one scheduler fetches a single API page at a time. Selecting a project waits 250 ms before fetching its missing or stale data, so rapid navigation does not trigger requests for every project you pass.

| Data | Refresh target |
| --- | --- |
| Inspected unfinished pipeline's jobs | 5 seconds |
| Selected project activity | 10 seconds |
| Other projects with running pipelines | 15 seconds |
| Selected full pipeline summary | 60 seconds |
| Previously checked idle projects | 10 minutes |

Request slots are shared as follows:

- Three slots serve selected data, one serves projects with running pipelines, and one serves background discovery. Spare slots serve other due work.
- All paths, including manual refresh, share a limit of 60 pages per rolling minute, at least one second between request starts, and one request in flight.
- Full summaries cover every unfinished status (`running`, `pending`, `created`, `waiting_for_resource`, `preparing`) plus the ten most recent pipelines.
- `manual` and `scheduled` pipelines appear in history but do not count as running.

When a running pipeline disappears from the running list, the panel fetches its final status rather than assuming success. A finished pipeline's jobs are fetched once and reused until you refresh, or until the pipeline is retried: GitLab updates a retried pipeline's `updated_at`, and that triggers a new fetch.

GitLab's `Retry-After` and `RateLimit-Reset` headers pause all work. A rate limit without a deadline starts with a one-minute wait and backs off up to fifteen minutes. Network and server errors back off the affected resource from five seconds up to five minutes. Permission failures leave that project unavailable until the next catalogue or manual refresh. Authentication failures pause polling until you retry or reopen. Manual refresh never bypasses a server cooldown.

Closing the panel cancels the helper and its `glab` child. Nothing is polled while the panel is closed. Each request times out after 25 seconds and shares your account's GitLab API quota with other tools.

## Known limits

- **Downstream pipelines** (trigger/bridge jobs) are not shown, only the parent pipeline's own jobs.
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

## Development process

Changes follow an **intent → spec → plan** workflow. Each task has one slug, `YYYY-MM-DD-<issue>-<slug>`, shared by `intent/`, `spec/` and `plan/`. Each file carries `status: draft | approved`, and each approval is its own commit. No implementation starts before the plan is approved, and review checks the diff against the plan.

## Remove

- **Git installation:** `omarchy plugin remove olafkfreund.gitlab-pipelines`.
- **Nix installation:** remove the declarative plugin entry and rebuild.

Then remove both keybindings, and the `apps.gitlab-pipelines` and `learn.gitlab-pipelines-keybindings` menu entries.
