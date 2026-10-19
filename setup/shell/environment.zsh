# Read by interactive and noninteractive zsh sessions.
typeset -U path
# mise's official installer puts mise here. The activation blocks need it on PATH.
path=("$HOME/.local/bin" $path)

export IMPECCABLE_NO_TELEMETRY=1
