package main

// The listen protocol of providers/messenger/README.md: JSON lines, one object per line, UTF-8 and ASCII-escaped,
// flushed after every line, at most 1 MiB per line. Descriptor 1 is reserved for it (see fd.go).

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"
	"unicode/utf16"
	"unicode/utf8"
)

// maxLine is the longest line of the protocol, either way, without its newline.
const maxLine = 1 << 20

var errLineTooLong = errors.New("a line is over the limit")

// asciiJSON turns every non-ASCII character of a marshalled JSON document into a \uXXXX escape (a surrogate pair above the
// basic plane), the way Python's json.dumps(ensure_ascii=True) does. Non-ASCII characters occur only inside strings.
func asciiJSON(in []byte) []byte {
	out := make([]byte, 0, len(in))
	for i := 0; i < len(in); {
		if in[i] < 0x80 {
			out = append(out, in[i])
			i++
			continue
		}
		r, size := utf8.DecodeRune(in[i:])
		i += size
		if r >= 0x10000 {
			hi, lo := utf16.EncodeRune(r)
			out = append(out, fmt.Sprintf("\\u%04x\\u%04x", hi, lo)...)
		} else {
			out = append(out, fmt.Sprintf("\\u%04x", r)...)
		}
	}
	return out
}

// Writer writes protocol lines to one descriptor under a lock.
type Writer struct {
	mu sync.Mutex
	w  io.Writer
}

func NewWriter(w io.Writer) *Writer { return &Writer{w: w} }

// Line is the bytes of one protocol line for a value, with its newline.
func Line(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	line := append(asciiJSON(raw), '\n')
	if len(line)-1 > maxLine {
		return nil, errLineTooLong
	}
	return line, nil
}

// Write writes one value as one line and flushes it (a single write call). It returns errLineTooLong, writing nothing, for a
// line over the limit.
func (p *Writer) Write(v any) error {
	line, err := Line(v)
	if err != nil {
		return err
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	_, err = p.w.Write(line)
	return err
}

// ReadLine reads one line of at most max bytes (without its newline). A longer line is read to its end and dropped:
// it returns errLineTooLong, and the next call starts after it. At the end of the input it returns io.EOF (a last line
// with no newline is dropped, as the bridge's reader drops it).
func ReadLine(r *bufio.Reader, max int) ([]byte, error) {
	var buf []byte
	tooLong := false
	for {
		chunk, err := r.ReadSlice('\n')
		if !tooLong {
			buf = append(buf, chunk...)
			if len(buf) > max+1 {
				tooLong = true
				buf = nil
			}
		}
		if err == bufio.ErrBufferFull {
			continue
		}
		if err != nil {
			return nil, err
		}
		break
	}
	if tooLong {
		return nil, errLineTooLong
	}
	buf = bytes.TrimSuffix(buf, []byte("\n"))
	if len(buf) > max {
		return nil, errLineTooLong
	}
	return buf, nil
}

// exitOnWriteError ends the process when the protocol cannot be written (the bridge is gone).
func exitOnWriteError(err error) {
	if err == nil || errors.Is(err, errLineTooLong) {
		return
	}
	fmt.Fprintln(os.Stderr, "whatsapp: the protocol output is closed; exiting")
	os.Exit(1)
}
