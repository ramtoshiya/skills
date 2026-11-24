package guard

import (
	"errors"
	"strings"

	"ramtoshiya-hooks/shell"
)

type words = []shell.Word

var errValue = errors.New("value is not usable")

func set(values ...string) map[string]bool {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		result[value] = true
	}
	return result
}

func is(w shell.Word, s string) bool {
	text, ok := w.Literal()
	return ok && text == s
}

func oneOf(w shell.Word, values map[string]bool) bool {
	text, ok := w.Literal()
	return ok && values[text]
}

func dashed(w shell.Word) bool { return strings.HasPrefix(w.Prefix(), "-") }

func has(args words, s string) bool { return indexOf(args, s) >= 0 }

func indexOf(args words, s string) int {
	for i, arg := range args {
		if is(arg, s) {
			return i
		}
	}
	return -1
}

func baseName(w shell.Word) string {
	name, _ := w.BaseName()
	return name
}

func lower(w shell.Word) (string, bool) {
	text, ok := w.Literal()
	return strings.ToLower(text), ok
}

func isFalse(w shell.Word) bool {
	text, ok := lower(w)
	return ok && (text == "false" || text == "0" || text == "no")
}

func split(w shell.Word) (key string, value shell.Word, equal bool) {
	if key, value, ok := w.Cut("="); ok {
		return key, value, true
	}
	if text, ok := w.Literal(); ok {
		return text, shell.Word{}, false
	}
	return "", shell.Word{}, false
}

type position struct {
	index int
	word  shell.Word
}

var valueOptions = set("--prefix", "--cache", "--registry", "--userconfig", "--loglevel",
	"--directory", "--project", "--config-file", "--python", "-p",
	"--package", "--from", "--with", "--with-editable", "--index",
	"--index-url", "--extra-index-url", "--workspace", "-w", "-C",
	"--exclude-newer", "--exclude-newer-package", "--min-release-age",
	"--config.minimumReleaseAge", "--minimum-release-age", "--before",
	"--env-file", "--config-dir", "--globalconfig", "--call", "-c")

func positions(args words) []position {
	var result []position
	for i := 0; i < len(args); i++ {
		token := args[i]
		if is(token, "--") {
			for j := i + 1; j < len(args); j++ {
				result = append(result, position{j, args[j]})
			}
			break
		}
		if oneOf(token, valueOptions) {
			i++
			continue
		}
		if !dashed(token) {
			result = append(result, position{i, token})
		}
	}
	return result
}

func at(list []position, i int) shell.Word {
	if i < len(list) {
		return list[i].word
	}
	return shell.Word{}
}

func options(args words, names map[string]bool) (words, error) {
	var values words
	for i := 0; i < len(args); i++ {
		token := args[i]
		if is(token, "--") {
			break
		}
		key, value, equal := split(token)
		if names[key] {
			if !equal {
				i++
				if i >= len(args) {
					return nil, errors.New("missing policy option value")
				}
				value = args[i]
			}
			values = append(values, value)
		} else if !equal && oneOf(token, valueOptions) {
			i++
		}
	}
	return values, nil
}

func oneOption(args words, names map[string]bool) (shell.Word, bool, error) {
	values, err := options(args, names)
	if err != nil || len(values) == 0 {
		return shell.Word{}, false, err
	}
	return values[len(values)-1], true, nil
}
