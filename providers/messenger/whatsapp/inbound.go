package main

import (
	"context"
	"math"
	"regexp"
	"strings"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

// Update is the update of the listen protocol: the shape of one element of a one-shot provider's `receive`. `action` and
// `action_ref` are always null (there are no buttons), `private` is always true.
//
// `text` is null when the message is a file with no caption; `attachments` is there only when the message carries a file.
type Update struct {
	UpdateID    string       `json:"update_id"`
	Sender      string       `json:"sender"`
	Chat        string       `json:"chat"`
	Private     bool         `json:"private"`
	Text        *string      `json:"text"`
	Action      *string      `json:"action"`
	ActionRef   *string      `json:"action_ref"`
	ReplyTo     *string      `json:"reply_to"`
	Attachments []Attachment `json:"attachments,omitempty"`
}

// Attachment is one element of an update's `attachments` (providers/messenger/README.md): the reference the bridge fetches
// the file by, and what the message declared about it. `msg` is the downloadable part of the message; it never leaves the
// process, and the listener turns it into a random Ref (refs.go) before the update is written.
type Attachment struct {
	Ref  string  `json:"ref"`
	Name *string `json:"name"`
	Size *int64  `json:"size"`
	Type *string `json:"type"`

	msg whatsmeow.DownloadableMessage
}

const maxDeclaredType = 100 // a declared media type is cut here; nothing a sender writes is kept whole

// Resolver turns a LID address into the phone-number address of the same account: ok is false when it cannot.
type Resolver func(ctx context.Context, lid types.JID) (types.JID, bool)

var digitsRe = regexp.MustCompile(phonePattern)

// Why an incoming message is not an update. Only the last of them is worth a diagnostic line.
const (
	dropNone       = ""
	dropFromMe     = "from this device"
	dropGroup      = "group, broadcast, status or newsletter"
	dropNotOne     = "not a one-to-one chat of a person"
	dropEdit       = "edit"
	dropNotText    = "not a text message"
	dropUnresolved = "unresolved"
)

// senderDigits is the phone-number digits of the person who wrote a one-to-one chat message, or why the message is not one.
// It looks at the chat and the sender only (not at the kind of message), so `whoami` can use it for any message.
//
// whatsmeow sets Chat to the sender without device (`from.ToNonAD()`) and Sender to the address as received (with its device
// part); both compared by user and server. A LID address is resolved with the message's own alternative address first, then
// with the store.
func senderDigits(ctx context.Context, info types.MessageInfo, resolve Resolver) (string, string) {
	if info.IsFromMe {
		return "", dropFromMe
	}
	if info.IsGroup || info.IsIncomingBroadcast() {
		return "", dropGroup
	}
	chat, sender := info.Chat, info.Sender.ToNonAD()
	if chat.Server != types.DefaultUserServer && chat.Server != types.HiddenUserServer {
		return "", dropGroup
	}
	if chat.User == "" || sender.User != chat.User || sender.Server != chat.Server {
		return "", dropNotOne
	}
	phone := chat
	if chat.Server == types.HiddenUserServer {
		alt := info.SenderAlt.ToNonAD()
		if alt.Server == types.DefaultUserServer && alt.User != "" {
			phone = alt
		} else if resolve != nil {
			found, ok := resolve(ctx, chat)
			if !ok || found.Server != types.DefaultUserServer || found.User == "" {
				return "", dropUnresolved
			}
			phone = found.ToNonAD()
		} else {
			return "", dropUnresolved
		}
	}
	if !digitsRe.MatchString(phone.User) {
		return "", dropNotOne
	}
	return phone.User, dropNone
}

// textOf is the text of a conversation or extended text message, and the id of the message it quotes ("" when none).
func textOf(m *waE2E.Message) (text, quoted string) {
	if m == nil {
		return "", ""
	}
	if t := m.GetConversation(); t != "" {
		return t, ""
	}
	if x := m.GetExtendedTextMessage(); x != nil {
		return x.GetText(), x.GetContextInfo().GetStanzaID()
	}
	return "", ""
}

// mediaOf is the file a message carries, its caption and the id of the message it quotes, or nil when it carries none. A
// document keeps what its message declared (name, media type, length); a photo, a video, an audio file, a voice note and a
// sticker are named by their kind, which is all the bridge needs to refuse them. A message with no download path has nothing
// to fetch by and is not a file. A document sent with a caption arrives inside a wrapper, which is read the same way.
func mediaOf(m *waE2E.Message) (att *Attachment, caption, quoted string) {
	if m == nil {
		return nil, "", ""
	}
	doc := m.GetDocumentMessage()
	if doc == nil {
		doc = m.GetDocumentWithCaptionMessage().GetMessage().GetDocumentMessage()
	}
	switch {
	case doc != nil && doc.GetDirectPath() != "":
		name := doc.GetFileName()
		if name == "" {
			name = doc.GetTitle()
		}
		return fileOf(doc, nameOf(name), doc.GetMimetype(), doc.GetFileLength()), doc.GetCaption(), doc.GetContextInfo().GetStanzaID()
	case m.GetImageMessage().GetDirectPath() != "":
		i := m.GetImageMessage()
		return fileOf(i, nil, "photo", i.GetFileLength()), i.GetCaption(), i.GetContextInfo().GetStanzaID()
	case m.GetVideoMessage().GetDirectPath() != "":
		v := m.GetVideoMessage()
		return fileOf(v, nil, "video", v.GetFileLength()), v.GetCaption(), v.GetContextInfo().GetStanzaID()
	case m.GetPtvMessage().GetDirectPath() != "":
		v := m.GetPtvMessage()
		return fileOf(v, nil, "video", v.GetFileLength()), "", v.GetContextInfo().GetStanzaID()
	case m.GetAudioMessage().GetDirectPath() != "":
		a := m.GetAudioMessage()
		kind := "audio"
		if a.GetPTT() {
			kind = "voice"
		}
		return fileOf(a, nil, kind, a.GetFileLength()), "", a.GetContextInfo().GetStanzaID()
	case m.GetStickerMessage().GetDirectPath() != "":
		s := m.GetStickerMessage()
		return fileOf(s, nil, "sticker", s.GetFileLength()), "", s.GetContextInfo().GetStanzaID()
	}
	return nil, "", ""
}

// fileOf is the attachment for a downloadable part: a declared type cut short, a declared length of 0 as unknown.
func fileOf(msg whatsmeow.DownloadableMessage, name *string, kind string, length uint64) *Attachment {
	a := &Attachment{Name: name, msg: msg}
	if kind != "" {
		if r := []rune(kind); len(r) > maxDeclaredType {
			kind = string(r[:maxDeclaredType])
		}
		a.Type = &kind
	}
	if length > 0 && length <= math.MaxInt64 {
		size := int64(length)
		a.Size = &size
	}
	return a
}

// nameOf is the name a sender gave a file, as a person may be shown it: no path separators, no control characters, at most 100
// characters; nil when there is none.
func nameOf(name string) *string {
	if strings.TrimSpace(name) == "" {
		return nil
	}
	clean := documentName(name)
	return &clean
}

// inbound is the update for an incoming message, or the reason it is dropped. whatsmeow has already unwrapped the
// disappearing-message, view-once and device-sent wrappers into evt.Message; edits, reactions and protocol messages carry
// no text of their own and are ignored.
func inbound(ctx context.Context, evt *events.Message, resolve Resolver) (*Update, string) {
	digits, why := senderDigits(ctx, evt.Info, resolve)
	if why != dropNone {
		return nil, why
	}
	if evt.IsEdit {
		return nil, dropEdit
	}
	text, quoted := textOf(evt.Message)
	var attachments []Attachment
	if text == "" {
		if a, caption, q := mediaOf(evt.Message); a != nil {
			attachments, text, quoted = []Attachment{*a}, caption, q
		}
	}
	if (text == "" && len(attachments) == 0) || evt.Info.ID == "" {
		return nil, dropNotText
	}
	u := &Update{UpdateID: evt.Info.ID, Sender: digits, Chat: digits, Private: true, Attachments: attachments}
	if text != "" {
		u.Text = &text
	}
	if quoted != "" {
		u.ReplyTo = &quoted
	}
	return u, dropNone
}
