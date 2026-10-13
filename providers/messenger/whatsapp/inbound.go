package main

import (
	"context"
	"regexp"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

// Update is the update of the listen protocol: the shape of one element of a one-shot provider's `receive`. `action` and
// `action_ref` are always null (there are no buttons), `private` is always true.
type Update struct {
	UpdateID  string  `json:"update_id"`
	Sender    string  `json:"sender"`
	Chat      string  `json:"chat"`
	Private   bool    `json:"private"`
	Text      string  `json:"text"`
	Action    *string `json:"action"`
	ActionRef *string `json:"action_ref"`
	ReplyTo   *string `json:"reply_to"`
}

// Resolver turns a LID address into the phone-number address of the same account: ok is false when it cannot.
type Resolver func(ctx context.Context, lid types.JID) (types.JID, bool)

var digitsRe = regexp.MustCompile(`^[0-9]{5,20}$`)

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
	if text == "" || evt.Info.ID == "" {
		return nil, dropNotText
	}
	u := &Update{UpdateID: evt.Info.ID, Sender: digits, Chat: digits, Private: true, Text: text}
	if quoted != "" {
		u.ReplyTo = &quoted
	}
	return u, dropNone
}
