# Interactive zsh settings. mise writes its own activation block into ~/.zshrc.
typeset -U path
path=("$HOME/.local/bin" $path)

export HOMEBREW_CLEANUP_MAX_AGE_DAYS=30
if tty -s; then
  export GPG_TTY="$(tty)"
fi

autoload -Uz compinit
compinit
if command -v uv >/dev/null 2>&1; then
  eval "$(uv generate-shell-completion zsh)"
fi
if command -v uvx >/dev/null 2>&1; then
  eval "$(uvx --generate-shell-completion zsh)"
fi

# Load after completion initialization.
if [[ -n "$HOMEBREW_PREFIX" && -r "$HOMEBREW_PREFIX/share/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
  source "$HOMEBREW_PREFIX/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
fi
