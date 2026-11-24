package guard

import (
	"errors"
	"regexp"

	"ramtoshiya-hooks/shell"
)

const (
	npmGlobalDenial  = "Global package installs and mutations are disabled. Use a project dependency or exact-pinned one-shot execution."
	globalToolDenial = "Global package installs and mutations are disabled."
	pinDenial        = "One-shot execution requires exact package versions: package@1.2.3 for Node or package==1.2.3 for Python. Tags, ranges, and unversioned packages are blocked."
)

var (
	mutations = set("install", "i", "add", "update", "up", "upgrade", "uninstall", "remove", "rm", "rebuild", "link", "unlink")
	npmPin    = regexp.MustCompile(`^(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+@` +
		`(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)` +
		`(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?\z`)
	pythonPin = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?==` +
		`[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?` +
		`(?:\.post[0-9]+)?(?:\.dev[0-9]+)?(?:\+[A-Za-z0-9.-]+)?\z`)
	oneShotNames = set("npx", "pnpx", "pnx", "uvx")
	toolFamilies = map[string]string{"npx": "npm", "pnpx": "pnpm", "pnx": "pnpm", "uvx": "uv"}
)

func upToSeparator(args words) words {
	if i := indexOf(args, "--"); i >= 0 {
		return args[:i]
	}
	return args
}

func globalFlag(args words, env shell.Env) bool {
	text, ok := envText(env, "npm_config_global")
	if !ok {
		text = "false"
	}
	enabled := !isFalseText(text)
	for _, token := range args {
		if is(token, "--") {
			break
		}
		prefix := token.Prefix()
		key, value, equal := token.Cut("=")
		switch {
		case is(token, "--global"), len(prefix) > 1 && prefix[0] == '-' && prefix[1] != '-' && containsByte(prefix[1:], 'g'):
			enabled = true
		case equal && key == "--global":
			enabled = !isFalse(value)
		case is(token, "--no-global"):
			enabled = false
		}
	}
	return enabled
}

func containsByte(s string, b byte) bool {
	for i := 0; i < len(s); i++ {
		if s[i] == b {
			return true
		}
	}
	return false
}

func globalRule(c shell.Call) error {
	name := baseName(c.Name)
	pargs := upToSeparator(c.Args)
	pos := positions(pargs)
	switch {
	case (name == "npm" || name == "pnpm") && len(pos) > 0 && oneOf(pos[0].word, mutations):
		if globalFlag(pargs, c.Env) {
			return shell.Denial(npmGlobalDenial)
		}
	case name == "yarn" && len(pos) > 1 && is(pos[0].word, "global") && oneOf(pos[1].word, mutations):
		return shell.Denial(globalToolDenial)
	case name == "uv" && len(pos) > 1 && is(pos[0].word, "tool") && oneOf(pos[1].word, mutations):
		return shell.Denial(globalToolDenial)
	}
	return nil
}

func breakSystemRule(c shell.Call) error {
	if baseName(c.Name) != "uv" {
		return nil
	}
	pos := positions(upToSeparator(c.Args))
	if len(pos) == 0 || !is(pos[0].word, "pip") {
		return nil
	}
	for _, arg := range c.Args {
		if key, _, _ := split(arg); key == "--break-system-packages" {
			return shell.Denial(pythonDenial)
		}
	}
	return nil
}

type operation struct {
	family   string
	args     words
	packages words
	userTool bool
	pip      bool
}

func packageOperation(name string, args words) (*operation, error) {
	pos := positions(args)
	sub := at(pos, 0)
	family := name
	if f, ok := toolFamilies[name]; ok {
		family = f
	}
	oneShot := oneShotNames[name]
	consumed := 0
	userTool := name == "uvx"
	pip := false
	if oneShot && len(pos) == 0 && (has(args, "--help") || has(args, "-h") || has(args, "--version") || has(args, "-V")) {
		return nil, nil
	}
	switch {
	case name == "npm" || name == "pnpm" || name == "yarn":
		if name == "npm" && is(sub, "init") && len(pos) == 1 {
			return nil, nil
		}
		if name == "npm" {
			oneShot = oneOf(sub, set("exec", "x", "create", "init"))
		} else {
			oneShot = oneOf(sub, set("dlx", "create"))
		}
		if !oneShot && !oneOf(sub, set("install", "i", "add", "update", "up", "upgrade", "ci", "rebuild", "dedupe")) {
			if !(name == "npm" && is(sub, "audit") && len(pos) > 1 && is(pos[1].word, "fix")) {
				return nil, nil
			}
		}
		consumed = 1
	case name == "uv":
		switch {
		case is(sub, "tool") && len(pos) > 1 && is(pos[1].word, "run"):
			oneShot, userTool = true, true
			consumed = 2
		case is(sub, "pip") && len(pos) > 1 && oneOf(pos[1].word, set("install", "sync", "compile")):
			pip = true
		case !oneOf(sub, set("add", "sync", "lock", "run")):
			return nil, nil
		}
	case !oneShot:
		return nil, nil
	}
	var packages words
	managerArgs := args
	if oneShot {
		var target *position
		if len(pos) > consumed {
			target = &pos[consumed]
		}
		if target != nil && name != "npm" {
			managerArgs = args[:target.index]
		}
		var explicit words
		var err error
		if family == "uv" {
			explicit, err = options(managerArgs, set("--from"))
		} else {
			explicit, err = options(managerArgs, set("--package", "-p"))
		}
		if err != nil {
			return nil, err
		}
		packages = explicit
		if len(packages) == 0 && target != nil {
			packages = words{target.word}
		}
		if len(packages) == 0 {
			return &operation{family, managerArgs, words{shell.Word{}}, userTool, pip}, nil
		}
	}
	if name == "uv" && is(sub, "run") {
		managerArgs = args
		if len(pos) > 1 {
			managerArgs = args[:pos[1].index]
		}
	}
	if family == "uv" {
		with, err := options(managerArgs, set("--with"))
		if err != nil {
			return nil, err
		}
		packages = append(packages, with...)
		editable, err := options(managerArgs, set("--with-editable"))
		if err != nil {
			return nil, err
		}
		if len(editable) > 0 && oneShot {
			packages = append(packages, shell.Word{})
		}
	}
	return &operation{family, managerArgs, packages, userTool, pip}, nil
}

func packageRule(c shell.Call) error {
	op, err := packageOperation(baseName(c.Name), c.Args)
	if err != nil || op == nil {
		return err
	}
	pin := npmPin
	if op.family == "uv" {
		pin = pythonPin
	}
	for _, p := range op.packages {
		if text, ok := p.Literal(); !ok || !pin.MatchString(text) {
			return shell.Denial(pinDenial)
		}
	}
	reason, err := check(c, op.family, op.args, op.userTool, op.pip)
	switch {
	case errors.Is(err, shell.ErrUnknownDir):
		return shell.Denial(unknownDirDenial)
	case err != nil:
		return err
	case reason != "":
		return shell.Denial(reason)
	}
	return nil
}
