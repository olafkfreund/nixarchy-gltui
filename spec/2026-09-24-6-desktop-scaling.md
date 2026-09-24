---
status: approved
issue: 6
intent: intent/2026-09-24-6-desktop-scaling.md
---

# Spec: Panel text and window follow desktop size and scale

## Design

All changes are in `ActionsPanel.qml` and use the host's `qs.Commons` `Style`
tokens, which already follow `[font] base-size` and `[spacing] scale`
(omarchy-shell `Commons/Style.qml`). Wayland logical pixels already carry the
Hyprland monitor scale.

1. **Text matches the host (open question 1).** Delete `textScale` (`:36`) and
   use `Style.font.title`, `Style.font.body` and `Style.font.caption` as they
   are. The user's `[font] base-size` then controls the panel the same way it
   controls the host's menus. Users who want larger text raise `base-size`.
2. **Panel grows with the screen (open question 2).** The card at `:232-233`
   becomes:
   - width  `Math.min(Math.max(Style.space(900), Math.round(window.width * 0.6)), window.width - Style.gapsOut * 2)`
   - height `Math.min(Math.max(Style.space(680), Math.round(window.height * 0.7)), window.height - Style.gapsOut * 2)`

   The current size stays the minimum, so small and normal screens look the
   same. Large screens get 60% × 70%. The screen edge still clamps it, as the
   host's `Menu.qml:111` does.
3. **Rows follow text height.** Row heights at `:327` use the host's menu
   formula (`Menu.qml:102-103`):
   - plain row `Math.max(Style.space(40), Style.font.body + Style.spacing.rowPaddingX * 2)`
   - row with subtitle `Math.max(Style.space(64), Style.font.body + Style.font.caption + Style.spacing.rowPaddingX * 2)`
4. **Tokens instead of raw numbers.**
   - `:314` divider `height: 1` → `Style.spacing.hairline`.
   - `:343` `Style.space(26)` → `<icon>.width + parent.spacing`, reading the
     icon item's real width.
   - The search field height at `:281` (`font.pixelSize * 1.4`) stays; it
     already follows the font.

## Alternatives rejected

- **Keep 1.5× or make it a `shell.json` `textScale` setting.** Rejected because
  it duplicates `[font] base-size`, which already exists and applies everywhere.
  This is easy to add later if the user wants the panel alone larger.
- **Copy the host menu's fixed width (`Style.space(300)`/`520`).** Too narrow
  for pipeline and job rows, and it does not grow with the screen, which is the
  point of the issue.
- **Pure screen fraction with no minimum.** On a 1280-wide screen the panel
  would shrink below today's size.
- **Reading `Screen.devicePixelRatio` or the Hyprland scale by hand.** Not
  needed; Qt and Wayland already apply it, and doing it again would scale twice.

## Risks

- Text is a third smaller than today at the same `base-size`. Users who liked
  the old size need to raise `base-size`, which also enlarges the rest of the
  shell. The README should say so.
- A larger card on big screens shows more rows. `rebuild()`'s scroll
  preservation (`:70-93`) is untested and may behave differently with more
  visible rows.
- `tests/qml-smoke.py` may check sizes or `textScale`. Update it if so.

## Verification

- `nix flake check` passes (Python, Node and QML smoke).
- `python3 tests/qml-smoke.py` passes against source and `./result`.
- `omarchy plugin validate "$(readlink -f result)"` exits 0.
- `grep -n 'textScale\|height: 1\b\|space(26)' ActionsPanel.qml` returns nothing.
- Manual: open the panel with `base-size` 12 and 18, and on a 1080p and a
  4K/1.5-scale monitor. Text matches the host menu, rows do not clip, and the
  panel grows on the large screen and stays inside the screen gaps on the small one.
