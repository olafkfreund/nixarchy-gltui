---
status: draft
issue: 31
intent: intent/2026-11-18-31-gitlab-token.md
---

# Spec: Document that GITLAB_TOKEN overrides the glab login

## Design

`README.md` only. The exact new text follows. Facts are from
`glab config --help` (glab 1.130.0, the `token` and `host` keys), and from
two live checks with an invalid token. Those checks showed an override on
`gitlab.com`, and a refusal for an unconfigured host.

### 1. Requirements (`README.md:10`)

Replace:

> - [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use. The token needs the `read_api` scope.

with:

> - [`glab`](https://gitlab.com/gitlab-org/cli), authenticated with `glab auth login` for every host you use, or with an environment token (see [Authentication](#authentication)). The token needs the `read_api` scope.

### 2. Nix note (`README.md:55`)

The last sentence,

> Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab auth login`.

becomes:

> Never put tokens in `flake.nix` or `flake.lock`; runtime API access comes from `glab`'s stored login or an environment token (see [Authentication](#authentication)).

### 3. Host note (`README.md:147`)

The sentence

> The host must be authenticated with `glab auth login --hostname gitlab.example.org`.

becomes:

> The host must be authenticated with `glab auth login --hostname gitlab.example.org` (or reachable by an environment token, see [Authentication](#authentication)).

### 4. Authentication (`README.md:149-151`)

The existing paragraph stays unchanged. It is still true: the plugin itself
never reads a token, and `glab` does. After it, add:

> **Environment tokens.** `glab` prefers a token from the environment over its stored login: `GITLAB_TOKEN`, then `GITLAB_ACCESS_TOKEN`, then `OAUTH_TOKEN`, the first one set wins. It needs the same `read_api` scope. `glab` only sends such a token to some hosts: the default host (`GITLAB_HOST`), the host in `GITLAB_REPO`, and hosts already in its configuration. `glab config --help` has the full rules. The panel names its host only on the command line, so for any other host run `glab auth login --hostname …` once. Setting `GITLAB_HOST` for the whole session also works, but then every `glab` command in that session uses that host, and fails in repositories whose remotes do not match it.
>
> The variable must be in the environment the Omarchy shell was started with. Exporting it in a terminal does not change a running shell.
>
> If the panel keeps asking you to authenticate although `glab auth status` looks fine, check for a stale environment token. In a terminal, compare with all three cleared:
>
> ```bash
> env -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN glab api --hostname gitlab.example.org user
> ```
>
> If that works, remove the variable from your session's environment and restart the shell (`omarchy-restart-shell`). Keep tokens out of world-readable files and the Nix store.

`CI_JOB_TOKEN` is not mentioned: it is out of scope.

### 5. No other change

- No code, test or `manifest.json` change.
- No release: the text ships with the next feature release (intent,
  question 2).

## Alternatives rejected

- **Repeating glab's full host rules:** they can change between glab
  versions, so the README points to `glab config --help`.
- **Recommending `GITLAB_HOST`:** it has a session-wide side effect, so it
  is mentioned as an option with that warning, not as the main route.
- **Changing the panel's error text:** a separate code change (intent,
  question 1).

## Risks

- **glab versions:** a later glab could change the variable order or the
  host rules. The README points to `glab config --help` for that reason.
- **Hosts:** none. This is a README change only, so nothing is deployed.

## Verification

- `grep` that the three replaced sentences are gone and the new ones are
  present.
- Check that the `#authentication` anchor resolves: the heading is
  `### Authentication`, and GitHub's generated anchor is `authentication`.
- A Markdown render check: `gh api /markdown` on the changed README, or a
  look at the PR's rendered file.
- `python3 -m unittest discover -s tests` and the node tests still pass.
  Nothing they test changes; this checks that nothing else was touched.
- Re-run the two live checks with an invalid token before merging, so the
  README's two key claims are confirmed on the current glab:

  ```bash
  GITLAB_TOKEN=glpat-invalid glab api --hostname gitlab.com user          # 401: env overrides login
  GITLAB_TOKEN=glpat-invalid glab api --hostname gitlab.example.invalid user  # refused: not sent
  ```
