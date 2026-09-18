#!/usr/bin/env bash
set -euo pipefail

keys() {
  cat <<'KEYS'
SUPER ALT + A → Open or close GitHub Actions
SUPER CTRL ALT + A → GitHub Actions keybindings
↓ / j → Next row (j only outside search editing)
↑ / k → Previous row (k only outside search editing)
Enter / Space / → / l → Expand or collapse repository, run or job
← / h → Collapse or select parent
Page Down / Page Up → Move eight rows
Home / End → First or last row
/ → Search repositories and workflows; select existing query
↑ / ↓ while searching → Select a result without leaving search
Enter while searching → Expand selected result and resume navigation
Tab while searching → Resume navigation without expanding
Esc while searching → Clear search and resume navigation
Esc → Clear filter, then close
r → Refresh selected repository, expanded run and activity
Shift + R → Rediscover accessible repositories
o → Open selected repository, run or job on GitHub
Search editing → Native cursor movement, selection, Backspace and Delete
KEYS
}

if [[ ${1-} == --print || ${1-} == -p ]]; then
  keys
else
  omarchy-shell shell hide olafkfreund.github-actions
  keys | omarchy-menu-select 'GitHub Actions keybindings' -- --width 1000 --height 650 >/dev/null
fi
