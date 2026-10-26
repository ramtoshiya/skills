#!/usr/bin/env python3
"""PreToolUse package/model policy and Python command guard.

Command text is parsed, never evaluated. This is an ordinary-command guard,
not a shell sandbox or a complete boundary against deliberate bypass.
"""
import json
from datetime import datetime, timezone
import os
from pathlib import Path, PurePath
import re
import shlex
import sys
import tomllib

MUTATIONS = {"install", "i", "add", "update", "up", "upgrade", "uninstall",
             "remove", "rm", "rebuild", "link", "unlink"}
FALSE_VALUES = {"false", "0", "no"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
WRAPPERS = {"command", "builtin", "noglob", "time", "env", "sudo"}
VALUE_OPTIONS = {"--prefix", "--cache", "--registry", "--userconfig", "--loglevel",
                 "--directory", "--project", "--config-file", "--python", "-p",
                 "--package", "--from", "--with", "--with-editable", "--index",
                 "--index-url", "--extra-index-url", "--workspace", "-w", "-C",
                 "--exclude-newer", "--exclude-newer-package", "--min-release-age",
                 "--config.minimumReleaseAge", "--minimum-release-age", "--before",
                 "--env-file", "--config-dir", "--globalconfig", "--call", "-c"}
MINIMUM_SECONDS = 3 * 86400
NPM_PIN = re.compile(r"(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+@"
                     r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
                     r"(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?")
PYTHON_PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?=="
                        r"[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?"
                        r"(?:\.post[0-9]+)?(?:\.dev[0-9]+)?(?:\+[A-Za-z0-9.-]+)?")
PYTHON_COMMAND = re.compile(r"(?:python|pip)(?:[0-9]+(?:\.[0-9]+)*)?")


def options(args, names):
    """Read literal option values without interpreting shell text."""
    values = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            break
        key, equal, value = token.partition("=")
        if key in names:
            if not equal:
                i += 1
                if i >= len(args):
                    raise ValueError("missing policy option value")
                value = args[i]
            values.append(value)
        elif not equal and token in VALUE_OPTIONS:
            i += 1
        i += 1
    return values


def one_option(args, names, fallback=None):
    values = options(args, names)
    return values[-1] if values else fallback


def resolve_path(value, cwd, environment):
    home = environment.get("home", str(Path.home()))
    value = value.replace("${HOME}", home).replace("$HOME", home)
    if value == "~" or value.startswith("~/"):
        value = home + value[1:]
    if "$" in value or "`" in value:
        raise ValueError("dynamic configuration path")
    path = Path(value)
    return path if path.is_absolute() else cwd / path


def nearest(cwd, name):
    for parent in (cwd, *cwd.parents):
        path = parent / name
        if path.is_file():
            return path
    return None


def scalar_settings(path, keys, yaml=False):
    """Read policy keys only; YAML policy keys must be simple root scalars.

    Unsupported/duplicate policy syntax fails closed. Unrelated config and
    credentials are never returned or printed.
    """
    result = {}
    if path is None or not path.exists():
        return result
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9_.-]*(?:\[\])?)\s*[:=]\s*(.*)", line)
        key = match[1].removesuffix("[]") if match else None
        if key not in keys:
            # Flow mappings and YAML quoted/nested keys cannot silently hide
            # an age-policy override from this dependency-free reader.
            if yaml and any(re.search(r"\b" + re.escape(k) + r"\b\s*['\"]?\s*:", line) for k in keys):
                raise ValueError("unsupported YAML policy syntax")
            continue
        if key in result or (yaml and line[:1].isspace()):
            raise ValueError("duplicate or nested policy setting")
        value = match[2].split("#", 1)[0].strip()
        if value[:1] in {"'", '"'}:
            parts = shlex.split(value)
            if len(parts) != 1:
                raise ValueError("unsupported policy scalar")
            value = parts[0]
        result[key] = value
    return result


def age_seconds(value, family):
    if isinstance(value, bool) or value is None:
        return -1
    text = str(value).strip().lower()
    if family in {"npm", "pnpm"} or (family == "yarn" and re.fullmatch(r"[0-9]+", text)):
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
            return -1
        return float(text) * (86400 if family == "npm" else 60)
    friendly = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(w|weeks?|d|days?|h|hours?|m|minutes?|s|seconds?)", text)
    if friendly:
        return float(friendly[1]) * {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}[friendly[2][0]]
    iso = re.fullmatch(r"p(?:(\d+(?:\.\d+)?)w)?(?:(\d+(?:\.\d+)?)d)?(?:t(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?)?", text)
    if iso and any(iso.groups()):
        return sum(float(n or 0) * unit for n, unit in zip(iso.groups(), [604800, 86400, 3600, 60, 1]))
    if family == "uv" or family == "date":
        try:
            cutoff = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                cutoff = cutoff.astimezone()
            return (datetime.now(timezone.utc) - cutoff).total_seconds()
        except ValueError:
            pass
    return -1


def uv_settings(path):
    if path is None or not path.exists():
        return {}
    data = tomllib.loads(path.read_text())
    return data.get("tool", {}).get("uv", {}) if path.name == "pyproject.toml" else data


def freshness_reason(family, args, environment, cwd, user_tool=False, pip=False):
    """Require a configured age floor; reject any weaker policy declaration.

    Checking every discovered policy declaration is deliberately conservative:
    a stronger CLI value does not excuse a weak project/user override. This
    avoids guessing manager-version-specific precedence without running it.
    """
    home = Path(environment.get("home", str(Path.home()))).resolve()
    config = resolve_path(environment.get("xdg_config_home", str(home / ".config")), cwd, environment)
    cwd = resolve_path(one_option(args, {"--directory", "-C"}, str(cwd)), cwd, environment).resolve()
    if family == "uv":
        cwd = resolve_path(one_option(args, {"--project"}, str(cwd)), cwd, environment).resolve()
    values = []
    exemptions = []
    if family == "uv":
        files = []
        explicit = one_option(args, {"--config-file"}, environment.get("uv_config_file"))
        no_config = "--no-config" in args or environment.get("uv_no_config", "0").lower() not in FALSE_VALUES
        if explicit:
            files = [resolve_path(explicit, cwd, environment)]
            if not files[0].is_file():
                raise ValueError("configuration file is missing")
        elif not no_config:
            files = [Path("/etc/uv/uv.toml"), config / "uv/uv.toml"]
            if not user_tool:
                for parent in (cwd, *cwd.parents):
                    uvfile = parent / "uv.toml"
                    pyfile = parent / "pyproject.toml"
                    candidate = uvfile if uvfile.exists() else pyfile
                    if candidate.exists() and uv_settings(candidate):
                        files.append(candidate)
                        break
        for path in files:
            settings = uv_settings(path)
            tables = [settings] + ([settings.get("pip", {})] if pip else [])
            for table in tables:
                if "exclude-newer" in table:
                    values.append((table["exclude-newer"], "uv"))
                per_package = table.get("exclude-newer-package", {})
                if not isinstance(per_package, dict):
                    raise ValueError("unsupported per-package age policy")
                exemptions.extend((value, "uv") for value in per_package.values())
        values.extend((v, "uv") for v in options(args, {"--exclude-newer"}))
        if "uv_exclude_newer" in environment:
            values.append((environment["uv_exclude_newer"], "uv"))
        for value in options(args, {"--exclude-newer-package"}):
            if "=" not in value:
                raise ValueError("invalid per-package cutoff")
            exemptions.append((value.split("=", 1)[1], "uv"))
        if environment.get("uv_exclude_newer_package"):
            # The mapping syntax depends on uv version; don't accept an
            # unverified package-specific bypass via the environment.
            return "Package-specific age overrides must use reviewed config or explicit flags."
    else:
        key = {"npm": "min-release-age", "pnpm": "minimumReleaseAge", "yarn": "npmMinimalAgeGate"}[family]
        exempt = {"npm": "min-release-age-exclude", "pnpm": "minimumReleaseAgeExclude", "yarn": "npmPreapprovedPackages"}[family]
        keys = {key, exempt, "before", "minimum-release-age", "global"}
        if family == "npm":
            userfile = one_option(args, {"--userconfig"}, environment.get("npm_config_userconfig", str(home / ".npmrc")))
            files = [resolve_path(userfile, cwd, environment)]
            globalfile = one_option(args, {"--globalconfig"}, environment.get("npm_config_globalconfig"))
            if globalfile:
                files.insert(0, resolve_path(globalfile, cwd, environment))
            project = resolve_path(one_option(args, {"--prefix"}, str(cwd)), cwd, environment)
            projectfile = nearest(project, ".npmrc")
            if projectfile != home / ".npmrc":
                files.append(projectfile)
        elif family == "pnpm":
            default = config / "pnpm/config.yaml" if "xdg_config_home" in environment or sys.platform != "darwin" else home / "Library/Preferences/pnpm/config.yaml"
            configdir = one_option(args, {"--config-dir"})
            files = [(resolve_path(configdir, cwd, environment) / "config.yaml") if configdir else default,
                     nearest(cwd, "pnpm-workspace.yaml"), nearest(cwd, ".npmrc")]
        else:
            files = [home / ".yarnrc.yml"] + list(reversed([parent / ".yarnrc.yml" for parent in (cwd, *cwd.parents) if parent != home]))
        for path in files:
            settings = scalar_settings(path, keys, yaml=family != "npm" and path is not None and path.suffix in {".yaml", ".yml"})
            for k in {key, "minimum-release-age"} if family == "pnpm" else {key}:
                if k in settings:
                    values.append((settings[k], family))
            if exempt in settings and settings[exempt].lower() not in {"[]", "false", "null"}:
                return "Release-age exemption lists weaken the three-day policy."
            if family == "npm" and "before" in settings:
                exemptions.append((settings["before"], "date"))
            if family in {"npm", "pnpm"} and settings.get("global", "false").lower() not in FALSE_VALUES:
                return "Configuration-derived global package mutations are disabled."
        envkey = {"npm": "npm_config_min_release_age", "pnpm": "npm_config_minimum_release_age", "yarn": "yarn_npm_minimal_age_gate"}[family]
        flags = {"npm": {"--min-release-age"}, "pnpm": {"--config.minimumReleaseAge", "--minimum-release-age"}, "yarn": set()}[family]
        values.extend((v, family) for v in options(args, flags))
        if envkey in environment:
            values.append((environment[envkey], family))
        exempt_flags = {"--" + exempt, "--" + exempt + "[]", "--config." + exempt}
        if options(args, exempt_flags) or environment.get({"npm": "npm_config_min_release_age_exclude", "pnpm": "npm_config_minimum_release_age_exclude", "yarn": "yarn_npm_preapproved_packages"}[family]):
            return "Release-age exemption lists weaken the three-day policy."
        if family == "npm":
            exemptions.extend((v, "date") for v in options(args, {"--before"}))
            if "npm_config_before" in environment:
                exemptions.append((environment["npm_config_before"], "date"))
    if any(age_seconds(v, kind) < MINIMUM_SECONDS for v, kind in values + exemptions):
        return "Release-age overrides must preserve a minimum of three days; disabling or weakening the policy is blocked."
    if not values and not (family == "npm" and exemptions):
        return "Package operations require a configured three-day release-age floor."
    return None


def without_heredoc_bodies(command):
    # Here-doc bodies are script/data payloads, not outer-shell command tokens.
    # Their contents are outside this guard's ordinary-command coverage.
    output = []
    pending = []
    for line in command.splitlines(keepends=True):
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.rstrip("\r\n")
            if (candidate.lstrip("\t") if strip_tabs else candidate) == delimiter:
                pending.pop(0)
            continue
        output.append(line)
        for match in re.finditer(r"<<(-)?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", line):
            pending.append((match[3], bool(match[1])))
    return "".join(output)


def segments(command):
    lexer = shlex.shlex(without_heredoc_bodies(command), posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    current = []
    for token in lexer:
        if token and all(char in ";&|()\n" for char in token):
            if current:
                yield current
                current = []
        else:
            current.append(token)
    if current:
        yield current


def unwrap(tokens, inherited=None):
    environment = dict(inherited or {})
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            key, value = token.split("=", 1)
            environment[key.lower()] = value
            i += 1
        elif PurePath(token).name in WRAPPERS:
            wrapper = PurePath(token).name
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                flag = tokens[i]
                i += 1
                if wrapper == "env" and flag in ("-S", "--split-string"):
                    if i >= len(tokens):
                        raise ValueError("missing env command")
                    return unwrap(shlex.split(tokens[i]) + tokens[i + 1:], environment)
                if wrapper == "env" and flag.startswith("--split-string="):
                    return unwrap(shlex.split(flag.split("=", 1)[1]) + tokens[i:], environment)
                if wrapper == "env" and flag in ("-i", "--ignore-environment"):
                    environment.clear()
                if wrapper == "env" and flag in ("-u", "--unset") and i < len(tokens):
                    environment.pop(tokens[i].lower(), None)
                if (wrapper == "env" and flag in ("-u", "--unset")) or (wrapper == "sudo" and flag in ("-u", "--user", "-g", "--group")):
                    i += 1
        elif token in {"if", "then", "elif", "else", "do", "!"}:
            i += 1
        else:
            break
    return tokens[i:], environment


def global_flag(args, environment):
    enabled = environment.get("npm_config_global", "false").lower() not in FALSE_VALUES
    for token in args:
        if token == "--":
            break
        if token == "--global" or (token.startswith("-") and not token.startswith("--") and "g" in token[1:]):
            enabled = True
        elif token.startswith("--global="):
            enabled = token.split("=", 1)[1].lower() not in FALSE_VALUES
        elif token == "--no-global":
            enabled = False
    return enabled


def positional_arguments(args):
    words = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            break
        if token in VALUE_OPTIONS:
            i += 2
            continue
        if not token.startswith("-"):
            words.append(token)
        i += 1
    return words


def positions(args):
    """Positional tokens with indexes, including command targets after --."""
    result = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            result.extend((index, args[index]) for index in range(i + 1, len(args)))
            break
        if token in VALUE_OPTIONS:
            i += 2
            continue
        if not token.startswith("-"):
            result.append((i, token))
        i += 1
    return result


def package_operation(name, args):
    """Return (family, manager options, requested one-shot packages, mode)."""
    words = positions(args)
    sub = words[0][1] if words else ""
    family = {"npx": "npm", "pnpx": "pnpm", "pnx": "pnpm", "uvx": "uv"}.get(name, name)
    one_shot = name in {"npx", "pnpx", "pnx", "uvx"}
    consumed = 0
    user_tool = name == "uvx"
    pip = False
    if one_shot and not words and any(flag in args for flag in {"--help", "-h", "--version", "-V"}):
        return None
    if name in {"npm", "pnpm", "yarn"}:
        if name == "npm" and sub == "init" and len(words) == 1:
            return None  # Built-in package.json creation does not fetch a package.
        one_shot = sub in ({"exec", "x", "create", "init"} if name == "npm" else {"dlx", "create"})
        if not one_shot and sub not in {"install", "i", "add", "update", "up", "upgrade", "ci", "rebuild", "dedupe"}:
            if not (name == "npm" and sub == "audit" and len(words) > 1 and words[1][1] == "fix"):
                return None
        consumed = 1
    elif name == "uv":
        if sub == "tool" and len(words) > 1 and words[1][1] == "run":
            one_shot = user_tool = True
            consumed = 2
        elif sub == "pip" and len(words) > 1 and words[1][1] in {"install", "sync", "compile"}:
            pip = True
        elif sub not in {"add", "sync", "lock", "run"}:
            return None
    elif not one_shot:
        return None
    packages = []
    manager_args = args
    if one_shot:
        target = words[consumed] if len(words) > consumed else None
        if target and name not in {"npm"}:
            manager_args = args[:target[0]]
        explicit = options(manager_args, {"--from"}) if family == "uv" else options(manager_args, {"--package", "-p"})
        packages = explicit or ([target[1]] if target else [])
        if not packages:
            return family, manager_args, [""], user_tool, pip
    if name == "uv" and sub == "run":
        target = words[1] if len(words) > 1 else None
        manager_args = args[:target[0]] if target else args
    if family == "uv":
        packages.extend(options(manager_args, {"--with"}))
        if options(manager_args, {"--with-editable"}):
            # Editable/local code has no registry version or publish-age
            # metadata. Keep project development available outside one-shots.
            if one_shot:
                packages.append("")
    return family, manager_args, packages, user_tool, pip


def python_reason(executable, cwd, environment):
    if not PYTHON_COMMAND.fullmatch(PurePath(executable).name):
        return None
    if "/" in executable:
        path = resolve_path(executable, cwd, environment)
        if path.parent.name == "bin" and (path.parent.parent.name in {".venv", "venv"} or (path.parent.parent / "pyvenv.cfg").is_file()):
            return None
    return "Bare Python/pip commands are disabled. Use uv run, uv pip, or an explicit virtual-environment interpreter path."


def model_option(args, names):
    """Read all model option declarations, rejecting missing/dynamic values."""
    values = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            break
        key, equal, value = token.partition("=")
        if key in names:
            if not equal:
                i += 1
                value = args[i] if i < len(args) else ""
            if not value or value.startswith("-") or any(c in value for c in "$`"):
                raise ValueError("model options require literal values")
            values.append(value)
        i += 1
    return values


def model_reason(name, args, cwd, environment):
    """Guard common acquisition/loading CLIs, not arbitrary SDK code."""
    if name in {"hf", "huggingface-cli", "ollama"} and len(args) == 2 and args[1] in {"--help", "-h"}:
        return None
    if name in {"hf", "huggingface-cli"} and args[:1] == ["download"]:
        revisions = model_option(args[1:], {"--revision"})
        if not revisions or any(not re.fullmatch(r"[0-9a-fA-F]{40}", v) for v in revisions):
            return "Model downloads require --revision with a full 40-character commit hash from a reviewed publisher. Branches and tags are mutable."
        # Dataset/space repositories can also carry executable/model artifacts.
        return None
    if name == "ollama" and args[:1] in (["pull"], ["run"], ["create"]):
        return "Ollama pull/run/create cannot establish immutable artifact provenance here. Use a reviewed commit-pinned download and an explicit local model path instead."

    model_cli = name.startswith(("mlx_lm.", "mlx_vlm.")) or name in {"omlx", "vllm", "llama-server", "llama-cli"}
    if not model_cli:
        return None
    if any(len(token.split("=", 1)[0]) > 2 and forbidden.startswith(token.split("=", 1)[0])
           for token in args for forbidden in {"--trust-remote-code", "--trust_remote_code"}):
        return "Model remote code execution is disabled. Review code separately and use local artifacts without trust-remote-code."
    if any(flag in args for flag in {"--help", "-h", "--version"}):
        return None

    server = name in {"llama-server", "mlx_lm.server", "mlx_vlm.server"} or (name in {"omlx", "vllm"} and args[:1] == ["serve"])
    loaders = {"mlx_lm.generate", "mlx_vlm.generate", "mlx_lm.convert", "mlx_vlm.convert", "llama-cli"}
    if not server and name not in loaders:
        return None
    remote_flags = {"-hf", "--hf-repo", "-hfr", "--hf-repo-v", "-hff", "--hf-file", "-mu", "--model-url"}
    if name in {"llama-server", "llama-cli"} and (
        any(token.split("=", 1)[0] in remote_flags for token in args)
        or any(environment.get(key) for key in {"llama_arg_hf_repo", "llama_arg_hf_repo_v", "llama_arg_hf_file", "llama_arg_model_url"})
    ):
        return "Remote model sources are disabled for llama commands. Download a reviewed revision separately and load only local artifacts."
    model_flags = {"--model", "--model-dir", "--hf-path", "-m"}
    models = model_option(args, model_flags)
    if name == "vllm" and args[:1] == ["serve"] and len(args) > 1 and not args[1].startswith("-"):
        models.append(args[1])
    if not models:
        return "Model loading requires an explicit local artifact path. Download a reviewed full revision first, then verify the artifact hashes."
    models.extend(model_option(args, {"--adapter-path"}))
    for value in models:
        # A repo id (publisher/model) must not silently trigger a Hub fetch.
        if not (value.startswith(("/", "./", "../", "~/"))):
            return "Model loading requires an explicit local artifact path, not a repository id or mutable model name."
        path = resolve_path(value, cwd, environment)
        if not path.exists():
            return "The local model path must already exist. Acquire and verify pinned artifacts before loading."
    if server:
        hosts = model_option(args, {"--host"})
        if not hosts or any(host not in {"127.0.0.1", "::1", "localhost"} for host in hosts):
            return "Model servers require an explicit loopback --host (127.0.0.1, ::1, or localhost). Keep secrets and tool execution outside the inference process."
    return None


def model_command(tokens):
    """Expose uv run and Python -m targets without evaluating script bodies."""
    if not tokens:
        return "", []
    name, args = PurePath(tokens[0]).name, tokens[1:]
    if name == "uv":
        words = positions(args)
        if len(words) < 2 or words[0][1] != "run":
            return name, args
        return model_command(args[words[1][0]:])
    if PYTHON_COMMAND.fullmatch(name):
        index = 0
        while index < len(args):
            token = args[index]
            if token in {"-W", "-X", "--check-hash-based-pycs"}:
                index += 2
                continue
            module = re.fullmatch(r"-[bBdEiIOPqRsSuvVx]*m(.*)", token)
            if module:
                if module[1]:
                    return module[1], args[index + 1:]
                if index + 1 < len(args):
                    return args[index + 1], args[index + 2:]
                break
            if not token.startswith("-") or token == "-" or re.match(r"-[bBdEiIOPqRsSuvVx]*c", token):
                break
            index += 1
    return name, args


def reason(command, cwd=None, environment=None, depth=0):
    if depth > 4:
        return "Shell wrappers are too deeply nested to review. Use a simple command."
    cwd = Path(cwd or Path.cwd()).resolve()
    environment = {key.lower(): value for key, value in (os.environ if environment is None else environment).items()}
    for segment in segments(command):
        if all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token) for token in segment):
            for token in segment:
                key, value = token.split("=", 1)
                environment[key.lower()] = value
            continue
        tokens, effective = unwrap(segment, environment)
        if not tokens:
            continue
        name = PurePath(tokens[0]).name
        args = tokens[1:]
        if name in {"export", "readonly"}:
            assignments = segment[1:]
            for token in assignments:
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                    key, value = token.split("=", 1)
                    environment[key.lower()] = value
            continue
        if name == "cd" and args:
            cwd = resolve_path(args[-1], cwd, effective).resolve()
            continue
        denial_reason = python_reason(tokens[0], cwd, effective)
        if denial_reason:
            return denial_reason
        if name in SHELLS:
            for index, token in enumerate(args[:-1]):
                if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:
                    nested = reason(args[index + 1], cwd, effective, depth + 1)
                    if nested:
                        return nested
                    break
        model_name, model_args = model_command(tokens)
        try:
            denial_reason = model_reason(model_name, model_args, cwd, effective)
        except ValueError:
            return "Model options require explicit literal values and existing local paths."
        if denial_reason:
            return denial_reason
        # Only check mutating subcommands; an echoed command or npm test's
        # arguments do not become package-manager operations.
        package_args = args[:args.index("--")] if "--" in args else args
        words = positional_arguments(package_args)
        if name in {"npm", "pnpm"} and words and words[0] in MUTATIONS:
            if global_flag(package_args, effective):
                return "Global package installs and mutations are disabled. Use a project dependency or exact-pinned one-shot execution."
        if name == "yarn" and len(words) > 1 and words[0] == "global" and words[1] in MUTATIONS:
            return "Global package installs and mutations are disabled."
        if name == "uv" and len(words) > 1 and words[0] == "tool" and words[1] in MUTATIONS:
            return "Global package installs and mutations are disabled."
        operation = package_operation(name, args)
        if operation:
            family, manager_args, packages, user_tool, pip = operation
            pin = PYTHON_PIN if family == "uv" else NPM_PIN
            if any(not pin.fullmatch(package) for package in packages):
                return "One-shot execution requires exact package versions: package@1.2.3 for Node or package==1.2.3 for Python. Tags, ranges, and unversioned packages are blocked."
            denial_reason = freshness_reason(family, manager_args, effective, cwd, user_tool, pip)
            if denial_reason:
                return denial_reason
    return None


def blocked(command, cwd=None, environment=None):
    return reason(command, cwd, environment) is not None


def denial(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def main():
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "")
        if tool not in {"Bash", "Monitor", "Shell", "shell", "exec_command", "functions.exec_command", "terminal"}:
            return
        data = payload.get("tool_input", {})
        command = data.get("command", data.get("cmd", ""))
        if not isinstance(command, str):
            raise ValueError("command must be a string")
        denial_reason = reason(command, data.get("workdir") or payload.get("cwd"))
        if denial_reason:
            denial(denial_reason)
    except (ValueError, TypeError, AttributeError, OSError):
        denial("The package/Python guard could not verify this tool call or its policy settings. Use literal paths and simple policy settings.")


if __name__ == "__main__":
    main()
