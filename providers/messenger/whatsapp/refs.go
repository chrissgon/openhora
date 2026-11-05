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
	maxRefs = 200 // the most references held in all; the oldest is dropped for a new one
	// maxRefsPerSender is the most one sender holds. The list of senders is applied by the bridge, so any one-to-one chat reaches
	// this table, and one sender must never push another's references out.
	maxRefsPerSender = 10
	refTTL           = time.Hour // a reference is served for this long after it was made
)

// refRe is the one shape of a reference this program makes (16 random bytes in lower-case hex).
var refRe = regexp.MustCompile(`^[0-9a-f]{32}$`)

type refEntry struct {
	ref     string
	owner   string
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
	count  map[string]int
}

func newRefTable() *refTable {
	return &refTable{now: time.Now, newRef: randomRef, byRef: map[string]*refEntry{}, byKey: map[string]*refEntry{}, count: map[string]int{}}
}

func randomRef() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("the system random source failed") // crypto/rand does not fail on a working system
	}
	return hex.EncodeToString(b[:])
}

// add keeps msg and returns its reference. The owner is the sender; one owner holds at most maxRefsPerSender references (its own
// oldest goes first), so no sender can evict another's. The key names the message and its place in it (the sender, the message id
// and the index of the file), so that WhatsApp delivering the same message again within the hour (delivery is at least once)
// gives the same reference and the bridge sees one file, not two.
func (t *refTable) add(owner, key string, msg whatsmeow.DownloadableMessage) string {
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	t.purge(now)
	if found, ok := t.byKey[key]; ok {
		return found.ref
	}
	entry := &refEntry{ref: t.newRef(), owner: owner, key: key, msg: msg, expires: now.Add(refTTL)}
	t.byRef[entry.ref] = entry
	t.byKey[key] = entry
	t.order = append(t.order, entry)
	t.count[owner]++
	for t.count[owner] > maxRefsPerSender {
		for _, old := range t.order {
			if old.owner == owner {
				t.drop(old)
				break
			}
		}
	}
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
	if t.count[entry.owner]--; t.count[entry.owner] <= 0 {
		delete(t.count, entry.owner)
	}
	for i, e := range t.order {
		if e == entry {
			t.order = append(t.order[:i], t.order[i+1:]...)
			break
		}
	}
}
