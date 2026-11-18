---
status: draft
issue: 31
author: olafkfreund
---

# Intent: Document that GITLAB_TOKEN overrides the glab login

## Problem

The README's Authentication section (`README.md:149-151`) says the plugin
uses "your existing `glab` login". It does not mention that `glab` prefers
a token from the environment, which matters in three ways.

**1. An environment token wins over the stored login.** glab 1.130 reads
`GITLAB_TOKEN`, `GITLAB_ACCESS_TOKEN` or `OAUTH_TOKEN`, first one set wins
(`glab config --help`, `token` key). I checked this here:
`GITLAB_TOKEN=<invalid> glab api --hostname gitlab.com user` returns
`401 Unauthorized`, although the stored `gitlab.com` login is valid.

As a result, a stale or wrong `GITLAB_TOKEN` makes the panel show
"Authenticate with glab auth login" (`gitlab.py:189,215`). A new
`glab auth login` does not fix that.

**2. It only reaches some hosts.** glab sends an environment token only to:
- the host in `GITLAB_HOST` (or the `host` config key);
- the host in `GITLAB_REPO`;
- hosts already in glab's config file.

The plugin names its host only on the command line
(`glab api --hostname <host>`, `gitlab.py:44`). For a host that is not in
the config, glab refuses to send it: "GITLAB_TOKEN is set, but … is
neither the default host nor a configured host" (checked here with an
unconfigured host).

**3. It must be in the shell's environment.** `gitlab.py:43` passes no
`env`, so `glab` inherits the environment of the helper, which the Omarchy
shell (Quickshell) starts. Exporting `GITLAB_TOKEN` in a terminal does not
change an already-running shell. Only a shell started with that variable
sees it.

## Proposed outcome

The README's Authentication section gains a short paragraph. Three other
README lines that say the login is the only way are reworded to "a
`glab` login (or an environment token, see Authentication)":
- Requirements (`:10`);
- the Nix note (`:55`);
- the host note (`:147`).

The paragraph says that:

- `GITLAB_TOKEN` (or `GITLAB_ACCESS_TOKEN`, `OAUTH_TOKEN`) overrides the
  `glab auth login` token;
- the token needs the `read_api` scope (already stated; kept next to it);
- it is sent only to some hosts: the default host (`GITLAB_HOST`), the
  host in `GITLAB_REPO`, and hosts already in glab's config. The README
  points to `glab config --help` for the full rules, rather than repeating
  them;
- for any other host, `glab auth login --hostname …` is the
  straightforward route, as today. Setting `GITLAB_HOST` session-wide also
  works, but glab then always uses that host and errors in repositories
  whose remotes do not match it, which affects every other `glab` command
  in that session;
- it must be in the environment the Omarchy shell was started with.
  Exporting it in a terminal does not change a running shell;
- **troubleshooting:** if the panel keeps saying "Authenticate with glab
  auth login" although `glab auth status` looks fine, a stale environment
  token is the first suspect.
  - To compare in a terminal, clear all three variables and retry:

    ```bash
    env -u GITLAB_TOKEN -u GITLAB_ACCESS_TOKEN -u OAUTH_TOKEN glab api --hostname <host> user
    ```
  - That only diagnoses. To fix the panel, remove the variable from the
    session's environment and restart the shell.
- a `glab auth login` stores its credential in the system keyring when
  one is available, so the README says "stored login", not "token in the
  config file". CI job tokens (`CI_JOB_TOKEN`) are out of scope.

The README keeps its rule that tokens never go in `flake.nix` or
`flake.lock`, and it does not recommend putting a token in an environment
file.

## Affected users and systems

- `README.md` only. No code, test or version change, so no plugin release
  or redeploy is needed. The README text ships with the next release; it
  changes nothing on any host.

## Constraints

- Every statement must be accurate for the glab version Nixarchy ships
  (1.130 here). Refer to `glab config --help` rather than repeating its
  full rules.
- No secrets or real token values in examples.
- Do not tell users to set a token in a world-readable file or in the Nix
  store.

## Open questions

1. **Change the error text?** The panel's "Authenticate with glab auth
   login" is misleading when `GITLAB_TOKEN` is the cause. I recommend
   docs-only here, and a separate issue if the message should mention
   `GITLAB_TOKEN`. That issue would be a code change with its own tests.
2. **Release:** I recommend not cutting a release for a README change. It
   ships with the next feature release.

## Review notes

Codex reviewed the draft read-only; agy is out of use (#2748). It confirmed
the variable order, the host rules against `glab config --help` (glab
1.130.0) and the error text (`gitlab.py:188-189,214-215`). I had checked
the override and the unconfigured-host refusal live, with an invalid token.
Its findings, which I checked and folded in above:
- the terminal comparison now clears all three variables, and is marked as
  a diagnosis, not a fix for the running shell;
- the side effect of a session-wide `GITLAB_HOST` is now stated;
- the `GITLAB_REPO` host is included, and the README points to glab's own
  rules;
- three README lines that call the login the only way are now in scope;
- inheritance is stated as "a running shell is not changed";
- the keyring and `CI_JOB_TOKEN` are now mentioned.
