---
status: draft
issue: 1
author: olafkfreund
---

# Intent: Port the GitHub Actions panel to GitLab pipelines

## Problem

The Omarchy GitHub Actions panel ([nixarchy-ghtui](https://github.com/olafkfreund/nixarchy-ghtui))
only understands GitHub. Pipelines on GitLab (gitlab.com or self-managed) can
only be followed in a browser, with no keyboard-driven, themed overview on the
desktop.

The GitHub code cannot simply be pointed at GitLab. The CLI (`gh` vs `glab`), the
REST endpoints, the status model (`status` + `conclusion` vs a single `status`),
the hierarchy (GitLab jobs have no steps), re-run detection (`run_attempt`),
pagination, rate-limit headers and project naming (nested groups) all differ.

## Proposed outcome

A separate plugin, `olafkfreund.gitlab-pipelines`, in this repository that gives
GitLab users the same experience as the GitHub panel:

- Same visual design, theme use, 1.5× text scale and keyboard model.
- Automatic discovery of the user's GitLab projects, with running pipelines first.
- Drill-down **project → pipeline → stage → job** in place of repo → run → job → step.
- The same polling guarantees: one request in flight, per-minute ceilings, back-off,
  rate-limit cooldowns, and no polling while closed.
- **Apps → GitLab Pipelines** and **Learn → GitLab Pipelines keybindings** menu
  entries, shortcut **Super+Alt+P**, keybindings reference **Super+Ctrl+Alt+P**.
- Git and Nix flake installation routes, as in the GitHub plugin.
- It can be installed alongside the GitHub plugin without conflict.

## Affected users and systems

This new public repository, and Omarchy/Nixarchy users with GitLab projects.
The GitHub plugin repository is only a source to copy from; it is not changed.
Host configurations (P620, Razer) are a later consumer task.

## Constraints

- Keep the GitHub plugin's design and every feature, apart from the step level that GitLab lacks.
- Use `glab`'s existing authentication (`read_api`). Never read, extract or store tokens.
- Support nested group paths. Validate every project id, pipeline id and page
  number before it reaches `glab api`.
- Only allow browser links to the configured GitLab host.
- Unique plugin id, menu keys, layer namespace and shortcuts, so this plugin
  coexists with `olafkfreund.github-actions`. Super+Alt+G is taken by Omarchy's
  "Move active window out of group", so it is not used.
- Respect user-owned and managed menu, shell and keybinding files, as the GitHub plugin does.
- No new runtime dependencies beyond `glab`, Python 3 and `xdg-open`. Node is for tests only.
- Tests must not make live GitLab requests.

## Open questions

Defaults below apply unless the approver changes them:

1. **Host:** default `gitlab.com`, with an optional `host` setting in
   `shell.json` for self-managed GitLab.
2. **`manual` and `scheduled` pipelines:** shown in history, but not counted as
   running and not given faster polling.
3. **Shortcut:** Super+Alt+P and Super+Ctrl+Alt+P (both free on this desktop).
4. **License:** the repository is public without a license. Pick one (e.g. MIT) or leave none.
