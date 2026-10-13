package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}
func (b *lockedBuffer) lines() []map[string]any {
	b.mu.Lock()
	defer b.mu.Unlock()
	var out []map[string]any
	for _, l := range strings.Split(strings.TrimSpace(b.buf.String()), "\n") {
		if l == "" {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(l), &m); err != nil {
			panic("a protocol line is not JSON: " + l)
		}
		out = append(out, m)
	}
	return out
}

func newTestListener(f Sender) (*listener, *lockedBuffer) {
	out := &lockedBuffer{}
	return newListener(context.Background(), NewWriter(out), f, noResolver), out
}

func TestLoggedOutWritesPausedAndExits3(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(&events.LoggedOut{})
	lines := out.lines()
	if len(lines) != 1 || lines[0]["event"] != "error" || lines[0]["kind"] != "paused" || !strings.Contains(lines[0]["reason"].(string), "pair --phone") {
		t.Fatalf("%v", lines)
	}
	if code := <-l.exit; code != 3 {
		t.Fatalf("exit %d", code)
	}
	l.handle(&events.LoggedOut{}) // only the first stop counts
	if len(out.lines()) != 1 {
		t.Fatal("a second stop wrote again")
	}
}

func TestAStreamReplacedIsNotPausedItIsNotConfigured(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(&events.StreamReplaced{})
	line := out.lines()[0]
	if line["kind"] != "not-configured" || !strings.Contains(line["reason"].(string), "another program is using this WhatsApp session") {
		t.Fatalf("%v", line)
	}
	if <-l.exit != 3 {
		t.Fatal("exit code")
	}
}

func TestAnOutdatedClientIsNotConfiguredAndNamesBuild(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(&events.ClientOutdated{})
	line := out.lines()[0]
	if line["kind"] != "not-configured" || !strings.Contains(line["reason"].(string), "build") || <-l.exit != 3 {
		t.Fatalf("%v", line)
	}
}

func TestOtherFailuresAreFailedAndExitWithTheCodeThatRestartsTheProgram(t *testing.T) {
	for _, evt := range []any{&events.TemporaryBan{}, &events.ConnectFailure{Reason: 500}} {
		l, out := newTestListener(&fakeSender{})
		l.handle(evt)
		lines := out.lines()
		if len(lines) != 1 || lines[0]["kind"] != "failed" || <-l.exit != 1 {
			t.Fatalf("%T: %v", evt, lines)
		}
	}
}

func TestReadyComesOnEveryConnectionAndALostConnectionIsAFailedEventOnce(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(&events.Disconnected{}) // never connected: nothing to report
	l.handle(&events.Connected{})
	l.handle(&events.Disconnected{})
	l.handle(&events.Disconnected{})
	l.handle(&events.Connected{})
	var kinds []string
	for _, m := range out.lines() {
		if m["event"] == "ready" {
			kinds = append(kinds, "ready")
		} else {
			kinds = append(kinds, m["kind"].(string))
		}
	}
	if strings.Join(kinds, ",") != "ready,failed,ready" {
		t.Fatalf("%v", kinds)
	}
	select {
	case <-l.exit:
		t.Fatal("a reconnect must not end the program")
	default:
	}
}

func TestAMessageBecomesAnUpdateLineAndOtherMessagesWriteNothing(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(textEvent(pn(person), pn(person), "caf\xc3\xa9 /pending"))
	l.handle(textEvent(pn("5511911111111"), pn("5511911111111"), "hi"))
	group := textEvent(types.NewJID("120363000000000000", types.GroupServer), pn(person), "hi")
	group.Info.IsGroup = true
	l.handle(group)
	l.handle(&events.Message{Info: textEvent(pn(person), pn(person), "").Info, Message: &waE2E.Message{ImageMessage: &waE2E.ImageMessage{}}})
	l.handle(textEvent(lid(lidOf), lid(lidOf), "unresolved"))
	lines := out.lines()
	if len(lines) != 2 {
		t.Fatalf("%v", lines)
	}
	u := lines[0]["update"].(map[string]any)
	if lines[0]["event"] != "update" || u["sender"] != person || u["chat"] != person || u["private"] != true ||
		u["text"] != "café /pending" || u["action"] != nil || u["action_ref"] != nil || u["reply_to"] != nil || u["update_id"] != "3EB0AAAA0001" {
		t.Fatalf("%v", u)
	}
	raw := out.buf.String()
	for _, b := range []byte(raw) {
		if b >= 0x80 {
			t.Fatal("the protocol carries a non-ASCII byte")
		}
	}
}

func TestAnUpdateOverTheLineLimitIsDroppedAndTheNextOneStillGoes(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(textEvent(pn(person), pn(person), strings.Repeat("\U0001F600", 100_000))) // 12 bytes each once escaped
	l.handle(textEvent(pn(person), pn(person), "after"))
	lines := out.lines()
	if len(lines) != 1 || lines[0]["update"].(map[string]any)["text"] != "after" {
		t.Fatalf("%d lines", len(lines))
	}
}

func TestRequestsAreAnsweredInOrderAndTheInputEndingEndsTheServing(t *testing.T) {
	f := &fakeSender{}
	l, out := newTestListener(f)
	long := strings.Repeat("a", maxLine+10)
	input := `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "one"}}` + "\n" +
		"this is not json\n" +
		long + "\n" +
		`{"id": 2, "op": "send", "chat": "bad", "message": {"text": "two"}}` + "\n" +
		`{"id": 3, "op": "send", "chat": "5511900000000", "message": {"text": "three"}}` + "\n"
	done, returned := make(chan struct{}), make(chan struct{})
	go func() { l.serveRequests(strings.NewReader(input), done); close(returned) }()
	select {
	case <-returned:
	case <-time.After(5 * time.Second):
		t.Fatal("did not end at the end of its input")
	}
	select {
	case <-done:
	default:
		t.Fatal("done was not closed")
	}
	lines := out.lines()
	if len(lines) != 3 || lines[0]["id"] != float64(1) || lines[0]["ok"] != true || lines[1]["id"] != float64(2) ||
		lines[1]["ok"] != false || lines[1]["kind"] != "usage" || lines[2]["id"] != float64(3) || lines[2]["ok"] != true {
		t.Fatalf("%v", lines)
	}
	if strings.Join(f.texts, ",") != "one,three" {
		t.Fatalf("%v", f.texts)
	}
}

func TestServingStopsAtTheEndOfInputEvenWithARequestInFlight(t *testing.T) {
	pr, pw := io.Pipe()
	l, _ := newTestListener(&fakeSender{})
	done := make(chan struct{})
	go l.serveRequests(pr, done)
	pw.Write([]byte(`{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x"}}` + "\n"))
	pw.Close()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("did not end")
	}
}

type blockingSender struct {
	started chan struct{}
	fakeSender
}

func (b *blockingSender) SendText(ctx context.Context, to types.JID, text string) (string, error) {
	close(b.started)
	<-ctx.Done()
	return "", ctx.Err()
}

func TestTheEndOfInputSignalsDoneAtOnceEvenWhileASendIsInFlight(t *testing.T) {
	b := &blockingSender{started: make(chan struct{})}
	ctx, cancel := context.WithCancel(context.Background())
	out := &lockedBuffer{}
	l := newListener(ctx, NewWriter(out), b, noResolver)
	pr, pw := io.Pipe()
	done := make(chan struct{})
	returned := make(chan struct{})
	go func() { l.serveRequests(pr, done); close(returned) }()
	pw.Write([]byte(`{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x"}}` + "\n"))
	<-b.started
	for i := 2; i < 10; i++ { // more queued behind the one in flight
		pw.Write([]byte(`{"id": ` + string(rune('0'+i)) + `, "op": "send", "chat": "5511900000000", "message": {"text": "y"}}` + "\n"))
	}
	pw.Close()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("done waited for the send worker")
	}
	cancel() // what cmdListen does next: the in-flight send fails, the queued ones are skipped
	select {
	case <-returned:
	case <-time.After(5 * time.Second):
		t.Fatal("the worker did not stop after the cancel")
	}
	if n := len(out.lines()); n != 0 {
		t.Fatalf("%d answers were written while stopping", n)
	}
}
