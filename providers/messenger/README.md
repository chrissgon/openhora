# Messenger providers

An implementation of the class `messenger:<platform>` (`contracts/environment.md`) connects a messaging app to the messaging bridge (`runtime/messaging.py`). The bridge has no model in it: it turns what a person sends into an operation of the operations layer and turns a pending decision into a card. A provider only moves messages. The platform is a parameter, handed to the script as `--platform`; the script declares the platforms it serves on one top-level line, `PLATFORMS = ("<platform>",)`, which `providers/resolve.py` reads as text.

The bridge reaches a provider through `providers/resolve.py` (`call("messenger:<platform>", verb, args)`): the variables `MESSENGER_<PLATFORM>_PROVIDER` then `MESSENGER_PROVIDER` choose among several, and one candidate is chosen on its own. Nothing in the bridge names an implementation.

## The four subcommands

JSON on stdout, diagnostics on stderr, input by flags or files, never a prompt, `--help`. Exit codes: 0 ok, 1 the service failed, 2 usage (also a message beyond the capabilities), 3 not configured (no credential, a credential the service rejects, a webhook set where polling is needed). The credential is read only through `providers/secrets/resolver.py` and never appears in an argument, a log, an output or a traceback.

| Subcommand | Prints |
|------------|--------|
| `capabilities --platform <p>` | `{"max_text": int, "buttons": bool, "max_buttons": int, "max_button_label": int, "lists": bool, "max_list_rows": int, "url_buttons": bool, "reply_context": bool, "documents": bool}` |
| `receive --platform <p> --offset <n> --timeout <s>` | `{"updates": [{"update_id", "sender", "chat", "private": bool, "text": str or null, "action": str or null, "action_ref": str or null, "reply_to": str or null}], "next_offset": n}` |
| `send --platform <p> --chat <id> --message-file <f>` | `{"message_id": str}` |
| `ack --platform <p> --action-ref <ref>` | `{"acked": true}` |

- `receive` waits up to `--timeout` seconds for an update (long polling where the platform has it). `action` is the id of a tapped button, `action_ref` what `ack` needs to acknowledge it, `reply_to` the platform's id of the message the person replied to, `sender` and `chat` strings, `private` true for a chat between the bot and one person. An update that is neither a text nor a tapped button is not returned, and `next_offset` still moves past it.
- `send` reads the neutral message from the file: `{"text": str, "actions": [{"id": str, "label": str}], "link": {"label", "url"} | null, "document": {"name", "text"} | null}`. The provider renders it with the means of its platform and prints the id of the message that carries the text (a document is sent after it, as a reply to it). The text is plain text: never a mode that reads markup, because text from a project is text. The provider refuses (exit 2) a message beyond its capabilities; the bridge never sends one, because it reads `capabilities` first and folds what does not fit into typed-command lines (`Send /approve 12`).
- `ack` acknowledges a tapped button where the platform needs it.

`send` has no `--confirmed` and no idempotency key, which `providers/CONTRACT.md` asks of other verbs that send: the bridge is the only caller, sends only to a chat of the project's accepted `messaging.senders` list, and keeps its own record (the ledger of `runtime/messaging_ledger.py`) of what it sent.

## Adding a platform

Add one file, `providers/messenger/<impl>.py`, that declares `PLATFORMS` and implements the four subcommands as above, and register its credential in `providers/secrets/resolver.py` and `contracts/secrets.md`. Nothing in the bridge changes: the platform's name goes in `runtime.json` (`messaging.senders.<platform>`) and on the bridge's `--platform` flag. Tests are offline, in `providers/messenger/tests/`, with the network patched out.

## Telegram

`telegram.py` serves `telegram` with the Bot API over HTTPS and the standard library: `getUpdates` long polling (never a webhook; a `409` is reported with the sentence that tells the person to remove the webhook), `sendMessage` with an inline keyboard (the action ids are the buttons' `callback_data`, at most 64 bytes), a URL button for the link, `sendDocument` for a document, `answerCallbackQuery` for `ack`. The token is the secret `MESSENGER_TELEGRAM_BOT_TOKEN` (store username `messenger-telegram`): a bot created for the person, used only by this bridge. Telegram carries the token in the request path, so every error is built from the class of the exception, the HTTP status and the service's own description, with anything shaped like a token removed. A chat with a bot is not end-to-end encrypted: what the person writes and every notice that carries text passes Telegram's servers.
