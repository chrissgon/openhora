package main

import (
	"fmt"
	"io"
	"os"
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

func (l *stderrLogger) emit(level, msg string, args ...any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	fmt.Fprintf(l.out, "%s [%s %s] %s\n", time.Now().Format("15:04:05"), l.mod, level, fmt.Sprintf(msg, args...))
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
