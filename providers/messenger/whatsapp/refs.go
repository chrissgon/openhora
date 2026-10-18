package main

import (
	"crypto/rand"
	"encoding/hex"
	"regexp"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
)

// The table that turns the reference an update carries into the message to download. The reference is random: it carries
// no media key, no address and no part of the message, and means nothing outside this process. The table lives in memory
// only, so a restart of the program makes every earlier reference `gone`, which the bridge answers with "send it again".
const (
	maxRefs = 50        // the most references held; the oldest is dropped for a new one
	refTTL  = time.Hour // a reference is served for this long after it was made
)

// refRe is the one shape of a reference this program makes (16 random bytes in lower-case hex).
var refRe = regexp.MustCompile(`^[0-9a-f]{32}$`)

type refEntry struct {
	ref     string
	key     string
	msg     whatsmeow.DownloadableMessage
	expires time.Time
}

type refTable struct {
	mu     sync.Mutex
	now    func() time.Time
	newRef func() string
	byRef  map[string]*refEntry
	byKey  map[string]*refEntry
	order  []*refEntry // oldest first
}

func newRefTable() *refTable {
	return &refTable{now: time.Now, newRef: randomRef, byRef: map[string]*refEntry{}, byKey: map[string]*refEntry{}}
}

func randomRef() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("the system random source failed") // crypto/rand does not fail on a working system
	}
	return hex.EncodeToString(b[:])
}

// add keeps msg and returns its reference. The key names the message and its place in it (the sender, the message id and the
// index of the file), so that WhatsApp delivering the same message twice (delivery is at least once) gives the same reference
// and the bridge sees one file, not two.
func (t *refTable) add(key string, msg whatsmeow.DownloadableMessage) string {
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	t.purge(now)
	if found, ok := t.byKey[key]; ok {
		return found.ref
	}
	entry := &refEntry{ref: t.newRef(), key: key, msg: msg, expires: now.Add(refTTL)}
	t.byRef[entry.ref] = entry
	t.byKey[key] = entry
	t.order = append(t.order, entry)
	for len(t.order) > maxRefs {
		t.drop(t.order[0])
	}
	return entry.ref
}

// get is the message a reference stands for, or false when the reference is not known, was dropped or has expired.
func (t *refTable) get(ref string) (whatsmeow.DownloadableMessage, bool) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.purge(t.now())
	entry, ok := t.byRef[ref]
	if !ok {
		return nil, false
	}
	return entry.msg, true
}

// purge drops what has expired (the table is in the order of making, so the expired ones are at the front). The caller holds the lock.
func (t *refTable) purge(now time.Time) {
	for len(t.order) > 0 && !now.Before(t.order[0].expires) {
		t.drop(t.order[0])
	}
}

func (t *refTable) drop(entry *refEntry) {
	delete(t.byRef, entry.ref)
	delete(t.byKey, entry.key)
	t.order = t.order[1:]
}
