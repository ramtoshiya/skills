package shell

import (
	"errors"
	"os"
	"os/user"
	"path/filepath"
	"strings"
)

var (
	ErrUnknownDir = errors.New("the working directory is not known")
	ErrDynamic    = errors.New("the path is not a literal")
)

type Dir struct{ path string }

func NewDir(path string) Dir { return Dir{path} }

func (d Dir) Path() (string, bool) { return d.path, d.path != "" }

func Resolve(w Word, dir Dir, homeDir string) (string, error) {
	var b strings.Builder
	for _, p := range w.parts {
		if p.kind == opaque {
			return "", ErrDynamic
		}
		b.WriteString(p.text)
	}
	value := strings.ReplaceAll(strings.ReplaceAll(b.String(), "${HOME}", homeDir), "$HOME", homeDir)
	if len(w.parts) > 0 && w.parts[0].kind == home {
		value = homeDir + value[1:]
	}
	if strings.ContainsAny(value, "$`") {
		return "", ErrDynamic
	}
	return Join(dir, value)
}

func Join(dir Dir, value string) (string, error) {
	path := Normalize(value)
	if strings.HasPrefix(path, "/") {
		return path, nil
	}
	base, ok := dir.Path()
	if !ok {
		return "", ErrUnknownDir
	}
	if path == "." {
		return base, nil
	}
	return Normalize(base + "/" + path), nil
}

func Normalize(path string) string {
	var parts []string
	for _, part := range strings.Split(path, "/") {
		if part != "" && part != "." {
			parts = append(parts, part)
		}
	}
	prefix := ""
	if strings.HasPrefix(path, "/") {
		prefix = "/"
		if strings.HasPrefix(path, "//") && !strings.HasPrefix(path, "///") {
			prefix = "//"
		}
	}
	if len(parts) == 0 && prefix == "" {
		return "."
	}
	return prefix + strings.Join(parts, "/")
}

func pyName(path string) string {
	path = Normalize(path)
	if path == "." || strings.Trim(path, "/") == "" {
		return ""
	}
	return path[strings.LastIndex(path, "/")+1:]
}

func Parent(path string) string {
	path = Normalize(path)
	i := strings.LastIndex(path, "/")
	switch {
	case i < 0:
		return "."
	case i == 0 || strings.Trim(path[:i], "/") == "":
		return path[:i+1]
	}
	return path[:i]
}

func Name(path string) string { return pyName(path) }

func Ancestors(path string) []string {
	result := []string{Normalize(path)}
	for {
		last := result[len(result)-1]
		parent := Parent(last)
		if parent == last || last == "." {
			return result
		}
		result = append(result, parent)
	}
}

func RealPath(path string) string {
	resolved := "/"
	parts := strings.Split(path, "/")
	for links := 0; len(parts) > 0; {
		part := parts[0]
		parts = parts[1:]
		switch part {
		case "", ".":
			continue
		case "..":
			resolved = filepath.Dir(resolved)
			continue
		}
		next := filepath.Join(resolved, part)
		info, err := os.Lstat(next)
		if err != nil || info.Mode()&os.ModeSymlink == 0 {
			resolved = next
			continue
		}
		target, err := os.Readlink(next)
		if err != nil || links > 40 {
			resolved = next
			continue
		}
		links++
		if strings.HasPrefix(target, "/") {
			resolved = "/"
		}
		parts = append(strings.Split(target, "/"), parts...)
	}
	return resolved
}

func Absolute(path string) string {
	if !strings.HasPrefix(path, "/") {
		cwd, _ := os.Getwd()
		path = cwd + "/" + path
	}
	return RealPath(path)
}

func Home(env Env) string {
	if w, ok := env["home"]; ok {
		return w.Script()
	}
	if home, err := os.UserHomeDir(); err == nil {
		return home
	}
	if current, err := user.Current(); err == nil {
		return current.HomeDir
	}
	return ""
}
