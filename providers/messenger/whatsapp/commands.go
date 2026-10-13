package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"regexp"
	"sync"
	"syscall"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types/events"
)

type statusAnswer struct {
	Paired bool    `json:"paired"`
	Phone  *string `json:"phone"`
}

// cmdStatus prints whether the session holds a paired device. It never connects and never creates the session file.
func cmdStatus(args []string, stdout, stderr io.Writer) int {
	c, ok, help := parseFlags("status", args, stdout, stderr, nil)
	if help {
		return exitOK
	}
	if !ok {
		return exitUsage
	}
	answer := statusAnswer{}
	if sessionExists(c.session) {
		ctx := context.Background()
		container, err := openStore(ctx, c.session)
		if err != nil {
			fmt.Fprintf(stderr, "whatsapp-bridge status: %v\n", err)
			return exitFailed
		}
		defer container.Close()
		device, err := pairedDevice(ctx, container)
		if err != nil {
			fmt.Fprintf(stderr, "whatsapp-bridge status: the session cannot be read: %v\n", err)
			return exitFailed
		}
		if device != nil {
			phone := phoneOf(device.ID)
			answer = statusAnswer{Paired: true, Phone: &phone}
		}
	}
	out, _ := json.Marshal(answer)
	fmt.Fprintln(stdout, string(out))
	return exitOK
}

var phoneRe = regexp.MustCompile(`^[1-9][0-9]{6,14}$`)

const pairSteps = `
Pairing code: %s

On the phone that has the number %s:
  1. Open WhatsApp, then Settings (iPhone) or the three dots (Android).
  2. Choose Linked devices, then Link a device.
  3. Choose "Link with phone number instead" and type the code above.
The code is valid for about two minutes. Waiting for the phone...
`

// cmdPair links this program as a device of the account of --phone, with a pairing code. No QR code is drawn: that would
// need one more module, and the code does the same.
func cmdPair(args []string, stdout, stderr io.Writer) int {
	var phone string
	c, ok, help := parseFlags("pair", args, stdout, stderr, func(fs *flag.FlagSet) {
		fs.StringVar(&phone, "phone", "", "the phone number of the account, as digits with the country code and no plus sign (required)")
	})
	if help {
		return exitOK
	}
	if !ok {
		return exitUsage
	}
	if !phoneRe.MatchString(phone) {
		fmt.Fprintln(stderr, "whatsapp-bridge pair: --phone is the number as digits with the country code and no plus sign, for example 5511900000000")
		return exitUsage
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(ctx, 4*time.Minute)
	defer cancel()

	container, err := openStore(ctx, c.session)
	if err != nil {
		fmt.Fprintf(stderr, "whatsapp-bridge pair: %v\n", err)
		return exitFailed
	}
	defer container.Close()
	existing, err := pairedDevice(ctx, container)
	if err != nil {
		fmt.Fprintf(stderr, "whatsapp-bridge pair: the session cannot be read: %v\n", err)
		return exitFailed
	}
	if existing != nil {
		fmt.Fprintln(stderr, "whatsapp-bridge pair: this session is already paired. Unlink the device in WhatsApp (Linked devices), delete the session file, and pair again.")
		return exitUsage
	}

	cli := whatsmeow.NewClient(container.NewDevice(), newStderrLogger("whatsmeow"))
	var mu sync.Mutex
	connected := make(chan struct{})
	var once sync.Once
	cli.AddEventHandler(func(evt any) {
		if _, isConnected := evt.(*events.Connected); isConnected {
			mu.Lock()
			once.Do(func() { close(connected) })
			mu.Unlock()
		}
	})
	qr, err := cli.GetQRChannel(ctx)
	if err != nil {
		fmt.Fprintf(stderr, "whatsapp-bridge pair: %v\n", err)
		return exitFailed
	}
	if err := cli.Connect(); err != nil {
		fmt.Fprintln(stderr, "whatsapp-bridge pair: the connection to WhatsApp could not be made")
		return exitFailed
	}
	defer cli.Disconnect()

	// The pairing code needs the connection to be fully up, which the first item of the QR channel tells.
	var first whatsmeow.QRChannelItem
	select {
	case first = <-qr:
	case <-ctx.Done():
		fmt.Fprintln(stderr, "whatsapp-bridge pair: stopped before WhatsApp answered")
		return exitFailed
	}
	if first.Event != whatsmeow.QRChannelEventCode {
		fmt.Fprintf(stderr, "whatsapp-bridge pair: WhatsApp did not start a pairing (%s)\n", first.Event)
		return exitFailed
	}
	code, err := cli.PairPhone(ctx, phone, true, whatsmeow.PairClientChrome, "Chrome (Linux)")
	if err != nil {
		fmt.Fprintln(stderr, "whatsapp-bridge pair: WhatsApp refused the pairing request; check the number and try again")
		return exitFailed
	}
	fmt.Fprintf(stdout, pairSteps, code, phone)
	for {
		select {
		case item, open := <-qr:
			if !open {
				fmt.Fprintln(stderr, "whatsapp-bridge pair: the pairing ended without success")
				return exitFailed
			}
			switch item.Event {
			case whatsmeow.QRChannelEventCode:
				continue // codes keep rotating; only the pairing code is shown
			case whatsmeow.QRChannelSuccess.Event:
				select {
				case <-connected:
				case <-time.After(30 * time.Second):
				case <-ctx.Done():
				}
				fmt.Fprintln(stdout, "Paired. This computer is now a linked device of that number. Next: put your personal number in messaging.senders.whatsapp and start the bridge.")
				return exitOK
			default:
				fmt.Fprintf(stderr, "whatsapp-bridge pair: the pairing failed (%s)\n", item.Event)
				return exitFailed
			}
		case <-ctx.Done():
			fmt.Fprintln(stderr, "whatsapp-bridge pair: the code expired or the pairing was stopped; run pair again")
			return exitFailed
		}
	}
}

// cmdWhoami prints, one per line and once each, the phone digits of every person who writes to the bridge's number while it
// listens. It sends nothing and does not use the bridge; its instructions go to standard error so standard output is the digits.
func cmdWhoami(args []string, stdout, stderr io.Writer) int {
	seconds := 120
	c, ok, help := parseFlags("whoami", args, stdout, stderr, func(fs *flag.FlagSet) {
		fs.IntVar(&seconds, "seconds", 120, "how long to listen, 1 to 600")
	})
	if help {
		return exitOK
	}
	if !ok || seconds < 1 || seconds > 600 {
		fmt.Fprintln(stderr, "whatsapp-bridge whoami: --seconds is a number from 1 to 600")
		return exitUsage
	}
	if !sessionExists(c.session) {
		fmt.Fprintln(stderr, reasonUnpaired)
		return exitNotReady
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	container, err := openStore(ctx, c.session)
	if err != nil {
		fmt.Fprintf(stderr, "whatsapp-bridge whoami: %v\n", err)
		return exitFailed
	}
	defer container.Close()
	device, err := pairedDevice(ctx, container)
	if err != nil {
		fmt.Fprintf(stderr, "whatsapp-bridge whoami: the session cannot be read: %v\n", err)
		return exitFailed
	}
	if device == nil {
		fmt.Fprintln(stderr, reasonUnpaired)
		return exitNotReady
	}
	cli := whatsmeow.NewClient(device, newStderrLogger("whatsmeow"))
	resolve := storeResolver(device)
	seen := map[string]bool{}
	var mu sync.Mutex
	lost := make(chan struct{})
	var lostOnce sync.Once
	cli.AddEventHandler(func(raw any) {
		switch evt := raw.(type) {
		case *events.Message:
			digits, why := senderDigits(ctx, evt.Info, resolve)
			if why != dropNone {
				return
			}
			mu.Lock()
			defer mu.Unlock()
			if !seen[digits] {
				seen[digits] = true
				fmt.Fprintln(stdout, digits)
			}
		case *events.LoggedOut, *events.StreamReplaced:
			lostOnce.Do(func() { close(lost) })
		}
	})
	if err := cli.Connect(); err != nil {
		fmt.Fprintln(stderr, "whatsapp-bridge whoami: the connection to WhatsApp could not be made")
		return exitFailed
	}
	defer cli.Disconnect()
	fmt.Fprintf(stderr, "Connected. For %d seconds, send any message from your personal WhatsApp to the bridge's number; the digits of each sender are printed here.\n", seconds)
	select {
	case <-time.After(time.Duration(seconds) * time.Second):
	case <-ctx.Done():
	case <-lost:
		fmt.Fprintln(stderr, "The session was lost while listening.")
		return exitNotReady
	}
	return exitOK
}

var _ = os.Stdout
