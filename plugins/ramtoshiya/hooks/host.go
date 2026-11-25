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

var shellTools = map[string]bool{"Bash": true, "Monitor": true}

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
	if raw, present := input["command"]; present {
		if err := json.Unmarshal(raw, &call.Script); err != nil || string(raw) == "null" {
			return ShellCall{}, false, errors.New("command must be a string")
		}
	}
	call.Dir, err = truthyString(p["cwd"])
	return call, true, err
}

func falsy(raw json.RawMessage) bool {
	switch strings.TrimSpace(string(raw)) {
	case "", "null", `""`, "0", "false", "[]", "{}":
		return true
	}
	return false
}

func truthyString(raw json.RawMessage) (string, error) {
	if falsy(raw) {
		return "", nil
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		return "", errors.New("directory must be a string")
	}
	return s, nil
}

type Output struct {
	HookEventName            string `json:"hookEventName"`
	PermissionDecision       string `json:"permissionDecision,omitempty"`
	PermissionDecisionReason string `json:"permissionDecisionReason,omitempty"`
	AdditionalContext        string `json:"additionalContext,omitempty"`
}

func deny(reason string) Output {
	if reason == "" {
		return Output{}
	}
	return Output{HookEventName: "PreToolUse", PermissionDecision: "deny", PermissionDecisionReason: reason}
}

func addContext(event, text string) Output {
	if text == "" {
		return Output{}
	}
	return Output{HookEventName: event, AdditionalContext: text}
}

func (o Output) write(w io.Writer) error {
	if o.HookEventName == "" {
		return nil
	}
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	return enc.Encode(struct {
		HookSpecificOutput Output `json:"hookSpecificOutput"`
	}{o})
}
