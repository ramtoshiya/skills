#!/bin/sh
set -eu
case "${1-}" in virtual|fallback) mode=$1 ;; *) echo 'Usage: focus.sh virtual|fallback' >&2; exit 2 ;; esac
owner=${CLAUDE_CODE_SESSION_ID:-}
: "${owner:?Set the session ID used for the desktop lease}"
takeaturn check desktop --owner "$owner" >/dev/null
root=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/${owner}.focus.XXXXXXXX")
profile="focus-${owner}-$$"
launcher="$root/plugins/ramtoshiya/skills/visible-chrome/scripts/chrome.mjs"
swiftc "$root/dev/verification/visible-chrome/focus.swift" -o "$tmp/focus"
set -- $("$tmp/focus" capture)
pid=$1 x=$2 y=$3
if [ "$mode" = fallback ]; then
  mkdir "$tmp/bin"
  printf '#!/bin/sh\nif [ "$1" = get ]; then echo Failed. >&2; else echo unavailable >&2; fi\nexit 1\n' > "$tmp/bin/betterdisplaycli"
  chmod +x "$tmp/bin/betterdisplaycli"
  PATH="$tmp/bin:$PATH"
  export PATH
fi
sampler=
cleanup() {
  if [ -n "$sampler" ]; then kill "$sampler" 2>/dev/null || :; wait "$sampler" 2>/dev/null || :; fi
  node "$launcher" close "$profile" >/dev/null 2>&1 || :
  rm -rf "$HOME/.local/share/agent-chrome/$profile"
  "$tmp/focus" restore "$pid" "$x" "$y"
  rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM
osascript -e 'tell application "Finder" to activate'
set -- $("$tmp/focus" capture)
finder=$1
"$tmp/focus" sample > "$tmp/trace" &
sampler=$!
sleep 1
printf '%s open %s\n' "$(date +%s)" "$mode"
url=$(node "$launcher" open "$profile" corner)
printf '%s\n' "$url"
if [ "$mode" = virtual ] && [ ! -f "$HOME/.local/share/agent-chrome/$profile/virtual-display" ]; then
  echo 'Virtual display was not created' >&2
  exit 1
fi
signal_status=0
node "$root/dev/verification/visible-chrome/signals.mjs" "$url" || signal_status=1
sleep 2
printf '%s reuse\n' "$(date +%s)"
node "$launcher" open "$profile" corner
node "$root/dev/verification/visible-chrome/signals.mjs" "$url" || signal_status=1
sleep 2
printf '%s close\n' "$(date +%s)"
node "$launcher" close "$profile"
sleep 1
kill "$sampler"
wait "$sampler" 2>/dev/null || :
sampler=
cat "$tmp/trace"
focus_status=0
if awk -v expected="[$finder]" '$NF != expected { bad = 1 } END { exit !bad }' "$tmp/trace"; then
  echo 'The frontmost app changed' >&2
  focus_status=1
fi
node "$launcher" open "$profile" corner >/dev/null
"$tmp/focus" sample > "$tmp/front-trace" &
sampler=$!
printf '%s open front\n' "$(date +%s)"
node "$launcher" open "$profile" front
sleep 3
kill "$sampler"
wait "$sampler" 2>/dev/null || :
sampler=
cat "$tmp/front-trace"
if ! rg 'Google Chrome' "$tmp/front-trace"; then
  echo 'Chrome did not become frontmost in front mode' >&2
  focus_status=1
fi
node "$launcher" close "$profile"
if [ "$focus_status" -ne 0 ] || [ "$signal_status" -ne 0 ]; then exit 1; fi
