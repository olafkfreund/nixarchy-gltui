---
status: approved
issue: 31
spec: spec/2026-11-18-31-gitlab-token.md
coders:
  1: lead    # one file, four exact text replacements from the spec; a handoff costs more than the edit
reviewers:
  - codex    # independent read of the diff against this plan; agy omitted, out of use (#2748)
---

# Plan: Document that GITLAB_TOKEN overrides the glab login

Self-contained. Branch `docs/31-gitlab-token`, based on `823472f` (v1.6.0).
Only `README.md` changes. There is no code, test, version or release
change.

## Approved decisions (from the spec)

The exact README text, copied from the spec. Apply it verbatim. The code
block below is unindented in the README.

### Edit 1: `README.md:10` (Requirements)

Old line:

```
- [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use. The token needs the `read_api` scope.
```

New line:

```
- [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use, or with an environment token (see [Authentication](#authentication)). The token needs the `read_api` scope.
```

### Edit 2: `README.md:55` (the Nix note's last sentence)

Old:

```
Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab auth login`.
```

New:

```
Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab`'s stored login or an environment token (see [Authentication](#authentication)).
```

### Edit 3: `README.md:147` (host note)

Old:

```
The host must be authenticated with `glab auth login --hostname gitlab.example.org`.
```

New:

```
The host must be authenticated with `glab auth login --hostname gitlab.example.org` (or reachable by an environment token, see [Authentication](#authentication)).
```

### Edit 4: after `README.md:151` (Authentication)

The existing paragraph stays. Add a blank line, then exactly:

````
**Environment tokens.** `glab` prefers a token from the environment over its stored login: `GITLAB_TOKEN`, then `GITLAB_ACCESS_TOKEN`, then `OAUTH_TOKEN`, the first one set wins. It needs the same `read_api` scope. `glab` only sends such a token to some hosts: the default host (`GITLAB_HOST`), the host in `GITLAB_REPO`, and hosts already in its configuration. `glab config --help` has the full rules. The panel names its host only on the command line, so for any other host run `glab auth login --hostname …` once. Setting `GITLAB_HOST` for the whole session also works, but then every `glab` command in that session uses that host, and fails in repositories whose remotes do not match it.

The variable must be in the environment the Omarchy shell was started with. Exporting it in a terminal does not change a running shell.

If the panel keeps asking you to authenticate although `glab auth status` looks fine, check for a stale environment token. In a terminal, compare with all three cleared, using the panel's host in place of `gitlab.example.org`:

```bash
env -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN glab api --hostname gitlab.example.org user
```

If that works, the stale token is in the session's environment. `omarchy-restart-shell` starts the shell through Hyprland, so the shell gets Hyprland's environment: remove the variable where your session sets it, then log out and back in. Keep tokens out of world-readable files and the Nix store.
````

`CI_JOB_TOKEN` is not mentioned. Nothing else in the README changes.

## Steps

1. **`README.md`: Edits 1–4, by the lead.**

   Check (fail-fast; each line must pass):

   ```bash
   python3 - <<'PY'
   import re, sys
   r = open("README.md").read()
   new = [
     "for every host you use, or with an environment token (see [Authentication](#authentication)). The token needs the `read_api` scope.",
     "runtime API access comes from `glab`'s stored login or an environment token (see [Authentication](#authentication)).",
     "`glab auth login --hostname gitlab.example.org` (or reachable by an environment token, see [Authentication](#authentication)).",
     "**Environment tokens.** `glab` prefers a token from the environment",
     "\n```bash\nenv -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN glab api --hostname gitlab.example.org user\n```\n",
     "then log out and back in. Keep tokens out of world-readable files and the Nix store.",
   ]
   old = ["runtime API access comes from `glab auth login`.", "for every host you use. The token"]
   assert all(n in r for n in new), [n for n in new if n not in r]
   assert not any(o in r for o in old), [o for o in old if o in r]
   a = r.index("### Authentication"); e = r.index("**Environment tokens.**"); k = r.index("\n## Keyboard")
   assert a < e < k, "Environment tokens must sit inside Authentication"
   print("text-ok")
   PY
   html=$(gh api -X POST /markdown -f mode=gfm -f text="$(cat README.md)") || exit 1
   grep -q 'id="user-content-authentication"' <<<"$html" && echo anchor-ok
   grep -q '<pre><code class="language-bash">env -u GITLAB_TOKEN' <<<"$html" && echo fence-ok   # the exact class markup is checked when run; adjust the pattern if GitHub's markup differs, without loosening it
   git diff --stat -- . ':!README.md' | grep -q . && echo "OTHER FILES CHANGED" || echo only-readme
   ```

   Expected: `text-ok`, `anchor-ok`, `fence-ok` and `only-readme`. Then
   `python3 -m unittest discover -s tests`, `node tests/model.cjs` and
   `node tests/polling.cjs` still pass.

   Traps:
   - Keep the code fence unindented in the README.
   - Do not touch other README sections.

## Tests

- The step's checks.
- **The live checks,** run by the lead before merging.
  - **Prerequisites:**
    - `gitlab.com` is a configured glab host with a working stored login;
    - `gitlab.example.invalid` is not a configured host;
    - `GITLAB_HOST` and `GITLAB_REPO` are unset.
  - Output is captured and only searched, so nothing is printed. Each
    check depends on the one before.

  ```bash
  set -e
  env -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN -u GITLAB_HOST -u GITLAB_REPO \
    glab api --hostname gitlab.com user >/dev/null 2>&1 && echo baseline-ok
  out=$(env -u GITLAB_HOST -u GITLAB_REPO GITLAB_TOKEN=glpat-invalid glab api --hostname gitlab.com user 2>&1 || true)
  grep -q '401 Unauthorized' <<<"$out" && echo override-401
  out=$(env -u GITLAB_HOST -u GITLAB_REPO GITLAB_TOKEN=glpat-invalid glab api --hostname gitlab.example.invalid user 2>&1 || true)
  grep -q 'did not send the credential' <<<"$out" && echo not-sent
  ```

  Expected: `baseline-ok`, `override-401` and `not-sent`, in that order.
  A missing line is a failure, not a pass. `did not send the credential`
  is glab 1.130.0's wording, seen in the intent's live check.
- No QML smoke run and no microVM: no QML changes.

**Review:** Codex's read-only review of the diff against this plan. The
Opus code review is skipped, because there is no code. Say so in the PR.

**After merge:** no tag, no release, no deploy (intent, question 2).

## Review notes

Codex reviewed the draft plan read-only. It confirmed the four positions
and the verbatim-application rules. Its findings, which I checked and
folded in above:
- any failure was reported as `override-401`: the checks now need the
  baseline to pass, and search the captured output for `401 Unauthorized`;
- the render check could match any `<pre>`: it now checks the anchor and
  the new command block separately;
- the plan only summarised the text: it now carries the exact text;
- the unconfigured-host prerequisite is restored;
- the text checks now assert every new string, the removal of the old
  ones, the placement, and that no other file changed.

## Rollback

Revert the PR's merge commit.

## Deviations
