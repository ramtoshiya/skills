#!/bin/sh
set -eu

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
command -v node >/dev/null 2>&1 || { printf 'Install Node.js and put node on PATH.\n' >&2; exit 1; }
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) { console.error("Node.js 22.19 or newer is required."); process.exit(1); }'
target="$HOME/.local/bin/worktreeinclude"
if [ -L "$target" ] || { [ -e "$target" ] && { [ ! -f "$target" ] || ! grep -q "^const owner = 'skills-worktreeinclude-v1';$" "$target"; }; }; then
    printf 'Refusing to replace an unrelated command: %s\n' "$target" >&2
    exit 1
fi
mkdir -p "$HOME/.local/bin"
install -m 755 "$source_dir/worktreeinclude.mjs" "$target"
printf 'Installed %s\n' "$target"
"$target" --version
