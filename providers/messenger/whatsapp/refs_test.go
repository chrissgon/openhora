package main

import (
	"encoding/hex"
	"fmt"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waE2E"
)

var testKey = []byte("0123456789abcdef0123456789abcdef")

func sampleDoc() *waE2E.DocumentMessage {
	return &waE2E.DocumentMessage{
		URL:        ptr("https://mmg.whatsapp.net/v/t62.7119-24/secret-path"),
		DirectPath: ptr("/v/t62.7119-24/secret-path"),
		MediaKey:   testKey,
		FileName:   ptr("Q3 budget.pdf"),
	}
}

func TestARefIsRandomHexThatCarriesNeitherTheMediaKeyNorTheAddress(t *testing.T) {
	table := newRefTable()
	a := table.add("o", "k1", sampleDoc())
	b := table.add("o", "k2", sampleDoc())
	if !refRe.MatchString(a) || !refRe.MatchString(b) || a == b {
		t.Fatalf("%q %q", a, b)
	}
	for _, ref := range []string{a, b} {
		if strings.Contains(ref, hex.EncodeToString(testKey)[:8]) || strings.Contains(ref, "secret") || strings.Contains(ref, "whatsapp") {
			t.Fatalf("the ref carries something of the message: %q", ref)
		}
	}
	if len(a) > 512 {
		t.Fatal("a ref is at most 512 characters for the bridge")
	}
}

func TestTheSameMessageDeliveredTwiceKeepsItsRef(t *testing.T) {
	table := newRefTable()
	first := table.add("o", "5511900000000:3EB0A:0", sampleDoc())
	again := table.add("o", "5511900000000:3EB0A:0", sampleDoc())
	other := table.add("o", "5511900000000:3EB0B:0", sampleDoc())
	if first != again || first == other {
		t.Fatalf("%q %q %q", first, again, other)
	}
}

func TestARefServesItsMessageAndAnUnknownOneNothing(t *testing.T) {
	table := newRefTable()
	doc := sampleDoc()
	ref := table.add("o", "k", doc)
	got, ok := table.get(ref)
	if !ok || got != doc {
		t.Fatal("the message of a ref")
	}
	if _, ok := table.get(strings.Repeat("0", 32)); ok {
		t.Fatal("a ref the table never made")
	}
	if _, ok := table.get(""); ok {
		t.Fatal("an empty ref")
	}
}

func TestOneSenderHoldsAtMostTenAndLosesItsOwnOldest(t *testing.T) {
	table := newRefTable()
	var refs []string
	for i := 0; i < maxRefsPerSender+3; i++ {
		refs = append(refs, table.add("o", fmt.Sprintf("k%d", i), sampleDoc()))
	}
	for i, ref := range refs {
		_, ok := table.get(ref)
		if want := i >= 3; ok != want {
			t.Fatalf("ref %d: held %v, want %v", i, ok, want)
		}
	}
	// a dropped message delivered again gets a new ref
	if again := table.add("o", "k0", sampleDoc()); again == refs[0] {
		t.Fatal("a dropped ref came back")
	}
}

func TestASenderFloodingStickersNeverEvictsAnotherSendersRef(t *testing.T) {
	table := newRefTable()
	listed := table.add("5511900000000", "5511900000000:3EB0A:0", sampleDoc())
	for i := 0; i < 5*maxRefs; i++ { // a stranger sends far more than the whole table holds
		table.add("5511911111111", fmt.Sprintf("5511911111111:S%d:0", i), sampleDoc())
	}
	if _, ok := table.get(listed); !ok {
		t.Fatal("a stranger's flood evicted a listed sender's ref")
	}
	if got := table.count["5511911111111"]; got != maxRefsPerSender {
		t.Fatalf("the flooding sender holds %d", got)
	}
}

func TestTheTableHoldsAtMostTwoHundredInAllAndDropsTheOldest(t *testing.T) {
	table := newRefTable()
	var refs []string
	for i := 0; i < maxRefs+3; i++ { // one sender each, so only the total bound applies
		refs = append(refs, table.add(fmt.Sprintf("s%d", i), fmt.Sprintf("s%d:m:0", i), sampleDoc()))
	}
	for i, ref := range refs {
		_, ok := table.get(ref)
		if want := i >= 3; ok != want {
			t.Fatalf("ref %d: held %v, want %v", i, ok, want)
		}
	}
	if len(table.byRef) != maxRefs || len(table.order) != maxRefs || len(table.count) != maxRefs {
		t.Fatalf("the indexes disagree: %d %d %d", len(table.byRef), len(table.order), len(table.count))
	}
}

func TestARefExpiresAnHourAfterItWasMade(t *testing.T) {
	table := newRefTable()
	now := time.Date(2026, 10, 17, 12, 0, 0, 0, time.UTC)
	table.now = func() time.Time { return now }
	ref := table.add("o", "k", sampleDoc())
	now = now.Add(refTTL - time.Second)
	if _, ok := table.get(ref); !ok {
		t.Fatal("served until the hour is up")
	}
	now = now.Add(2 * time.Second)
	if _, ok := table.get(ref); ok {
		t.Fatal("an expired ref was served")
	}
	if again := table.add("o", "k", sampleDoc()); again == ref {
		t.Fatal("an expired key must make a new ref")
	}
}
