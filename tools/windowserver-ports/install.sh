#!/bin/sh
set -eu

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="$HOME/.local/share/windowserver-ports"
link="$HOME/.local/bin/windowserver-ports"

command -v node >/dev/null 2>&1 || { printf 'Install Node.js and put node on PATH.\n' >&2; exit 1; }
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) { console.error("Node.js 22.19 or newer is required."); process.exit(1); }'
if [ -e "$link" ] || [ -L "$link" ]; then
    if [ "$(readlink "$link" || true)" != "$install_dir/windowserver-ports.mjs" ]; then
        printf 'Refusing to replace an unrelated command: %s\n' "$link" >&2
        exit 1
    fi
fi
build_dir=$(mktemp -d)
cleanup_build() {
    if [ -f "$build_dir/windowserver-ports-probe" ]; then
        rm "$build_dir/windowserver-ports-probe"
    fi
    rmdir "$build_dir"
}
trap cleanup_build EXIT HUP INT TERM
# A bare xcrun can pair Xcode's linker with a newer Command Line Tools SDK that it cannot read.
xcrun --sdk macosx clang -O2 -fobjc-arc -Wall -Wextra -Werror \
    -framework AppKit "$source_dir/probe-client.m" -o "$build_dir/windowserver-ports-probe"
mkdir -p "$install_dir" "$HOME/.local/bin"
install -m 755 "$build_dir/windowserver-ports-probe" "$install_dir/windowserver-ports-probe"
install -m 644 "$source_dir/probe-client.m" "$install_dir/probe-client.m"
install -m 755 "$source_dir/windowserver-ports.mjs" "$install_dir/windowserver-ports.mjs"
if [ ! -L "$link" ]; then
    ln -s "$install_dir/windowserver-ports.mjs" "$link"
fi
printf 'Installed %s\n' "$link"
"$link" --version
