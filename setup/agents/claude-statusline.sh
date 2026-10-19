#!/bin/bash
input=$(cat)

# Forward the payload to Orca's hook (rate limits) when present; it prints nothing.
if [ -x "$HOME/.orca/agent-hooks/claude-statusline.sh" ]; then
  printf '%s' "$input" | /bin/sh "$HOME/.orca/agent-hooks/claude-statusline.sh" >/dev/null 2>&1 || :
fi

model=$(jq -r '.model.id // empty' <<< "$input")
effort=$(jq -r '.effort.level // empty' <<< "$input")
context_pct=$(jq -r '.context_window.used_percentage // empty' <<< "$input")
context_size=$(jq -r '
  .context_window.context_window_size as $n
  | if $n == null then empty
    elif $n >= 1000000 then
      ($n/1000000) as $v | if ($v|floor) == $v then "\($v|floor)M" else "\($v*10|floor/10)M" end
    elif $n >= 1000 then
      ($n/1000) as $v | if ($v|floor) == $v then "\($v|floor)K" else "\($v*10|floor/10)K" end
    else
      "\($n)"
    end
' <<< "$input")

parts=()
[ -n "$model" ] && parts+=("$model")
[ -n "$effort" ] && parts+=("$effort")
[ -n "$context_pct" ] && [ -n "$context_size" ] && parts+=("${context_pct}% / ${context_size}")

if [ ${#parts[@]} -gt 0 ]; then
  printf '%s' "${parts[0]}"
  if [ ${#parts[@]} -gt 1 ]; then
    printf ' | %s' "${parts[@]:1}"
  fi
  printf '\n'
fi
