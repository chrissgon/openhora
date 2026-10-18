package main

import (
	"context"
	"fmt"
	"io"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waE2E"
)

func TestAnUpdateWithAFileCarriesARandomRefTheTableServes(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	doc := docFor([]byte("plan"))
	l.handle(mediaEvent(&waE2E.Message{DocumentMessage: doc}))
	l.handle(mediaEvent(&waE2E.Message{DocumentMessage: doc})) // delivered twice
	lines := out.lines()
	if len(lines) != 2 {
		t.Fatalf("%v", lines)
	}
	refs := []string{}
	for _, line := range lines {
		u := line["update"].(map[string]any)
		atts := u["attachments"].([]any)
		a := atts[0].(map[string]any)
		ref := a["ref"].(string)
		if !refRe.MatchString(ref) || a["name"] != secretName || a["type"] != "application/pdf" || a["size"] != float64(4) || u["text"] != nil {
			t.Fatalf("%v", u)
		}
		if msg, ok := l.refs.get(ref); !ok || msg != doc {
			t.Fatal("the ref does not serve the message")
		}
		refs = append(refs, ref)
	}
	if refs[0] != refs[1] {
		t.Fatal("the same message delivered twice must keep one ref")
	}
	raw := out.buf.String()
	for _, bad := range []string{hexOf(testKey), "mmg.whatsapp.net", "/v/t62"} {
		if strings.Contains(raw, bad) {
			t.Fatalf("%q reached the protocol", bad)
		}
	}
}

func hexOf(b []byte) string { return fmt.Sprintf("%x", b) }

func TestATextUpdateRegistersNoRef(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(textEvent(pn(person), pn(person), "hi"))
	if len(out.lines()) != 1 || len(l.refs.order) != 0 {
		t.Fatal("a text holds no ref")
	}
}

func serve(t *testing.T, l *listener, in io.Reader) {
	t.Helper()
	done, returned := make(chan struct{}), make(chan struct{})
	go func() { l.serveRequests(in, done); close(returned) }()
	select {
	case <-returned:
	case <-time.After(5 * time.Second):
		t.Fatal("did not end at the end of its input")
	}
}

func fetchLine(id int, ref, out string, max int64) string {
	return fmt.Sprintf(`{"id": %d, "op": "fetch", "ref": %q, "out": %q, "max_bytes": %d}`+"\n", id, ref, out, max)
}

func TestAFetchRequestIsAnsweredWithTheBytesAndTheHash(t *testing.T) {
	data := []byte("%PDF-1.7 plan")
	l, out := newTestListener(&fakeSender{})
	dl := &fakeDownloader{data: data}
	l.fetcher = newFetcher(l.refs, dl)
	ref := l.refs.add("o", "k", docFor(data))
	dir := privateDir(t)
	input := fetchLine(5, ref, dir, 1<<20) + fetchLine(6, strings.Repeat("c", 32), dir, 1<<20)
	serve(t, l, strings.NewReader(input))
	lines := out.lines()
	if len(lines) != 2 {
		t.Fatalf("%v", lines)
	}
	byID := map[float64]map[string]any{}
	for _, line := range lines {
		byID[line["id"].(float64)] = line
	}
	ok, gone := byID[5], byID[6]
	if ok["ok"] != true || ok["bytes"] != float64(len(data)) || ok["sha256"] != sha(data) {
		t.Fatalf("%v", ok)
	}
	if gone["ok"] != false || gone["kind"] != "gone" {
		t.Fatalf("%v", gone)
	}
	if _, err := filepath.Glob(filepath.Join(dir, "content")); err != nil {
		t.Fatal(err)
	}
}

func TestAFetchInFlightDoesNotHoldUpASend(t *testing.T) {
	data := []byte("plan")
	f := &fakeSender{}
	l, out := newTestListener(f)
	release := make(chan struct{})
	started := make(chan struct{})
	dl := &fakeDownloader{data: data, hook: func(context.Context) { close(started); <-release }}
	l.fetcher = newFetcher(l.refs, dl)
	ref := l.refs.add("o", "k", docFor(data))
	dir := privateDir(t)

	pr, pw := io.Pipe()
	returned := make(chan struct{})
	go func() { l.serveRequests(pr, make(chan struct{})); close(returned) }()
	pw.Write([]byte(fetchLine(1, ref, dir, 1<<20)))
	<-started
	pw.Write([]byte(`{"id": 2, "op": "send", "chat": "5511900000000", "message": {"text": "card"}}` + "\n"))
	deadline := time.After(5 * time.Second)
	for {
		if lines := out.lines(); len(lines) == 1 && lines[0]["id"] == float64(2) && lines[0]["ok"] == true {
			break
		}
		select {
		case <-deadline:
			t.Fatalf("the send waited for the fetch: %v", out.lines())
		case <-time.After(10 * time.Millisecond):
		}
	}
	close(release)
	pw.Close()
	select {
	case <-returned:
	case <-time.After(5 * time.Second):
		t.Fatal("did not end")
	}
	lines := out.lines()
	if len(lines) != 2 || lines[1]["id"] != float64(1) || lines[1]["ok"] != true {
		t.Fatalf("%v", lines)
	}
}

func TestMoreFetchesThanTheQueueHoldsAreRefusedAtOnce(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	release := make(chan struct{})
	started := make(chan struct{}, 1)
	dl := &fakeDownloader{data: []byte("x"), hook: func(context.Context) {
		select {
		case started <- struct{}{}:
		default:
		}
		<-release
	}}
	l.fetcher = newFetcher(l.refs, dl)
	ref := l.refs.add("o", "k", docFor([]byte("x")))
	dir := privateDir(t)
	pr, pw := io.Pipe()
	returned := make(chan struct{})
	go func() { l.serveRequests(pr, make(chan struct{})); close(returned) }()
	pw.Write([]byte(fetchLine(1, ref, dir, 100)))
	<-started
	for id := 2; id <= 9; id++ {
		pw.Write([]byte(fetchLine(id, ref, dir, 100)))
	}
	deadline := time.After(5 * time.Second)
	for {
		refused := 0
		for _, line := range out.lines() {
			if line["ok"] == false && line["kind"] == "failed" {
				refused++
			}
		}
		if refused >= 1 {
			break
		}
		select {
		case <-deadline:
			t.Fatal("nothing was refused")
		case <-time.After(10 * time.Millisecond):
		}
	}
	close(release)
	pw.Close()
	<-returned
}

func TestAFetchWithNoFetcherIsAUsageAnswer(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	serve(t, l, strings.NewReader(fetchLine(3, strings.Repeat("a", 32), "/tmp", 10)))
	lines := out.lines()
	if len(lines) != 1 || lines[0]["kind"] != "usage" {
		t.Fatalf("%v", lines)
	}
}

func TestTheEndOfInputEndsTheServingEvenWithAFetchInFlight(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	out := &lockedBuffer{}
	l := newListener(ctx, NewWriter(out), &fakeSender{}, noResolver)
	started := make(chan struct{})
	dl := &fakeDownloader{data: []byte("x"), hook: func(c context.Context) { close(started); <-c.Done() }}
	l.fetcher = newFetcher(l.refs, dl)
	ref := l.refs.add("o", "k", docFor([]byte("x")))
	pr, pw := io.Pipe()
	done := make(chan struct{})
	returned := make(chan struct{})
	go func() { l.serveRequests(pr, done); close(returned) }()
	pw.Write([]byte(fetchLine(1, ref, privateDir(t), 100)))
	<-started
	pw.Close()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("done waited for the fetch")
	}
	cancel()
	select {
	case <-returned:
	case <-time.After(5 * time.Second):
		t.Fatal("the fetch worker did not stop after the cancel")
	}
	if n := len(out.lines()); n != 0 {
		t.Fatalf("%d answers were written while stopping", n)
	}
}

func TestAnUnknownOpIsStillAUsageAnswerThatNamesBothRequests(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	serve(t, l, strings.NewReader(`{"id": 4, "op": "delete", "chat": "5511900000000"}`+"\n"))
	lines := out.lines()
	if len(lines) != 1 || lines[0]["kind"] != "usage" || !strings.Contains(lines[0]["reason"].(string), "send and fetch") {
		t.Fatalf("%v", lines)
	}
}
