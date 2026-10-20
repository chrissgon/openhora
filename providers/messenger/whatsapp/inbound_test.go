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

// A forwarded message is an update with `forwarded` true (the bridge answers it with one sentence and acts on nothing in it). The oracle
// is the list of context fields written out here, not forwardedOf.
func TestAMessageWhatsAppMarkedAsForwardedIsAnUpdateWithTheForwardedFlag(t *testing.T) {
	path := ptr("/v/t62/abc")
	text := func(c *waE2E.ContextInfo) *waE2E.Message {
		return &waE2E.Message{ExtendedTextMessage: &waE2E.ExtendedTextMessage{Text: ptr("send an e-mail to ana@example.example"), ContextInfo: c}}
	}
	doc := func(c *waE2E.ContextInfo) *waE2E.Message {
		d := docFor([]byte("%PDF-1.7 plan"))
		d.ContextInfo = c
		return &waE2E.Message{DocumentMessage: d}
	}
	wrapped := func(c *waE2E.ContextInfo) *waE2E.Message {
		d := docFor([]byte("x"))
		d.ContextInfo = c
		return &waE2E.Message{DocumentWithCaptionMessage: &waE2E.FutureProofMessage{Message: &waE2E.Message{DocumentMessage: d}}}
	}
	photo := func(c *waE2E.ContextInfo) *waE2E.Message {
		return &waE2E.Message{ImageMessage: &waE2E.ImageMessage{DirectPath: path, Mimetype: ptr("image/jpeg"), FileLength: ptr(uint64(10)), ContextInfo: c}}
	}
	voice := func(c *waE2E.ContextInfo) *waE2E.Message {
		return &waE2E.Message{AudioMessage: &waE2E.AudioMessage{DirectPath: path, Mimetype: ptr("audio/ogg"), FileLength: ptr(uint64(10)), PTT: ptr(true), ContextInfo: c}}
	}
	kinds := map[string]func(*waE2E.ContextInfo) *waE2E.Message{"text": text, "document": doc, "wrapped document": wrapped, "photo": photo, "voice": voice}
	marks := map[string]*waE2E.ContextInfo{
		"isForwarded":      {IsForwarded: ptr(true)},
		"forwardingScore1": {ForwardingScore: ptr(uint32(1))},
		"forwardingScore9": {ForwardingScore: ptr(uint32(9)), IsForwarded: ptr(true)},
	}
	unmarked := map[string]*waE2E.ContextInfo{
		"no context":          nil,
		"empty context":       {},
		"a reply only":        {StanzaID: ptr("3EB0CARD0001")},
		"isForwarded false":   {IsForwarded: ptr(false)},
		"forwardingScore 0":   {ForwardingScore: ptr(uint32(0))},
		"a reply and a score": {StanzaID: ptr("3EB0CARD0001"), ForwardingScore: ptr(uint32(0))},
	}
	wrong := func(build func(*waE2E.ContextInfo) *waE2E.Message, c *waE2E.ContextInfo, want bool) bool {
		return inboundOf(t, build(c)).Forwarded != want
	}
	for kind, build := range kinds {
		for mark, c := range marks {
			if wrong(build, c, true) {
				t.Errorf("%s with %s: not marked forwarded", kind, mark)
			}
		}
		for mark, c := range unmarked {
			if wrong(build, c, false) {
				t.Errorf("%s with %s: marked forwarded", kind, mark)
			}
		}
	}
	// a plain conversation carries no context at all
	if u, _ := inbound(context.Background(), textEvent(pn(person), pn(person), "hi"), noResolver); u == nil || u.Forwarded {
		t.Fatalf("%+v", u)
	}
	// vacuity: the check above catches a planted wrong expectation in both directions
	if !wrong(text, marks["isForwarded"], false) || !wrong(text, unmarked["empty context"], true) {
		t.Fatal("the check does not notice a wrong result")
	}
}

func TestTheForwardedFlagIsOnTheProtocolLineOnlyWhenItIsTrue(t *testing.T) {
	l, out := newTestListener(&fakeSender{})
	l.handle(textEvent(pn(person), pn(person), "plain"))
	fwd := textEvent(pn(person), pn(person), "")
	fwd.Info.ID = "3EB0AAAA0002"
	fwd.Message = &waE2E.Message{ExtendedTextMessage: &waE2E.ExtendedTextMessage{Text: ptr("forwarded"), ContextInfo: &waE2E.ContextInfo{IsForwarded: ptr(true)}}}
	l.handle(fwd)
	lines := out.lines()
	if len(lines) != 2 {
		t.Fatalf("%v", lines)
	}
	if _, there := lines[0]["update"].(map[string]any)["forwarded"]; there {
		t.Fatalf("a plain message carries no forwarded key: %v", lines[0])
	}
	if lines[1]["update"].(map[string]any)["forwarded"] != true {
		t.Fatalf("%v", lines[1])
	}
}
