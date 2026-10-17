package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
)

const (
	sendTimeout = 50 * time.Second // the bridge waits 60 s for an answer
	maxDocument = 900_000          // bytes of a document's text: it travels inside one protocol line
	maxDocName  = 100
	// phonePattern is the one shape of a phone number in digits (country code, no plus sign, 6 to 15 digits) that the
	// inbound filter, the send validation and the pair command all use.
	phonePattern  = `^[1-9][0-9]{5,14}$`
	kindUsage     = "usage"
	kindFailed    = "failed"
	sentenceChat  = "chat must be a phone number as digits with the country code and no plus sign"
	sentenceMedia = "whatsapp has no buttons and no link buttons: the message must carry no actions and no link"
)

var chatRe = regexp.MustCompile(phonePattern)

// Neutral is the platform-neutral message of providers/messenger/README.md.
type Neutral struct {
	Text    *string `json:"text"`
	Actions []struct {
		ID    string `json:"id"`
		Label string `json:"label"`
	} `json:"actions"`
	Link     json.RawMessage `json:"link"`
	Document *struct {
		Name *string `json:"name"`
		Text *string `json:"text"`
	} `json:"document"`
}

// Request is one line the bridge writes on standard input.
type Request struct {
	ID      json.RawMessage `json:"id"`
	Op      string          `json:"op"`
	Chat    *string         `json:"chat"`
	Message *Neutral        `json:"message"`
}

// Answer is the provider's answer to a request.
type Answer struct {
	ID        json.RawMessage `json:"id"`
	OK        bool            `json:"ok"`
	MessageID string          `json:"message_id,omitempty"`
	// DocumentFailed is true when the text went out and the document that was to follow it did not: the send is still ok (the
	// text must not be sent twice), and the bridge reads this to know that the whole text was not delivered.
	DocumentFailed bool   `json:"document_failed,omitempty"`
	Kind           string `json:"kind,omitempty"`
	Reason         string `json:"reason,omitempty"`
}

// Sender is what a send needs from the WhatsApp client. The program's client implements it; the tests use a fake.
type Sender interface {
	SendText(ctx context.Context, to types.JID, text string) (string, error)
	SendDocument(ctx context.Context, to types.JID, name, mime string, data []byte) (string, error)
}

var idRe = regexp.MustCompile(`^[0-9]{1,18}$`)

// ParseRequest decodes one line. When the line has no usable id there is nobody to answer: ok is false.
func ParseRequest(line []byte) (req Request, answer *Answer, ok bool) {
	dec := json.NewDecoder(bytes.NewReader(line))
	var probe struct {
		ID json.RawMessage `json:"id"`
	}
	if err := json.Unmarshal(line, &probe); err != nil || !idRe.Match(probe.ID) {
		return Request{}, nil, false
	}
	if err := dec.Decode(&req); err != nil {
		return req, &Answer{ID: probe.ID, Kind: kindUsage, Reason: "the request is not a valid send request"}, true
	}
	req.ID = probe.ID
	return req, nil, true
}

// document is a checked document of a request.
type document struct {
	name, mime string
	data       []byte
}

// Validate checks the request. It returns the text (rendered, possibly empty), the document or nil, and an answer when the
// request does not fit (kind usage).
func Validate(req Request) (to types.JID, text string, doc *document, bad *Answer) {
	usage := func(reason string) *Answer { return &Answer{ID: req.ID, Kind: kindUsage, Reason: reason} }
	if req.Op != "send" {
		return to, "", nil, usage("the only request is send")
	}
	if req.Chat == nil || !chatRe.MatchString(*req.Chat) {
		return to, "", nil, usage(sentenceChat)
	}
	m := req.Message
	if m == nil || m.Text == nil {
		return to, "", nil, usage("the message needs a text")
	}
	if len(m.Actions) > 0 || (len(m.Link) > 0 && string(m.Link) != "null") {
		return to, "", nil, usage(sentenceMedia)
	}
	if !utf8.ValidString(*m.Text) {
		return to, "", nil, usage("the text is not valid UTF-8")
	}
	if m.Document != nil {
		d := m.Document
		if d.Name == nil || d.Text == nil || *d.Name == "" || len(*d.Text) > maxDocument || !utf8.ValidString(*d.Text) {
			return to, "", nil, usage("the document needs a name and a text of at most 900000 bytes")
		}
		doc = &document{name: documentName(*d.Name), mime: documentMime(*d.Name), data: []byte(*d.Text)}
	}
	if strings.TrimSpace(*m.Text) == "" && doc == nil {
		return to, "", nil, usage("the message has nothing to send")
	}
	if strings.TrimSpace(*m.Text) != "" {
		text = renderWhatsApp(*m.Text)
	}
	return types.NewJID(*req.Chat, types.DefaultUserServer), text, doc, nil
}

// documentName keeps the name a person sees: no path separators, no control characters, at most 100 characters.
func documentName(name string) string {
	var b strings.Builder
	for _, r := range name {
		switch {
		case r == '/' || r == '\\' || unicode.IsControl(r):
			b.WriteRune('_')
		default:
			b.WriteRune(r)
		}
	}
	out := strings.TrimSpace(b.String())
	if utf8.RuneCountInString(out) > maxDocName {
		out = string([]rune(out)[:maxDocName])
	}
	if out == "" {
		out = "document.txt"
	}
	return out
}

func documentMime(name string) string {
	lower := strings.ToLower(name)
	if strings.HasSuffix(lower, ".md") || strings.HasSuffix(lower, ".markdown") {
		return "text/markdown"
	}
	return "text/plain"
}

// Handle sends one request and returns its answer. A failure is a sentence, never the library's error text (it can name a
// number).
func Handle(ctx context.Context, s Sender, req Request) Answer {
	to, text, doc, bad := Validate(req)
	if bad != nil {
		return *bad
	}
	ctx, cancel := context.WithTimeout(ctx, sendTimeout)
	defer cancel()
	messageID := ""
	documentFailed := false
	if text != "" {
		id, err := s.SendText(ctx, to, text)
		if err != nil {
			return Answer{ID: req.ID, Kind: kindFailed, Reason: failureSentence(err)}
		}
		messageID = id
	}
	if doc != nil {
		id, err := s.SendDocument(ctx, to, doc.name, doc.mime, doc.data)
		if err != nil {
			if messageID == "" {
				return Answer{ID: req.ID, Kind: kindFailed, Reason: failureSentence(err)}
			}
			logf("a document could not be sent after its text (%s)", failureClass(err))
			documentFailed = true
		} else if messageID == "" {
			messageID = id
		}
	}
	return Answer{ID: req.ID, OK: true, MessageID: messageID, DocumentFailed: documentFailed}
}

func failureClass(err error) string {
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return "timeout"
	case errors.Is(err, whatsmeow.ErrNotConnected), errors.Is(err, whatsmeow.ErrNotLoggedIn):
		return "not connected"
	default:
		return "refused"
	}
}

func failureSentence(err error) string {
	switch failureClass(err) {
	case "timeout":
		return "WhatsApp did not answer in time"
	case "not connected":
		return "WhatsApp is not connected right now; the bridge sends the card again after the reconnection"
	default:
		return "WhatsApp could not deliver the message; for a number that has never written to the bridge's number there is no conversation yet, so write to it from that number first"
	}
}

func ptr[T any](v T) *T { return &v }

// clientSender sends through a connected whatsmeow client. No link preview is built (no MatchedText, no thumbnail) and no
// mention is ever set (no ContextInfo at all).
type clientSender struct{ cli *whatsmeow.Client }

// textMessage is a plain text message: an extended text message with no context (no quote, so no mention is possible) and
// none of the fields a link preview is made of.
func textMessage(text string) *waE2E.Message {
	return &waE2E.Message{ExtendedTextMessage: &waE2E.ExtendedTextMessage{Text: ptr(text)}}
}

func documentMessage(up whatsmeow.UploadResponse, name, mime string) *waE2E.Message {
	return &waE2E.Message{DocumentMessage: &waE2E.DocumentMessage{
		URL:           ptr(up.URL),
		DirectPath:    ptr(up.DirectPath),
		MediaKey:      up.MediaKey,
		Mimetype:      ptr(mime),
		FileEncSHA256: up.FileEncSHA256,
		FileSHA256:    up.FileSHA256,
		FileLength:    ptr(up.FileLength),
		FileName:      ptr(name),
		Title:         ptr(name),
	}}
}

func (c clientSender) SendText(ctx context.Context, to types.JID, text string) (string, error) {
	resp, err := c.cli.SendMessage(ctx, to, textMessage(text))
	if err != nil {
		return "", err
	}
	return resp.ID, nil
}

func (c clientSender) SendDocument(ctx context.Context, to types.JID, name, mime string, data []byte) (string, error) {
	up, err := c.cli.Upload(ctx, data, whatsmeow.MediaDocument)
	if err != nil {
		return "", err
	}
	resp, err := c.cli.SendMessage(ctx, to, documentMessage(up, name, mime))
	if err != nil {
		return "", err
	}
	return resp.ID, nil
}
