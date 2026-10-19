#!/bin/sh
# Check Mermaid diagram syntax with the real Mermaid parser (mmdc).
#
# Usage: mermaid-check.sh <diagram.mmd | doc.md | ->
#   -                          one diagram read from stdin
#   *.md, *.markdown, *.mdx    every ```mermaid / ~~~mermaid / :::mermaid block, checked one by one
#   anything else              the whole file is one diagram
#
# Exit 0: the parser accepted every diagram.
# Exit 1: at least one diagram failed; the parse error is printed without the stack trace.
# Exit 2: usage error, or a Markdown file with no mermaid block.
#
# Nothing is written next to the source; all render output goes to a temp dir that is removed on exit.

set -u

mmdc() {
  # Flag order matters: after the package name, npx forwards --min-release-age to mmdc, which rejects it.
  npx --min-release-age=3 @mermaid-js/mermaid-cli@12.0.0 "$@"
}

# Keep the parse error, source snippet, caret and "Expecting" line; drop puppeteer/mermaid stack frames.
print_error() {
  grep -Ev '^[[:space:]]+at |^[^ ]+ \((https?|file)://' "$1" | grep -Ev '^[[:space:]]*$' >&2
}

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <diagram.mmd | doc.md | ->" >&2
  exit 2
fi

src=$1
tmp=$(mktemp -d "${TMPDIR:-/tmp}/mermaid-check.XXXXXX") || exit 2
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

# check_one <diagram file> <label>: run the parser on one diagram, report on failure.
check_one() {
  if mmdc -i "$1" -o - -e svg -q >/dev/null 2>"$tmp/err"; then
    return 0
  fi
  echo "$2" >&2
  print_error "$tmp/err"
  return 1
}

case "$src" in
  -)
    cat >"$tmp/stdin.mmd"
    check_one "$tmp/stdin.mmd" "stdin: parse failed" && echo "ok: stdin"
    exit $?
    ;;
  *.md|*.markdown|*.mdx)
    ;;
  *)
    check_one "$src" "$src: parse failed" && echo "ok: $src"
    exit $?
    ;;
esac

# Markdown: split out every mermaid block into $tmp/block-<N>.mmd, where N is the file line of the
# block's first diagram line. Prints one N per block.
starts=$(awk -v dir="$tmp" '
  !inblock && /^[[:space:]]*(```+|~~~+|:::)[[:space:]]*mermaid([[:space:]]|$)/ {
    inblock = 1; start = NR + 1; out = dir "/block-" start ".mmd"; printf "" > out; next
  }
  inblock && /^[[:space:]]*(```+|~~~+|:::)[[:space:]]*$/ {
    close(out); print start; inblock = 0; next
  }
  inblock { print > out }
' "$src")

if [ -z "$starts" ]; then
  echo "$src: no mermaid block found (looked for \`\`\`mermaid, ~~~mermaid, :::mermaid)" >&2
  exit 2
fi
count=$(printf '%s\n' "$starts" | wc -l | tr -d ' ')

# Fast path: one mmdc run over the whole document (one Chromium launch for all blocks).
# mmdc stops at the first failing block and does not say which one it was, so on failure fall
# through to the per-block pass, which names each failing block by its file line.
# mmdc's own extraction sees only ``` and ::: fences; a ~~~mermaid block would pass unchecked, so
# a file with one skips the fast path.
tilde=0
grep -Eq '^[[:space:]]*~~~+[[:space:]]*mermaid([[:space:]]|$)' "$src" && tilde=1

if [ "$tilde" -eq 0 ] && mmdc -i "$src" -o "$tmp/checked.md" -q >/dev/null 2>"$tmp/err"; then
  echo "ok: $src ($count mermaid block(s))"
  exit 0
fi

failed=0
for start in $starts; do
  check_one "$tmp/block-$start.mmd" "$src:$start: mermaid block failed (diagram line 1 = file line $start)" || failed=$((failed + 1))
done

if [ "$failed" -eq 0 ]; then
  if [ "$tilde" -eq 1 ]; then
    echo "ok: $src ($count mermaid block(s))"
    exit 0
  fi
  echo "$src: mmdc rejected the document, but every extracted block passed alone. mmdc output:" >&2
  print_error "$tmp/err"
  exit 1
fi
echo "$failed of $count mermaid block(s) failed in $src" >&2
exit 1
