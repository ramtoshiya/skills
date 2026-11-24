package guard

import (
	"regexp"
	"strings"

	"ramtoshiya-hooks/shell"
)

var signal = regexp.MustCompile(`^-(?:[0-9]+|[A-Z][A-Z0-9]+)$`)

const processValueOptions = "FGPUdgtu"

func processRule(c shell.Call) error {
	name := baseName(c.Name)
	if (name == "pkill" || name == "pgrep") && len(processPatterns(name, c.Args)) > 1 {
		return shell.Denial(processDenial)
	}
	return nil
}

func processPatterns(name string, args words) words {
	i := 0
	if first, ok := firstLiteral(args); name == "pkill" && ok && signal.MatchString(first) {
		i = 1
	}
	for i < len(args) {
		token := args[i]
		if is(token, "--") {
			return args[i+1:]
		}
		if is(token, "-") || !dashed(token) {
			return args[i:]
		}
		letters := token.Prefix()[1:]
		_, complete := token.Literal()
		for position, letter := range letters {
			if strings.ContainsRune(processValueOptions, letter) {
				if complete && position == len(letters)-1 {
					i++
				}
				break
			}
		}
		i++
	}
	return nil
}

func firstLiteral(args words) (string, bool) {
	if len(args) == 0 {
		return "", false
	}
	return args[0].Literal()
}
