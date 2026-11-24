package guard

import "time"

type isoText []byte

func (s isoText) at(i int) byte {
	if i < len(s) {
		return s[i]
	}
	return 0
}

func (s isoText) digits(i, n int) (value, next int, ok bool) {
	for k := 0; k < n; k++ {
		c := s.at(i + k)
		if c < '0' || c > '9' {
			return 0, 0, false
		}
		value = value*10 + int(c-'0')
	}
	return value, i + n, true
}

func (s isoText) isDigit(i int) bool { return s.at(i) >= '0' && s.at(i) <= '9' }

func (s isoText) separator() int {
	length := len(s)
	if length == 7 {
		return 7
	}
	if s.at(4) == '-' {
		if s.at(5) != 'W' {
			return 10
		}
		if length < 8 {
			return -1
		}
		if length > 8 && s.at(8) == '-' {
			if length == 9 {
				return -1
			}
			if length > 10 && s.isDigit(10) {
				return 8
			}
			return 10
		}
		return 8
	}
	if s.at(4) != 'W' {
		return 8
	}
	i := 7
	for i < length && s.isDigit(i) {
		i++
	}
	switch {
	case i < 9:
		return i
	case i%2 == 0:
		return 7
	}
	return 8
}

func (s isoText) date(length int) (year, month, day int, ok bool) {
	year, i, ok := s.digits(0, 4)
	if !ok {
		return
	}
	dashed := s.at(i) == '-'
	if dashed {
		i++
	}
	if s.at(i) == 'W' {
		week, next, ok := s.digits(i+1, 2)
		if !ok {
			return 0, 0, 0, false
		}
		i = next
		weekday := 1
		if i < length {
			if dashed {
				if s.at(i) != '-' {
					return 0, 0, 0, false
				}
				i++
			}
			if weekday, _, ok = s.digits(i, 1); !ok {
				return 0, 0, 0, false
			}
		}
		return isoWeekDate(year, week, weekday)
	}
	if month, i, ok = s.digits(i, 2); !ok {
		return 0, 0, 0, false
	}
	if dashed {
		if s.at(i) != '-' {
			return 0, 0, 0, false
		}
		i++
	}
	if day, _, ok = s.digits(i, 2); !ok {
		return 0, 0, 0, false
	}
	return year, month, day, true
}

func isoWeekDate(year, week, weekday int) (int, int, int, bool) {
	if year < 1 || week < 1 || week > 53 || weekday < 1 || weekday > 7 {
		return 0, 0, 0, false
	}
	if week == 53 {
		if _, last := time.Date(year, 12, 28, 0, 0, 0, 0, time.UTC).ISOWeek(); last != 53 {
			return 0, 0, 0, false
		}
	}
	jan4 := time.Date(year, 1, 4, 0, 0, 0, 0, time.UTC)
	offset := int(jan4.Weekday()+6) % 7
	d := jan4.AddDate(0, 0, (week-1)*7+weekday-1-offset)
	if d.Year() < 1 || d.Year() > 9999 {
		return 0, 0, 0, false
	}
	return d.Year(), int(d.Month()), d.Day(), true
}

type clock struct {
	hour, minute, second, micro int
}

func (s isoText) clock(i, end int) (c clock, trailing bool, ok bool) {
	fields := []*int{&c.hour, &c.minute, &c.second}
	separated := true
	for n := 0; n < 3; n++ {
		value, next, good := s.digits(i, 2)
		if !good {
			return c, false, false
		}
		*fields[n] = value
		i = next
		ch := s.at(i)
		i++
		if n == 0 {
			separated = ch == ':'
		}
		fraction := ch == '.' || ch == ','
		if i >= end {
			return c, ch != 0 && !fraction, !fraction
		}
		if fraction {
			if n < 2 {
				return c, false, false
			}
			break
		}
		if n == 2 && separated {
			return c, false, false
		}
		if separated && ch == ':' {
			continue
		}
		if !separated {
			i--
		} else {
			return c, false, false
		}
	}
	count := end - i
	if count >= 6 {
		count = 6
	}
	value, next, good := s.digits(i, count)
	if !good {
		return c, false, false
	}
	for k := count; k < 6; k++ {
		value *= 10
	}
	c.micro = value
	i = next
	for s.isDigit(i) {
		i++
	}
	return c, s.at(i) != 0, true
}

func (s isoText) time(i int) (c clock, offset time.Duration, zoned, ok bool) {
	end := len(s)
	zone := i
	for zone < end && s.at(zone) != 'Z' && s.at(zone) != '+' && s.at(zone) != '-' {
		zone++
	}
	c, trailing, ok := s.clock(i, zone)
	if !ok {
		return c, 0, false, false
	}
	if zone == end {
		return c, 0, false, !trailing
	}
	if s.at(zone) == 'Z' {
		return c, 0, true, s.at(zone+1) == 0
	}
	sign := 1
	if s.at(zone) == '-' {
		sign = -1
	}
	z, trailing, ok := s.clock(zone+1, end)
	if !ok || trailing {
		return c, 0, false, false
	}
	if z.minute > 59 || z.second > 59 {
		return c, 0, false, false
	}
	return c, time.Duration(sign) * (time.Duration(z.hour*3600+z.minute*60+z.second)*time.Second + time.Duration(z.micro)*time.Microsecond), true, true
}

func parseISO(text string) (time.Time, bool) {
	s := isoText(text)
	split := s.separator()
	if split < 0 {
		return time.Time{}, false
	}
	year, month, day, ok := s.date(split)
	if !ok {
		return time.Time{}, false
	}
	var c clock
	var offset time.Duration
	zoned := false
	if len(s) > split {
		i := split
		switch b := s.at(i); {
		case b&0x80 == 0:
			i++
		case b&0xf0 == 0xe0:
			i += 3
		case b&0xf0 == 0xf0:
			i += 4
		default:
			i += 2
		}
		if i > len(s) {
			return time.Time{}, false
		}
		if c, offset, zoned, ok = s.time(i); !ok {
			return time.Time{}, false
		}
	}
	extra := 0
	if c.hour == 24 {
		if c.minute != 0 || c.second != 0 || c.micro != 0 {
			return time.Time{}, false
		}
		c.hour = 0
		extra = 1
	}
	if year < 1 || month < 1 || month > 12 || day < 1 || c.hour > 23 || c.minute > 59 || c.second > 59 {
		return time.Time{}, false
	}
	if zoned && (offset <= -86400*time.Second || offset >= 86400*time.Second) {
		return time.Time{}, false
	}
	loc := time.Local
	if zoned {
		loc = time.UTC
	}
	t := time.Date(year, time.Month(month), day, c.hour, c.minute, c.second, c.micro*1000, loc)
	if t.Day() != day {
		return time.Time{}, false
	}
	if extra > 0 {
		t = t.AddDate(0, 0, extra)
		if t.Year() > 9999 {
			return time.Time{}, false
		}
	}
	if zoned {
		t = t.Add(-offset)
	}
	return t, true
}
