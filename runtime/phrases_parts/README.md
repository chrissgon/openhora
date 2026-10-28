# Phrase parts

A package that adds keys to the phrase table writes them here, in its own pair of files, so that two packages that add keys at the same time edit different files (SPEC-HOTSPOTS).

- `<id>.en.json` is `{"package": "<id>", "table": {"KEY": "sentence"}}`.
- `<id>.pt-BR.json` is `{"package": "<id>", "table": {"KEY": "frase"}, "same_as_english": ["KEY"]}`; `same_as_english` lists the keys whose Portuguese is the English sentence on purpose.
- The two files have the same keys, a key is never in the core table or in another part, and `package` is the file's stem. `runtime/phrases.py` refuses anything else when it is imported.
- A Portuguese file needs its own line in `.security-scan-allow` (rule `english-only`: the scanner names each file, never a glob). The text of an existing key is changed in place, in the file that holds it.
