package main

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"sync/atomic"
	"time"
)

// The library downloads a medium into memory with no bound of its own (it reads the whole body). The bound is put where the
// bytes arrive: the client that downloads media counts what a response delivers and ends the request over the cap. The cap
// of one fetch travels in the request's context, so a download that no fetch started (an upload, the library's own) is not
// limited by it.

const (
	connectTimeout = 10 * time.Second
	// encOverhead is what an encrypted medium holds beyond its plaintext: up to 16 bytes of padding and the 10 bytes of the MAC.
	// 64 leaves room for both and is nothing next to the cap.
	encOverhead = 64
)

var (
	errOverCap  = errors.New("the file is over the byte cap")
	errNotHTTPS = errors.New("a media address is not HTTPS")
)

type limitKey struct{}

// byteLimit is the cap of one fetch.
type byteLimit struct {
	max      int64 // the most plaintext bytes the fetch may hold
	cancel   context.CancelFunc
	exceeded atomic.Bool
}

// withByteLimit returns a context that carries the cap, and the limit itself. Cancelling the context (the returned function)
// ends the download in progress.
func withByteLimit(ctx context.Context, max int64) (context.Context, *byteLimit, context.CancelFunc) {
	ctx, cancel := context.WithCancel(ctx)
	lim := &byteLimit{max: max, cancel: cancel}
	return context.WithValue(ctx, limitKey{}, lim), lim, cancel
}

func limitOf(ctx context.Context) *byteLimit {
	lim, _ := ctx.Value(limitKey{}).(*byteLimit)
	return lim
}

// exceed records that the cap was passed and stops the download, so that the library does not go on to the next host.
func (l *byteLimit) exceed() {
	l.exceeded.Store(true)
	l.cancel()
}

// mediaTransport sends a media request over HTTPS only and, when the request belongs to a fetch, bounds its response.
type mediaTransport struct{ base http.RoundTripper }

func (t mediaTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.URL == nil || req.URL.Scheme != "https" {
		return nil, errNotHTTPS
	}
	resp, err := t.base.RoundTrip(req)
	if err != nil {
		return resp, err
	}
	lim := limitOf(req.Context())
	if lim == nil || req.Method != http.MethodGet {
		return resp, nil
	}
	allowed := lim.max + encOverhead
	if resp.ContentLength > allowed {
		resp.Body.Close()
		lim.exceed()
		return nil, errOverCap
	}
	resp.Body = &limitedBody{rc: resp.Body, left: allowed, lim: lim}
	return resp, nil
}

type limitedBody struct {
	rc   io.ReadCloser
	left int64
	lim  *byteLimit
}

func (b *limitedBody) Read(p []byte) (int, error) {
	if b.left <= 0 {
		var probe [1]byte // the cap is spent: one byte more is over it, the end of the body is not
		n, err := b.rc.Read(probe[:])
		if n > 0 {
			b.lim.exceed()
			return 0, errOverCap
		}
		return 0, err
	}
	if int64(len(p)) > b.left {
		p = p[:b.left]
	}
	n, err := b.rc.Read(p)
	b.left -= int64(n)
	return n, err
}

func (b *limitedBody) Close() error { return b.rc.Close() }

// newMediaClient is the HTTP client the library downloads media with: HTTPS only, a 10-second connect, the bound above and no
// redirect followed (the address is built by the library from WhatsApp's own media hosts, which do not redirect; a redirect
// is refused and the download fails).
func newMediaClient() *http.Client {
	base := (http.DefaultTransport.(*http.Transport)).Clone()
	base.DialContext = (&net.Dialer{Timeout: connectTimeout, KeepAlive: 30 * time.Second}).DialContext
	return &http.Client{
		Transport:     mediaTransport{base: base},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
}
