# Phrase parts

A package that adds keys to the phrase table writes them here, in its own pair of files, so that two packages that add keys at the same time edit different files (SPEC-HOTSPOTS).

- `<id>.en.json` is `{"package": "<id>", "table": {"KEY": "sentence"}}`.
- `<id>.pt-BR.json` is `{"package": "<id>", "table": {"KEY": "frase"}, "same_as_english": ["KEY"]}`; `same_as_english` lists the keys whose Portuguese is the English sentence on purpose.
- The two files have the same keys, a key is never in the core table or in another part, and `package` is the file's stem. `runtime/phrases.py` refuses anything else when it is imported.
- A Portuguese file needs no line in `.security-scan-allow`: the `english-only` check of `scripts/validate.py` exempts every `runtime/phrases_parts/<id>.pt-BR.json` by rule (so two packages never conflict on that file), and a file there that is not a valid part pair is still refused by `phrases.load_parts`. Only that exact folder and name are exempt; a Portuguese word in any other file still fails. The text of an existing key is changed in place, in the file that holds it.
