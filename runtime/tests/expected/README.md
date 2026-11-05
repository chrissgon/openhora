# expected/: the expectation ledger of the runtime's tests

One file per package, `<id>.json` (the PR title's id, lower case): `{"package": "<id>", "add": {"<test module without test_>.<CONSTANT>": [items] or {key: value}}}`.
A test reads its constant as `extend("<name>", <base literal>)` (`runtime/tests/expected_kit.py`): the base stays in the test module, the packages' additions come from here, in file-name order.
An item listed twice, a wrong `package`, an unknown key or a name that no `extend("<name>"` reads fails `test_expected_kit.py`. The double entry is kept: the source (the operations table, the registry) still has to agree.
`python3 runtime/tests/expected_kit.py --show <name>` prints one merged constant; `--list` prints the names the files add to. A removal edits the base literal or the file that added the item.
