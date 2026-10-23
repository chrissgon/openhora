package main

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
)

type fakeTransport struct {
	body          string
	contentLength int64
	calls         int
}

func (f *fakeTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	f.calls++
	return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(f.body)), ContentLength: f.contentLength, Request: req}, nil
}

func get(t *testing.T, tr http.RoundTripper, ctx context.Context, url string) (*http.Response, error) {
	t.Helper()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		t.Fatal(err)
	}
	return tr.RoundTrip(req)
}

func TestAResponseWithinTheCapIsReadWhole(t *testing.T) {
	tr := mediaTransport{base: &fakeTransport{body: strings.Repeat("a", 100), contentLength: -1}}
	ctx, lim, stop := withByteLimit(context.Background(), 100)
	defer stop()
	resp, err := get(t, tr, ctx, "https://media.example/file")
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil || len(data) != 100 || lim.exceeded.Load() {
		t.Fatalf("%d %v %v", len(data), err, lim.exceeded.Load())
	}
}

func TestTheEncryptionOverheadIsAllowedOnTopOfTheCap(t *testing.T) {
	tr := mediaTransport{base: &fakeTransport{body: strings.Repeat("a", 100+encOverhead), contentLength: -1}}
	ctx, lim, stop := withByteLimit(context.Background(), 100)
	defer stop()
	resp, _ := get(t, tr, ctx, "https://media.example/file")
	if _, err := io.ReadAll(resp.Body); err != nil || lim.exceeded.Load() {
		t.Fatalf("%v %v", err, lim.exceeded.Load())
	}
}

func TestABodyOverTheCapIsStoppedMidStreamAndTheDownloadCancelled(t *testing.T) {
	tr := mediaTransport{base: &fakeTransport{body: strings.Repeat("a", 5000), contentLength: -1}}
	ctx, lim, stop := withByteLimit(context.Background(), 100)
	defer stop()
	resp, err := get(t, tr, ctx, "https://media.example/file")
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(resp.Body)
	if !errors.Is(err, errOverCap) || len(data) > 100+encOverhead || !lim.exceeded.Load() {
		t.Fatalf("read %d bytes, err %v, exceeded %v", len(data), err, lim.exceeded.Load())
	}
	if ctx.Err() == nil {
		t.Fatal("the download was not cancelled, so the library would try the next host")
	}
}

func TestADeclaredContentLengthOverTheCapIsRefusedBeforeABodyByteIsRead(t *testing.T) {
	tr := mediaTransport{base: &fakeTransport{body: "x", contentLength: 1 << 30}}
	ctx, lim, stop := withByteLimit(context.Background(), 100)
	defer stop()
	resp, err := get(t, tr, ctx, "https://media.example/file")
	if !errors.Is(err, errOverCap) || resp != nil || !lim.exceeded.Load() {
		t.Fatalf("%v %v", resp, err)
	}
}

func TestARequestOutsideAFetchIsNotLimited(t *testing.T) {
	tr := mediaTransport{base: &fakeTransport{body: strings.Repeat("a", 5000), contentLength: 5000}}
	resp, err := get(t, tr, context.Background(), "https://media.example/file")
	if err != nil {
		t.Fatal(err)
	}
	if data, err := io.ReadAll(resp.Body); err != nil || len(data) != 5000 {
		t.Fatalf("%d %v", len(data), err)
	}
}

func TestOnlyHTTPSIsSent(t *testing.T) {
	base := &fakeTransport{body: "x", contentLength: 1}
	tr := mediaTransport{base: base}
	for _, url := range []string{"http://media.example/file", "ftp://media.example/file"} {
		if _, err := get(t, tr, context.Background(), url); !errors.Is(err, errNotHTTPS) {
			t.Fatalf("%s: %v", url, err)
		}
	}
	if base.calls != 0 {
		t.Fatal("a plain request reached the network")
	}
}

func TestNoRedirectIsFollowedAndTheMediaClientUsesTheBoundedTransport(t *testing.T) {
	client := newMediaClient()
	if err := client.CheckRedirect(&http.Request{}, nil); !errors.Is(err, http.ErrUseLastResponse) {
		t.Fatalf("a redirect would be followed: %v", err)
	}
	if _, ok := client.Transport.(mediaTransport); !ok {
		t.Fatalf("%T", client.Transport)
	}
}
