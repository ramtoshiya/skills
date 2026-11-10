#!/bin/sh
set -eu

sidecar_source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sidecar_install_dir="$HOME/.local/share/sidecar/0.1.0"
sidecar_link="$HOME/.local/bin/sidecar"

if [ -e "$sidecar_link" ] || [ -L "$sidecar_link" ]; then
    if [ "$(readlink "$sidecar_link" || true)" != "$sidecar_install_dir/sidecar" ]; then
        printf 'Refusing to replace an unrelated command: %s\n' "$sidecar_link" >&2
        exit 1
    fi
fi
sidecar_build_dir=$(mktemp -d)
cleanup_sidecar_build() {
    if [ -f "$sidecar_build_dir/sidecar" ]; then
        rm "$sidecar_build_dir/sidecar"
    fi
    rmdir "$sidecar_build_dir"
}
trap cleanup_sidecar_build EXIT HUP INT TERM
xcrun clang -O2 -fobjc-arc -Wall -Wextra -Werror \
    -framework Foundation -framework CoreGraphics \
    "$sidecar_source_dir/sidecar.m" -o "$sidecar_build_dir/sidecar"
mkdir -p "$sidecar_install_dir" "$HOME/.local/bin"
install -m 755 "$sidecar_build_dir/sidecar" "$sidecar_install_dir/sidecar"
if [ ! -L "$sidecar_link" ]; then
    ln -s "$sidecar_install_dir/sidecar" "$sidecar_link"
fi
printf 'Installed %s\n' "$sidecar_link"
"$sidecar_link" --version
