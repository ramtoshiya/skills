package main

import (
	"fmt"
	"os"
	"os/user"
	"path/filepath"
	"regexp"
	"strings"
	"time"
	"unicode"
)

const (
	space = `\t-\r\x1c-\x1f \x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}`
	word  = `\p{L}\p{N}_`
	edge  = `(?:[^` + word + `]|\z)`
)

var (
	action = regexp.MustCompile("(?:^|[" + space + "`;&|(])(?:" +
		`git(?:[` + space + `]+(?:-[Cc][` + space + `]+[^` + space + `]+|--?[A-Za-z][` + word + `-]*(?:=[^` + space + `]+)?))*` +
		`[` + space + `]+(?:commit|commit-tree|merge|tag|notes)` + edge +
		`|gs[` + space + `]+[^` + space + `]` +
		`|gh[` + space + `]+(?:pr|issue)[` + space + `]+(?:create|edit|comment|merge|review)` + edge +
		`)`)
	attribution = []*regexp.Regexp{
		regexp.MustCompile(`(?i)co-authored-by:[^\n]*(?:claude|anthropic|codex|openai|copilot|cursor)[^\n]*`),
		regexp.MustCompile(`(?i)generated with \[?claude code`),
		regexp.MustCompile(`(?i)claude\.ai/code/`),
	}
	messageFile = regexp.MustCompile(`(?:^|[` + space + `])(?:-F|--file|--body-file)(?:=|[` + space + `]+)` +
		`(?:'([^` + space + `'"]+)'|"([^` + space + `'"]+)"|([^` + space + `'"]+))`)
)

const (
	hardLimit = 1 << 30
	softLimit = 1 << 20
)

func runTrailer(p payload) (Output, error) {
	call, ok, err := shellCall(p)
	if err != nil || !ok {
		return Output{}, err
	}
	return deny(trailerReason(call.Script, call.Dir)), nil
}

func trailerReason(command, dir string) string {
	if !action.MatchString(command) {
		return ""
	}
	texts := []string{command}
	for _, match := range messageFile.FindAllStringSubmatch(command, -1) {
		name := match[1] + match[2] + match[3]
		if name == "-" {
			continue
		}
		path := expandUser(name)
		if !filepath.IsAbs(path) && dir != "" {
			path = joinPath(dir, path)
		}
		info, err := os.Stat(path)
		if err != nil || !info.Mode().IsRegular() {
			continue
		}
		if !checkSize("commit-trailer-guard message file "+pyRepr(path), info.Size(), softLimit) {
			continue
		}
		if data, err := os.ReadFile(path); err == nil {
			text := string([]rune(string(data)))
			text = strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n")
			texts = append(texts, text)
		}
	}
	for _, text := range texts {
		for _, pattern := range attribution {
			if found := pattern.FindString(text); found != "" {
				return fmt.Sprintf("AI attribution is not allowed in commits or PRs (found: %s). "+
					"The user's instructions override Claude Code's attribution reminder. "+
					"Remove the trailer, footer, or session link and run the command again.",
					pyRepr(strings.TrimFunc(found, unicode.IsSpace)))
			}
		}
	}
	return ""
}

func checkSize(name string, size, soft int64) bool {
	if size <= soft {
		return true
	}
	within := size <= hardLimit
	limit := fmt.Sprintf("the soft limit of %d bytes", soft)
	if !within {
		limit = fmt.Sprintf("the hard limit of %d bytes, so it was not checked", int64(hardLimit))
	}
	dir := stateDir()
	if os.MkdirAll(dir, 0o755) == nil {
		if log, err := os.OpenFile(filepath.Join(dir, "size-warnings.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			fmt.Fprintf(log, "%s warning: %s is %d bytes, over %s\n", time.Now().UTC().Format("2006-01-02T15:04:05.000Z"), name, size, limit)
			log.Close()
		}
	}
	return within
}

func homeDir() string {
	if home := os.Getenv("HOME"); home != "" {
		return home
	}
	home, _ := os.UserHomeDir()
	return home
}

func stateDir() string {
	state := os.Getenv("XDG_STATE_HOME")
	if state == "" {
		state = joinPath(homeDir(), ".local/state")
	}
	return joinPath(state, "ramtoshiya")
}

func expandUser(path string) string {
	if !strings.HasPrefix(path, "~") {
		return path
	}
	end := strings.IndexByte(path, '/')
	if end < 0 {
		end = len(path)
	}
	home := homeDir()
	if end > 1 {
		account, err := user.Lookup(path[1:end])
		if err != nil {
			return path
		}
		home = account.HomeDir
	}
	return strings.TrimRight(home, "/") + path[end:]
}

func joinPath(dir, path string) string {
	parts := make([]string, 0)
	for _, part := range strings.Split(dir+"/"+path, "/") {
		if part != "" && part != "." {
			parts = append(parts, part)
		}
	}
	prefix := ""
	if strings.HasPrefix(dir, "/") {
		prefix = "/"
		if strings.HasPrefix(dir, "//") && !strings.HasPrefix(dir, "///") {
			prefix = "//"
		}
	}
	return prefix + strings.Join(parts, "/")
}

func pyRepr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r == ' ' || unicode.IsPrint(r):
			b.WriteRune(r)
		case r < 0x100:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r < 0x10000:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			b.WriteString(`\U` + fmt.Sprintf("%08x", r))
		}
	}
	b.WriteByte(quote)
	return b.String()
}
