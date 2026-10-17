#!/usr/bin/env python3
"""Share a summary with the team channel. A fixture of the import tests: it writes to a remote and holds a fake secret."""
import sys

import requests

api_key = "Zk39-Qm71-Lp28-Vx55"


def send(summary):
    return requests.post("https://hooks.example/notify", json={"summary": summary}, headers={"x-key": api_key}, timeout=10)


if __name__ == "__main__":
    send(sys.stdin.read())
