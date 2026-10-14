package main

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	"go.mau.fi/whatsmeow/proto/waAdv"
	"go.mau.fi/whatsmeow/types"
)

// TestMain lets a test run this very binary's entry points in a child process: WHATSAPP_TEST_CHILD names the entry point.
func TestMain(m *testing.M) {
	switch os.Getenv("WHATSAPP_TEST_CHILD") {
	case "run":
		syscall.Umask(0o077)
		os.Exit(run(strings.Split(os.Getenv("WHATSAPP_TEST_ARGS"), "\x1f"), os.Stdin, os.Stdout, os.Stderr))
	case "reserve":
		// a library prints to descriptor 1 after the reservation; the protocol must not see it
		p, err := reserveProtocol()
		if err != nil {
			os.Exit(9)
		}
		os.Stdout.WriteString("noise on standard output\n")
		os.Stderr.WriteString("")
		NewWriter(p).Write(map[string]string{"event": "ready"})
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func child(t *testing.T, mode string, args ...string) (stdout, stderr string, code int) {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=NONE")
	cmd.Env = append(os.Environ(), "WHATSAPP_TEST_CHILD="+mode, "WHATSAPP_TEST_ARGS="+strings.Join(args, "\x1f"))
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	err := cmd.Run()
	code = 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	return out.String(), errb.String(), code
}

func TestTheProtocolDescriptorIsReservedSoALibraryPrintCannotCorruptALine(t *testing.T) {
	stdout, stderr, code := child(t, "reserve")
	if code != 0 || stdout != "{\"event\":\"ready\"}\n" {
		t.Fatalf("stdout %q code %d", stdout, code)
	}
	if !strings.Contains(stderr, "noise on standard output") {
		t.Fatalf("the stray print should have gone to standard error: %q", stderr)
	}
}

func TestListenWithoutASessionFileWritesPausedAndExits3WithoutCreatingIt(t *testing.T) {
	dir := t.TempDir()
	session := filepath.Join(dir, "session.db")
	stdout, _, code := child(t, "run", "listen", "--session", session, "--platform", "whatsapp")
	if code != 3 || !strings.HasPrefix(stdout, `{"event":"error","kind":"paused","reason":"`) || strings.Count(stdout, "\n") != 1 {
		t.Fatalf("%q %d", stdout, code)
	}
	if _, err := os.Stat(session); err == nil {
		t.Fatal("listen created the session file")
	}
}

func TestStatusOfNoSessionAndOfAnEmptySessionIsNotPairedAndNeverCreatesTheFile(t *testing.T) {
	dir := t.TempDir()
	session := filepath.Join(dir, "session.db")
	stdout, _, code := child(t, "run", "status", "--session", session)
	if code != 0 || stdout != "{\"paired\":false,\"phone\":null}\n" {
		t.Fatalf("%q %d", stdout, code)
	}
	if _, err := os.Stat(session); err == nil {
		t.Fatal("status created the session file")
	}
	// a database that exists but holds no device (a logged-out session) is not paired either, and listen pauses on it
	ctx := context.Background()
	c, err := openStore(ctx, session)
	if err != nil {
		t.Fatal(err)
	}
	if d, err := pairedDevice(ctx, c); err != nil || d != nil {
		t.Fatalf("%v %v", d, err)
	}
	c.Close()
	stdout, _, code = child(t, "run", "status", "--session", session)
	if code != 0 || stdout != "{\"paired\":false,\"phone\":null}\n" {
		t.Fatalf("%q %d", stdout, code)
	}
	stdout, _, code = child(t, "run", "listen", "--session", session)
	if code != 3 || !strings.Contains(stdout, `"kind":"paused"`) {
		t.Fatalf("%q %d", stdout, code)
	}
}

func TestTheSessionDatabaseIsMadeWithTheSQLiteDriverAndIsPrivate(t *testing.T) {
	dir := t.TempDir()
	session := filepath.Join(dir, "with space", "session.db")
	os.MkdirAll(filepath.Dir(session), 0o700)
	syscall.Umask(0o077)
	c, err := openStore(context.Background(), session)
	if err != nil {
		t.Fatalf("the pure-Go driver and the pragmas must open the store: %v", err)
	}
	c.Close()
	entries, _ := os.ReadDir(filepath.Dir(session))
	for _, e := range entries {
		info, _ := e.Info()
		if info.Mode().Perm()&0o077 != 0 {
			t.Errorf("%s has mode %o", e.Name(), info.Mode().Perm())
		}
	}
	if info, err := os.Stat(session); err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("session mode: %v %v", info, err)
	}
	// an existing file with wider access is narrowed
	os.Chmod(session, 0o644)
	c, err = openStore(context.Background(), session)
	if err != nil {
		t.Fatal(err)
	}
	c.Close()
	if info, _ := os.Stat(session); info.Mode().Perm() != 0o600 {
		t.Fatalf("not narrowed: %o", info.Mode().Perm())
	}
}

func TestPairRefusesBadPhonesAndUnknownCommandsAndFlags(t *testing.T) {
	dir := t.TempDir()
	session := filepath.Join(dir, "s.db")
	for _, phone := range []string{"", "+5511900000000", "0123456789", "123", "55 11 90000 0000", "abc"} {
		_, stderr, code := child(t, "run", "pair", "--session", session, "--phone", phone)
		if code != 2 || !strings.Contains(stderr, "--phone") {
			t.Errorf("phone %q: %q %d", phone, stderr, code)
		}
	}
	if _, err := os.Stat(session); err == nil {
		t.Error("a refused pair created the session")
	}
	for _, args := range [][]string{{}, {"nope"}, {"status"}, {"status", "--session", session, "extra"}, {"listen", "--session", session, "--platform", "telegram"}, {"whoami", "--session", session, "--seconds", "0"}, {"whoami", "--session", session, "--seconds", "601"}} {
		_, _, code := child(t, "run", args...)
		if code != 2 {
			t.Errorf("%v: exit %d", args, code)
		}
	}
	stdout, _, code := child(t, "run", "--help")
	if code != 0 || !strings.Contains(stdout, "listen") || !strings.Contains(stdout, "pair") {
		t.Errorf("help: %q %d", stdout, code)
	}
	for _, sub := range []string{"listen", "pair", "status", "whoami"} {
		stdout, _, code := child(t, "run", sub, "--help")
		if code != 0 || !strings.Contains(stdout, "-session") {
			t.Errorf("%s --help: %q %d", sub, stdout, code)
		}
	}
}

func TestWhoamiWithoutASessionSaysHowToPairAndExits3(t *testing.T) {
	dir := t.TempDir()
	_, stderr, code := child(t, "run", "whoami", "--session", filepath.Join(dir, "none.db"))
	if code != 3 || !strings.Contains(stderr, "pair --phone") {
		t.Fatalf("%q %d", stderr, code)
	}
}

func TestSourcesHoldNoNonASCIICharacter(t *testing.T) {
	files, _ := filepath.Glob("*.go")
	for _, f := range files {
		b, _ := os.ReadFile(f)
		for _, r := range string(b) {
			if r > 0x7e {
				// test files may carry a literal accent; program files may not (invisible characters, lookalikes)
				if !strings.HasSuffix(f, "_test.go") {
					t.Errorf("%s holds a non-ASCII character %U", f, r)
				}
			}
		}
	}
}

func TestStatusOfAPairedSessionNamesThePhoneDigitsAndNeverConnects(t *testing.T) {
	dir := t.TempDir()
	session := filepath.Join(dir, "session.db")
	ctx := context.Background()
	c, err := openStore(ctx, session)
	if err != nil {
		t.Fatal(err)
	}
	device := c.NewDevice()
	id := types.NewADJID(person, 0, 7)
	device.ID = &id
	device.Account = &waAdv.ADVSignedDeviceIdentity{Details: []byte{1}, AccountSignature: make([]byte, 64), AccountSignatureKey: make([]byte, 32), DeviceSignature: make([]byte, 64)}
	if err := c.PutDevice(ctx, device); err != nil {
		t.Fatal(err)
	}
	found, err := pairedDevice(ctx, c)
	if err != nil || found == nil || phoneOf(found.ID) != person {
		t.Fatalf("%v %v", found, err)
	}
	c.Close()
	stdout, _, code := child(t, "run", "status", "--session", session, "--platform", "whatsapp")
	if code != 0 || stdout != "{\"paired\":true,\"phone\":\""+person+"\"}\n" {
		t.Fatalf("%q %d", stdout, code)
	}
	// pairing again refuses and says what to do first
	_, stderr, code := child(t, "run", "pair", "--session", session, "--phone", "5511911111111")
	if code != 2 || !strings.Contains(stderr, "already paired") || !strings.Contains(stderr, "Linked devices") {
		t.Fatalf("%q %d", stderr, code)
	}
}
