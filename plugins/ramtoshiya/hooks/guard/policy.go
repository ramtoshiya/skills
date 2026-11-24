package guard

import (
	"errors"
	"runtime"
	"strings"

	"ramtoshiya-hooks/shell"
)

const (
	exemptionDenial  = "Release-age exemption lists weaken the three-day policy."
	globalDenial     = "Configuration-derived global package mutations are disabled."
	ageDenial        = "Release-age overrides must preserve a minimum of three days; disabling or weakening the policy is blocked."
	floorDenial      = "Package operations require a configured three-day release-age floor."
	perPackageDenial = "Package-specific age overrides must use reviewed config or explicit flags."
)

type cutoff struct {
	value  any
	family string
}

type npmFamily struct {
	key, exempt, envKey, exemptEnv string
	flags                          map[string]bool
}

var npmFamilies = map[string]npmFamily{
	"npm": {"min-release-age", "min-release-age-exclude", "npm_config_min_release_age",
		"npm_config_min_release_age_exclude", set("--min-release-age")},
	"pnpm": {"minimumReleaseAge", "minimumReleaseAgeExclude", "npm_config_minimum_release_age",
		"npm_config_minimum_release_age_exclude", set("--config.minimumReleaseAge", "--minimum-release-age")},
	"yarn": {"npmMinimalAgeGate", "npmPreapprovedPackages", "yarn_npm_minimal_age_gate",
		"yarn_npm_preapproved_packages", set()},
}

func texts(ws words) []string {
	result := make([]string, len(ws))
	for i, w := range ws {
		result[i] = w.Script()
	}
	return result
}

func cutoffs(values []string, family string) []cutoff {
	result := make([]cutoff, len(values))
	for i, v := range values {
		result[i] = cutoff{v, family}
	}
	return result
}

func envText(env shell.Env, key string) (string, bool) {
	w, ok := env[key]
	return w.Script(), ok
}

func truthyEnv(env shell.Env, key string) bool {
	text, _ := envText(env, key)
	return text != ""
}

type freshness struct {
	family   string
	args     words
	env      shell.Env
	dir      shell.Dir
	userTool bool
	pip      bool
	home     string
	config   string
}

func (f *freshness) resolve(w shell.Word, dir shell.Dir) (string, error) {
	return shell.Resolve(w, dir, shell.Home(f.env))
}

func (f *freshness) cwd() (string, error) {
	path, ok := f.dir.Path()
	if !ok {
		return "", shell.ErrUnknownDir
	}
	return path, nil
}

func (f *freshness) startDirectory() (shell.Word, bool, error) {
	value, found, err := oneOption(f.args, set("--directory", "-C"))
	if err != nil || found && !value.Empty() {
		return value, found, err
	}
	switch f.family {
	case "uv":
		value, found, err = oneOption(f.args, set("--project"))
		if err != nil || found && !value.Empty() {
			return value, found, err
		}
	case "npm":
		return oneOption(f.args, set("--prefix"))
	}
	return shell.Word{}, false, nil
}

func (f *freshness) enter() error {
	if _, ok := f.dir.Path(); ok {
		return nil
	}
	directory, found, err := f.startDirectory()
	if err != nil {
		return err
	}
	if found {
		path, err := f.resolve(directory, shell.Dir{})
		if err != nil {
			return err
		}
		f.dir = shell.NewDir(shell.RealPath(path))
		return nil
	}
	if f.family == "uv" && f.userTool {
		return nil
	}
	return shell.ErrUnknownDir
}

func (f *freshness) retarget(names map[string]bool) error {
	path, _ := f.dir.Path()
	value, found, err := oneOption(f.args, names)
	if err != nil {
		return err
	}
	if found {
		if path, err = f.resolve(value, f.dir); err != nil {
			return err
		}
	}
	f.dir = shell.NewDir(shell.RealPath(path))
	return nil
}

func check(c shell.Call, family string, args words, userTool, pip bool) (string, error) {
	f := &freshness{family: family, args: args, env: c.Env, dir: c.Dir, userTool: userTool, pip: pip}
	if err := f.enter(); err != nil {
		return "", err
	}
	f.home = shell.Absolute(shell.Home(f.env))
	xdg, ok := f.env["xdg_config_home"]
	if !ok {
		xdg = shell.NewLiteral(shell.Normalize(f.home + "/.config"))
	}
	config, err := f.resolve(xdg, f.dir)
	if err != nil {
		return "", err
	}
	f.config = config
	if _, known := f.dir.Path(); known {
		if err := f.retarget(set("--directory", "-C")); err != nil {
			return "", err
		}
		if family == "uv" {
			if err := f.retarget(set("--project")); err != nil {
				return "", err
			}
		}
	}
	var values, exemptions []cutoff
	if family == "uv" {
		return f.uv(&values, &exemptions)
	}
	return f.node(&values, &exemptions)
}

func verdict(values, exemptions []cutoff, npm bool) string {
	for _, c := range append(append([]cutoff{}, values...), exemptions...) {
		if ageSeconds(c.value, c.family) < minimumSeconds {
			return ageDenial
		}
	}
	if len(values) == 0 && !(npm && len(exemptions) > 0) {
		return floorDenial
	}
	return ""
}

func (f *freshness) uvFiles() ([]string, error) {
	explicit, found, err := oneOption(f.args, set("--config-file"))
	if err != nil {
		return nil, err
	}
	if !found {
		explicit, found = f.env["uv_config_file"]
	}
	noConfig := has(f.args, "--no-config")
	if !noConfig {
		text, ok := envText(f.env, "uv_no_config")
		if !ok {
			text = "0"
		}
		noConfig = !isFalseText(text)
	}
	if found && !explicit.Empty() {
		path, err := f.resolve(explicit, f.dir)
		if err != nil {
			return nil, err
		}
		ok, err := isFile(path)
		if err != nil {
			return nil, err
		}
		if !ok {
			return nil, errors.New("configuration file is missing")
		}
		return []string{path}, nil
	}
	if noConfig {
		return nil, nil
	}
	files := []string{"/etc/uv/uv.toml", child(f.config, "uv/uv.toml")}
	if f.userTool {
		return files, nil
	}
	start, err := f.cwd()
	if err != nil {
		return nil, err
	}
	for _, parent := range shell.Ancestors(start) {
		candidate := child(parent, "uv.toml")
		ok, err := exists(candidate)
		if err != nil {
			return nil, err
		}
		if !ok {
			candidate = child(parent, "pyproject.toml")
			if ok, err = exists(candidate); err != nil {
				return nil, err
			}
		}
		if !ok {
			continue
		}
		settings, err := uvSettings(candidate)
		if err != nil {
			return nil, err
		}
		if len(settings) > 0 {
			return append(files, candidate), nil
		}
	}
	return files, nil
}

func isFalseText(text string) bool {
	switch strings.ToLower(text) {
	case "false", "0", "no":
		return true
	}
	return false
}

func tableOf(value any, present bool) (map[string]any, error) {
	if !present {
		return map[string]any{}, nil
	}
	table, ok := value.(map[string]any)
	if !ok {
		return nil, errors.New("unsupported policy table")
	}
	return table, nil
}

func (f *freshness) uv(values, exemptions *[]cutoff) (string, error) {
	files, err := f.uvFiles()
	if err != nil {
		return "", err
	}
	for _, path := range files {
		settings, err := uvSettings(path)
		if err != nil {
			return "", err
		}
		tables := []map[string]any{settings}
		if f.pip {
			pip, err := tableOf(settings["pip"], settings["pip"] != nil)
			if err != nil {
				return "", err
			}
			tables = append(tables, pip)
		}
		for _, table := range tables {
			if v, ok := table["exclude-newer"]; ok {
				*values = append(*values, cutoff{v, "uv"})
			}
			per, err := tableOf(table["exclude-newer-package"], table["exclude-newer-package"] != nil)
			if err != nil {
				return "", err
			}
			for _, v := range per {
				*exemptions = append(*exemptions, cutoff{v, "uv"})
			}
		}
	}
	flagged, err := options(f.args, set("--exclude-newer"))
	if err != nil {
		return "", err
	}
	*values = append(*values, cutoffs(texts(flagged), "uv")...)
	if text, ok := envText(f.env, "uv_exclude_newer"); ok {
		*values = append(*values, cutoff{text, "uv"})
	}
	packages, err := options(f.args, set("--exclude-newer-package"))
	if err != nil {
		return "", err
	}
	for _, text := range texts(packages) {
		_, after, ok := strings.Cut(text, "=")
		if !ok {
			return "", errors.New("invalid per-package cutoff")
		}
		*exemptions = append(*exemptions, cutoff{after, "uv"})
	}
	if truthyEnv(f.env, "uv_exclude_newer_package") {
		return perPackageDenial, nil
	}
	return verdict(*values, *exemptions, false), nil
}

func suffix(path string) string {
	name := path[strings.LastIndex(path, "/")+1:]
	if i := strings.LastIndex(name, "."); i > 0 && i < len(name)-1 {
		return name[i:]
	}
	return ""
}

func (f *freshness) nodeFiles() ([]string, error) {
	cwd, err := f.cwd()
	if err != nil {
		return nil, err
	}
	switch f.family {
	case "npm":
		userfile, found, err := oneOption(f.args, set("--userconfig"))
		if err != nil {
			return nil, err
		}
		if !found {
			if userfile, found = f.env["npm_config_userconfig"]; !found {
				userfile = shell.NewLiteral(child(f.home, ".npmrc"))
			}
		}
		user, err := f.resolve(userfile, f.dir)
		if err != nil {
			return nil, err
		}
		files := []string{user}
		globalfile, found, err := oneOption(f.args, set("--globalconfig"))
		if err != nil {
			return nil, err
		}
		if !found {
			globalfile, found = f.env["npm_config_globalconfig"]
		}
		if found && !globalfile.Empty() {
			global, err := f.resolve(globalfile, f.dir)
			if err != nil {
				return nil, err
			}
			files = append([]string{global}, files...)
		}
		prefix, found, err := oneOption(f.args, set("--prefix"))
		if err != nil {
			return nil, err
		}
		project := cwd
		if found {
			if project, err = f.resolve(prefix, f.dir); err != nil {
				return nil, err
			}
		}
		projectfile, err := nearest(project, ".npmrc")
		if err != nil {
			return nil, err
		}
		if projectfile != child(f.home, ".npmrc") {
			files = append(files, projectfile)
		}
		return files, nil
	case "pnpm":
		fallback := child(f.config, "pnpm/config.yaml")
		if _, ok := f.env["xdg_config_home"]; !ok && runtime.GOOS == "darwin" {
			fallback = child(f.home, "Library/Preferences/pnpm/config.yaml")
		}
		configfile := fallback
		dirOption, found, err := oneOption(f.args, set("--config-dir"))
		if err != nil {
			return nil, err
		}
		if found && !dirOption.Empty() {
			base, err := f.resolve(dirOption, f.dir)
			if err != nil {
				return nil, err
			}
			configfile = child(base, "config.yaml")
		}
		workspace, err := nearest(cwd, "pnpm-workspace.yaml")
		if err != nil {
			return nil, err
		}
		npmrc, err := nearest(cwd, ".npmrc")
		if err != nil {
			return nil, err
		}
		return []string{configfile, workspace, npmrc}, nil
	}
	files := []string{child(f.home, ".yarnrc.yml")}
	ancestors := shell.Ancestors(cwd)
	for i := len(ancestors) - 1; i >= 0; i-- {
		if ancestors[i] != f.home {
			files = append(files, child(ancestors[i], ".yarnrc.yml"))
		}
	}
	return files, nil
}

func (f *freshness) node(values, exemptions *[]cutoff) (string, error) {
	spec := npmFamilies[f.family]
	keys := set(spec.key, spec.exempt, "before", "minimum-release-age", "global")
	files, err := f.nodeFiles()
	if err != nil {
		return "", err
	}
	for _, path := range files {
		yaml := f.family != "npm" && (suffix(path) == ".yaml" || suffix(path) == ".yml")
		settings, err := scalarSettings(path, keys, yaml)
		if err != nil {
			return "", err
		}
		names := []string{spec.key}
		if f.family == "pnpm" {
			names = append(names, "minimum-release-age")
		}
		for _, name := range names {
			if v, ok := settings[name]; ok {
				*values = append(*values, cutoff{v, f.family})
			}
		}
		if v, ok := settings[spec.exempt]; ok {
			switch strings.ToLower(v) {
			case "[]", "false", "null":
			default:
				return exemptionDenial, nil
			}
		}
		if v, ok := settings["before"]; ok && f.family == "npm" {
			*exemptions = append(*exemptions, cutoff{v, "date"})
		}
		if f.family == "npm" || f.family == "pnpm" {
			v, ok := settings["global"]
			if !ok {
				v = "false"
			}
			if !isFalseText(v) {
				return globalDenial, nil
			}
		}
	}
	flagged, err := options(f.args, spec.flags)
	if err != nil {
		return "", err
	}
	*values = append(*values, cutoffs(texts(flagged), f.family)...)
	if text, ok := envText(f.env, spec.envKey); ok {
		*values = append(*values, cutoff{text, f.family})
	}
	excluded, err := options(f.args, set("--"+spec.exempt, "--"+spec.exempt+"[]", "--config."+spec.exempt))
	if err != nil {
		return "", err
	}
	if len(excluded) > 0 || truthyEnv(f.env, spec.exemptEnv) {
		return exemptionDenial, nil
	}
	if f.family == "npm" {
		before, err := options(f.args, set("--before"))
		if err != nil {
			return "", err
		}
		*exemptions = append(*exemptions, cutoffs(texts(before), "date")...)
		if text, ok := envText(f.env, "npm_config_before"); ok {
			*exemptions = append(*exemptions, cutoff{text, "date"})
		}
	}
	return verdict(*values, *exemptions, f.family == "npm"), nil
}
