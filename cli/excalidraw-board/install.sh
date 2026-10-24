#!/bin/sh
set -eu

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="$HOME/.local/share/excalidraw-board"
link="$HOME/.local/bin/excalidraw-board"
command -v node >/dev/null 2>&1 || { printf 'Install Node.js and put node on PATH.\n' >&2; exit 1; }
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 24 || (major === 24 && minor < 21)) { console.error("Node.js 24.21 or newer is required."); process.exit(1); }'
if [ -e "$link" ] || [ -L "$link" ]; then
    case "$(readlink "$link" || true)" in
        "$install_dir/excalidraw-board.mjs") ;;
        *) printf 'Refusing to replace an unrelated command: %s\n' "$link" >&2; exit 1 ;;
    esac
fi
mkdir -p "$install_dir" "$HOME/.local/bin"
for file in excalidraw-board.mjs rooms.mjs protocol.mjs scene.mjs images.mjs request.mjs; do
    install -m 644 "$source_dir/$file" "$install_dir/$file"
done
chmod 755 "$install_dir/excalidraw-board.mjs"
ln -sfn "$install_dir/excalidraw-board.mjs" "$link"
printf 'Installed %s\n' "$link"
"$link" --version
