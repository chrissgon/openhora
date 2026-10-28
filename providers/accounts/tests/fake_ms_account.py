"""A stand-in for what the Microsoft account authorization (providers/accounts/microsoft_auth.py) talks to: the Microsoft identity token endpoint
and the two Graph reads the command makes (`GET /me` for the address, `GET /me/drive` for the kind of account), on 127.0.0.1. Not a test file,
and never a copy of the live service. The token side is the one the mail suite uses (providers/mailbox/tests/fake_microsoft.py), loaded from
there: it issues a new refresh token on every refresh and leaves the old one valid, answers a scope string a test can change, and records every
form posted to it and every method the Graph side saw. Every address is on a `.example` domain and every credential is a made-up string.

Usage (from a test):
  fake = FakeMsAccount()
  fake.base, fake.token_url             what the command's environment names (ACCOUNT_MICROSOFT_API_BASE, ACCOUNT_MICROSOFT_TOKEN_URL)
  fake.account_record_json()            an account record (MICROSOFT_ACCOUNT_TOKEN) that this fake's token endpoint accepts
  fake.scope_granted = "..."            what the next token answers say they granted (a missing or an extra permission)
  fake.address = None                   GET /me names no address
  fake.close()
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mailbox" / "tests"))
import fake_microsoft  # noqa: E402
from fake_microsoft import ACCESS_TOKEN, CODE, REFRESH_TOKEN, SCOPE_URL_PREFIX, TENANT  # noqa: E402,F401  (re-exported for the tests)

PREVIOUS = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")      # a token made before To Do tasks was added
PLATFORM = PREVIOUS + ("Tasks.ReadWrite",)      # CB-4: the set the authorization asks
CLIENT_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
ADDRESS = "casey.rivera@mail.example"
GRANTED = " ".join(SCOPE_URL_PREFIX + name for name in PLATFORM) + " offline_access openid profile"   # Microsoft adds the three words that grant nothing


class FakeMsAccount(fake_microsoft.FakeMicrosoft):
    SCOPE = " ".join(PLATFORM)
    CLIENT_ID = CLIENT_ID

    def __init__(self):
        super().__init__()
        self.scope_granted = GRANTED
        self.address = ADDRESS              # what GET /me names as `mail`; None: the field is absent
        self.principal = "casey.rivera@work.example"   # what GET /me names as `userPrincipalName`; None: the field is absent
        self.me_status = 200                # set another status to make GET /me fail
        self.drive_type = "personal"
        self.drive_status = 200

    def route(self, handler, rest, query):
        if rest == "/me":
            if self.me_status != 200:
                return handler.error(self.me_status, "generalException", "an error")
            body = {"displayName": "Casey Rivera"}
            if self.address:
                body["mail"] = self.address
            if self.principal:
                body["userPrincipalName"] = self.principal
            return handler.json(200, body)
        if rest == "/me/drive":
            if self.drive_status != 200:
                return handler.error(self.drive_status, "generalException", "an error")
            return handler.json(200, {"id": "b!Fake-Drive_1", "driveType": self.drive_type})
        handler.error(404, "notFound", "not served")

    # --- what a test reads -------------------------------------------------------------------------------------------------------

    def account_record(self, **over):
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": self.CLIENT_ID, "tenant": TENANT, "scope": self.SCOPE,
                  "account_kind": "personal", "account": ADDRESS, "obtained_at": "2026-10-18T08:00:00Z"}
        record.update(over)
        return record

    def account_record_json(self, **over):
        return json.dumps(self.account_record(**over))

    def env(self, **over):
        """What the authorization command's process needs to talk to this fake."""
        return {"ACCOUNT_MICROSOFT_API_BASE": self.base, "ACCOUNT_MICROSOFT_TOKEN_URL": self.token_url, "MICROSOFT_CLIENT_ID": self.CLIENT_ID, **over}
