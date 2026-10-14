package main

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

// The sentences the bridge shows the person when the session is lost. They name the command that mends it.
const (
	reasonUnpaired = "the WhatsApp session is missing or logged out; link this computer again with: python3 providers/messenger/whatsapp.py pair --phone <digits of the bridge's number>"
	reasonReplaced = "another program is using this WhatsApp session; if it is not yours, unlink every device in Linked devices on the phone"
	reasonOutdated = "WhatsApp no longer accepts this version of the client; update openhora and run: python3 providers/messenger/whatsapp.py build"
)

type errorEvent struct {
	Event  string `json:"event"`
	Kind   string `json:"kind"`
	Reason string `json:"reason"`
}

type readyEvent struct {
	Event string `json:"event"`
}

type updateEvent struct {
	Event  string  `json:"event"`
	Update *Update `json:"update"`
}

// listener holds what the event handler and the request worker share.
type listener struct {
	ctx     context.Context
	w       *Writer
	sender  Sender
	resolve Resolver
	exit    chan int
	once    sync.Once

	mu        sync.Mutex
	connected bool
}

func newListener(ctx context.Context, w *Writer, sender Sender, resolve Resolver) *listener {
	return &listener{ctx: ctx, w: w, sender: sender, resolve: resolve, exit: make(chan int, 1)}
}

func (l *listener) write(v any) {
	exitOnWriteError(l.w.Write(v))
}

// stop writes the error event (when there is a reason) and asks the program to exit with code. Only the first call counts.
func (l *listener) stop(code int, kind, reason string) {
	l.once.Do(func() {
		if reason != "" {
			l.write(errorEvent{Event: "error", Kind: kind, Reason: reason})
		}
		l.exit <- code
	})
}

func (l *listener) failed(reason string) {
	l.write(errorEvent{Event: "error", Kind: kindFailed, Reason: reason})
}

// handle is the client's event handler.
func (l *listener) handle(raw any) {
	switch evt := raw.(type) {
	case *events.Connected:
		l.mu.Lock()
		l.connected = true
		l.mu.Unlock()
		l.write(readyEvent{Event: "ready"})
	case *events.Disconnected:
		l.mu.Lock()
		was := l.connected
		l.connected = false
		l.mu.Unlock()
		if was {
			l.failed("the connection to WhatsApp was lost; reconnecting")
		}
	case *events.Message:
		l.message(evt)
	case *events.LoggedOut:
		// whatsmeow has deleted the session: only a new pairing mends it, which the person does; the bridge waits and asks again
		l.stop(exitNotReady, "paused", reasonUnpaired)
	case *events.StreamReplaced:
		// a second client uses the same keys (a copied session, or a second bridge): whatsmeow keeps the store, so this is not a pause
		l.stop(exitNotReady, "not-configured", reasonReplaced)
	case *events.ClientOutdated:
		l.stop(exitNotReady, "not-configured", reasonOutdated)
	case *events.TemporaryBan:
		l.failed("WhatsApp has restricted this number for a while")
		l.stop(exitFailed, kindFailed, "")
	case *events.ConnectFailure:
		l.failed("WhatsApp refused the connection")
		l.stop(exitFailed, kindFailed, "")
	case *events.KeepAliveTimeout:
		logf("the keepalive timed out; the library reconnects")
	}
}

func (l *listener) message(evt *events.Message) {
	u, why := inbound(l.ctx, evt, l.resolve)
	switch {
	case u != nil:
		err := l.w.Write(updateEvent{Event: "update", Update: u})
		if errors.Is(err, errLineTooLong) {
			logf("an update over the line limit was dropped")
			return
		}
		exitOnWriteError(err)
	case why == dropUnresolved:
		logf("a message from an address that could not be resolved to a phone number was dropped")
	}
}

// serveRequests reads the bridge's lines from in and sends each request, one at a time, until the input ends.
func (l *listener) serveRequests(in io.Reader, done chan<- struct{}) {
	requests := make(chan Request, 64)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for req := range requests {
			if l.ctx.Err() != nil {
				continue // the program is stopping: queued requests fail with it (the bridge fails what it was waiting for)
			}
			answer := Handle(l.ctx, l.sender, req)
			if l.ctx.Err() != nil {
				continue
			}
			l.write(answer)
		}
	}()
	r := bufio.NewReaderSize(in, 64*1024)
	for {
		line, err := ReadLine(r, maxLine)
		if errors.Is(err, errLineTooLong) {
			logf("a line over the limit was dropped")
			continue
		}
		if err != nil {
			break
		}
		req, bad, ok := ParseRequest(line)
		switch {
		case !ok:
			logf("a line without a usable id was dropped")
		case bad != nil:
			l.write(*bad)
		default:
			requests <- req
		}
	}
	// The end of the input ends the program at once: done closes here, the caller cancels the context (which fails an
	// in-flight send) and the 3 s bound of the disconnect applies. The worker is waited for only after that.
	close(done)
	close(requests)
	wg.Wait()
}

func cmdListen(args []string, stdin io.Reader, stderr io.Writer) int {
	c, ok, help := parseFlags("listen", args, os.Stdout, stderr, nil)
	if help {
		return exitOK
	}
	if !ok {
		return exitUsage
	}
	protocol, err := reserveProtocol()
	if err != nil {
		logf("the protocol descriptor cannot be reserved: %v", err)
		return exitFailed
	}
	w := NewWriter(protocol)
	pause := func(reason string) int {
		exitOnWriteError(w.Write(errorEvent{Event: "error", Kind: "paused", Reason: reason}))
		return exitNotReady
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if !sessionExists(c.session) {
		return pause(reasonUnpaired)
	}
	container, err := openStore(ctx, c.session)
	if err != nil {
		logf("%v", err)
		exitOnWriteError(w.Write(errorEvent{Event: "error", Kind: kindFailed, Reason: "the session database cannot be opened"}))
		return exitFailed
	}
	defer container.Close()
	device, err := pairedDevice(ctx, container)
	if err != nil {
		logf("the session cannot be read: %v", err)
		exitOnWriteError(w.Write(errorEvent{Event: "error", Kind: kindFailed, Reason: "the session database cannot be read"}))
		return exitFailed
	}
	if device == nil {
		return pause(reasonUnpaired)
	}

	cli := whatsmeow.NewClient(device, newStderrLogger("whatsmeow"))
	cli.EnableAutoReconnect = true
	cli.InitialAutoReconnect = true
	l := newListener(ctx, w, clientSender{cli}, storeResolver(device))
	cli.AddEventHandler(l.handle)

	inputDone := make(chan struct{})
	go l.serveRequests(stdin, inputDone)
	go l.connect(cli)

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGTERM, syscall.SIGINT)
	code := exitOK
	select {
	case code = <-l.exit:
	case <-inputDone:
	case <-sigs:
	}
	cancel()
	closed := make(chan struct{})
	go func() { cli.Disconnect(); close(closed) }()
	select {
	case <-closed:
	case <-time.After(3 * time.Second):
	}
	return code
}

// connect connects the client, retrying with a backoff of 1, 2, 4 ... 60 s while the connection cannot be made (the library
// reconnects by itself once it has been up).
func (l *listener) connect(cli *whatsmeow.Client) {
	delay := time.Second
	for {
		err := cli.Connect()
		if err == nil {
			return
		}
		if errors.Is(err, store.ErrDeviceDeleted) {
			l.stop(exitNotReady, "paused", reasonUnpaired)
			return
		}
		l.failed("the connection to WhatsApp could not be made; trying again")
		select {
		case <-l.ctx.Done():
			return
		case <-time.After(delay):
		}
		if delay < 60*time.Second {
			delay *= 2
		}
	}
}

// storeResolver resolves a LID address with the device's own store.
func storeResolver(device *store.Device) Resolver {
	return func(ctx context.Context, lid types.JID) (types.JID, bool) {
		if device == nil || device.LIDs == nil {
			return types.EmptyJID, false
		}
		pn, err := device.LIDs.GetPNForLID(ctx, lid)
		if err != nil || pn.IsEmpty() {
			return types.EmptyJID, false
		}
		return pn, true
	}
}
