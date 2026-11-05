package main

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types"
)

type fakeSender struct {
	texts   []string
	docs    []document
	to      []types.JID
	textErr error
	docErr  error
}

func (f *fakeSender) SendText(_ context.Context, to types.JID, text string) (string, error) {
	if f.textErr != nil {
		return "", f.textErr
	}
	f.to = append(f.to, to)
	f.texts = append(f.texts, text)
	return "3EB0TEXT000" + string(rune('0'+len(f.texts))), nil
}

func (f *fakeSender) SendDocument(_ context.Context, to types.JID, name, mime string, data []byte) (string, error) {
	if f.docErr != nil {
		return "", f.docErr
	}
	f.to = append(f.to, to)
	f.docs = append(f.docs, document{name: name, mime: mime, data: data})
	return "3EB0DOC0001", nil
}

func request(t *testing.T, line string) Request {
	t.Helper()
	req, bad, ok := ParseRequest([]byte(line))
	if !ok || bad != nil {
		t.Fatalf("the request did not parse: %v %+v", ok, bad)
	}
	return req
}

func TestASendRequestIsRenderedSentToThePhoneAndAnsweredWithTheMessageId(t *testing.T) {
	f := &fakeSender{}
	req := request(t, `{"id": 7, "op": "send", "chat": "5511900000000", "message": {"text": "# Plan #12\n\n**Approve** it", "actions": [], "link": null, "document": null}}`)
	a := Handle(context.Background(), f, req)
	if !a.OK || a.MessageID != "3EB0TEXT0001" || string(a.ID) != "7" {
		t.Fatalf("%+v", a)
	}
	if len(f.texts) != 1 || f.texts[0] != "*Plan #12*\n\n*Approve* it" || f.to[0] != pn(person) {
		t.Fatalf("%q %v", f.texts, f.to)
	}
	out, _ := Line(a)
	var back map[string]any
	if json.Unmarshal(out, &back); back["ok"] != true || back["message_id"] != "3EB0TEXT0001" || back["id"] != float64(7) {
		t.Fatalf("%s", out)
	}
}

func TestADocumentIsSentAfterTheTextWithItsNameAndMime(t *testing.T) {
	f := &fakeSender{}
	req := request(t, `{"id": 8, "op": "send", "chat": "5511900000000", "message": {"text": "A plan.", "actions": [], "link": null, "document": {"name": "plan-12.md", "text": "# The whole plan"}}}`)
	a := Handle(context.Background(), f, req)
	if !a.OK || a.MessageID != "3EB0TEXT0001" {
		t.Fatalf("%+v", a)
	}
	if len(f.docs) != 1 || f.docs[0].name != "plan-12.md" || f.docs[0].mime != "text/markdown" || string(f.docs[0].data) != "# The whole plan" {
		t.Fatalf("%+v", f.docs)
	}
	txt := request(t, `{"id": 9, "op": "send", "chat": "5511900000000", "message": {"text": "", "document": {"name": "decision-3.txt", "text": "x"}}}`)
	a = Handle(context.Background(), f, txt)
	if !a.OK || a.MessageID != "3EB0DOC0001" || f.docs[1].mime != "text/plain" {
		t.Fatalf("a document alone: %+v %+v", a, f.docs)
	}
}

func TestAFailedDocumentAfterTheTextStillAnswersOkBecauseTheCardWasDelivered(t *testing.T) {
	f := &fakeSender{docErr: errors.New("boom")}
	req := request(t, `{"id": 8, "op": "send", "chat": "5511900000000", "message": {"text": "A plan.", "document": {"name": "p.txt", "text": "x"}}}`)
	a := Handle(context.Background(), f, req)
	if !a.OK || !a.DocumentFailed {
		t.Fatalf("the send is ok and says the document did not go out: %+v", a)
	}
	line, _ := json.Marshal(a)
	if !strings.Contains(string(line), `"document_failed":true`) {
		t.Fatalf("the answer line carries the flag the bridge reads: %s", line)
	}
	ok := Handle(context.Background(), &fakeSender{}, req)
	if !ok.OK || ok.DocumentFailed {
		t.Fatalf("a document that arrived is not flagged: %+v", ok)
	}
	if line, _ := json.Marshal(ok); strings.Contains(string(line), "document_failed") {
		t.Fatalf("an answer without a failure does not mention it: %s", line)
	}
}

func TestRequestsThatDoNotFitAnswerUsageAndSendNothing(t *testing.T) {
	bad := map[string]string{
		"unknown op":       `{"id": 1, "op": "ack", "chat": "5511900000000", "message": {"text": "x"}}`,
		"no chat":          `{"id": 1, "op": "send", "message": {"text": "x"}}`,
		"chat with plus":   `{"id": 1, "op": "send", "chat": "+5511900000000", "message": {"text": "x"}}`,
		"chat with zero":   `{"id": 1, "op": "send", "chat": "05511900000000", "message": {"text": "x"}}`,
		"chat too short":   `{"id": 1, "op": "send", "chat": "12345", "message": {"text": "x"}}`,
		"chat too long":    `{"id": 1, "op": "send", "chat": "1234567890123456", "message": {"text": "x"}}`,
		"a group id":       `{"id": 1, "op": "send", "chat": "120363000000000000@g.us", "message": {"text": "x"}}`,
		"no message":       `{"id": 1, "op": "send", "chat": "5511900000000"}`,
		"no text":          `{"id": 1, "op": "send", "chat": "5511900000000", "message": {}}`,
		"empty":            `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "   "}}`,
		"actions":          `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x", "actions": [{"id": "a", "label": "A"}]}}`,
		"link":             `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x", "link": {"label": "Open", "url": "https://example.com"}}}`,
		"text not string":  `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": 5}}`,
		"document no name": `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x", "document": {"text": "y"}}}`,
		"document too big": `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x", "document": {"name": "a.txt", "text": "` + strings.Repeat("y", maxDocument+1) + `"}}}`,
		"document array":   `{"id": 1, "op": "send", "chat": "5511900000000", "message": {"text": "x", "document": [1]}}`,
	}
	for name, line := range bad {
		f := &fakeSender{}
		req, answer, ok := ParseRequest([]byte(line))
		if !ok {
			t.Errorf("%s: no id was found", name)
			continue
		}
		if answer == nil {
			a := Handle(context.Background(), f, req)
			answer = &a
		}
		if answer.OK || answer.Kind != kindUsage || answer.Reason == "" || string(answer.ID) != "1" {
			t.Errorf("%s: %+v", name, answer)
		}
		if len(f.texts)+len(f.docs) != 0 {
			t.Errorf("%s: something was sent", name)
		}
	}
}

func TestALineWithoutAUsableIdHasNobodyToAnswer(t *testing.T) {
	for _, line := range []string{`not json`, `{}`, `{"id": "x"}`, `{"id": 1.5}`, `{"id": -1}`, `[1]`, `{"id": null}`} {
		if _, _, ok := ParseRequest([]byte(line)); ok {
			t.Errorf("%s: found an id", line)
		}
	}
}

func TestSendFailuresAreSentencesAndNeverTheLibrariesText(t *testing.T) {
	secret := "5511900000000@lid: no LID found"
	cases := map[error]string{
		context.DeadlineExceeded:        "did not answer in time",
		whatsmeow.ErrNotConnected:       "not connected",
		errors.New("failed: " + secret): "could not deliver",
	}
	for err, want := range cases {
		f := &fakeSender{textErr: err}
		a := Handle(context.Background(), f, request(t, `{"id": 2, "op": "send", "chat": "5511900000000", "message": {"text": "x"}}`))
		if a.OK || a.Kind != kindFailed || !strings.Contains(a.Reason, want) || strings.Contains(a.Reason, "5511900000000") || strings.Contains(a.Reason, "LID") {
			t.Errorf("%v: %+v", err, a)
		}
	}
}

func TestTheRenderedTextOfARequestIsCutAt4096(t *testing.T) {
	f := &fakeSender{}
	text := strings.Repeat("[a](https://example.com/aaaaaaaa) ", 300)
	line, _ := json.Marshal(map[string]any{"id": 3, "op": "send", "chat": person, "message": map[string]any{"text": text}})
	Handle(context.Background(), f, request(t, string(line)))
	if len([]rune(f.texts[0])) > renderLimit || !strings.HasSuffix(f.texts[0], cutNote) {
		t.Fatalf("%d runes", len([]rune(f.texts[0])))
	}
}

func TestDocumentNamesAreCleaned(t *testing.T) {
	if got := documentName("../../etc/passwd\n.txt"); strings.ContainsAny(got, "/\\\n") {
		t.Errorf("%q", got)
	}
	if got := documentName(strings.Repeat("a", 300)); len(got) != maxDocName {
		t.Errorf("length %d", len(got))
	}
	if documentMime("A.MD") != "text/markdown" || documentMime("a.txt") != "text/plain" || documentMime("noext") != "text/plain" {
		t.Error("mime types")
	}
}

func TestMessagesBuiltForWhatsAppHaveNoMentionNoContextAndNoPreview(t *testing.T) {
	m := textMessage("hello @5511911111111")
	x := m.GetExtendedTextMessage()
	if x == nil || x.GetText() != "hello @5511911111111" {
		t.Fatal("text")
	}
	if x.GetContextInfo() != nil || len(x.GetContextInfo().GetMentionedJID()) != 0 {
		t.Error("a mention is possible")
	}
	if x.MatchedText != nil || x.PreviewType != nil || x.JPEGThumbnail != nil || x.Title != nil || x.Description != nil {
		t.Error("a link preview was built")
	}
	d := documentMessage(whatsmeow.UploadResponse{URL: "u", DirectPath: "p", FileLength: 3}, "n.md", "text/markdown").GetDocumentMessage()
	if d.GetFileName() != "n.md" || d.GetMimetype() != "text/markdown" || d.GetContextInfo() != nil {
		t.Errorf("%+v", d)
	}
}
