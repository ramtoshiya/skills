#!/bin/sh
set -eu

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="$HOME/.local/share/excalidraw-web-export"
link="$HOME/.local/bin/excalidraw-web-export"
command -v node >/dev/null 2>&1 || { printf 'Install Node.js and put node on PATH.\n' >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { printf 'Install npm and put it on PATH.\n' >&2; exit 1; }
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 24 || (major === 24 && minor < 21)) { console.error("Node.js 24.21 or newer is required."); process.exit(1); }'
if [ -e "$link" ] || [ -L "$link" ]; then
    case "$(readlink "$link" || true)" in
        "$install_dir/export.mjs") ;;
        *) printf 'Refusing to replace an unrelated command: %s\n' "$link" >&2; exit 1 ;;
    esac
fi
mkdir -p "$install_dir" "$HOME/.local/bin"
for file in export.mjs size-limit.mjs package.json package-lock.json .npmrc; do
    install -m 644 "$source_dir/$file" "$install_dir/$file"
done
(
    # npm ci needs a canonical project path, including when HOME uses macOS /tmp.
    cd -P -- "$install_dir"
    unset npm_config_prefix npm_config_local_prefix npm_config_global_prefix
    npm ci --prefix "$PWD" --omit=dev --ignore-scripts --min-release-age=3
)
chmod 755 "$install_dir/export.mjs"
ln -sfn "$install_dir/export.mjs" "$link"
"$link" --help >/dev/null
printf 'Installed %s\n' "$link"
printf 'Uses existing macOS Chrome when available. See the README to install managed Chromium.\n'
