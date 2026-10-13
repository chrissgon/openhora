package main

// renderWhatsApp turns the bridge's Markdown into WhatsApp's formatting. WhatsApp has no escape mechanism and no hidden
// links, so nothing can be made safe by escaping; the conversion only keeps what WhatsApp shows and shows every link target:
//
//	**x** -> *x*, ~~x~~ -> ~x~, a heading -> *text*, [text](url) -> text (url), a run of table lines -> a fenced block;
//	bullets, quotes and fences stay; a single *x* or _x_ of the source is left as it is (WhatsApp may italicise or bold it);
//	a code span (the effect command of a card) and a fenced block stay byte for byte.
//
// The rendering is in the binary because, after the provider script has replaced itself with it, no Python is on the send path.

import (
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

const (
	renderLimit = 4096
	cutNote     = "(continues on the page)"
)

var (
	headingRe = regexp.MustCompile(`^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$`)
	linkRe    = regexp.MustCompile(`!?\[([^\[\]]*)\]\([ \t]*<?((?:[^()\s<>]|\([^()\s<>]*\))+)>?(?:[ \t]+"[^"]*")?[ \t]*\)`)
	boldRe    = regexp.MustCompile(`\*\*([^\s*](?:[^\n]*?[^\s*])??)\*\*`)
	strikeRe  = regexp.MustCompile(`~~([^\s~](?:[^\n]*?[^\s~])??)~~`)
)

func renderWhatsApp(text string) string {
	text = strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\x00", "")
	lines := strings.Split(text, "\n")
	out := make([]string, 0, len(lines))
	for i := 0; i < len(lines); {
		line := lines[i]
		if opensFence(line) {
			if j := closingFence(lines, i+1); j >= 0 {
				out = append(out, lines[i:j+1]...)
				i = j + 1
				continue
			}
		}
		if isTableLine(line) {
			j := i
			for j < len(lines) && isTableLine(lines[j]) {
				j++
			}
			if j-i >= 2 {
				out = append(out, "```")
				for _, row := range lines[i:j] {
					out = append(out, strings.ReplaceAll(row, "```", "``\u200b`"))
				}
				out = append(out, "```")
				i = j
				continue
			}
		}
		out = append(out, renderLine(line))
		i++
	}
	return cutRendered(strings.Join(out, "\n"))
}

func opensFence(line string) bool {
	t := strings.TrimLeft(line, " ")
	return strings.HasPrefix(t, "```") && !strings.Contains(t[3:], "```")
}

func closingFence(lines []string, from int) int {
	for j := from; j < len(lines); j++ {
		if strings.TrimSpace(lines[j]) == "```" {
			return j
		}
	}
	return -1
}

func isTableLine(line string) bool {
	t := strings.TrimSpace(line)
	return len(t) >= 2 && strings.HasPrefix(t, "|") && strings.HasSuffix(t, "|")
}

func renderLine(line string) string {
	if m := headingRe.FindStringSubmatch(line); m != nil && m[1] != "" {
		return "*" + inline(m[1], true) + "*"
	}
	return inline(line, false)
}

// inline converts the marks of one line outside its code spans. Code spans are lifted out and put back byte for byte.
func inline(line string, inHeading bool) string {
	var spans []string
	var b strings.Builder
	for i := 0; i < len(line); {
		if line[i] != '`' {
			b.WriteByte(line[i])
			i++
			continue
		}
		n := 0
		for i+n < len(line) && line[i+n] == '`' {
			n++
		}
		if end := closingRun(line, i+n, n); end >= 0 {
			spans = append(spans, line[i:end])
			b.WriteString("\x00" + strconv.Itoa(len(spans)-1) + "\x00")
			i = end
			continue
		}
		b.WriteString(line[i : i+n])
		i += n
	}
	s := b.String()
	s = linkRe.ReplaceAllStringFunc(s, func(m string) string {
		parts := linkRe.FindStringSubmatch(m)
		label, url := strings.TrimSpace(parts[1]), parts[2]
		if label == "" || label == url {
			return url
		}
		return label + " (" + url + ")"
	})
	if inHeading {
		s = boldRe.ReplaceAllString(s, "$1")
	} else {
		s = boldRe.ReplaceAllString(s, "*$1*")
	}
	s = strikeRe.ReplaceAllString(s, "~$1~")
	for k := len(spans) - 1; k >= 0; k-- {
		s = strings.Replace(s, "\x00"+strconv.Itoa(k)+"\x00", spans[k], 1)
	}
	return s
}

// closingRun is the end (exclusive) of the next run of exactly n backticks at or after from, or -1.
func closingRun(line string, from, n int) int {
	for i := from; i < len(line); {
		if line[i] != '`' {
			i++
			continue
		}
		m := 0
		for i+m < len(line) && line[i+m] == '`' {
			m++
		}
		if m == n {
			return i + m
		}
		i += m
	}
	return -1
}

// cutRendered keeps the rendered text within the limit of runes, ending with the note that the rest is on the page. It cuts
// at a line boundary, so a code span (one line) is never cut; a fenced block that would be cut is closed, so the rest of the
// message does not turn into code. Only a single line longer than the limit is cut inside the line, and then before any
// code span that the cut would have split.
func cutRendered(s string) string {
	if utf8.RuneCountInString(s) <= renderLimit {
		return s
	}
	note := "\n" + cutNote
	closer := "\n```"
	noteRunes, closerRunes := utf8.RuneCountInString(note), utf8.RuneCountInString(closer)
	lines := strings.Split(s, "\n")
	used, kept, inFence, keptFence := 0, 0, false, false
	for i, line := range lines {
		add := utf8.RuneCountInString(line)
		if i > 0 {
			add++
		}
		fence := inFence
		if inFence && strings.TrimSpace(line) == "```" {
			fence = false
		} else if !inFence && opensFence(line) {
			fence = true
		}
		need := used + add + noteRunes
		if fence {
			need += closerRunes
		}
		if need > renderLimit {
			break
		}
		used, kept, inFence, keptFence = used+add, i+1, fence, fence
	}
	if kept == 0 {
		first := lines[0]
		room := renderLimit - noteRunes
		r := []rune(first)
		if len(r) > room {
			r = r[:room]
		}
		cut := len(string(r))
		cut = beforeSpan(first, cut)
		return strings.TrimRight(first[:cut], " \t") + note
	}
	out := strings.Join(lines[:kept], "\n")
	if keptFence {
		out += closer
	}
	return out + note
}

// beforeSpan moves a cut position (a byte index) back to the start of the code span that contains it, if any.
func beforeSpan(line string, cut int) int {
	for i := 0; i < len(line); {
		if line[i] != '`' {
			i++
			continue
		}
		n := 0
		for i+n < len(line) && line[i+n] == '`' {
			n++
		}
		if end := closingRun(line, i+n, n); end >= 0 {
			if i < cut && cut < end {
				return i
			}
			i = end
			continue
		}
		i += n
	}
	return cut
}
