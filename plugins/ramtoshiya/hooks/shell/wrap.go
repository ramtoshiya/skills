package shell

import (
	"errors"
	"strings"
)

var wrappers = map[string]bool{"command": true, "builtin": true, "noglob": true, "time": true, "env": true, "sudo": true}

var shells = map[string]bool{"sh": true, "bash": true, "zsh": true, "dash": true, "ksh": true, "fish": true}

func is(w Word, s string) bool {
	text, ok := w.Literal()
	return ok && text == s
}

func literals(values []string) []Word {
	words := make([]Word, len(values))
	for i, value := range values {
		words[i] = NewLiteral(value)
	}
	return words
}

func unwrap(words []Word, env Env) ([]Word, Env, error) {
	i := 0
	for i < len(words) {
		if name, value, ok := words[i].SplitAssign(); ok {
			env[strings.ToLower(name)] = value
			i++
			continue
		}
		wrapper, ok := words[i].BaseName()
		if !ok || !wrappers[wrapper] {
			break
		}
		i++
		for i < len(words) && strings.HasPrefix(words[i].Prefix(), "-") {
			flag := words[i]
			i++
			isEnv := wrapper == "env"
			if isEnv && (is(flag, "-S") || is(flag, "--split-string")) {
				if i >= len(words) {
					return nil, nil, errors.New("missing env command")
				}
				split, err := ShlexSplit(words[i].Script())
				if err != nil {
					return nil, nil, err
				}
				return unwrap(append(literals(split), words[i+1:]...), env)
			}
			if key, value, ok := flag.Cut("="); isEnv && ok && key == "--split-string" {
				split, err := ShlexSplit(value.Script())
				if err != nil {
					return nil, nil, err
				}
				return unwrap(append(literals(split), words[i:]...), env)
			}
			unset := isEnv && (is(flag, "-u") || is(flag, "--unset"))
			if isEnv && (is(flag, "-i") || is(flag, "-") || is(flag, "--ignore-environment")) {
				clear(env)
			}
			if unset && i < len(words) {
				delete(env, strings.ToLower(words[i].Script()))
			}
			if unset || wrapper == "sudo" && (is(flag, "-u") || is(flag, "--user") || is(flag, "-g") || is(flag, "--group")) {
				i++
			}
		}
	}
	return words[i:], env, nil
}

func shellScript(args []Word) (Word, bool) {
	for i := 0; i+1 < len(args); i++ {
		flag := args[i].Prefix()
		if strings.HasPrefix(flag, "-") && !strings.HasPrefix(flag, "--") && strings.Contains(flag[1:], "c") {
			return args[i+1], true
		}
	}
	return Word{}, false
}
