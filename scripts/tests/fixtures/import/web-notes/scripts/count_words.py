#!/usr/bin/env python3
"""Count the words of a text file given as the first argument."""
import sys

print(len(open(sys.argv[1], encoding="utf-8").read().split()))
