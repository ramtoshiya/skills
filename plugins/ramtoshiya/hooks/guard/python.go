package guard

import (
	"regexp"
	"strings"

	"ramtoshiya-hooks/shell"
)

var (
	pythonCommand = regexp.MustCompile(`^(?:python|pip)(?:[0-9]+(?:\.[0-9]+)*)?\z`)
	moduleFlag    = regexp.MustCompile(`^-[bBdEiIOPqRsSuvVx]*m`)
	commandFlag   = regexp.MustCompile(`^-[bBdEiIOPqRsSuvVx]*[cm]`)
	codeFlag      = regexp.MustCompile(`^-[bBdEiIOPqRsSuvVx]*c`)
	valueFlags    = set("-W", "-X", "--check-hash-based-pycs")
)

func modelCommand(name shell.Word, args words) (shell.Word, words) {
	base := baseName(name)
	if base == "uv" {
		pos := positions(args)
		if len(pos) < 2 || !is(pos[0].word, "run") {
			return shell.NewLiteral(base), args
		}
		next := pos[1].index
		return modelCommand(args[next], args[next+1:])
	}
	if pythonCommand.MatchString(base) {
		for index := 0; index < len(args); {
			token := args[index]
			if oneOf(token, valueFlags) {
				index += 2
				continue
			}
			if m := moduleFlag.FindString(token.Prefix()); m != "" {
				if module := token.After(len(m)); !module.Empty() {
					return module, args[index+1:]
				}
				if index+1 < len(args) {
					return args[index+1], args[index+2:]
				}
				break
			}
			if !dashed(token) || is(token, "-") || codeFlag.MatchString(token.Prefix()) {
				break
			}
			index++
		}
	}
	return shell.NewLiteral(base), args
}

func pythonRule(c shell.Call) error {
	name := baseName(c.Name)
	if !pythonCommand.MatchString(name) {
		return nil
	}
	module, _ := modelCommand(c.Name, c.Args)
	script := c.Args
	index := 0
	for index < len(script) && dashed(script[index]) {
		token := script[index]
		if is(token, "--") {
			index++
			break
		}
		if is(token, "-") || commandFlag.MatchString(token.Prefix()) {
			break
		}
		if oneOf(token, valueFlags) {
			index += 2
		} else {
			index++
		}
	}
	if index > len(script) {
		index = len(script)
	}
	script = script[index:]
	blocked := strings.HasPrefix(name, "pip") || oneOf(module, set("pip", "ensurepip"))
	if !blocked && strings.HasPrefix(name, "python") && len(script) > 0 && baseName(script[0]) == "setup.py" {
		for _, arg := range script[1:] {
			if oneOf(arg, set("install", "develop")) {
				blocked = true
			}
		}
	}
	if !blocked {
		return nil
	}
	venv, err := virtualEnv(c)
	if err != nil {
		return err
	}
	if venv {
		return nil
	}
	return shell.Denial(pythonDenial)
}

func virtualEnv(c shell.Call) (bool, error) {
	text := c.Name.Script()
	if !strings.Contains(text, "/") {
		return false, nil
	}
	path := shell.Normalize(text)
	bin := shell.Parent(path)
	if shell.Name(bin) != "bin" {
		return false, nil
	}
	if env := shell.Name(shell.Parent(bin)); env == ".venv" || env == "venv" {
		return true, nil
	}
	_, known := c.Dir.Path()
	if !strings.HasPrefix(path, "/") && !known {
		return false, nil
	}
	resolved, err := shell.Resolve(c.Name, c.Dir, shell.Home(c.Env))
	if err != nil {
		return false, err
	}
	return isFile(shell.Parent(shell.Parent(resolved)) + "/pyvenv.cfg")
}
