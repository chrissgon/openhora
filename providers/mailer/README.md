# Mailer provider (`sender:email`)

The outbox of the task runtime: it sends one e-mail from the machine's one outbox account, over SMTP, to exactly the recipients it is given, once. The runtime calls it only after the person approved the hash of the whole message (`runtime/effect_send.py`, the effect word `send`; `docs/architecture/platform/outputs.md`, "Sending an e-mail"); the verbs and what each prints are in `providers/CONTRACT.md`, "Verbs per class".

| File | What it is |
|------|------------|
| `smtp.py` | The implementation: `send`, `resolve`, `lookup`, `setup` and `--check`. Python 3.9, standard library only (`smtplib`, `imaplib`, `email`). Any mailbox with SMTP, IMAP and a password works; an app password where the host requires one |
| `../_email.py` | Shared code, not an implementation: the form of an address and of a header value, the Message-ID, the rules of the connection and the MIME message. The e-mail channel of the messaging bridge will use it too |
| `tests/` | Offline tests against a fake SMTP server and a fake IMAP server on loopback (`tests/fake_mail.py`); no mail service is called, no credential is real, every address is on `.example` |

## Use

```
python3 providers/mailer/smtp.py setup --from outbox@office.example --smtp-host smtp.office.example --imap-host imap.office.example --sent-folder Sent
uv run --with keyring==25.7.0 keyring set openhora mailer-smtp      # the app password, at a hidden prompt (or export MAILER_SMTP_PASSWORD); spaces in it are dropped (hosts show an app password in groups)
python3 providers/mailer/smtp.py --check                           # logs in to SMTP and IMAP; sends nothing
```

Then name the same address in the project's `docs/workbench/runtime.json`, accept the change, and start the flow (the sender is never an argument; it is the `from` of the outbox):

```
"outbox": {"provider": "auto", "from": "outbox@office.example"}
python3 runtime/cli.py accept-config --project <project> --sha256 <hash>
python3 runtime/cli.py request --project <project> --text "Send Ana her October invoice"
python3 runtime/cli.py route --project <project> --request <request id> --flow send-email --param to=ana@client.example --param subject="Your invoice" --param body="Hello Ana, ..."
python3 runtime/cli.py approve --project <project> --id <the plan's pending id> --sha256 <the plan's hash>      # the plan holds the filled arguments
python3 runtime/cli.py run-step --project <project> --task <task>      # prepares the e-mail and stops at its effect decision
python3 runtime/cli.py approve --project <project> --id <the effect's pending id> --sha256 <the effect's hash>   # sends it, once
```

Use a **dedicated account** made for the runtime, never a person's own mailbox: the password sits in the secret store of this machine, and the account sends nothing the person did not approve. One outbox account per machine (decision EMAIL-SEND): `send` with another `--from` is exit 3, and `setup` again changes the account.

## What it keeps

- `<state>/mailer-smtp/settings.json`: the address, the hosts, the ports, the Sent folder. No secret. `<state>` is `$OPENHORA_STATE_DIR`, else `$XDG_STATE_HOME/openhora`, else `~/.local/state/openhora`; the folder is mode 0700 and the files 0600.
- `<state>/mailer-smtp/ledger.json` (and its lock): one entry per idempotency key. `pending` is written before the first connection, `done` after the server's 250 to DATA. The ledger keeps a key for ever, so a decision of any age can be approved again without a second send.
- The secret `MAILER_SMTP_PASSWORD` (store username `mailer-smtp`), read by `providers/secrets/resolver.py`. It is never printed, logged or put in an error, and it is sent only over TLS.

## Rules

- **Nothing is sent without `--confirmed`.** `--dry-run` prints the headers, the envelope, the text and the name, size and sha256 of each attachment, reads no credential, opens no connection and writes nothing. Its `would_sha256` is what the effect document records, and the execution compares it again before it sends.
- **The recipients are exactly the flags.** The envelope is To + Cc + Bcc; the headers have To and Cc only (a Bcc is never a header); every header is built here from checked parts. A display name, a comment, a quote, a line break or any control character, a second `@`, a repeated address (compared in lower case), more than 20 recipients in all, an attachment that is not a regular file or whose extension is not one of `pdf, docx, xlsx, pptx, odt, txt, csv, md, png, jpg`, is exit 2 and nothing is sent.
- **All or nothing.** One recipient the server refuses is `RSET`, nothing sent, the key released and exit 1 naming the address.
- **Exit codes.** 0 sent (or replayed); 1 refused or failed, and **nothing was sent** (a caller may rely on it); 2 usage; 3 not configured (no settings, no password, a login the server refuses, another outbox account); 4 the outcome is **not known**: the answer to the message was lost, or an earlier attempt's was and the Sent folder does not say. With 4 the key stays `pending`.
- **A lost answer.** The next `send` with that key runs `lookup` first: the Message-ID found in the Sent folder means the e-mail was sent (`"replayed": true`, nothing is sent again); not found, or no Sent folder set up, is exit 4 and the key is blocked until `resolve --idempotency-key <k> --sent` or `--not-sent --confirmed`, which the person runs after looking in the Sent folder.
- **TLS before any password.** SMTP 465 (TLS from the first byte) or 587 with a required STARTTLS; IMAP 993; the certificate and the name are verified. A server that does not offer STARTTLS, or whose certificate is not trusted, gets no `AUTH`. A port that says nothing about TLS is refused unless `--smtp-security ssl|starttls` names it. A connection without TLS exists for tests only: `OPENHORA_MAIL_TEST_PLAIN=1` and a loopback host (the variable refuses any other host).
- **What is read back.** A mail library decodes some texts into more than was approved (an RFC 2047 encoded word such as `=?utf-8?b?...?=` in a subject or an address, which on some Python versions can put a line break on the wire). So `=?` is refused in the subject, in every address and in a reply id (exit 2), a lone `\r` in the text is refused, a domain that is not ASCII is refused unless it is given in its `xn--` form, and the message is built and **read back** (`providers/_email.py` `inspect_message`) before the dry run prints and before anything is sent: its headers, its text and its attachments must be exactly the ones asked for, with no other header, part or line end; else exit 2 and nothing is sent. The dry run's `would.wire` is that reading, and its hash covers it.
- **The Sent folder is read only.** `lookup` sends `EXAMINE` and `UID SEARCH` and nothing that changes a mailbox; the provider never files, moves or deletes a message. A Sent folder is named in plain ASCII (letters, digits, spaces and `. _ / [ ] - & , +`): a localized name in IMAP's modified UTF-7 (`&AOc-...-`) is accepted as written, with `& , +` allowed, and is not decoded.

## To verify on first use

The tests use stand-ins; nothing here was run against a real mail service. The maintainer checks, once, with a dedicated mailbox and its app password:

1. `setup`, then `--check`: both logins work. Say which host and port the mailbox uses for SMTP and IMAP, and what the Sent folder is called there.
2. A send to a second address of your own, through `send-email`, approved in the terminal and on the page: it arrives once, with the right sender, the text and (a second try) an attachment, and no trace of the Bcc in the headers.
3. A recipient the server refuses (an address that does not exist at a domain that checks): the send stops, names the address, nothing is delivered to the others.
4. An interrupted send (stop the process while it sends, or cut the network after DATA): the next approval of the same hash looks in the Sent folder first. This depends on the host filing a copy of a message sent over SMTP in its Sent folder; if it does not, `lookup` never finds it and the key waits for `resolve` (then the person settles it by hand).
5. Assumptions to check there: the host accepts a message of about 25 MB (the cap here is 18 MB of attachments); a host that forbids password logins (Microsoft 365 by default) cannot use this implementation, and needs the Gmail-API-style second implementation of the class (a later package); the page offers a flow's parameters as a form (otherwise `request --flow send-email --param ...` in the terminal is the path); `imaplib` has no IDLE before Python 3.14, which `lookup` does not need.
