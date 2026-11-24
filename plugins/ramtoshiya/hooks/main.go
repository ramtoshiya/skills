package main

import (
	"fmt"
	"io"
	"os"

	"ramtoshiya-hooks/guard"
	"ramtoshiya-hooks/shell"
)

const couldNotVerify = "The package/Python guard could not verify this tool call or its policy settings. Use literal paths and simple policy settings."

type hook struct {
	run     func(payload) (Output, error)
	onError Output
}

var hooks = map[string]hook{
	"commit-trailer": {runTrailer, Output{}},
	"guard":          {runGuard, Output{Deny: couldNotVerify}},
}

func runGuard(p payload) (Output, error) {
	call, ok, err := shellCall(p)
	if err != nil || !ok {
		return Output{}, err
	}
	dir := call.Dir
	if dir == "" {
		if dir, err = os.Getwd(); err != nil {
			return Output{}, err
		}
	}
	deny, err := guard.Check(call.Script, shell.State{Dir: shell.NewDir(shell.Absolute(dir)), Env: shell.EnvFrom(os.Environ())})
	return Output{Deny: deny}, err
}

func dispatch(h hook, in io.Reader) (out Output) {
	defer func() {
		if recover() != nil {
			out = h.onError
		}
	}()
	data, err := io.ReadAll(in)
	if err != nil {
		return h.onError
	}
	p, err := decode(data)
	if err != nil {
		return h.onError
	}
	if out, err = h.run(p); err != nil {
		return h.onError
	}
	return out
}

func main() {
	var name string
	if len(os.Args) > 1 {
		name = os.Args[1]
	}
	h, ok := hooks[name]
	if !ok {
		fmt.Fprintf(os.Stderr, "ramtoshiya-hooks: unknown subcommand %q\n", name)
		os.Exit(1)
	}
	dispatch(h, os.Stdin).write(os.Stdout)
}
