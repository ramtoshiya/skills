package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
)

const (
	suggestPercent = 75
	bandPercent    = 5
	tailLimit      = 8 << 20
	chunk          = 256 << 10
	stateSessions  = 100
)

var usageKeys = []string{"input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"}

var compactHosts = []struct{ variable, format string }{
	{"BB_THREAD_ID", " This session runs in BB, thread id %s. Use the BB section of the skill."},
	{"PASEO_AGENT_ID", " This session runs in Paseo, agent id %s. Use the Paseo section of the skill."},
}

func runBudget(p payload) (Output, error) {
	if !falsy(p["agent_id"]) {
		return Output{}, nil
	}
	var text string
	var err error
	switch event := jsonString(p["hook_event_name"]); event {
	case "SessionStart":
		if jsonString(p["source"]) == "compact" {
			text, err = afterCompaction(p)
		}
		return addContext(event, text), err
	case "PostToolUse", "UserPromptSubmit":
		text, err = suggestion(p)
		return addContext(event, text), err
	}
	return Output{}, nil
}

func suggestion(p payload) (string, error) {
	window, err := compactWindow(p)
	if err != nil || window == 0 {
		return "", err
	}
	tokens, found, err := contextTokens(jsonString(p["transcript_path"]))
	if err != nil || !found {
		return "", err
	}
	session, err := sessionID(p)
	if err != nil {
		return "", err
	}
	percent := tokens * 100 / window
	band := 0
	if percent >= suggestPercent {
		band = suggestPercent + (percent-suggestPercent)/bandPercent*bandPercent
	}
	if raised, err := updateBand(session, band); err != nil || !raised {
		return "", err
	}
	text := fmt.Sprintf("Context budget: about %d%% of the %s-token auto-compact window is in use (%s tokens). "+
		"At the next natural boundary, compact on your own by following the ramtoshiya:self-compact skill. "+
		"Handoff note path: %s.", percent, thousands(window), thousands(tokens), handoffPath(p, session))
	for _, host := range compactHosts {
		if id := os.Getenv(host.variable); id != "" {
			return text + fmt.Sprintf(host.format, id), nil
		}
	}
	return text + " Without a supported host control, automatic compaction is the fallback.", nil
}

func afterCompaction(p payload) (string, error) {
	session, err := sessionID(p)
	if err != nil {
		return "", err
	}
	if _, err := updateBand(session, 0); err != nil {
		return "", err
	}
	note := handoffPath(p, session)
	if info, err := os.Stat(note); err != nil || !info.Mode().IsRegular() {
		return "", nil
	}
	return "A self-compact handoff note exists at " + note + ". Read it before you continue. " +
		"It records the task state written before this compaction.", nil
}

func jsonString(raw json.RawMessage) string {
	var s string
	if json.Unmarshal(raw, &s) != nil {
		return ""
	}
	return s
}

func sessionID(p payload) (string, error) {
	var id string
	err := json.Unmarshal(p["session_id"], &id)
	return id, err
}

func handoffPath(p payload, session string) string {
	if scratch := jsonString(p["scratchpad_dir"]); scratch != "" {
		return joinPath(scratch, "handoff.md")
	}
	return joinPath(stateDir(), "handoff/"+session+".md")
}

func compactWindow(p payload) (int, error) {
	project := os.Getenv("CLAUDE_PROJECT_DIR")
	if project == "" {
		cwd, err := truthyString(p["cwd"])
		if err != nil {
			return 0, err
		}
		project = cwd
	}
	config := os.Getenv("CLAUDE_CONFIG_DIR")
	if config == "" {
		config = filepath.Join(homeDir(), ".claude")
	}
	candidates := []string{filepath.Join(config, "settings.json")}
	if project != "" {
		candidates = append([]string{filepath.Join(project, ".claude/settings.local.json"),
			filepath.Join(project, ".claude/settings.json")}, candidates...)
	}
	for _, path := range candidates {
		var settings map[string]json.RawMessage
		data, err := os.ReadFile(path)
		if err != nil || json.Unmarshal(data, &settings) != nil {
			continue
		}
		value, ok := settings["autoCompactWindow"]
		if !ok || string(value) == "null" {
			continue
		}
		if window, err := strconv.Atoi(string(value)); err == nil && window > 0 {
			return window, nil
		}
		return 0, nil
	}
	return 0, nil
}

func contextTokens(path string) (int, bool, error) {
	file, err := os.Open(path)
	if err != nil {
		return 0, false, err
	}
	defer file.Close()
	end, err := file.Seek(0, io.SeekEnd)
	if err != nil {
		return 0, false, err
	}
	var rest []byte
	for position := end; position > 0 && end-position < tailLimit; {
		step := min(chunk, position)
		position -= step
		block := make([]byte, step, step+int64(len(rest)))
		if _, err := file.ReadAt(block, position); err != nil {
			return 0, false, err
		}
		lines := bytes.Split(append(block, rest...), []byte("\n"))
		rest = nil
		if position > 0 {
			rest, lines = lines[0], lines[1:]
		}
		for i := len(lines) - 1; i >= 0; i-- {
			if tokens, ok := entryTokens(lines[i]); ok {
				return tokens, true, nil
			}
		}
	}
	return 0, false, nil
}

func entryTokens(line []byte) (int, bool) {
	var entry map[string]json.RawMessage
	if json.Unmarshal(line, &entry) != nil {
		return 0, false
	}
	kind := jsonString(entry["type"])
	if kind == "system" && jsonString(entry["subtype"]) == "compact_boundary" {
		return 0, true
	}
	if kind != "assistant" || !falsy(entry["isSidechain"]) {
		return 0, false
	}
	var message struct {
		Usage map[string]json.RawMessage `json:"usage"`
	}
	if json.Unmarshal(entry["message"], &message) != nil || message.Usage == nil {
		return 0, false
	}
	total := 0
	for _, key := range usageKeys {
		if n, err := strconv.Atoi(string(message.Usage[key])); err == nil {
			total += n
		}
	}
	return total, true
}

type sessionBand struct {
	session string
	band    json.RawMessage
}

func updateBand(session string, band int) (bool, error) {
	path := filepath.Join(stateDir(), "context-budget.json")
	var kept []sessionBand
	var previous *float64
	for _, entry := range readBands(path) {
		if entry.session != session {
			kept = append(kept, entry)
		} else if json.Unmarshal(entry.band, &previous) != nil {
			previous = nil
		}
	}
	if previous == nil && band == 0 || previous != nil && *previous == float64(band) {
		return false, nil
	}
	if band != 0 {
		kept = append(kept, sessionBand{session, json.RawMessage(strconv.Itoa(band))})
	}
	kept = kept[max(0, len(kept)-stateSessions):]
	var out bytes.Buffer
	out.WriteByte('{')
	for i, entry := range kept {
		if i > 0 {
			out.WriteString(", ")
		}
		key, err := json.Marshal(entry.session)
		if err != nil {
			return false, err
		}
		out.Write(key)
		out.WriteString(": ")
		out.Write(entry.band)
	}
	out.WriteByte('}')
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return false, err
	}
	temporary := filepath.Join(filepath.Dir(path), fmt.Sprintf("context-budget.%d.tmp", os.Getpid()))
	if err := os.WriteFile(temporary, out.Bytes(), 0o666); err != nil {
		return false, err
	}
	if err := os.Rename(temporary, path); err != nil {
		return false, err
	}
	return band != 0 && (previous == nil || float64(band) > *previous), nil
}

func readBands(path string) []sessionBand {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	if token, err := decoder.Token(); err != nil || token != json.Delim('{') {
		return nil
	}
	var bands []sessionBand
	for decoder.More() {
		key, err := decoder.Token()
		if err != nil {
			return nil
		}
		var band json.RawMessage
		if decoder.Decode(&band) != nil {
			return nil
		}
		bands = append(bands, sessionBand{key.(string), band})
	}
	if token, err := decoder.Token(); err != nil || token != json.Delim('}') {
		return nil
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil
	}
	return bands
}

func thousands(n int) string {
	s := strconv.Itoa(n)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}
