package main

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func TestRenderConvertsTheMarksWhatsAppKnows(t *testing.T) {
	cases := []struct{ in, want string }{
		{"a **bold** word", "a *bold* word"},
		{"two **a** and **b** here", "two *a* and *b* here"},
		{"~~gone~~ stays", "~gone~ stays"},
		{"# Title", "*Title*"},
		{"### Third level ###", "*Third level*"},
		{"## Mixed **bold** heading", "*Mixed bold heading*"},
		{"# C# language", "*C# language*"},
		{"- one\n- two", "- one\n- two"},
		{"* one\n* two", "* one\n* two"},
		{"> quoted **text**", "> quoted *text*"},
		{"see [the page](https://example.com/a?b=1) now", "see the page (https://example.com/a?b=1) now"},
		{"[https://example.com](https://example.com)", "https://example.com"},
		{"[t](<https://example.com/x> \"title\")", "t (https://example.com/x)"},
		{"![chart](https://example.com/c.png)", "chart (https://example.com/c.png)"},
		{"[**bold link**](https://example.com)", "*bold link* (https://example.com)"},
		{"single *star* and _under_ stay", "single *star* and _under_ stay"},
		{"snake_case and a * b * c", "snake_case and a * b * c"},
		{"**", "**"},
		{"** spaced **", "** spaced **"},
	}
	for _, c := range cases {
		if got := renderWhatsApp(c.in); got != c.want {
			t.Errorf("render(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestRenderKeepsCodeSpansAndFencesByteForByte(t *testing.T) {
	spans := []string{
		"`/approve-effect 12 --path /srv/northwind-shop --hash abc**def**`",
		"`a **b** ~~c~~ [d](e) # f`",
		"``double `tick` span **x**``",
	}
	for _, span := range spans {
		in := "Run this:\n" + span
		if got := renderWhatsApp(in); got != in {
			t.Errorf("the code span changed: %q -> %q", in, got)
		}
		mixed := "**bold** " + span + " and **more**"
		want := "*bold* " + span + " and *more*"
		if got := renderWhatsApp(mixed); got != want {
			t.Errorf("mixed: %q, want %q", got, want)
		}
	}
	fence := "```go\nx := \"**not bold**\" // [a](b)\n# not a heading\n```"
	in := "before **b**\n" + fence + "\nafter"
	want := "before *b*\n" + fence + "\nafter"
	if got := renderWhatsApp(in); got != want {
		t.Errorf("fence changed: %q", got)
	}
	// a bold run that spans a code span is still bold
	if got := renderWhatsApp("**use `x` here**"); got != "*use `x` here*" {
		t.Errorf("bold around a code span: %q", got)
	}
	// an unclosed fence is ordinary text: its marks are converted, nothing is lost
	if got := renderWhatsApp("```\n**b**"); got != "```\n*b*" {
		t.Errorf("unclosed fence: %q", got)
	}
	// an unclosed backtick is literal
	if got := renderWhatsApp("a ` **b**"); got != "a ` *b*" {
		t.Errorf("unclosed backtick: %q", got)
	}
}

func TestRenderFencesATableAndBreaksAFenceInsideACell(t *testing.T) {
	in := "intro\n| a | b |\n|---|---|\n| 1 | ```x``` |\nafter"
	want := "intro\n```\n| a | b |\n|---|---|\n| 1 | ``\u200b`x``\u200b` |\n```\nafter"
	if got := renderWhatsApp(in); got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	// a single table-looking line is text
	if got := renderWhatsApp("| just one |"); got != "| just one |" {
		t.Errorf("single line: %q", got)
	}
}

func TestRenderCutsOverTheLimitWithTheNote(t *testing.T) {
	long := strings.Repeat("word ", 2000)
	got := renderWhatsApp(long)
	if utf8.RuneCountInString(got) > renderLimit || !strings.HasSuffix(got, "\n"+cutNote) {
		t.Fatalf("not cut right: %d runes, tail %q", utf8.RuneCountInString(got), got[len(got)-40:])
	}
	exact := strings.Repeat("x", renderLimit)
	if renderWhatsApp(exact) != exact {
		t.Error("a text of exactly the limit must stay whole")
	}
	// the rendering can make a text longer than the raw text: the cut applies after it
	links := strings.Repeat("[a](https://example.com/aaaaaaaaaa) ", 200)
	out := renderWhatsApp(links)
	if utf8.RuneCountInString(out) > renderLimit {
		t.Fatalf("rendered links over the limit: %d", utf8.RuneCountInString(out))
	}
	emoji := strings.Repeat("\U0001F600", 5000)
	if out := renderWhatsApp(emoji); !utf8.ValidString(out) || utf8.RuneCountInString(out) > renderLimit {
		t.Fatalf("cut broke a character or the limit")
	}
}

func TestRenderRemovesNULsSoTheMarkersOfCodeSpansCannotBeForged(t *testing.T) {
	in := "`real` \x000\x00 and `second`"
	got := renderWhatsApp(in)
	if got != "`real` 0 and `second`" {
		t.Fatalf("got %q", got)
	}
}

func TestSourceHasNoInvisibleCharacter(t *testing.T) {
	// "\u200b" in render.go is an escape sequence; the file holds no real zero-width character
	src, err := readFile("render.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range src {
		if r == 0x200b || r == 0x200c || r == 0x200d || r == 0xfeff || r == 0x2060 {
			t.Fatalf("an invisible character is in render.go")
		}
	}
}

func TestRenderCutsAtALineBoundaryAndNeverInsideACodeSpan(t *testing.T) {
	span := "`/approve-effect 12 --path /srv/northwind-shop --hash " + strings.Repeat("a", 64) + "`"
	var lines []string
	for i := 0; i < 400; i++ {
		lines = append(lines, "line "+strings.Repeat("w", 8))
	}
	text := strings.Join(lines, "\n") + "\n" + span
	got := renderWhatsApp(text)
	if utf8.RuneCountInString(got) > renderLimit || !strings.HasSuffix(got, "\n"+cutNote) {
		t.Fatalf("not cut right")
	}
	body := strings.TrimSuffix(got, "\n"+cutNote)
	for _, l := range strings.Split(body, "\n") {
		if l != "line wwwwwwww" {
			t.Fatalf("a line was cut in the middle: %q", l)
		}
	}
	// a span near the limit is kept whole or dropped whole
	pad := strings.Repeat("x", renderLimit-30)
	got = renderWhatsApp(pad + "\n" + span)
	if strings.Contains(got, "`") && !strings.Contains(got, span) {
		t.Fatalf("a code span was cut: %q", got[len(got)-80:])
	}
	// a single line over the limit is cut before a span it would split
	one := strings.Repeat("y", renderLimit-60) + " " + span + " tail"
	got = renderWhatsApp(one)
	if strings.Contains(got, "`") && !strings.Contains(got, span) {
		t.Fatalf("a span in a long line was split")
	}
	if utf8.RuneCountInString(got) > renderLimit {
		t.Fatal("over the limit")
	}
}

func TestRenderClosesAFenceItCutsInside(t *testing.T) {
	var body []string
	for i := 0; i < 600; i++ {
		body = append(body, "code line "+strings.Repeat("c", 10))
	}
	text := "intro\n```\n" + strings.Join(body, "\n") + "\n```\nafter"
	got := renderWhatsApp(text)
	if utf8.RuneCountInString(got) > renderLimit || !strings.HasSuffix(got, "\n```\n"+cutNote) {
		t.Fatalf("fence not closed before the note: %q", got[len(got)-60:])
	}
	if strings.Count(got, "```")%2 != 0 {
		t.Fatal("unbalanced fences")
	}
}

func TestRenderRewritesLinksWhoseTargetHasBalancedParentheses(t *testing.T) {
	in := "see [Go](https://example.com/wiki/Go_(language)) and [x](https://example.com/a_(b)_c) end"
	want := "see Go (https://example.com/wiki/Go_(language)) and x (https://example.com/a_(b)_c) end"
	if got := renderWhatsApp(in); got != want {
		t.Fatalf("%q", got)
	}
}
