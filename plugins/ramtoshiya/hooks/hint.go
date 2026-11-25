package main

import (
	"regexp"
	"slices"
	"strings"
)

var missingModule = regexp.MustCompile(`ModuleNotFoundError: No module named '([A-Za-z0-9_]+)`)

func runModuleHint(p payload) (Output, error) {
	var modules []string
	for _, match := range missingModule.FindAllSubmatch(p["tool_response"], -1) {
		modules = append(modules, string(match[1]))
	}
	if len(modules) == 0 {
		return Output{}, nil
	}
	slices.Sort(modules)
	return addContext("PostToolUse", "Python could not import `"+strings.Join(slices.Compact(modules), "`, `")+"`"+
		". The tool can still run: rerun the same command as "+
		"`uv run --with PACKAGE==VERSION python SCRIPT ARGS`, with one `--with` per missing "+
		"package. PACKAGE is the distribution that provides the module and its name can differ, "+
		"for example `pyyaml` provides `yaml`. Pin an exact version released at least three days "+
		"ago, and add `--offline` to use only versions already in uv's cache. Do not install into "+
		"the system Python."), nil
}
