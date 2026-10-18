package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
)

const secretName = "Payroll-Maria-Souza.pdf"

type fakeDownloader struct {
	data  []byte
	err   error
	calls int
	got   whatsmeow.DownloadableMessage
	hook  func(ctx context.Context)
}

func (f *fakeDownloader) Download(ctx context.Context, msg whatsmeow.DownloadableMessage) ([]byte, error) {
	f.calls++
	f.got = msg
	if f.hook != nil {
		f.hook(ctx)
	}
	return f.data, f.err
}

// docFor is a document message that declares data (its hash and length), as a sender's client would.
func docFor(data []byte) *waE2E.DocumentMessage {
	sum := sha256.Sum256(data)
	return &waE2E.DocumentMessage{
		DirectPath: ptr("/v/t62.7119-24/abc"),
		MediaKey:   testKey,
		FileName:   ptr(secretName),
		Mimetype:   ptr("application/pdf"),
		FileLength: ptr(uint64(len(data))),
		FileSHA256: sum[:],
	}
}

func sha(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func privateDir(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "incoming")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	return dir
}

type fetchKit struct {
	t     *testing.T
	refs  *refTable
	dl    *fakeDownloader
	f     *fetcher
	out   string
	ref   string
	bytes []byte
}

// newKit makes a fetcher whose table holds one document of data, ready to be fetched into a private folder.
func newKit(t *testing.T, data []byte) *fetchKit {
	t.Helper()
	refs := newRefTable()
	dl := &fakeDownloader{data: data}
	return &fetchKit{t: t, refs: refs, dl: dl, f: newFetcher(refs, dl), out: privateDir(t), ref: refs.add("k", docFor(data)), bytes: data}
}

func (k *fetchKit) request(ref, out string, max int64) Request {
	k.t.Helper()
	return request(k.t, fmt.Sprintf(`{"id": 9, "op": "fetch", "ref": %q, "out": %q, "max_bytes": %d}`, ref, out, max))
}

func (k *fetchKit) fetch(max int64) Answer {
	k.t.Helper()
	return k.f.Handle(context.Background(), k.request(k.ref, k.out, max))
}

func (k *fetchKit) noContent() {
	k.t.Helper()
	if _, err := os.Lstat(filepath.Join(k.out, "content")); !errors.Is(err, os.ErrNotExist) {
		k.t.Fatalf("a file was left in the folder: %v", err)
	}
}

func TestAFetchWritesTheFileAs0600ContentAndAnswersItsSizeAndHash(t *testing.T) {
	data := []byte("%PDF-1.7 the quarterly plan")
	k := newKit(t, data)
	a := k.fetch(1 << 20)
	if !a.OK || a.Bytes == nil || *a.Bytes != int64(len(data)) || a.SHA256 != sha(data) || string(a.ID) != "9" {
		t.Fatalf("%+v", a)
	}
	path := filepath.Join(k.out, "content")
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		t.Fatalf("%v %v", info, err)
	}
	if got, _ := os.ReadFile(path); string(got) != string(data) {
		t.Fatal("the bytes written")
	}
	entries, _ := os.ReadDir(k.out)
	if len(entries) != 1 {
		t.Fatalf("only content is written: %v", entries)
	}
	if k.dl.got != k.refs.mustGet(k.ref) {
		t.Fatal("the downloader got another message")
	}
	line, _ := Line(a)
	if !strings.Contains(string(line), `"bytes":27`) || !strings.Contains(string(line), `"sha256":"`+sha(data)+`"`) {
		t.Fatalf("%s", line)
	}
}

func (t *refTable) mustGet(ref string) whatsmeow.DownloadableMessage {
	msg, _ := t.get(ref)
	return msg
}

func TestAnEmptyFileIsAnAnswerWithZeroBytes(t *testing.T) {
	k := newKit(t, []byte{})
	a := k.fetch(100)
	line, _ := Line(a)
	if !a.OK || !strings.Contains(string(line), `"bytes":0`) {
		t.Fatalf("%s", line)
	}
}

func TestAReferenceThatIsNotKnownOrHasExpiredIsGone(t *testing.T) {
	k := newKit(t, []byte("x"))
	a := k.f.Handle(context.Background(), k.request(strings.Repeat("a", 32), k.out, 100))
	if a.OK || a.Kind != "gone" || k.dl.calls != 0 {
		t.Fatalf("%+v", a)
	}
	now := time.Date(2026, 10, 17, 12, 0, 0, 0, time.UTC)
	refs := newRefTable()
	refs.now = func() time.Time { return now }
	ref := refs.add("other", docFor([]byte("y")))
	now = now.Add(refTTL + time.Second)
	a = newFetcher(refs, k.dl).Handle(context.Background(), k.request(ref, k.out, 100))
	if a.Kind != "gone" || k.dl.calls != 0 {
		t.Fatalf("%+v", a)
	}
	k.noContent()
}

func TestARequestThatIsNotWellFormedIsAUsageAnswer(t *testing.T) {
	k := newKit(t, []byte("x"))
	bad := map[string]string{
		"no ref":         `{"id": 1, "op": "fetch", "out": "` + k.out + `", "max_bytes": 10}`,
		"a ref not made": `{"id": 1, "op": "fetch", "ref": "../../etc/passwd", "out": "` + k.out + `", "max_bytes": 10}`,
		"an upper ref":   `{"id": 1, "op": "fetch", "ref": "` + strings.ToUpper(k.ref) + `", "out": "` + k.out + `", "max_bytes": 10}`,
		"no out":         `{"id": 1, "op": "fetch", "ref": "` + k.ref + `", "max_bytes": 10}`,
		"no cap":         `{"id": 1, "op": "fetch", "ref": "` + k.ref + `", "out": "` + k.out + `"}`,
		"a zero cap":     `{"id": 1, "op": "fetch", "ref": "` + k.ref + `", "out": "` + k.out + `", "max_bytes": 0}`,
		"a negative cap": `{"id": 1, "op": "fetch", "ref": "` + k.ref + `", "out": "` + k.out + `", "max_bytes": -5}`,
	}
	for name, line := range bad {
		a := k.f.Handle(context.Background(), request(t, line))
		if a.OK || a.Kind != "usage" {
			t.Errorf("%s: %+v", name, a)
		}
	}
	if k.dl.calls != 0 {
		t.Fatal("nothing is downloaded for a request that is not whole")
	}
	req, bad2, ok := ParseRequest([]byte(`{"id": 1, "op": "fetch", "ref": "x", "out": "y", "max_bytes": "10"}`))
	if !ok || bad2 == nil || bad2.Kind != "usage" {
		t.Fatalf("a cap that is not a number: %+v %+v", req, bad2)
	}
}

func TestTheFolderMustBeAPrivateRealDirectoryOfTheUser(t *testing.T) {
	k := newKit(t, []byte("x"))
	open := privateDir(t)
	if err := os.Chmod(open, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(k.out, link); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(t.TempDir(), "a-file")
	os.WriteFile(file, nil, 0o600)
	for name, out := range map[string]string{
		"open to others": open,
		"a link":         link,
		"a file":         file,
		"missing":        filepath.Join(k.out, "nope"),
		"relative":       "incoming",
		"with ..":        k.out + "/../" + filepath.Base(k.out),
	} {
		a := k.f.Handle(context.Background(), k.request(k.ref, out, 100))
		if a.OK || a.Kind != "usage" {
			t.Errorf("%s: %+v", name, a)
		}
	}
	if k.dl.calls != 0 {
		t.Fatal("nothing is downloaded before the folder is checked")
	}
	if _, err := os.Lstat(filepath.Join(k.out, "content")); err == nil {
		t.Fatal("a file was written through a link")
	}
}

func TestADeclaredLengthOverTheCapIsRefusedWithoutADownload(t *testing.T) {
	k := newKit(t, []byte(strings.Repeat("a", 500)))
	a := k.fetch(499)
	if a.OK || a.Kind != "usage" || k.dl.calls != 0 {
		t.Fatalf("%+v calls %d", a, k.dl.calls)
	}
	k.noContent()
	if a := k.fetch(500); !a.OK {
		t.Fatalf("a file exactly at the cap is taken: %+v", a)
	}
}

func TestAFileLargerThanItsSenderDeclaredIsRefusedAndNotKept(t *testing.T) {
	declared := []byte("small")
	k := newKit(t, declared)
	k.dl.data = []byte(strings.Repeat("b", 500)) // the bytes that arrive are not what was declared
	a := k.fetch(100)
	if a.OK || a.Kind != "usage" {
		t.Fatalf("%+v", a)
	}
	k.noContent()
}

func TestTheCapIsCountedWhileTheBytesArriveAndStopsTheDownload(t *testing.T) {
	k := newKit(t, []byte("small"))
	k.dl.err = errors.New("stream cut at https://mmg.whatsapp.net/v/t62/abc")
	k.dl.hook = func(ctx context.Context) {
		lim := limitOf(ctx)
		if lim == nil || lim.max != 100 {
			t.Errorf("the cap did not travel with the context: %+v", lim)
			return
		}
		lim.exceed() // what the bounded transport does when the body passes the cap
	}
	a := k.fetch(100)
	if a.OK || a.Kind != "usage" || strings.Contains(a.Reason, "whatsapp.net") {
		t.Fatalf("%+v", a)
	}
	k.noContent()
}

func TestTheCapNeverPassesWhatTheProgramCanHoldInMemory(t *testing.T) {
	k := newKit(t, []byte("small"))
	var seen int64
	k.dl.hook = func(ctx context.Context) { seen = limitOf(ctx).max }
	k.fetch(1 << 40)
	if seen != maxAttachment {
		t.Fatalf("the cap was %d", seen)
	}
	k2 := newKit(t, []byte("tiny"))
	huge := docFor([]byte("tiny"))
	huge.FileLength = ptr(uint64(maxAttachment + 1))
	ref := k2.refs.add("huge", huge)
	if a := k2.f.Handle(context.Background(), k2.request(ref, k2.out, 1<<40)); a.Kind != "usage" || k2.dl.calls != 0 {
		t.Fatalf("%+v", a)
	}
}

func TestADownloadThatDoesNotMatchTheDeclaredHashIsNotKept(t *testing.T) {
	k := newKit(t, []byte("what the sender hashed"))
	k.dl.data = []byte("what arrived instead!!")
	a := k.fetch(100)
	if a.OK || a.Kind != "failed" {
		t.Fatalf("%+v", a)
	}
	k.noContent()
}

func TestAMessageWithoutAHashCannotBeCheckedAndIsNotDownloaded(t *testing.T) {
	k := newKit(t, []byte("x"))
	noHash := docFor([]byte("x"))
	noHash.FileSHA256 = nil
	ref := k.refs.add("nohash", noHash)
	a := k.f.Handle(context.Background(), k.request(ref, k.out, 100))
	if a.OK || a.Kind != "failed" || k.dl.calls != 0 {
		t.Fatalf("%+v", a)
	}
}

func TestAMediumWhatsAppNoLongerServesIsGone(t *testing.T) {
	for _, err := range []error{
		fmt.Errorf("wrapped: %w", whatsmeow.ErrMediaDownloadFailedWith404),
		whatsmeow.ErrMediaDownloadFailedWith410,
		whatsmeow.ErrMediaDownloadFailedWith403,
		whatsmeow.ErrNoURLPresent,
		whatsmeow.DownloadHTTPError{Response: &http.Response{StatusCode: 404}},
	} {
		k := newKit(t, []byte("x"))
		k.dl.err = err
		if a := k.fetch(100); a.OK || a.Kind != "gone" {
			t.Errorf("%v: %+v", err, a)
		}
		k.noContent()
	}
}

func TestOtherFailuresAreFailedWithASentenceAndNoLibraryText(t *testing.T) {
	leak := errors.New("Get \"https://mmg.whatsapp.net/v/t62/abc?hash=QUJD\": dial tcp 5511900000000: " + secretName)
	for name, err := range map[string]error{
		"a network error": leak,
		"not connected":   whatsmeow.ErrNotConnected,
		"a timeout":       fmt.Errorf("download: %w", context.DeadlineExceeded),
		"a bad hmac":      whatsmeow.ErrInvalidMediaHMAC,
	} {
		k := newKit(t, []byte("x"))
		k.dl.err = err
		a := k.fetch(100)
		if a.OK || a.Kind != "failed" || a.Reason == "" {
			t.Errorf("%s: %+v", name, a)
		}
		for _, bad := range []string{"whatsapp.net", "hash=", "5511900000000", secretName, "dial tcp"} {
			if strings.Contains(a.Reason, bad) {
				t.Errorf("%s: %q in %q", name, bad, a.Reason)
			}
		}
		k.noContent()
	}
}

func TestAFetchHasATimeoutOfItsOwn(t *testing.T) {
	k := newKit(t, []byte("x"))
	k.f.timeout = 20 * time.Millisecond
	k.dl.hook = func(ctx context.Context) {
		<-ctx.Done()
		k.dl.err = ctx.Err()
	}
	a := k.fetch(100)
	if a.OK || a.Kind != "failed" || !strings.Contains(a.Reason, "in time") {
		t.Fatalf("%+v", a)
	}
}

func TestAnExistingContentFileIsNeverReplaced(t *testing.T) {
	data := []byte("new bytes")
	k := newKit(t, data)
	path := filepath.Join(k.out, "content")
	if err := os.WriteFile(path, []byte("kept"), 0o600); err != nil {
		t.Fatal(err)
	}
	a := k.fetch(100)
	if a.OK || a.Kind != "failed" {
		t.Fatalf("%+v", a)
	}
	if got, _ := os.ReadFile(path); string(got) != "kept" {
		t.Fatal("the file was replaced")
	}
}

func TestALinkPlantedAsContentIsNotFollowed(t *testing.T) {
	k := newKit(t, []byte("new bytes"))
	target := filepath.Join(t.TempDir(), "target")
	os.WriteFile(target, []byte("untouched"), 0o600)
	if err := os.Symlink(target, filepath.Join(k.out, "content")); err != nil {
		t.Fatal(err)
	}
	a := k.fetch(100)
	if a.OK {
		t.Fatalf("%+v", a)
	}
	if got, _ := os.ReadFile(target); string(got) != "untouched" {
		t.Fatal("the link was followed")
	}
}

func TestAFetchLogsNeitherTheNameNorTheReferenceNorTheAddress(t *testing.T) {
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	saved := os.Stderr
	os.Stderr = writer
	defer func() { os.Stderr = saved }()

	for _, e := range []error{errors.New("failed " + secretName + " https://mmg.whatsapp.net/v/t62/abc"), context.DeadlineExceeded, whatsmeow.ErrNotConnected} {
		k := newKit(t, []byte("x"))
		k.dl.err = e
		k.fetch(100)
	}
	writer.Close()
	os.Stderr = saved
	buf := make([]byte, 1<<16)
	n, _ := reader.Read(buf)
	logged := string(buf[:n])
	for _, bad := range []string{secretName, "whatsapp.net", "mmg", "/v/t62", "Payroll"} {
		if strings.Contains(logged, bad) {
			t.Fatalf("%q in the log: %q", bad, logged)
		}
	}
	if !strings.Contains(logged, "a download") {
		t.Fatalf("the failure class is logged: %q", logged)
	}
}

func TestTheLibraryLogLineNamesNoAddressOfAFile(t *testing.T) {
	line := redact(`Failed to download media due to network error: Get "https://mmg.whatsapp.net/v/t62.7119-24/abc_def?ccb=11&hash=QUJD": EOF, retrying in 1s`)
	if strings.Contains(line, "mmg") || strings.Contains(line, "hash=") || !strings.Contains(line, "<url>") || !strings.Contains(line, "retrying in 1s") {
		t.Fatalf("%q", line)
	}
}

func TestTheAnswersAreTheLinesTheBridgeChecks(t *testing.T) {
	// the same files providers/messenger/tests/test_whatsapp.py hands to the bridge's own checks
	data := []byte("%PDF-1.7 plan")
	k := newKit(t, data)
	check := func(a Answer, golden string) {
		t.Helper()
		line, err := Line(a)
		if err != nil {
			t.Fatal(err)
		}
		want, err := os.ReadFile("testdata/" + golden)
		if err != nil {
			t.Fatal(err)
		}
		var gotMap, wantMap map[string]any
		if json.Unmarshal(line, &gotMap) != nil || json.Unmarshal(want, &wantMap) != nil || !reflect.DeepEqual(gotMap, wantMap) {
			t.Fatalf("%s differs from testdata/%s\n got %s\nwant %s", golden, golden, line, want)
		}
	}
	check(k.fetch(1<<20), "fetch_ok.json")
	check(k.f.Handle(context.Background(), k.request(strings.Repeat("e", 32), k.out, 100)), "fetch_gone.json")
}

func TestTheProviderScriptAndTheProgramAgreeOnTheCeiling(t *testing.T) {
	if maxAttachment != 104857600 {
		t.Fatalf("whatsapp.py declares max_attachment_bytes 104857600; the program holds %d", maxAttachment)
	}
}
