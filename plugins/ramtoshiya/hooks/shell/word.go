package shell

import (
	"strings"

	"mvdan.cc/sh/v3/expand"
	"mvdan.cc/sh/v3/syntax"
)

type partKind uint8

const (
	literal partKind = iota
	home
	param
	opaque
)

type part struct {
	kind partKind
	text string
}

type Word struct {
	parts []part
}

func NewLiteral(s string) Word {
	if s == "" {
		return Word{}
	}
	return Word{[]part{{literal, s}}}
}

func (w Word) Empty() bool { return len(w.parts) == 0 }

func (w Word) run() int {
	n := 0
	for n < len(w.parts) && w.parts[n].kind <= home {
		n++
	}
	return n
}

func (w Word) Literal() (string, bool) {
	if w.run() != len(w.parts) {
		return "", false
	}
	return w.Prefix(), true
}

func (w Word) Prefix() string {
	var b strings.Builder
	for _, p := range w.parts[:w.run()] {
		b.WriteString(p.text)
	}
	return b.String()
}

func (w Word) Script() string {
	var b strings.Builder
	for _, p := range w.parts {
		b.WriteString(p.text)
	}
	return b.String()
}

func (w Word) After(n int) Word {
	text := w.Prefix()
	return w.rest(text[n:], w.run())
}

func (w Word) rest(text string, from int) Word {
	var parts []part
	if text != "" {
		parts = append(parts, part{literal, text})
	}
	return Word{append(parts, w.parts[from:]...)}
}

func (w Word) Cut(sep string) (string, Word, bool) {
	text := w.Prefix()
	i := strings.Index(text, sep)
	if i < 0 {
		return "", Word{}, false
	}
	return text[:i], w.rest(text[i+len(sep):], w.run()), true
}

func (w Word) SplitAssign() (string, Word, bool) {
	name, value, ok := w.Cut("=")
	if !ok || !isName(name) {
		return "", Word{}, false
	}
	return name, value, true
}

func isName(s string) bool {
	if s == "" {
		return false
	}
	for i, r := range s {
		if !(r == '_' || r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || i > 0 && r >= '0' && r <= '9') {
			return false
		}
	}
	return true
}

func (w Word) BaseName() (string, bool) {
	if text, ok := w.Literal(); ok {
		return pyName(text), true
	}
	start := len(w.parts)
	for start > 0 && w.parts[start-1].kind <= home {
		start--
	}
	var tail strings.Builder
	for _, p := range w.parts[start:] {
		tail.WriteString(p.text)
	}
	text := tail.String()
	i := strings.LastIndex(text, "/")
	if i < 0 || i == len(text)-1 {
		return "", false
	}
	return text[i+1:], true
}

type builder struct {
	src   string
	parts []part
}

func (b *builder) literal(s string) {
	if s == "" {
		return
	}
	if n := len(b.parts); n > 0 && b.parts[n-1].kind == literal {
		b.parts[n-1].text += s
		return
	}
	b.parts = append(b.parts, part{literal, s})
}

func (b *builder) source(n syntax.Node) string {
	start, end := int(n.Pos().Offset()), int(n.End().Offset())
	if start < 0 || end > len(b.src) || start > end {
		return ""
	}
	return b.src[start:end]
}

func (b *builder) expansion(n syntax.WordPart) {
	text := b.source(n)
	if p, ok := n.(*syntax.ParamExp); ok && plain(p) && isName(p.Param.Value) {
		b.parts = append(b.parts, part{param, text})
		return
	}
	b.parts = append(b.parts, part{opaque, text})
}

func plain(p *syntax.ParamExp) bool {
	return p.Param != nil && p.Flags == nil && !p.Excl && !p.Length && !p.Width && !p.IsSet &&
		p.Split == syntax.OptUnset && p.GlobSubst == syntax.OptUnset && p.RcExpand == syntax.OptUnset &&
		p.NestedParam == nil && p.Index == nil && len(p.Modifiers) == 0 && p.Slice == nil &&
		p.Repl == nil && p.Names == 0 && p.Exp == nil
}

func newWord(src string, w *syntax.Word) Word {
	b := &builder{src: src}
	for i, p := range w.Parts {
		switch x := p.(type) {
		case *syntax.Lit:
			value := x.Value
			if i == 0 && strings.HasPrefix(value, "~") && (len(value) == 1 && len(w.Parts) == 1 || len(value) > 1 && value[1] == '/') {
				b.parts = append(b.parts, part{home, "~"})
				value = value[1:]
			}
			b.literal(unescape(value))
		case *syntax.SglQuoted:
			value := x.Value
			if x.Dollar {
				value, _, _ = expand.Format(nil, value, nil)
				value, _, _ = strings.Cut(value, "\x00")
			}
			b.literal(value)
		case *syntax.DblQuoted:
			for _, q := range x.Parts {
				if lit, ok := q.(*syntax.Lit); ok {
					b.literal(unescapeDouble(lit.Value))
				} else {
					b.expansion(q)
				}
			}
		case *syntax.ExtGlob:
			b.literal(b.source(x))
		default:
			b.expansion(p)
		}
	}
	return Word{b.parts}
}

func unescape(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+1 < len(s) {
			i++
		}
		b.WriteByte(s[i])
	}
	return b.String()
}

func unescapeDouble(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+1 < len(s) && strings.IndexByte("$`\"\\\n", s[i+1]) >= 0 {
			i++
		}
		b.WriteByte(s[i])
	}
	return b.String()
}
