package guard

import (
	"errors"
	"regexp"
	"strings"

	"ramtoshiya-hooks/shell"
)

const (
	literalDenial      = "Model options require explicit literal values and existing local paths."
	revisionDenial     = "Model downloads require --revision with a full 40-character commit hash from a reviewed publisher. Branches and tags are mutable."
	ollamaDenial       = "Ollama pull/run/create cannot establish immutable artifact provenance here. Use a reviewed commit-pinned download and an explicit local model path instead."
	remoteCodeDenial   = "Model remote code execution is disabled. Review code separately and use local artifacts without trust-remote-code."
	remoteSourceDenial = "Remote model sources are disabled for llama commands. Download a reviewed revision separately and load only local artifacts."
	noModelDenial      = "Model loading requires an explicit local artifact path. Download a reviewed full revision first, then verify the artifact hashes."
	mutableModelDenial = "Model loading requires an explicit local artifact path, not a repository id or mutable model name."
	missingModelDenial = "The local model path must already exist. Acquire and verify pinned artifacts before loading."
	hostDenial         = "Model servers require an explicit loopback --host (127.0.0.1, ::1, or localhost). Keep secrets and tool execution outside the inference process."
)

var (
	commitHash  = regexp.MustCompile(`^[0-9a-fA-F]{40}\z`)
	remoteFlags = set("-hf", "--hf-repo", "-hfr", "--hf-repo-v", "-hff", "--hf-file", "-mu", "--model-url")
	remoteEnv   = []string{"llama_arg_hf_repo", "llama_arg_hf_repo_v", "llama_arg_hf_file", "llama_arg_model_url"}
	loaders     = set("mlx_lm.generate", "mlx_vlm.generate", "mlx_lm.convert", "mlx_vlm.convert", "llama-cli")
	loopback    = set("127.0.0.1", "::1", "localhost")
	trustFlags  = []string{"--trust-remote-code", "--trust_remote_code"}
	modelFlags  = set("--model", "--model-dir", "--hf-path", "-m")
)

func modelOption(args words, names map[string]bool) (words, error) {
	var values words
	for i := 0; i < len(args); i++ {
		token := args[i]
		if is(token, "--") {
			break
		}
		key, value, equal := split(token)
		if !names[key] {
			continue
		}
		if !equal {
			i++
			value = shell.Word{}
			if i < len(args) {
				value = args[i]
			}
		}
		if value.Empty() || dashed(value) || strings.ContainsAny(value.Script(), "$`") {
			return nil, errValue
		}
		values = append(values, value)
	}
	return values, nil
}

func first(args words, s string) bool { return len(args) > 0 && is(args[0], s) }

func modelRule(c shell.Call) error {
	name, args := modelCommand(c.Name, c.Args)
	reason, err := modelReason(name, args, c)
	switch {
	case errors.Is(err, shell.ErrUnknownDir):
		return shell.Denial(unknownDirDenial)
	case errors.Is(err, errValue), errors.Is(err, shell.ErrDynamic):
		return shell.Denial(literalDenial)
	case err != nil:
		return err
	case reason != "":
		return shell.Denial(reason)
	}
	return nil
}

func modelReason(nameWord shell.Word, args words, c shell.Call) (string, error) {
	name, _ := nameWord.Literal()
	if oneOf(nameWord, set("hf", "huggingface-cli", "ollama")) && len(args) == 2 && oneOf(args[1], set("--help", "-h")) {
		return "", nil
	}
	if oneOf(nameWord, set("hf", "huggingface-cli")) && first(args, "download") {
		revisions, err := modelOption(args[1:], set("--revision"))
		if err != nil {
			return "", err
		}
		for _, revision := range revisions {
			if text, ok := revision.Literal(); !ok || !commitHash.MatchString(text) {
				return revisionDenial, nil
			}
		}
		if len(revisions) == 0 {
			return revisionDenial, nil
		}
		return "", nil
	}
	if name == "ollama" && (first(args, "pull") || first(args, "run") || first(args, "create")) {
		return ollamaDenial, nil
	}
	prefix := nameWord.Prefix()
	modelCLI := strings.HasPrefix(prefix, "mlx_lm.") || strings.HasPrefix(prefix, "mlx_vlm.") ||
		oneOf(nameWord, set("omlx", "vllm", "llama-server", "llama-cli"))
	if !modelCLI {
		return "", nil
	}
	for _, token := range args {
		key, _, _ := split(token)
		if len(key) > 2 {
			for _, forbidden := range trustFlags {
				if strings.HasPrefix(forbidden, key) {
					return remoteCodeDenial, nil
				}
			}
		}
	}
	if has(args, "--help") || has(args, "-h") || has(args, "--version") {
		return "", nil
	}
	serve := first(args, "serve")
	server := oneOf(nameWord, set("llama-server", "mlx_lm.server", "mlx_vlm.server")) ||
		oneOf(nameWord, set("omlx", "vllm")) && serve
	if !server && !oneOf(nameWord, loaders) {
		return "", nil
	}
	if oneOf(nameWord, set("llama-server", "llama-cli")) {
		for _, token := range args {
			if key, _, _ := split(token); remoteFlags[key] {
				return remoteSourceDenial, nil
			}
		}
		for _, key := range remoteEnv {
			if truthyEnv(c.Env, key) {
				return remoteSourceDenial, nil
			}
		}
	}
	models, err := modelOption(args, modelFlags)
	if err != nil {
		return "", err
	}
	if oneOf(nameWord, set("vllm")) && serve && len(args) > 1 && !dashed(args[1]) {
		models = append(models, args[1])
	}
	if len(models) == 0 {
		return noModelDenial, nil
	}
	adapters, err := modelOption(args, set("--adapter-path"))
	if err != nil {
		return "", err
	}
	models = append(models, adapters...)
	for _, value := range models {
		prefix := value.Prefix()
		if !strings.HasPrefix(prefix, "/") && !strings.HasPrefix(prefix, "./") && !strings.HasPrefix(prefix, "../") && !strings.HasPrefix(prefix, "~/") {
			return mutableModelDenial, nil
		}
		path, err := shell.Resolve(value, c.Dir, shell.Home(c.Env))
		if err != nil {
			return "", err
		}
		ok, err := exists(path)
		if err != nil {
			return "", err
		}
		if !ok {
			return missingModelDenial, nil
		}
	}
	if server {
		hosts, err := modelOption(args, set("--host"))
		if err != nil {
			return "", err
		}
		if len(hosts) == 0 {
			return hostDenial, nil
		}
		for _, host := range hosts {
			if !oneOf(host, loopback) {
				return hostDenial, nil
			}
		}
	}
	return "", nil
}
