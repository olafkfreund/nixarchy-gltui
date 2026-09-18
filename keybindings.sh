#!/usr/bin/env bash
set -euo pipefail

keys() {
  cat <<'KEYS'
SUPER ALT + P → Open or close GitLab Pipelines
SUPER CTRL ALT + P → GitLab Pipelines keybindings
↓ / j → Next row (j only outside search editing)
↑ / k → Previous row (k only outside search editing)
Enter / Space / → / l → Expand or collapse project, pipeline or stage
← / h → Collapse or select parent
Page Down / Page Up → Move eight rows
Home / End → First or last row
/ → Search projects and pipelines; select existing query
↑ / ↓ while searching → Select a result without leaving search
Enter while searching → Expand selected result and resume navigation
Tab while searching → Resume navigation without expanding
Esc while searching → Clear search and resume navigation
Esc → Clear filter, then close
r → Refresh selected project, expanded pipeline and activity
Shift + R → Rediscover accessible projects
o → Open selected project, pipeline or job on GitLab
Search editing → Native cursor movement, selection, Backspace and Delete
KEYS
}

if [[ ${1-} == --print || ${1-} == -p ]]; then
  keys
else
  omarchy-shell shell hide olafkfreund.gitlab-pipelines
  keys | omarchy-menu-select 'GitLab Pipelines keybindings' -- --width 1000 --height 650 >/dev/null
fi
