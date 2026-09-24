---
status: draft
issue: 6
author: olafkfreund
---

# Intent: Panel text and window follow desktop size and scale

## Problem

The GitLab Pipelines panel ignores the desktop's size and font settings:

- Every font is multiplied by a fixed 1.5 (`ActionsPanel.qml:36`) on top of
  `Style.font.*`, which already follows the user's `[font] base-size`. Users who
  raise or lower their font size get text 1.5× what they chose.
- The panel is capped at a fixed 900×680 logical size
  (`ActionsPanel.qml:232-233`). On large or high-resolution screens it stays
  small and most of the screen is unused.
- Row heights have fixed minimums (`ActionsPanel.qml:327`), so scaled text can
  clip. The divider (`:314`) and a text-width offset (`:343`) use raw numbers
  instead of the host's tokens.

Hyprland's per-monitor scale is not part of the problem: Wayland logical pixels
already carry it.

## Proposed outcome

- Panel text is the same size as text in the host's own menus and panels at
  any `[font] base-size`.
- The panel grows and shrinks with the screen it opens on, and stays inside the
  screen with the usual gaps on small screens.
- No text clips in rows at small or large font sizes.
- Lines and spacing use the host's `Style` tokens, so theme changes apply.

## Affected users and systems

- `ActionsPanel.qml` only; the Python helpers, polling and model are unchanged.
- Everyone running the plugin in omarchy-shell, on any monitor or scale.
- `tests/qml-smoke.py` if it asserts sizes.

## Constraints

- Use the host's `Style` and `Border` tokens; add no new dependency or setting
  unless the open question below says so.
- Must not change keyboard behaviour, polling or data handling.
- Must still pass `nix flake check` and `omarchy plugin validate`.

## Open questions

1. Should the panel keep text larger than the host's menus (the reason 1.5 may
   have been added), or match them exactly? If larger, should it be a
   `shell.json` setting instead of a constant?
2. How much of the screen should the panel take: a fixed fraction (for example
   60% × 70%), or the host's menu size if it exposes one?
