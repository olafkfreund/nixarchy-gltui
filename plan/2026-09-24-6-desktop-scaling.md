---
status: approved
issue: 6
spec: spec/2026-09-24-6-desktop-scaling.md
---

# Plan: Panel text and window follow desktop size and scale

Approved decisions (from the spec):

- Text matches the host: remove `textScale`, use `Style.font.*` as they are.
  Users size text with `[font] base-size`.
- Card grows with the screen: 60% × 70% of the window, today's
  `Style.space(900)` × `Style.space(680)` as the minimum, clamped to
  `window - Style.gapsOut * 2`.
- Row heights use the host menu formula: font height plus
  `Style.spacing.rowPaddingX * 2`, with the current `Style.space(40)` /
  `Style.space(64)` minimums.
- Divider uses `Style.spacing.hairline`; the title column width is derived
  from the real icon width and row spacing.
- No manual `devicePixelRatio`/Hyprland scale handling; Wayland already
  applies it.
- Only `ActionsPanel.qml` and `README.md` change. No new settings or
  dependencies.

## Steps

1. `ActionsPanel.qml:36`: delete `readonly property real textScale: 1.5`, and in
   all 9 uses replace `Math.round(Style.font.<x> * root.textScale)` with
   `Style.font.<x>` → verify by `grep -c textScale ActionsPanel.qml` = 0.
2. `ActionsPanel.qml:231-232`: set card
   `width: Math.min(Math.max(Style.space(900), Math.round(window.width * 0.6)), window.width - Style.gapsOut * 2)` and
   `height: Math.min(Math.max(Style.space(680), Math.round(window.height * 0.7)), window.height - Style.gapsOut * 2)`
   → verify by reading the diff.
3. `ActionsPanel.qml:327` (row delegate `height`): subtitle rows
   `Math.max(Style.space(64), Style.font.body + Style.font.caption + Style.spacing.rowPaddingX * 2)`,
   plain rows `Math.max(Style.space(40), Style.font.body + Style.spacing.rowPaddingX * 2)`
   → verify by reading the diff.
4. `ActionsPanel.qml:314`: divider `height: 1` → `height: Style.spacing.hairline`
   → verify by grep.
5. `ActionsPanel.qml:336-343`: give the status-icon `Text` `id: statusIcon`,
   and set the title column
   `width: Math.max(0, parent.width - statusIcon.width - info.width - parent.spacing * 2)`
   (drops the magic `Style.space(26)`) → verify by grep for `space(26)` = 0.
6. `README.md:3`: replace "with text at 1.5× theme font size" with "and
   follows the theme font size (`[font] base-size`)" → verify by grep for `1.5×`.
7. Run the tests below; then a manual check in omarchy-shell.

## Tests

- `nix flake check` → all checks pass.
- `python3 tests/qml-smoke.py` → `QML_CHECKS_PASSED`.
- `nix build .#default && python3 tests/qml-smoke.py ./result` → `QML_CHECKS_PASSED`.
- `omarchy plugin validate "$(readlink -f result)"` → exit 0.
- `grep -nE 'textScale|height: 1[^0-9]|space\(26\)' ActionsPanel.qml` → no output.
- Manual: open the panel at `base-size` 12 and 18, on a 1080p screen and a
  large or 1.5-scale screen. Text matches the host menu, rows don't clip, and
  the card grows on the large screen and stays inside the gaps on the small one.

## Rollback

`git revert` the implementation commit; the change is limited to
`ActionsPanel.qml` and `README.md`, with no config or data migration.

## Revised by #12 (2026-09-24)

Owner decision after deployment: match nixarchy-ghtui. Its identical
screen-fraction design was checked live on 2560×1440, found "way too big"
(card ~1330 px wide) and reverted (ghtui PR #26). So:

- The card is back to a fixed `Style.space(900)` × `Style.space(680)`,
  shrinking only to `window - Style.gapsOut * 2` (design item 2 / plan step 2
  no longer apply).
- Row heights use ghtui's padding, `Style.space(16)` with a subtitle and
  `Style.space(12)` without, instead of `Style.spacing.rowPaddingX * 2`
  (design item 3 / plan step 3 revised).
- Unchanged: text follows `Style.font.*` with no multiplier, the divider is
  `Style.spacing.hairline`, and the title width comes from the icon's width.
