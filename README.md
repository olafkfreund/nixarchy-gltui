# GitLab Pipelines for Omarchy

> **Status: in development.** The design is being agreed through the
> [artifact workflow](#development-process); the plugin is not installable yet.
> This README describes the intended behaviour and will be updated as it ships.

A flat, keyboard-driven Quickshell popup for GitLab projects → pipelines → stages → jobs, hosted inside `omarchy-shell`. It is the GitLab sibling of [nixarchy-ghtui](https://github.com/olafkfreund/nixarchy-ghtui) (GitHub Actions) and keeps the same design: current Omarchy menu colours, fonts, spacing, border and corner radius, text at 1.5× theme font size, and no buttons, background daemon, database or token storage.

Both plugins can be installed side by side.

## Features

- **Automatic discovery** of every project you are a member of, including nested groups (`group/subgroup/project`). No manual project list.
- **Running pipelines first**, with pipelines that are still active sorted to the top as activity is discovered.
- **Drill-down**: project → pipeline → stage → job, with live status and duration.
- **Search** across project path, description, branch, pipeline name and status.
- **Smart polling** while open and none while closed. Only one request is in flight at a time, and the plugin honours GitLab rate limits.
- **Open in browser**: jump to the selected project, pipeline or job on GitLab.
- **gitlab.com and self-managed GitLab** through your existing `glab` login.
- **Omarchy integration**: **Apps → GitLab Pipelines**, a searchable **Learn → GitLab Pipelines keybindings** reference, and a Hyprland shortcut.

## Requirements

- Omarchy shell with the panel plugin contract and `qs.Commons` / `qs.Ui` components.
- [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login`. The token needs the `read_api` scope.
- Python 3, and `xdg-open` for the browser shortcut.

On NixOS, missing dependencies belong in your declarative configuration. Do not install them with pacman or an imperative Nix profile.

## Install (planned)

### Git installation

```sh
omarchy plugin add https://github.com/olafkfreund/nixarchy-gltui.git --enable
```

### Nix flake installation

Add the input to your NixOS flake. Nixarchy and its Home Manager module must already be enabled for your user:

```nix
inputs.gitlab-pipelines = {
  url = "github:olafkfreund/nixarchy-gltui";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

Then register the plugin for your user, replacing `YOUR_USER`:

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

Build and activate through NixOS, then enable the plugin once in the running session:

```sh
nixos-rebuild build --flake .#HOST
sudo nixos-rebuild switch --flake .#HOST
omarchy plugin enable olafkfreund.gitlab-pipelines
```

Never put tokens in `flake.nix` or `flake.lock`. Runtime API access comes from `glab auth login`.

### Keyboard shortcuts

Suggested chords, both unused on a default Omarchy desktop (Super+Alt+G is taken by *Move active window out of group*):

| Chord | Action |
| --- | --- |
| **Super + Alt + P** | Open or close GitLab Pipelines |
| **Super + Ctrl + Alt + P** | GitLab Pipelines keybindings |

Check `omarchy menu keybindings --print` for conflicts, then add the lines from `bindings.example.lua` to `~/.config/hypr/bindings.lua`. Validate with `hyprctl reload` and `hyprctl configerrors`.

## Panel keys

| Key | Action |
| --- | --- |
| ↑ / ↓ or k / j | Select a row |
| Enter / Space / → / l | Expand or collapse a project, pipeline or stage |
| ← / h | Collapse, or move to parent |
| Page Up / Down, Home / End | Move through long lists |
| / | Filter projects and pipelines |
| Esc | Clear filter, then close |
| r | Refresh the selected project and expanded pipeline |
| Shift + R | Rediscover projects from GitLab |
| o | Open the selected row on GitLab |

Status icons: ✓ success, ✕ failed, ◷ running, ○ created/pending/waiting, ⊘ canceled, − skipped/manual.

## How it maps from GitHub Actions

| GitHub Actions plugin | GitLab Pipelines plugin |
| --- | --- |
| `gh api` | `glab api` |
| Repository (`owner/name`) | Project (`group/…/project`, numeric id) |
| Workflow run | Pipeline |
| Job → step | Stage → job (GitLab has no steps API) |
| `Link` pagination | `X-Next-Page` |
| `x-ratelimit-*` headers | `RateLimit-*`, `Retry-After`, HTTP 429 |

## Development process

Changes follow an **intent → spec → plan** workflow. Each task has one slug `YYYY-MM-DD-<issue>-<slug>` shared by:

- `intent/<slug>.md`: the why (problem, outcome, constraints, open questions)
- `spec/<slug>.md`: the what (design, rejected alternatives, risks, verification)
- `plan/<slug>.md`: the how (ordered steps, tests, rollback)

Each file carries `status: draft | approved`, and each approval is its own commit. No implementation starts before the plan is approved. Pull requests link all three files, and review checks the diff against the plan.

## Checks (planned)

```sh
python3 -m unittest discover -s tests -v
node tests/model.cjs
node tests/polling.cjs
python3 tests/qml-smoke.py
nix flake check
```

The tests use fake API replies, never live GitLab requests.
