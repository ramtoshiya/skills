package main

import (
	"encoding/json"
	"errors"
	"io"
	"strings"
)

type payload map[string]json.RawMessage

func decode(data []byte) (payload, error) {
	var p payload
	if err := json.Unmarshal(data, &p); err != nil {
		return nil, err
	}
	if p == nil {
		return nil, errors.New("payload is not an object")
	}
	return p, nil
}

var shellTools = map[string]bool{
	"Bash": true, "Monitor": true, "Shell": true, "shell": true,
	"exec_command": true, "functions.exec_command": true, "terminal": true,
}

type ShellCall struct {
	Script string
	Dir    string
}

func shellCall(p payload) (call ShellCall, ok bool, err error) {
	var tool string
	if json.Unmarshal(p["tool_name"], &tool) != nil || !shellTools[tool] {
		return ShellCall{}, false, nil
	}
	input := map[string]json.RawMessage{}
	if raw, present := p["tool_input"]; present {
		input = nil
		if err := json.Unmarshal(raw, &input); err != nil || input == nil {
			return ShellCall{}, false, errors.New("tool_input is not an object")
		}
	}
	raw, present := input["command"]
	if !present {
		raw, present = input["cmd"]
	}
	if present {
		if err := json.Unmarshal(raw, &call.Script); err != nil || string(raw) == "null" {
			return ShellCall{}, false, errors.New("command must be a string")
		}
	}
	if call.Dir, err = truthyString(input["workdir"]); err == nil && call.Dir == "" {
		call.Dir, err = truthyString(p["cwd"])
	}
	return call, true, err
}

func truthyString(raw json.RawMessage) (string, error) {
	switch strings.TrimSpace(string(raw)) {
	case "", "null", `""`, "0", "false", "[]", "{}":
		return "", nil
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		return "", errors.New("directory must be a string")
	}
	return s, nil
}

type Output struct {
	Deny string
}

type permissionOutput struct {
	HookSpecificOutput struct {
		HookEventName            string `json:"hookEventName"`
		PermissionDecision       string `json:"permissionDecision"`
		PermissionDecisionReason string `json:"permissionDecisionReason"`
	} `json:"hookSpecificOutput"`
}

func (o Output) write(w io.Writer) error {
	if o.Deny == "" {
		return nil
	}
	var out permissionOutput
	out.HookSpecificOutput.HookEventName = "PreToolUse"
	out.HookSpecificOutput.PermissionDecision = "deny"
	out.HookSpecificOutput.PermissionDecisionReason = o.Deny
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	return enc.Encode(out)
}
