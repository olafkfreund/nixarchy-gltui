---
status: approved
issue: 4
spec: spec/2026-09-19-4-menu-managed-license.md
---

# Plan: the panel leaves the menu to nixarchy when nixarchy owns it, and ships its licence

## Approved decisions (from the spec)

- **One guard, first thing in `register_menu()`** (`menu.py:61`):
  `if Path(__file__).with_name('menu.managed').exists(): return`. Presence is
  the contract; the contents are never read, and a directory or broken symlink
  counts. `register` then exits 0, writes nothing and creates nothing.
- **Nothing else changes.** Without the marker, the symlink and `/nix/store`
  refusal (`menu.py:64-65`), the writability check and the row insertion behave
  exactly as today. `registered_menu()` stays a pure function and gains no
  file-system knowledge.
- **`LICENSE` joins `runtimeFiles`** (`flake.nix:15-24`), and the `plugin`
  check gains one explicit `assert (root / 'LICENSE').is_file()`, because its
  existing file-list assertion compares the package against `runtimeFiles`
  itself and so can never catch the licence going missing.
- nixarchy creates the marker in its wrapper (#786); this repo never writes it.

## Steps

1. `tests/test_menu.py`: add `test_managed_marker_leaves_menu_untouched` to
   `RegistrationTest`. In a temporary `HOME`, write
   `.config/omarchy/extensions/omarchy-menu.jsonc` holding a comment and one
   custom row; `patch.object(menu, '__file__', ...)` at a temporary directory
   containing both `menu.example.json` (copied from the repo) and an empty
   `menu.managed`; call `register_menu()`; assert the file's bytes and `stat()`
   are unchanged. A second case, with no menu file, asserts none is created.
   → Verify by running it **before** step 2: `python3 -m unittest
   tests.test_menu -v` must fail, because `register` appends
   `apps.gitlab-pipelines`. Capture that output for the PR (§1).
2. `menu.py`: add the two-line guard at the top of `register_menu()`.
   → Verify with `python3 -m unittest discover -s tests -v`: the new case
   passes and every existing case still passes, which is what proves the
   no-marker path is untouched.
3. `flake.nix`: add `"LICENSE"` to `runtimeFiles`, and
   `assert (root / 'LICENSE').is_file()` to the `plugin` check's python block.
   → Verify with `nix flake check`. Prove the assertion bites by adding it
   first, without the `runtimeFiles` entry: the check must fail on the missing
   licence (and on the file-list assertion), then pass once the entry is added.
4. `README.md`: one sentence under the registration paragraph, saying that a
   `menu.managed` file beside `menu.py` turns registration off, and that
   nixarchy ships one.
   → Verify by reading it; no test.
5. Open the PR: `Closes #4`, links to the intent, spec and plan, and the red
   output from steps 1 and 3.

## Tests

| Command | Expected | Its §1 break |
|---|---|---|
| `python3 -m unittest tests.test_menu -v` | all pass, including the new case | before step 2: the new case fails, the menu file differs |
| `python3 -m unittest discover -s tests -v` | all pass | — (guards the no-marker path) |
| `nix flake check` | green | assertion added before the `runtimeFiles` entry: fails on the missing LICENSE |
| `python3 menu.py register` (run inside the check, no marker) | still writes the rows | — |

## Rollback

Revert the commit. The guard is additive: without the marker, behaviour is
today's, so a revert only restores rewriting for nixarchy users. Menus already
written are unaffected either way, and removing `LICENSE` from `runtimeFiles`
only changes what the package ships.
