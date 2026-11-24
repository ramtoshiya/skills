package guard

import (
	"errors"
	"io/fs"
	"os"
	"regexp"
	"strings"
	"syscall"
	"unicode"
	"unicode/utf8"

	"github.com/BurntSushi/toml"

	"ramtoshiya-hooks/shell"
)

var settingLine = regexp.MustCompile(`^` + pySpace + `*([A-Za-z][A-Za-z0-9_.-]*(?:\[\])?)` + pySpace + `*[:=]` + pySpace + `*(.*)`)

func absent(err error) bool {
	return errors.Is(err, fs.ErrNotExist) || errors.Is(err, syscall.ENOTDIR) ||
		errors.Is(err, syscall.ELOOP) || errors.Is(err, syscall.EBADF)
}

func stat(path string) (os.FileInfo, error) {
	info, err := os.Stat(path)
	if err != nil && absent(err) {
		return nil, nil
	}
	return info, err
}

func exists(path string) (bool, error) {
	info, err := stat(path)
	return info != nil, err
}

func isFile(path string) (bool, error) {
	info, err := stat(path)
	return info != nil && info.Mode().IsRegular(), err
}

func child(parent, name string) string {
	return shell.Normalize(parent + "/" + name)
}

func nearest(start, name string) (string, error) {
	for _, parent := range shell.Ancestors(start) {
		path := child(parent, name)
		ok, err := isFile(path)
		if err != nil || ok {
			return path, err
		}
	}
	return "", nil
}

func readText(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	if !utf8.Valid(data) {
		return "", errors.New("configuration is not UTF-8")
	}
	return strings.ReplaceAll(strings.ReplaceAll(string(data), "\r\n", "\n"), "\r", "\n"), nil
}

func pyLines(text string) []string {
	var lines []string
	start := 0
	for i, r := range text {
		switch r {
		case '\n', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', ' ', ' ':
			lines = append(lines, text[start:i])
			start = i + utf8.RuneLen(r)
		}
	}
	if start < len(text) {
		lines = append(lines, text[start:])
	}
	return lines
}

func wordRune(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r) }

var yamlTail = regexp.MustCompile(`^` + pySpace + `*['"]?` + pySpace + `*:`)

func mentionsKey(line string, keys map[string]bool) bool {
	for key := range keys {
		for from := 0; ; {
			i := strings.Index(line[from:], key)
			if i < 0 {
				break
			}
			start, end := from+i, from+i+len(key)
			from = start + 1
			if before, _ := utf8.DecodeLastRuneInString(line[:start]); start > 0 && wordRune(before) {
				continue
			}
			if after, _ := utf8.DecodeRuneInString(line[end:]); end < len(line) && wordRune(after) {
				continue
			}
			if yamlTail.MatchString(line[end:]) {
				return true
			}
		}
	}
	return false
}

func scalarSettings(path string, keys map[string]bool, yaml bool) (map[string]string, error) {
	result := map[string]string{}
	if path == "" {
		return result, nil
	}
	ok, err := exists(path)
	if err != nil || !ok {
		return result, err
	}
	text, err := readText(path)
	if err != nil {
		return nil, err
	}
	for _, line := range pyLines(text) {
		stripped := pyStrip(line)
		if stripped == "" || stripped[0] == '#' || stripped[0] == ';' {
			continue
		}
		match := settingLine.FindStringSubmatch(line)
		key := ""
		if match != nil {
			key = strings.TrimSuffix(match[1], "[]")
		}
		if match == nil || !keys[key] {
			if yaml && mentionsKey(line, keys) {
				return nil, errors.New("unsupported YAML policy syntax")
			}
			continue
		}
		first, _ := utf8.DecodeRuneInString(line)
		if _, seen := result[key]; seen || yaml && pySpaceRune(first) {
			return nil, errors.New("duplicate or nested policy setting")
		}
		value, _, _ := strings.Cut(match[2], "#")
		value = pyStrip(value)
		if value != "" && (value[0] == '\'' || value[0] == '"') {
			parts, err := shell.ShlexSplit(value)
			if err != nil {
				return nil, err
			}
			if len(parts) != 1 {
				return nil, errors.New("unsupported policy scalar")
			}
			value = parts[0]
		}
		result[key] = value
	}
	return result, nil
}

func uvSettings(path string) (map[string]any, error) {
	ok, err := exists(path)
	if err != nil || !ok {
		return nil, err
	}
	text, err := readText(path)
	if err != nil {
		return nil, err
	}
	var data map[string]any
	if _, err := toml.Decode(text, &data); err != nil {
		return nil, err
	}
	if path[strings.LastIndex(path, "/")+1:] != "pyproject.toml" {
		return data, nil
	}
	tool, present := data["tool"]
	if !present {
		return nil, nil
	}
	table, isTable := tool.(map[string]any)
	if !isTable {
		return nil, errors.New("unsupported tool table")
	}
	uv, present := table["uv"]
	if !present {
		return nil, nil
	}
	settings, isTable := uv.(map[string]any)
	if !isTable {
		return nil, errors.New("unsupported uv table")
	}
	return settings, nil
}
