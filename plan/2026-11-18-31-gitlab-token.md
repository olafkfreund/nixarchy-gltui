---
status: draft
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

The README text is fixed by the spec (`spec/2026-11-18-31-gitlab-token.md`,
sections 1–4). The spec's quoted text is applied verbatim, without the
`> ` prefix on any line, including the fences and blank lines:

1. **`README.md:10`** (Requirements, the `glab` bullet): add
   `, or with an environment token (see [Authentication](#authentication))`
   after `for every host you use`.
2. **`README.md:55`** (Nix note): the last sentence ends
   `runtime API access comes from `glab`'s stored login or an environment token (see [Authentication](#authentication)).`
3. **`README.md:147`** (host note): append
   ` (or reachable by an environment token, see [Authentication](#authentication))`
   to the `glab auth login --hostname` sentence, before its full stop.
4. **After `README.md:151`** (Authentication), add the spec's three
   paragraphs and its code block:
   - **Environment tokens** (precedence, scope, which hosts, the
     `GITLAB_HOST` caveat);
   - the shell's environment;
   - troubleshooting: the `env -u …` command, then the Hyprland
     environment and logging out and back in;
   - keep tokens out of world-readable files and the Nix store.

The existing Authentication paragraph stays unchanged. `CI_JOB_TOKEN` is
not mentioned.

## Steps

1. **`README.md`: the four edits above,** done by the lead.

   Check:

   ```bash
   grep -c 'see \[Authentication\](#authentication)' README.md      # 3
   grep -n 'Environment tokens' README.md                            # 1 line, after :151
   grep -n 'runtime API access comes from `glab auth login`' README.md   # none
   gh api -X POST /markdown -f mode=gfm -f text="$(cat README.md)" | grep -c 'id="user-content-authentication"\|<pre'
   ```

   Also: `python3 -m unittest discover -s tests`, `node tests/model.cjs`
   and `node tests/polling.cjs` still pass.

   Traps:
   - Keep the code fence unindented in the README.
   - Do not touch other README sections.

## Tests

- The step's greps and the Markdown render.
- **The live checks,** run by the lead before merging. They need
  `gitlab.com` configured with a working stored login, and
  `GITLAB_HOST` / `GITLAB_REPO` unset. Output goes to `/dev/null`, so no
  token or user data is printed.

  ```bash
  env -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN -u GITLAB_HOST -u GITLAB_REPO \
    glab api --hostname gitlab.com user >/dev/null && echo baseline-ok
  env -u GITLAB_HOST -u GITLAB_REPO GITLAB_TOKEN=glpat-invalid \
    glab api --hostname gitlab.com user >/dev/null 2>&1 || echo override-401
  env -u GITLAB_HOST -u GITLAB_REPO GITLAB_TOKEN=glpat-invalid \
    glab api --hostname gitlab.example.invalid user 2>&1 | grep -q 'did not send' && echo not-sent
  ```

  Expected: `baseline-ok`, `override-401` and `not-sent`.

- No QML smoke run and no microVM: no QML changes.

**Review:** Codex's read-only review of the diff against this plan. The
Opus code review is skipped, because there is no code. Say so in the PR.

**After merge:** no tag, no release, no deploy (intent, question 2).

## Rollback

Revert the PR's merge commit.

## Deviations
