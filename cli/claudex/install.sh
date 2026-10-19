#!/bin/sh
set -eu

claudex_source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
claudex_install_dir="$HOME/.local/share/claudex"
claudex_link="$HOME/.local/bin/claudex"

command -v node >/dev/null 2>&1 || { echo 'Install Node.js and put node on PATH.' >&2; exit 1; }
command -v claude >/dev/null 2>&1 || { echo 'Install Claude Code and put claude on PATH.' >&2; exit 1; }
if [ -e "$claudex_link" ] || [ -L "$claudex_link" ]; then
    case "$(readlink "$claudex_link" || true)" in
        "$claudex_install_dir/claudex"|"$claudex_install_dir/claudex.cjs") ;;
        *) printf 'Refusing to replace an unrelated command: %s\n' "$claudex_link" >&2; exit 1 ;;
    esac
fi
mkdir -p "$claudex_install_dir" "$HOME/.local/bin"
install -m 755 "$claudex_source_dir/claudex.cjs" "$claudex_install_dir/claudex.cjs"
ln -sfn "$claudex_install_dir/claudex.cjs" "$claudex_link"
printf 'Installed %s\n' "$claudex_link"
"$claudex_link" --version
