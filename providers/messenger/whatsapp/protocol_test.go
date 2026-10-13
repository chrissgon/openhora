package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
)

type countingWriter struct {
	buf    bytes.Buffer
	writes int
}

func (c *countingWriter) Write(p []byte) (int, error) { c.writes++; return c.buf.Write(p) }

func TestLineIsASCIIAndRoundTrips(t *testing.T) {
	text := "caf\u00e9 \U0001F600 \u2028 <b>&</b> \x01 \"q\" \\"
	line, err := Line(map[string]any{"text": text})
	if err != nil {
		t.Fatal(err)
	}
	for _, b := range line {
		if b >= 0x80 {
			t.Fatalf("non-ASCII byte %x in %q", b, line)
		}
	}
	if !bytes.HasSuffix(line, []byte("\n")) || bytes.Count(line, []byte("\n")) != 1 {
		t.Fatalf("not exactly one line: %q", line)
	}
	var back map[string]string
	if err := json.Unmarshal(line, &back); err != nil || back["text"] != text {
		t.Fatalf("round trip lost the text: %v %q", err, back["text"])
	}
	if !strings.Contains(string(line), `\u00e9`) || !strings.Contains(string(line), `\ud83d\ude00`) {
		t.Fatalf("escapes are not Python's lower-case ensure_ascii form: %s", line)
	}
}

func TestWriterWritesOneCallPerLineAndRefusesALineOverTheLimit(t *testing.T) {
	cw := &countingWriter{}
	w := NewWriter(cw)
	for i := 0; i < 3; i++ {
		if err := w.Write(map[string]int{"n": i}); err != nil {
			t.Fatal(err)
		}
	}
	if cw.writes != 3 {
		t.Fatalf("each line must be one write (flushed), got %d writes", cw.writes)
	}
	before := cw.buf.Len()
	err := w.Write(map[string]string{"text": strings.Repeat("x", maxLine)})
	if !errors.Is(err, errLineTooLong) || cw.buf.Len() != before {
		t.Fatalf("a line over 1 MiB must be refused unwritten: %v", err)
	}
	// the largest line that fits is written whole
	body := strings.Repeat("x", maxLine-len(`{"t":""}`))
	if err := w.Write(map[string]string{"t": body}); err != nil {
		t.Fatalf("a line of exactly the limit must fit: %v", err)
	}
}

func TestReadLineCapDropsTheLongLineAndKeepsTheNext(t *testing.T) {
	long := strings.Repeat("a", 3<<20)
	exact := strings.Repeat("b", maxLine)
	input := "first\n" + long + "\n" + exact + "\n" + strings.Repeat("c", maxLine+1) + "\nlast\n" + "no newline"
	r := bufio.NewReaderSize(strings.NewReader(input), 4096)
	var got []string
	var dropped int
	for {
		line, err := ReadLine(r, maxLine)
		if errors.Is(err, errLineTooLong) {
			dropped++
			continue
		}
		if err != nil {
			if err != io.EOF {
				t.Fatal(err)
			}
			break
		}
		got = append(got, string(line))
	}
	if dropped != 2 || len(got) != 3 || got[0] != "first" || len(got[1]) != maxLine || got[2] != "last" {
		t.Fatalf("dropped %d, got %d lines", dropped, len(got))
	}
}

func TestReadLineIsBinarySafe(t *testing.T) {
	r := bufio.NewReader(bytes.NewReader([]byte("\xff\xfe\x00{\n")))
	line, err := ReadLine(r, maxLine)
	if err != nil || !bytes.Equal(line, []byte("\xff\xfe\x00{")) {
		t.Fatalf("%q %v", line, err)
	}
}

func readFile(name string) (string, error) {
	b, err := os.ReadFile(name)
	return string(b), err
}
