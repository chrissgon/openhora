package main

import (
	"fmt"
	"io"
	"os"
	"regexp"
	"sync"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// stderrLogger is the library's logger: warnings and errors to standard error, nothing below WARN, never to standard
// output (descriptor 1 belongs to the protocol). The library does not log message contents at these levels.
type stderrLogger struct {
	mod string
	out io.Writer
	mu  *sync.Mutex
}

func newStderrLogger(module string) waLog.Logger {
	return &stderrLogger{mod: module, out: os.Stderr, mu: &sync.Mutex{}}
}

var (
	jidRe    = regexp.MustCompile(`[A-Za-z0-9._:-]*@(?:s\.whatsapp\.net|lid|g\.us|broadcast|newsletter|hosted\.lid|hosted|bot)`)
	digitsRn = regexp.MustCompile(`[0-9]{6,}`)
	// urlRe is a web address: a media download's address holds the path and the hash of a file, and the library's warning about
	// a failed download prints it. It runs to the next space, so a quote (even an escaped one, as %q writes it) inside the address
	// cannot end the redaction early; it may take a closing quote or a colon with it, which is harmless.
	urlRe = regexp.MustCompile(`https?://\S*`)
)

// redact removes what names a person or a file from a library line: any web address, any JID and any run of six or more digits (a phone number).
// The bridge keeps the tail of standard error and may show it.
func redact(line string) string {
	return digitsRn.ReplaceAllString(jidRe.ReplaceAllString(urlRe.ReplaceAllString(line, "<url>"), "<jid>"), "<digits>")
}

func (l *stderrLogger) emit(level, msg string, args ...any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	fmt.Fprintf(l.out, "%s [%s %s] %s\n", time.Now().Format("15:04:05"), l.mod, level, redact(fmt.Sprintf(msg, args...)))
}

func (l *stderrLogger) Warnf(msg string, args ...any)  { l.emit("WARN", msg, args...) }
func (l *stderrLogger) Errorf(msg string, args ...any) { l.emit("ERROR", msg, args...) }
func (l *stderrLogger) Infof(string, ...any)           {}
func (l *stderrLogger) Debugf(string, ...any)          {}
func (l *stderrLogger) Sub(module string) waLog.Logger {
	return &stderrLogger{mod: l.mod + "/" + module, out: l.out, mu: l.mu}
}

// logf writes one diagnostic line to standard error. Callers pass classes and sentences, never a message text, a sender or an id.
func logf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "whatsapp: "+format+"\n", args...)
}
