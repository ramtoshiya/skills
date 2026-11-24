package guard

import (
	"errors"

	"ramtoshiya-hooks/shell"
)

const (
	unknownDirDenial = "The working directory comes from a variable here, so the guard cannot find this command's package settings or relative paths. cd to a literal path first, or run the command from that directory."
	pythonDenial     = "pip and package installs into a system or Homebrew Python are blocked. Use uv add, uv pip inside a project, uv run --with package==1.2.3 python, or a virtual environment's own bin/pip or bin/python -m pip. Plain Python commands are allowed, so continue the task."
	processDenial    = "macOS pkill and pgrep read every argument after the first pattern as another pattern, so this command can match and stop other sessions' processes. Put every option before a single pattern, as in pkill -TERM -f 'pattern', and join alternatives into one regular expression with |. -U does not separate sessions because they all run as the same user, so prefer killing the PID you started ($!)."
)

type rule func(c shell.Call) error

var rules = []rule{pythonRule, processRule, modelRule, globalRule, breakSystemRule, packageRule}

func Check(script string, start shell.State) (string, error) {
	err := shell.Walk(script, start, func(c shell.Call) error {
		for _, r := range rules {
			if err := r(c); err != nil {
				return err
			}
		}
		return nil
	})
	var denial shell.Denial
	if errors.As(err, &denial) {
		return string(denial), nil
	}
	return "", err
}
