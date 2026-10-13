// Command whatsapp-bridge is the WhatsApp side of openhora's messaging bridge: a small program on whatsmeow (an unofficial
// WhatsApp Web client) that holds one linked device of the person's separate WhatsApp number.
//
//	whatsapp-bridge listen  --session <file>                 the listen protocol of providers/messenger/README.md
//	whatsapp-bridge pair    --session <file> --phone <digits>  link this program as a device, with a pairing code
//	whatsapp-bridge status  --session <file>                 print {"paired": bool, "phone": "<digits>" | null}; never connects
//	whatsapp-bridge whoami  --session <file> [--seconds 120] print the digits of whoever writes to the number; never sends
//
// It is started by providers/messenger/whatsapp.py, which checks the build first. Descriptor 1 belongs to the protocol in
// listen; everything else goes to standard error.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"syscall"
)

const usageText = `usage: whatsapp-bridge <command> [flags]

commands:
  listen  --session <file>                  run the listen protocol (JSON lines on standard input and output)
  pair    --session <file> --phone <digits> link this program to the WhatsApp account of <digits> with a pairing code
  status  --session <file>                  print {"paired": bool, "phone": "<digits>" | null}; never connects
  whoami  --session <file> [--seconds 120]  print the phone digits of every person who writes to this number meanwhile

The flag --platform whatsapp is accepted and ignored. Run through providers/messenger/whatsapp.py.
`

const (
	exitOK       = 0
	exitFailed   = 1
	exitUsage    = 2
	exitNotReady = 3
)

func main() {
	syscall.Umask(0o077) // the session database and its -wal, -shm and -journal files are made 0600
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

func run(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(stderr, usageText)
		return exitUsage
	}
	switch args[0] {
	case "-h", "--help", "help":
		fmt.Fprint(stdout, usageText)
		return exitOK
	case "listen":
		return cmdListen(args[1:], stdin, stderr)
	case "pair":
		return cmdPair(args[1:], stdout, stderr)
	case "status":
		return cmdStatus(args[1:], stdout, stderr)
	case "whoami":
		return cmdWhoami(args[1:], stdout, stderr)
	}
	fmt.Fprintf(stderr, "whatsapp-bridge: unknown command %q\n\n%s", args[0], usageText)
	return exitUsage
}

type commonFlags struct {
	session  string
	platform string
}

// parseFlags parses a subcommand's flags. help is true when --help was given (the text went to standard output).
func parseFlags(name string, args []string, stdout, stderr io.Writer, extra func(*flag.FlagSet)) (c commonFlags, ok bool, help bool) {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.StringVar(&c.session, "session", "", "path of the session database (required)")
	fs.StringVar(&c.platform, "platform", "whatsapp", "accepted for the provider interface; must be whatsapp")
	if extra != nil {
		extra(fs)
	}
	if err := fs.Parse(args); err != nil {
		if err == flag.ErrHelp {
			fs.SetOutput(stdout)
			fs.Usage()
			return c, false, true
		}
		return c, false, false
	}
	if fs.NArg() > 0 || c.session == "" || c.platform != "whatsapp" {
		fmt.Fprintf(stderr, "whatsapp-bridge %s: --session <file> is required, and nothing else is accepted\n", name)
		return c, false, false
	}
	return c, true, false
}
