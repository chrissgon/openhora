package main

import (
	"context"
	"testing"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

const (
	person = "5511900000000"
	lidOf  = "1234567890123"
)

func pn(user string) types.JID  { return types.NewJID(user, types.DefaultUserServer) }
func lid(user string) types.JID { return types.NewJID(user, types.HiddenUserServer) }

func textEvent(chat, sender types.JID, text string) *events.Message {
	return &events.Message{
		Info: types.MessageInfo{
			MessageSource: types.MessageSource{Chat: chat, Sender: sender},
			ID:            "3EB0AAAA0001",
		},
		Message: &waE2E.Message{Conversation: ptr(text)},
	}
}

func noResolver(context.Context, types.JID) (types.JID, bool) { return types.EmptyJID, false }

func TestAPlainTextOneToOneMessageIsAnUpdateWithTheSenderDigits(t *testing.T) {
	evt := textEvent(pn(person), pn(person), "/pending")
	u, why := inbound(context.Background(), evt, noResolver)
	if u == nil || why != dropNone {
		t.Fatalf("dropped: %q", why)
	}
	if u.Sender != person || u.Chat != person || !u.Private || u.Text == nil || *u.Text != "/pending" || u.UpdateID != "3EB0AAAA0001" {
		t.Fatalf("%+v", u)
	}
	if u.Action != nil || u.ActionRef != nil || u.ReplyTo != nil {
		t.Fatalf("no buttons and no quote: %+v", u)
	}
}

func TestTheSenderMayCarryADevicePart(t *testing.T) {
	sender := types.NewADJID(person, 0, 7) // 5511900000000:7@s.whatsapp.net
	u, why := inbound(context.Background(), textEvent(pn(person), sender, "hi"), noResolver)
	if u == nil || u.Sender != person || u.Chat != person {
		t.Fatalf("dropped %q", why)
	}
}

func TestAnExtendedTextMessageCarriesTheQuotedMessageIdAsReplyTo(t *testing.T) {
	evt := textEvent(pn(person), pn(person), "")
	evt.Message = &waE2E.Message{ExtendedTextMessage: &waE2E.ExtendedTextMessage{
		Text:        ptr("approve it"),
		ContextInfo: &waE2E.ContextInfo{StanzaID: ptr("3EB0CARD0001")},
	}}
	u, _ := inbound(context.Background(), evt, noResolver)
	if u == nil || u.Text == nil || *u.Text != "approve it" || u.ReplyTo == nil || *u.ReplyTo != "3EB0CARD0001" {
		t.Fatalf("%+v", u)
	}
	evt.Message.ExtendedTextMessage.ContextInfo = nil
	u, _ = inbound(context.Background(), evt, noResolver)
	if u == nil || u.ReplyTo != nil {
		t.Fatalf("no quote means no reply_to: %+v", u)
	}
}

func TestALIDChatIsResolvedByTheMessageAlternativeAddressThenByTheStore(t *testing.T) {
	evt := textEvent(lid(lidOf), types.NewADJID(lidOf, 0, 3), "hello")
	evt.Info.Sender.Server = types.HiddenUserServer
	evt.Info.SenderAlt = pn(person)
	u, why := inbound(context.Background(), evt, noResolver)
	if u == nil || u.Sender != person || u.Chat != person {
		t.Fatalf("alternative address not used: %q", why)
	}

	evt.Info.SenderAlt = types.EmptyJID
	asked := 0
	store := func(_ context.Context, l types.JID) (types.JID, bool) {
		asked++
		if l.User == lidOf && l.Server == types.HiddenUserServer {
			return pn(person), true
		}
		return types.EmptyJID, false
	}
	u, why = inbound(context.Background(), evt, store)
	if u == nil || u.Sender != person || asked != 1 {
		t.Fatalf("store not used: %q asked %d", why, asked)
	}
}

func TestAnUnresolvedLIDIsDroppedAndNamedAsSuch(t *testing.T) {
	evt := textEvent(lid(lidOf), lid(lidOf), "hello")
	u, why := inbound(context.Background(), evt, noResolver)
	if u != nil || why != dropUnresolved {
		t.Fatalf("%+v %q", u, why)
	}
	u, why = inbound(context.Background(), evt, nil)
	if u != nil || why != dropUnresolved {
		t.Fatalf("nil resolver: %+v %q", u, why)
	}
	// a resolver that answers with something that is not a phone number address does not help
	bad := func(context.Context, types.JID) (types.JID, bool) { return lid("999"), true }
	if u, _ := inbound(context.Background(), evt, bad); u != nil {
		t.Fatal("a LID answer is not a phone number")
	}
}

func TestEverythingElseIsIgnored(t *testing.T) {
	ctx := context.Background()
	mutate := func(f func(*events.Message)) *events.Message {
		e := textEvent(pn(person), pn(person), "x")
		f(e)
		return e
	}
	cases := map[string]*events.Message{
		"from this device": mutate(func(e *events.Message) { e.Info.IsFromMe = true }),
		"group flag":       mutate(func(e *events.Message) { e.Info.IsGroup = true }),
		"group chat": mutate(func(e *events.Message) {
			e.Info.Chat = types.NewJID("120363000000000000", types.GroupServer)
		}),
		"broadcast list": mutate(func(e *events.Message) {
			e.Info.Chat = types.NewJID("1700000000", types.BroadcastServer)
		}),
		"status": mutate(func(e *events.Message) { e.Info.Chat = types.StatusBroadcastJID }),
		"newsletter": mutate(func(e *events.Message) {
			e.Info.Chat = types.NewJID("120363111111111111", types.NewsletterServer)
			e.Info.Sender = e.Info.Chat
		}),
		"sender is not the chat": mutate(func(e *events.Message) { e.Info.Sender = pn("5511911111111") }),
		"empty chat user":        mutate(func(e *events.Message) { e.Info.Chat = pn(""); e.Info.Sender = pn("") }),
		"not digits":             mutate(func(e *events.Message) { e.Info.Chat = pn("abc"); e.Info.Sender = pn("abc") }),
		"edit":                   mutate(func(e *events.Message) { e.IsEdit = true }),
		"image":                  mutate(func(e *events.Message) { e.Message = &waE2E.Message{ImageMessage: &waE2E.ImageMessage{}} }),
		"reaction": mutate(func(e *events.Message) {
			e.Message = &waE2E.Message{ReactionMessage: &waE2E.ReactionMessage{Text: ptr("+1")}}
		}),
		"protocol message": mutate(func(e *events.Message) {
			e.Message = &waE2E.Message{ProtocolMessage: &waE2E.ProtocolMessage{}}
		}),
		"empty text": mutate(func(e *events.Message) { e.Message = &waE2E.Message{Conversation: ptr("")} }),
		"no message": mutate(func(e *events.Message) { e.Message = nil }),
		"no id":      mutate(func(e *events.Message) { e.Info.ID = "" }),
	}
	for name, evt := range cases {
		if u, _ := inbound(ctx, evt, noResolver); u != nil {
			t.Errorf("%s: became an update %+v", name, u)
		}
	}
}

func TestSenderDigitsServesWhoamiForAnyKindOfMessage(t *testing.T) {
	evt := textEvent(pn(person), pn(person), "")
	evt.Message = &waE2E.Message{ImageMessage: &waE2E.ImageMessage{}}
	digits, why := senderDigits(context.Background(), evt.Info, noResolver)
	if digits != person || why != dropNone {
		t.Fatalf("%q %q", digits, why)
	}
	evt.Info.IsGroup = true
	if digits, _ := senderDigits(context.Background(), evt.Info, noResolver); digits != "" {
		t.Fatal("a group member is not a one-to-one sender")
	}
}
