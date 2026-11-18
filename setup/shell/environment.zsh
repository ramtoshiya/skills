# Read by interactive and noninteractive zsh sessions.
typeset -U path
# mise's official installer puts mise here. The activation blocks need it on PATH.
path=("$HOME/.local/bin" $path)

export IMPECCABLE_NO_TELEMETRY=1

# bb threads take Impeccable's decision rounds in the thread, because its
# decision page listens only on this Mac's loopback address.
if [[ -n $BB_THREAD_ID ]]; then
  export IMPECCABLE_QUESTION_DISABLED=1
fi
