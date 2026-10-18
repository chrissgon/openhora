package main

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func mediaEvent(msg *waE2E.Message) *events.Message {
	evt := textEvent(pn(person), pn(person), "")
	evt.Message = msg
	return evt
}

func inboundOf(t *testing.T, msg *waE2E.Message) *Update {
	t.Helper()
	u, why := inbound(context.Background(), mediaEvent(msg), noResolver)
	if u == nil {
		t.Fatalf("dropped: %q", why)
	}
	return u
}

func TestADocumentBecomesAnAttachmentWithWhatItsMessageDeclared(t *testing.T) {
	doc := docFor([]byte("%PDF-1.7 plan"))
	u := inboundOf(t, &waE2E.Message{DocumentMessage: doc})
	if len(u.Attachments) != 1 || u.Text != nil {
		t.Fatalf("%+v", u)
	}
	a := u.Attachments[0]
	if a.Name == nil || *a.Name != secretName || a.Type == nil || *a.Type != "application/pdf" || a.Size == nil || *a.Size != 13 {
		t.Fatalf("%+v", a)
	}
	if a.Ref != "" || a.msg != doc {
		t.Fatal("the reference is made by the listener, and the message stays inside the process")
	}
}

func TestADocumentSentWithACaptionArrivesInsideAWrapperAndKeepsItsCaption(t *testing.T) {
	doc := docFor([]byte("x"))
	doc.Caption = ptr("@q3-plan")
	doc.ContextInfo = &waE2E.ContextInfo{StanzaID: ptr("3EB0CARD0002")}
	u := inboundOf(t, &waE2E.Message{DocumentWithCaptionMessage: &waE2E.FutureProofMessage{Message: &waE2E.Message{DocumentMessage: doc}}})
	if len(u.Attachments) != 1 || u.Text == nil || *u.Text != "@q3-plan" || u.ReplyTo == nil || *u.ReplyTo != "3EB0CARD0002" {
		t.Fatalf("%+v", u)
	}
}

func TestTheMediaKindsAreNamedByTheirKind(t *testing.T) {
	path := ptr("/v/t62/abc")
	cases := map[string]*waE2E.Message{
		"photo":   {ImageMessage: &waE2E.ImageMessage{DirectPath: path, Mimetype: ptr("image/jpeg"), FileLength: ptr(uint64(10)), Caption: ptr("look")}},
		"video":   {VideoMessage: &waE2E.VideoMessage{DirectPath: path, Mimetype: ptr("video/mp4"), FileLength: ptr(uint64(10))}},
		"audio":   {AudioMessage: &waE2E.AudioMessage{DirectPath: path, Mimetype: ptr("audio/mpeg"), FileLength: ptr(uint64(10))}},
		"voice":   {AudioMessage: &waE2E.AudioMessage{DirectPath: path, PTT: ptr(true), FileLength: ptr(uint64(10))}},
		"sticker": {StickerMessage: &waE2E.StickerMessage{DirectPath: path, FileLength: ptr(uint64(10))}},
	}
	for kind, msg := range cases {
		u := inboundOf(t, msg)
		a := u.Attachments[0]
		if a.Type == nil || *a.Type != kind || a.Name != nil || a.Size == nil || *a.Size != 10 {
			t.Errorf("%s: %+v", kind, a)
		}
	}
	if u := inboundOf(t, cases["photo"]); u.Text == nil || *u.Text != "look" {
		t.Fatal("a photo's caption is the text")
	}
	if u := inboundOf(t, &waE2E.Message{PtvMessage: &waE2E.VideoMessage{DirectPath: path}}); *u.Attachments[0].Type != "video" {
		t.Fatal("a video note is a video")
	}
}

func TestWhatTheSenderWroteIsCutAndCleanedBeforeItReachesTheBridge(t *testing.T) {
	doc := docFor([]byte("x"))
	doc.FileName = ptr("../../etc/pass\x00wd\n" + strings.Repeat("n", 300))
	doc.Mimetype = ptr(strings.Repeat("m", 500))
	a := inboundOf(t, &waE2E.Message{DocumentMessage: doc}).Attachments[0]
	if strings.ContainsAny(*a.Name, "/\\\x00\n") || len([]rune(*a.Name)) > maxDocName || len([]rune(*a.Type)) > maxDeclaredType {
		t.Fatalf("%q %d", *a.Name, len(*a.Type))
	}
}

func TestMissingFactsAreNullNotInvented(t *testing.T) {
	doc := &waE2E.DocumentMessage{DirectPath: ptr("/v/t62/abc")}
	a := inboundOf(t, &waE2E.Message{DocumentMessage: doc}).Attachments[0]
	if a.Name != nil || a.Size != nil || a.Type != nil {
		t.Fatalf("%+v", a)
	}
	doc.Title = ptr("Title only")
	doc.FileLength = ptr(uint64(0))
	a = inboundOf(t, &waE2E.Message{DocumentMessage: doc}).Attachments[0]
	if a.Name == nil || *a.Name != "Title only" || a.Size != nil {
		t.Fatalf("a title names a document with no file name; a length of 0 is unknown: %+v", a)
	}
	doc.FileName = ptr("   ")
	doc.Title = nil
	if a = inboundOf(t, &waE2E.Message{DocumentMessage: doc}).Attachments[0]; a.Name != nil {
		t.Fatal("a blank name is no name")
	}
}

func TestAMediumWithNothingToFetchByIsNotAFile(t *testing.T) {
	for name, msg := range map[string]*waE2E.Message{
		"document": {DocumentMessage: &waE2E.DocumentMessage{FileName: ptr("a.pdf")}},
		"image":    {ImageMessage: &waE2E.ImageMessage{}},
		"wrapper":  {DocumentWithCaptionMessage: &waE2E.FutureProofMessage{}},
	} {
		if u, _ := inbound(context.Background(), mediaEvent(msg), noResolver); u != nil {
			t.Errorf("%s became an update: %+v", name, u)
		}
	}
}

func TestATextMessageStaysAPlainUpdateWithNoAttachmentsKey(t *testing.T) {
	u, _ := inbound(context.Background(), textEvent(pn(person), pn(person), "hello"), noResolver)
	raw, _ := json.Marshal(u)
	var back map[string]any
	json.Unmarshal(raw, &back)
	if _, has := back["attachments"]; has || back["text"] != "hello" {
		t.Fatalf("%s", raw)
	}
}

func TestAFileFromAGroupOrFromThisDeviceIsIgnoredLikeAText(t *testing.T) {
	doc := &waE2E.Message{DocumentMessage: docFor([]byte("x"))}
	group := mediaEvent(doc)
	group.Info.IsGroup = true
	group.Info.Chat = types.NewJID("120363000000000000", types.GroupServer)
	self := mediaEvent(doc)
	self.Info.IsFromMe = true
	edit := mediaEvent(doc)
	edit.IsEdit = true
	for name, evt := range map[string]*events.Message{"group": group, "self": self, "edit": edit} {
		if u, _ := inbound(context.Background(), evt, noResolver); u != nil {
			t.Errorf("%s: %+v", name, u)
		}
	}
}

func TestTheUpdateLineOfADocumentIsTheShapeTheBridgeChecks(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.refs.newRef = func() string { return "0123456789abcdef0123456789abcdef" }
	doc := docFor([]byte("%PDF-1.7 plan"))
	doc.FileName = ptr("Plan Q3 ü.pdf")
	l.handle(mediaEvent(&waE2E.Message{DocumentMessage: doc}))
	lines := out.lines()
	if len(lines) != 1 {
		t.Fatalf("%v", lines)
	}
	golden, err := os.ReadFile("testdata/attachment_update.json")
	if err != nil {
		t.Fatal(err)
	}
	var want map[string]any
	if err := json.Unmarshal(golden, &want); err != nil {
		t.Fatal(err)
	}
	gotRaw, _ := json.Marshal(lines[0])
	wantRaw, _ := json.Marshal(want)
	if string(gotRaw) != string(wantRaw) {
		t.Fatalf("the line differs from testdata/attachment_update.json (providers/messenger/tests/test_whatsapp.py reads it too)\n got %s\nwant %s", gotRaw, wantRaw)
	}
}
