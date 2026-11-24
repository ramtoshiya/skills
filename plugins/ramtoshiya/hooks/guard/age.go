package guard

import (
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const (
	minimumSeconds = 3 * 86400
	pySpace        = `[\t-\r\x1c-\x1f \x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}]`
	number         = `(\p{Nd}+(?:\.\p{Nd}+)?)`
)

var (
	decimal  = regexp.MustCompile(`^[0-9]+(?:\.[0-9]+)?\z`)
	integer  = regexp.MustCompile(`^[0-9]+\z`)
	friendly = regexp.MustCompile(`^([0-9]+(?:\.[0-9]+)?)` + pySpace + `*(w|weeks?|d|days?|h|hours?|m|minutes?|s|seconds?)\z`)
	duration = regexp.MustCompile(`^p(?:` + number + `w)?(?:` + number + `d)?(?:t(?:` + number + `h)?(?:` + number + `m)?(?:` + number + `s)?)?\z`)
)

var friendlyUnits = map[byte]float64{'w': 604800, 'd': 86400, 'h': 3600, 'm': 60, 's': 1}

var durationUnits = []float64{604800, 86400, 3600, 60, 1}

func pySpaceRune(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }

func pyStrip(s string) string { return strings.TrimFunc(s, pySpaceRune) }

func ageSeconds(value any, family string) float64 {
	var text string
	switch v := value.(type) {
	case time.Time:
		return timeAge(v, family)
	case string:
		text = v
	case int64:
		text = strconv.FormatInt(v, 10)
	default:
		return -1
	}
	lowered := strings.ToLower(pyStrip(text))
	if family == "npm" || family == "pnpm" || family == "yarn" && integer.MatchString(lowered) {
		if !decimal.MatchString(lowered) {
			return -1
		}
		n, _ := strconv.ParseFloat(lowered, 64)
		if family == "npm" {
			return n * 86400
		}
		return n * 60
	}
	if m := friendly.FindStringSubmatch(lowered); m != nil {
		n, _ := strconv.ParseFloat(m[1], 64)
		return n * friendlyUnits[m[2][0]]
	}
	if m := duration.FindStringSubmatch(lowered); m != nil {
		total, found := 0.0, false
		for i, group := range m[1:] {
			if group != "" {
				found = true
				total += pyFloat(group) * durationUnits[i]
			}
		}
		if found {
			return total
		}
	}
	if family == "uv" || family == "date" {
		if cutoff, ok := fromISO(text); ok {
			return since(cutoff)
		}
	}
	return -1
}

func timeAge(t time.Time, family string) float64 {
	if family != "uv" && family != "date" {
		return -1
	}
	switch t.Location().String() {
	case "time-local":
		return -1
	case "date-local", "datetime-local":
		t = time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.Local)
	}
	return since(t)
}

func since(t time.Time) float64 {
	now := time.Now()
	return float64(now.Unix()-t.Unix()) + float64(now.Nanosecond()-t.Nanosecond())/1e9
}

func pyFloat(s string) float64 {
	var b strings.Builder
	for _, r := range s {
		if unicode.IsDigit(r) {
			start := r
			for unicode.IsDigit(start - 1) {
				start--
			}
			r = '0' + (r-start)%10
		}
		b.WriteRune(r)
	}
	n, _ := strconv.ParseFloat(b.String(), 64)
	return n
}

func fromISO(s string) (time.Time, bool) {
	return parseISO(strings.ReplaceAll(s, "Z", "+00:00"))
}
