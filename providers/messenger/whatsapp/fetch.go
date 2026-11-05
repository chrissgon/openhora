package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"go.mau.fi/whatsmeow"
)

// The listen op `fetch` of providers/messenger/README.md: the bridge names a reference an update carried, a folder it made and
// a byte cap; the program downloads that medium with the library (the keys never leave this process), checks it, and writes
// it as <folder>/content. A file that is not whole, not what its sender declared or over the cap is never written.

const (
	kindGone     = "gone"
	fetchTimeout = 120 * time.Second // the bridge waits 150 s for the answer
	contentName  = "content"
	// maxAttachment is the most this program holds for one file: the library decrypts a medium in memory. The provider script
	// declares the same number as max_attachment_bytes (a test holds the two equal).
	maxAttachment = 100 << 20

	sentenceGone    = "WhatsApp no longer serves that file"
	sentenceTooBig  = "the file is larger than the cap"
	sentenceBadOut  = "the folder for the file is not a private folder of this user"
	sentenceBadRef  = "a fetch names a reference this program made, a folder and a positive byte cap"
	sentenceNoHash  = "the file cannot be checked: its message carries no hash"
	sentenceBadHash = "the file does not match the hash its message declared, so it was not kept"
)

// Downloader is what a fetch needs from the WhatsApp client: the bytes of a medium, decrypted and checked by the library
// against the hashes of the message. The program's client implements it; the tests use a fake.
type Downloader interface {
	Download(ctx context.Context, msg whatsmeow.DownloadableMessage) ([]byte, error)
}

type clientDownloader struct{ cli *whatsmeow.Client }

func (c clientDownloader) Download(ctx context.Context, msg whatsmeow.DownloadableMessage) ([]byte, error) {
	return c.cli.Download(ctx, msg)
}

type fetcher struct {
	refs    *refTable
	dl      Downloader
	timeout time.Duration
}

func newFetcher(refs *refTable, dl Downloader) *fetcher {
	return &fetcher{refs: refs, dl: dl, timeout: fetchTimeout}
}

// Handle answers one fetch request.
func (f *fetcher) Handle(ctx context.Context, req Request) Answer {
	fail := func(kind, reason string) Answer { return Answer{ID: req.ID, Kind: kind, Reason: reason} }
	if req.Ref == nil || !refRe.MatchString(*req.Ref) || req.Out == nil || req.MaxBytes == nil || *req.MaxBytes < 1 {
		return fail(kindUsage, sentenceBadRef)
	}
	max := *req.MaxBytes
	if max > maxAttachment {
		max = maxAttachment
	}
	msg, ok := f.refs.get(*req.Ref)
	if !ok {
		return fail(kindGone, sentenceGone)
	}
	if declared, ok := msg.(interface{ GetFileLength() uint64 }); ok && declared.GetFileLength() > uint64(max) {
		return fail(kindUsage, sentenceTooBig) // what the sender declared is over the cap: nothing is downloaded
	}
	want := msg.GetFileSHA256()
	if len(want) != sha256.Size {
		return fail(kindFailed, sentenceNoHash)
	}
	root, err := openOut(*req.Out)
	if err != nil {
		return fail(kindUsage, sentenceBadOut)
	}
	defer root.Close()

	ctx, cancel := context.WithTimeout(ctx, f.timeout)
	defer cancel()
	ctx, lim, stop := withByteLimit(ctx, max)
	defer stop()
	data, err := f.dl.Download(ctx, msg)
	switch {
	case lim.exceeded.Load():
		return fail(kindUsage, sentenceTooBig)
	case err != nil:
		return downloadFailure(req.ID, err)
	case int64(len(data)) > max:
		return fail(kindUsage, sentenceTooBig) // the sender declared less than it sent
	}
	sum := sha256.Sum256(data)
	if string(sum[:]) != string(want) {
		return fail(kindFailed, sentenceBadHash)
	}
	if err := writeContent(root, data); err != nil {
		logf("a downloaded file could not be written (%s)", writeClass(err))
		return fail(kindFailed, "the file could not be written into its folder")
	}
	size := int64(len(data))
	return Answer{ID: req.ID, OK: true, Bytes: &size, SHA256: hex.EncodeToString(sum[:])}
}

// downloadFailure is the answer to a download that did not succeed: a sentence, never the library's error text (it carries an address).
func downloadFailure(id []byte, err error) Answer {
	switch {
	case errors.Is(err, whatsmeow.ErrMediaDownloadFailedWith403), errors.Is(err, whatsmeow.ErrMediaDownloadFailedWith404),
		errors.Is(err, whatsmeow.ErrMediaDownloadFailedWith410), errors.Is(err, whatsmeow.ErrNoURLPresent):
		// WhatsApp keeps a medium for a limited time; 403, 404 and 410 are how it says the address no longer serves it
		return Answer{ID: id, Kind: kindGone, Reason: sentenceGone}
	case errors.Is(err, context.DeadlineExceeded):
		logf("a download timed out")
		return Answer{ID: id, Kind: kindFailed, Reason: "WhatsApp did not send the file in time"}
	case errors.Is(err, whatsmeow.ErrNotConnected), errors.Is(err, whatsmeow.ErrNotLoggedIn):
		logf("a download was refused: not connected")
		return Answer{ID: id, Kind: kindFailed, Reason: "WhatsApp is not connected right now"}
	}
	logf("a download failed")
	return Answer{ID: id, Kind: kindFailed, Reason: "WhatsApp could not deliver the file"}
}

// openOut opens the folder the bridge made as a root that no path can leave. The folder must be a real directory (not a link)
// of this user with no access for the group or others; the root is checked to be the very directory that was looked at.
func openOut(out string) (*os.Root, error) {
	if !filepath.IsAbs(out) || filepath.Clean(out) != out {
		return nil, os.ErrInvalid
	}
	before, err := os.Lstat(out)
	if err != nil || !before.IsDir() || before.Mode().Perm()&0o077 != 0 {
		return nil, os.ErrInvalid
	}
	if st, ok := before.Sys().(*syscall.Stat_t); !ok || int(st.Uid) != os.Getuid() {
		return nil, os.ErrInvalid
	}
	root, err := os.OpenRoot(out)
	if err != nil {
		return nil, err
	}
	dot, err := root.Open(".")
	if err != nil {
		root.Close()
		return nil, err
	}
	after, err := dot.Stat()
	dot.Close()
	if err != nil || !os.SameFile(before, after) {
		root.Close()
		return nil, os.ErrInvalid
	}
	return root, nil
}

// writeContent creates <folder>/content (never replacing a file, never through a link, mode 0600) and writes data into it. A
// file that could not be written whole is removed.
func writeContent(root *os.Root, data []byte) error {
	file, err := root.OpenFile(contentName, os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return err
	}
	_, werr := file.Write(data)
	cerr := file.Close()
	if werr != nil || cerr != nil {
		root.Remove(contentName)
		if werr != nil {
			return werr
		}
		return cerr
	}
	return nil
}

func writeClass(err error) string {
	switch {
	case errors.Is(err, os.ErrExist):
		return "the file exists"
	case errors.Is(err, os.ErrPermission):
		return "permission"
	default:
		return "other"
	}
}
