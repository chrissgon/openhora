#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the runtime needs to know of an e-mail address, and nothing else (package EMAIL-SEND): the same rule as providers/_email.py
`normalize_address`, written again because the runtime does not import a provider; a test holds the two equal on a table of addresses.

  normalize_address(text)    one plain address, the domain in lower-case IDNA ASCII, or AddressError. A display name, a comment, a quoted
                             local part, an angle bracket, a space, a comma, a control character, a second `@`, a local part over 64
                             characters, an address over 254 are refused.
  address_key(address)       the form two addresses are compared by: the whole address lower-cased
  split_list(text)           a comma-separated list of addresses, each normalised; "" and the word `none` are the empty list
  domain_of(address)         the part after the `@`

It imports no other module of runtime/, so project_config.py (the key `outbox`) and runtime/send_document.py can both use it.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re
import sys

LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
ADDRESS_MAX, LOCAL_MAX, DOMAIN_MAX = 254, 64, 253
NONE_WORD = "none"      # the value of an optional list of recipients that is empty (a flow's parameter cannot be blank)


class AddressError(ValueError):
    """An address is not in its form. `reason` never holds more than the rule that was broken."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def normalize_address(text) -> str:
    if not isinstance(text, str) or not text or text != text.strip():
        raise AddressError("an address is plain text with no space around it")
    if text.count("@") != 1:
        raise AddressError("an address has exactly one @")
    local, domain = text.split("@")
    if not local or len(local) > LOCAL_MAX or local.startswith("-") or not LOCAL_PART.fullmatch(local):
        raise AddressError("the part of an address before @ is plain letters, digits and . ! # $ % & ' * + / = ? ^ _ ` { | } ~ - (no display "
                           "name, comment, quote or space)")
    if not domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise AddressError("the domain of an address has two or more labels")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise AddressError("the domain of an address cannot be written in ASCII") from None
    labels = ascii_domain.split(".")
    if len(labels) < 2 or len(ascii_domain) > DOMAIN_MAX or not all(LABEL.fullmatch(label) for label in labels):
        raise AddressError("the domain of an address has two or more labels of letters, digits and hyphens")
    address = f"{local}@{ascii_domain}"
    if len(address) > ADDRESS_MAX:
        raise AddressError(f"an address is at most {ADDRESS_MAX} characters")
    return address


def address_key(address: str) -> str:
    return address.lower()


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[1]


def split_list(text) -> list:
    """The addresses of a comma-separated list, each normalised (a space around a comma is allowed, and nowhere else). An empty text and the
    word `none` are the empty list. AddressError names the entry that is not an address."""
    if not isinstance(text, str):
        raise AddressError("a list of addresses is text")
    if not text.strip() or text.strip().lower() == NONE_WORD:
        return []
    out = []
    for position, part in enumerate(text.split(","), 1):
        try:
            out.append(normalize_address(part.strip()))
        except AddressError as e:
            raise AddressError(f"entry {position}: {e.reason}") from None
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
