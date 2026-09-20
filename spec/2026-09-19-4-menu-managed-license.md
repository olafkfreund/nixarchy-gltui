---
status: approved
issue: 4
intent: intent/2026-09-19-4-menu-managed-license.md
---

# Spec: the panel leaves the menu to nixarchy when nixarchy owns it, and ships its licence

## Design

**The marker check goes first in `register_menu()`** (`menu.py:61`), before
anything reads the menu file:

```python
if Path(__file__).with_name('menu.managed').exists():
    return
```

That covers every caller. The panel runs `menu.py register` on every load
(`ActionsPanel.qml:192`), and the `__main__` dispatch (`menu.py:107-108`) is the
only route into `register_menu`, so this one guard is the whole behaviour
change. It exits 0, writes nothing and creates nothing. `exists()` also accepts
a directory or a broken marker. Presence is the contract, and the contents are
never read. The symlink and `/nix/store` refusal (`menu.py:64-65`) stays exactly
as it is, and still runs when the marker is absent.

**LICENSE is added to `runtimeFiles`** (`flake.nix:15-24`), so the package
build copies it. The `plugin` check's file-list assertion (`flake.nix:51`)
compares the package against that same list, so it can't notice LICENSE going
missing: removing it from `runtimeFiles` changes both sides at once. So the
check also gets one explicit line, `assert (root / 'LICENSE').is_file()`, which
is what fails if the licence ever stops shipping.

## Alternatives rejected

- **An environment variable** (`GITLAB_PIPELINES_MENU_MANAGED=1`) set by nixarchy.
  The panel's process environment comes from the shell, not the package, so
  nixarchy would have to thread it through the session. A file inside the
  package travels with the package, and nixarchy already ships it (#786).
- **Removing `register` entirely.** Standalone installs rely on it for their rows.
- **Checking `menu.managed` inside `registered_menu()`.** That's a pure function
  over strings; the guard belongs where the file system is.

## Risks

- **A stray `menu.managed` in a standalone checkout** silences registration. The
  name is specific, and the README says what it does.
- **Existing nixarchy homes** keep whatever rows `register` already wrote. The
  guard stops future rewrites, and the migration (delete the two keys) is
  already in nixarchy's manual (#786).

## Verification

- **New test** in `tests/test_menu.py` `RegistrationTest`,
  `test_managed_marker_leaves_menu_untouched`: in a temporary `HOME`, write a
  menu file with a comment and one custom row. Point `menu.__file__` at a
  temporary directory holding `menu.managed` (`patch.object`), call
  `register_menu()`, and assert the file is byte-for-byte unchanged. A second
  case with no menu file asserts none is created.
  - **Red first:** on today's `menu.py` it fails, because `register` appends
    `apps.gitlab-pipelines`, so the bytes differ and a file gets created.
- **Package:** `nix flake check`'s `plugin` check, with the explicit
  `LICENSE` assertion.
  - **Red first:** add the assertion before adding `LICENSE` to `runtimeFiles`,
    and the check fails. Adding the entry makes it pass.
- `nix flake check` green; `python3 -m unittest discover -s tests` green.
