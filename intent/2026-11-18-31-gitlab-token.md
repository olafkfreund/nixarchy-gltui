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

**3. It must be in the shell's environment.** The helper inherits the
environment of the Omarchy shell (Quickshell) that runs it (`gitlab.py:43`
passes no `env`). A `GITLAB_TOKEN` exported in a terminal does not reach
the panel. It has to be in the desktop session's environment.

## Proposed outcome

The README's Authentication section gains a short paragraph. It says that:

- `GITLAB_TOKEN` (or `GITLAB_ACCESS_TOKEN`, `OAUTH_TOKEN`) overrides the
  `glab auth login` token;
- the token needs the `read_api` scope (already stated; kept next to it);
- it is only sent to the default host (`GITLAB_HOST`) or to hosts already
  in glab's config. For any other host, run `glab auth login --hostname …`
  as today, or set `GITLAB_HOST` to the panel's host;
- it must be in the desktop session's environment, not just a terminal's;
- if the panel keeps saying "Authenticate with glab auth login" although
  `glab auth status` looks fine, the first thing to check is a stale
  `GITLAB_TOKEN`. To compare, unset it and run
  `glab api --hostname <host> user` in a terminal.

The README keeps its rule that tokens never go in `flake.nix` or
`flake.lock`, and it does not recommend putting a token in an environment
file.

## Affected users and systems

- `README.md` only. No code, test or version change. This is a docs-only
  change, so no plugin release or redeploy is needed. It ships with the
  next release.
- p620, razer and p510 are unaffected until that release.

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
