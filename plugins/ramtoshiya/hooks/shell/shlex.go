package shell

import (
	"errors"
	"strings"
)

func ShlexSplit(s string) ([]string, error) {
	var words []string
	var token strings.Builder
	inWord := false
	runes := []rune(s)
	for i := 0; i < len(runes); i++ {
		r := runes[i]
		switch {
		case r == ' ' || r == '\t' || r == '\r' || r == '\n':
			if inWord {
				words = append(words, token.String())
				token.Reset()
				inWord = false
			}
		case r == '\\':
			i++
			if i >= len(runes) {
				return nil, errors.New("no escaped character")
			}
			token.WriteRune(runes[i])
			inWord = true
		case r == '\'':
			end := i + 1
			for end < len(runes) && runes[end] != '\'' {
				end++
			}
			if end >= len(runes) {
				return nil, errors.New("no closing quotation")
			}
			token.WriteString(string(runes[i+1 : end]))
			i = end
			inWord = true
		case r == '"':
			i++
			for {
				if i >= len(runes) {
					return nil, errors.New("no closing quotation")
				}
				c := runes[i]
				if c == '"' {
					break
				}
				if c == '\\' {
					i++
					if i >= len(runes) {
						return nil, errors.New("no escaped character")
					}
					if runes[i] != '"' && runes[i] != '\\' {
						token.WriteRune('\\')
					}
					c = runes[i]
				}
				token.WriteRune(c)
				i++
			}
			inWord = true
		default:
			token.WriteRune(r)
			inWord = true
		}
	}
	if inWord {
		words = append(words, token.String())
	}
	return words, nil
}
