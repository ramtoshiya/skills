#!/bin/sh
set -eu

APP=${PASEO_DESKTOP_APP:-/Applications/Paseo.app}
RESOURCES="$APP/Contents/Resources"
HELPER="$APP/Contents/Frameworks/Paseo Helper.app/Contents/MacOS/Paseo Helper"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ ! -d "$APP" ]; then
  printf '%s\n' "Paseo Desktop bundle not found at $APP. Set PASEO_DESKTOP_APP to its installed location." >&2
  exit 1
fi
if [ ! -x "$HELPER" ] || [ ! -x "$RESOURCES/bin/paseo" ]; then
  printf '%s\n' 'This Paseo bundle does not provide the required macOS runtime and CLI.' >&2
  exit 1
fi
exec env ELECTRON_RUN_AS_NODE=1 "$HELPER" "$SCRIPT_DIR/paseo-compact.mjs" "$RESOURCES" "$@"
