#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="$HOME/.local/share/plugin-update-review"
link="$HOME/.local/bin/plugin-update-review"
command -v uv >/dev/null 2>&1 || { printf 'Install uv and put uv on PATH.\n' >&2; exit 1; }
if [ -e "$link" ] || [ -L "$link" ]; then
    case "$(readlink "$link" || true)" in
        "$install_dir/plugin-update-review") ;;
        *) printf 'Refusing to replace an unrelated command: %s\n' "$link" >&2; exit 1 ;;
    esac
fi
mkdir -p "$install_dir/src" "$install_dir/web" "$HOME/.local/bin"
install -m 644 "$source_dir/src/review.py" "$install_dir/src/review.py"
install -m 644 "$source_dir/web/index.html" "$install_dir/web/index.html"
install -m 755 "$source_dir/src/plugin-update-review" "$install_dir/plugin-update-review"
ln -sfn "$install_dir/plugin-update-review" "$link"
printf 'Installed %s\n' "$link"
"$link" --version
