package main

import (
	"fmt"
	"io"
	"os"
)

type hook struct {
	run     func(payload) (Output, error)
	onError Output
}

var hooks = map[string]hook{
	"commit-trailer": {runTrailer, Output{}},
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
