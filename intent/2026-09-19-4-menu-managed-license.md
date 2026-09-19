---
status: approved
issue: 4
author: olafkfreund
---

# Intent: the panel leaves the menu to nixarchy when nixarchy owns it, and ships its licence

Closes #4.

## Problem

nixarchy ships this panel on by default (olafkfreund/nixarchy#786) and declares its Omarchy
menu rows itself, through its own `nixarchy-plugin` helper. It marks that by
putting a `menu.managed` file next to `menu.py` in the package it installs.
Nothing in the panel reads that marker:

- `menu.py register` runs every time the panel loads (`ActionsPanel.qml:192`),
  and it only refuses when `omarchy-menu.jsonc` is a symlink or lives under
  `/nix/store` (`menu.py:61-65`). nixarchy seeds that file as a writable copy,
  so `register` rewrites it. Rows the user deleted come back, and there are two
  sources for the same rows.
- The package's `runtimeFiles` (`flake.nix:15-24`) doesn't include
  `LICENSE`, so the MIT notice the licence requires to travel with the
  software isn't in the output. nixarchy works around that by copying it from
  the source tree.

## Proposed outcome

- With a `menu.managed` file next to `menu.py`, `register` does nothing and
  exits 0. It doesn't write, doesn't create the file, and isn't an error. The
  panel loads as before.
- Without the marker, nothing changes: installs outside nixarchy still get
  their rows registered.
- `LICENSE` is in the package output, and the flake's own check (which compares
  the installed files with `runtimeFiles`) covers it.

## Affected users and systems

nixarchy users, where the panel is a default. Standalone installs are
unchanged. It affects `menu.py`, `flake.nix` and the tests.

## Constraints

- **The marker's name and place are nixarchy's contract:** a file named
  `menu.managed` in the same directory as `menu.py`. Its presence is all that
  matters; its contents are ignored.
- The existing symlink and `/nix/store` refusal stays as it is.
- Each change is proven by a test that fails first: `register` with the marker
  present leaves the menu file byte-for-byte unchanged, and the package
  contains `LICENSE`.

## Open questions

None.
