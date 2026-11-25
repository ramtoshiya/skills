package shell

import (
	"errors"
	"strings"

	"mvdan.cc/sh/v3/syntax"
)

type Env map[string]Word

func EnvFrom(environ []string) Env {
	env := Env{}
	for _, entry := range environ {
		if key, value, ok := strings.Cut(entry, "="); ok {
			env[strings.ToLower(key)] = NewLiteral(value)
		}
	}
	return env
}

func (e Env) clone() Env {
	copied := make(Env, len(e)+4)
	for key, value := range e {
		copied[key] = value
	}
	return copied
}

type State struct {
	Dir Dir
	Env Env
}

func (s *State) clone() *State { return &State{s.Dir, s.Env.clone()} }

type Call struct {
	Name Word
	Args []Word
	Env  Env
	Dir  Dir
}

type Denial string

func (d Denial) Error() string { return string(d) }

const nestingDenial = Denial("Shell wrappers are too deeply nested to review. Use a simple command.")

func Walk(script string, start State, visit func(Call) error) error {
	return walkScript(script, &start, visit, 0)
}

func walkScript(script string, st *State, visit func(Call) error, depth int) error {
	if depth > 4 {
		return nestingDenial
	}
	file, src, err := parse(script)
	if err != nil {
		return Denial("The package/Python guard could not parse this command (" + err.Error() + "). Rewrite it in plain bash syntax so the guard can check it.")
	}
	w := &walker{src: src, visit: visit, depth: depth}
	return w.stmts(file.Stmts, st)
}

func parse(script string) (*syntax.File, string, error) {
	file, src, err := parseAs(syntax.LangBash, script)
	if err == nil {
		return file, src, nil
	}
	if file, src, zshErr := parseAs(syntax.LangZsh, script); zshErr == nil {
		return file, src, nil
	}
	return nil, "", err
}

func parseAs(lang syntax.LangVariant, script string) (*syntax.File, string, error) {
	var first error
	for src := script; ; {
		file, err := syntax.NewParser(syntax.Variant(lang)).Parse(strings.NewReader(src), "")
		var parseErr syntax.ParseError
		if !errors.As(err, &parseErr) {
			return file, src, err
		}
		if first == nil {
			first = err
		}
		var ok bool
		if src, ok = repair(src, parseErr); !ok {
			return nil, script, first
		}
	}
}

func repair(src string, err syntax.ParseError) (string, bool) {
	at := int(err.Pos.Offset())
	switch err.Text {
	case "`;` can only immediately follow a statement":
		return src[:at] + src[at+1:], true
	case "`&&` must be followed by a statement", "`||` must be followed by a statement":
		return src[:at] + src[at+2:], true
	}
	if open := strings.LastIndex(src[:min(at+2, len(src))], "(("); open >= 0 {
		return src[:open+1] + " " + src[open+1:], true
	}
	return "", false
}

type walker struct {
	src   string
	visit func(Call) error
	depth int
}

func (w *walker) stmts(list []*syntax.Stmt, st *State) error {
	for _, s := range list {
		if err := w.stmt(s, st); err != nil {
			return err
		}
	}
	return nil
}

func (w *walker) stmt(s *syntax.Stmt, st *State) error {
	if s.Background || s.Coprocess || s.Disown {
		st = st.clone()
	}
	for _, r := range s.Redirs {
		if err := w.substitutions(r, st); err != nil {
			return err
		}
	}
	if s.Cmd == nil {
		return nil
	}
	return w.command(s.Cmd, st)
}

func (w *walker) command(cmd syntax.Command, st *State) error {
	switch c := cmd.(type) {
	case *syntax.CallExpr:
		return w.call(c, st)
	case *syntax.BinaryCmd:
		if c.Op == syntax.Pipe || c.Op == syntax.PipeAll {
			if err := w.stmt(c.X, st.clone()); err != nil {
				return err
			}
			return w.stmt(c.Y, st.clone())
		}
		if err := w.stmt(c.X, st); err != nil {
			return err
		}
		return w.stmt(c.Y, st)
	case *syntax.Subshell:
		return w.stmts(c.Stmts, st.clone())
	case *syntax.Block:
		return w.stmts(c.Stmts, st)
	case *syntax.IfClause:
		for clause := c; clause != nil; clause = clause.Else {
			if err := w.stmts(clause.Cond, st); err != nil {
				return err
			}
			if err := w.stmts(clause.Then, st); err != nil {
				return err
			}
		}
		return nil
	case *syntax.WhileClause:
		if err := w.stmts(c.Cond, st); err != nil {
			return err
		}
		return w.stmts(c.Do, st)
	case *syntax.ForClause:
		if err := w.substitutions(c.Loop, st); err != nil {
			return err
		}
		return w.stmts(c.Do, st)
	case *syntax.CaseClause:
		if err := w.substitutions(c.Word, st); err != nil {
			return err
		}
		for _, item := range c.Items {
			for _, pattern := range item.Patterns {
				if err := w.substitutions(pattern, st); err != nil {
					return err
				}
			}
			if err := w.stmts(item.Stmts, st); err != nil {
				return err
			}
		}
		return nil
	case *syntax.FuncDecl:
		return w.stmt(c.Body, st.clone())
	case *syntax.TimeClause:
		if c.Stmt == nil {
			return nil
		}
		return w.stmt(c.Stmt, st)
	case *syntax.CoprocClause:
		if c.Name != nil {
			if err := w.substitutions(c.Name, st); err != nil {
				return err
			}
		}
		return w.stmt(c.Stmt, st.clone())
	case *syntax.ArithmCmd, *syntax.LetClause, *syntax.TestClause:
		return w.substitutions(c, st)
	case *syntax.DeclClause:
		return w.declare(c, st)
	}
	return errors.New("unsupported shell syntax")
}

func (w *walker) substitutions(n syntax.Node, st *State) error {
	var failure error
	syntax.Walk(n, func(node syntax.Node) bool {
		if failure != nil {
			return false
		}
		switch x := node.(type) {
		case *syntax.CmdSubst:
			failure = w.stmts(x.Stmts, st.clone())
			return false
		case *syntax.ProcSubst:
			failure = w.stmts(x.Stmts, st.clone())
			return false
		}
		return true
	})
	return failure
}

func (w *walker) assigned(a *syntax.Assign) (string, Word, bool) {
	if a.Name == nil || a.Naked {
		return "", Word{}, false
	}
	name := strings.ToLower(a.Name.Value)
	if a.Append || a.Array != nil || a.Index != nil {
		return name, Word{[]part{{opaque, w.src[a.Pos().Offset():a.End().Offset()]}}}, true
	}
	if a.Value == nil {
		return name, Word{}, true
	}
	return name, newWord(w.src, a.Value), true
}

func (w *walker) declare(c *syntax.DeclClause, st *State) error {
	for _, a := range c.Args {
		if err := w.substitutions(a, st); err != nil {
			return err
		}
		if name, value, ok := w.assigned(a); ok {
			st.Env[name] = value
		}
	}
	return nil
}

func (w *walker) call(c *syntax.CallExpr, st *State) error {
	if err := w.substitutions(c, st); err != nil {
		return err
	}
	if len(c.Args) == 0 {
		for _, a := range c.Assigns {
			if name, value, ok := w.assigned(a); ok {
				st.Env[name] = value
			}
		}
		return nil
	}
	effective := st.Env.clone()
	for _, a := range c.Assigns {
		if name, value, ok := w.assigned(a); ok {
			effective[name] = value
		}
	}
	words := make([]Word, len(c.Args))
	for i, arg := range c.Args {
		words[i] = newWord(w.src, arg)
	}
	rest, effective, err := unwrap(words, effective)
	if err != nil {
		return err
	}
	if len(rest) == 0 {
		return nil
	}
	name, _ := rest[0].BaseName()
	switch name {
	case "export", "readonly":
		for _, word := range words[1:] {
			if key, value, ok := word.SplitAssign(); ok {
				st.Env[strings.ToLower(key)] = value
			}
		}
		return nil
	case "cd":
		target := NewLiteral("~")
		target.parts[0].kind = home
		if len(rest) > 1 {
			target = rest[len(rest)-1]
		}
		previous := st.Dir
		st.Dir = Dir{}
		if path, err := Resolve(target, previous, Home(effective)); err == nil {
			st.Dir = NewDir(Absolute(path))
		}
		return nil
	}
	call := Call{Name: rest[0], Args: rest[1:], Env: effective, Dir: st.Dir}
	if err := w.visit(call); err != nil {
		return err
	}
	if shells[name] {
		if script, ok := shellScript(call.Args); ok {
			return walkScript(script.Script(), &State{call.Dir, call.Env}, w.visit, w.depth+1)
		}
	}
	return nil
}
