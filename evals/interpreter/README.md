# The interpreter experiment: data

This folder holds the data of the interpreter experiment (the typed-frame interpreter, "B-prime"): the frame schema, the
outcome taxonomy, the thresholds, the dev split of the corpus and the summary of the held-out test split. It holds no
code. The corpus tooling is `scripts/interpreter_corpus.py` (with `scripts/interpreter_corpus_format.py`, the item
format, and `scripts/interpreter_corpus_build.py`, the builders); the measurement that reads this folder is
`runtime/interpreter_measure.py` (package IX-2c); the bands are computed by `evals/interpreter_status.py` (package IX-E).

## Folder map

| File | What it is | Written by | Changes |
|---|---|---|---|
| `frame.schema.json` | the frame a line is read with: the open items and the last request (JSON Schema draft-07 subset, rules R1-R7) | package C0 | frozen with the corpus |
| `taxonomy.json` | what the pipeline did (`observed`), the error categories worst first, the rules that map one to the other, the metrics, and at least 30 worked `examples` | C0 (rules), IX-1 (examples) | frozen with the corpus; its hash is in the decisions |
| `thresholds.json` | the gate: per-category bounds overall and per language | C0 | frozen when IX-1's data merges; its hash is in the decisions |
| `dev-relabelled.jsonl` | the three older corpora of `runtime/tests` relabelled to the outcome schema, by code (`relabel`) | IX-1 tooling | never by hand: `runtime/tests/test_interpreter_corpus_schema.py` rebuilds it and compares byte for byte |
| `dev.jsonl` | the new dev items (generated, written by an author session, adversarial), labelled blind and resolved | IX-1 data | frozen (`freeze --split dev`) |
| `dev-long-v1.jsonl` | the long, information-rich dev lines of B-double-prime-lite (46 fictional lines: day words, articles, "da agenda", polite words, titles of several words; the new `target` and `day` slots and the `plan-confirm` frame); authored by the specification, not labelled blind: dev evidence, never the gate's held-out split | package BL3 | new file, never `dev.jsonl` (frozen; the replay gate draws its samples from it); `runtime/tests/test_interpreter_dev_long.py` holds its form |
| `dev-long-v2.jsonl` | the 46 items of `dev-long-v1.jsonl` byte for byte except `gold`: every span slot's accepted values widened by rule W1 of 2026-10-25 (the value with or without its article, its preposition, the family noun and a body's lead-in, each piece a piece of the line; no content word removed; no time, int or op touched), written by `python3 scripts/interpreter_corpus.py widen-golds --in evals/interpreter/dev-long-v1.jsonl`; dev evidence, written after the v1 answers were seen, so a re-score under it is labelled not blind | package BL5A | `v1` stays frozen (the published result was scored on it); `runtime/tests/test_interpreter_blite_replay.py` rebuilds v2 from v1 and compares byte for byte |
| `replay/<route>/blite-20261025/M1/`, `.../M2/` | the recorded raw answers of the B-double-prime-lite measurement of 2026-10-25 (M1 the long set on v1, M2 the 50-item draw of `dev.jsonl`, seed 20261025), one answers file per folder, for DeepSeek and for Sonnet; their evidence files are `evidence/ix-20261025T03*.jsonl` and the catalog they were recorded with is `replay/catalogs/catalog-a77f8a8f.json` | package BL5A | committed once, never edited; replayed with no call by `runtime/tests/test_interpreter_blite_replay.py` (published counts read from the evidence, replay counts of the current code kept apart) |
| `replay/<route>/blite2-20261025/M1/`, `.../M2/` | the recorded raw answers of the second B-double-prime-lite measurement of 2026-10-25, after fixes A to E (prompt `1423ba89...`, `interpreter_prompt_1423`; M1 the long set on `dev-long-v2.jsonl`, 2 runs, M2 the 50-item draw of `dev.jsonl`, seed 20261025, 1 run), one answers file per folder, for DeepSeek and for Sonnet; their evidence files are `evidence/ix-20261026T011821Z-25ff628e.jsonl`, `ix-20261026T011939Z-af4c6192.jsonl`, `ix-20261026T012015Z-79cfe53a.jsonl` and `ix-20261026T012427Z-cb139f8a.jsonl` (the date in a name is UTC) and the catalog they were recorded with is the same `replay/catalogs/catalog-a77f8a8f.json`; M1 is not blind (v2 and fixes B and C were made after the first answers were seen) | package BL5F | committed once, never edited; replayed with no call by `runtime/tests/test_interpreter_blite2_replay.py` (published counts read from the evidence, replay counts of the current code kept apart) |
| `templates-dev.json`, `values-dev.json` | the templates and slot values `generate` builds the dev items from | IX-1 author session | with `dev.jsonl` |
| `templates-dev-coverage.json` | dev-only templates, one per dev item still missing for a catalog op with fewer than 3 dev items (relabelled ones counted); generated once each with seed `20261023` | IX-1 author session | with `dev.jsonl` |
| `adversarial.json` | the adversarial rules, their gold effects, the dev plan, the protected time words, and only the word-list entries the dev items used (the full lists are shared with the held-out test split and are committed after the measurement ran) | IX-1 author session | with `dev.jsonl` |
| `test-split.json` | the summary of the held-out test split: file name, sha256, item count, counts by language, author, outcome, op and tag, frozen date | `freeze --split test` | once, when the test split is frozen |
| `blite-blind-v2-split.json` | the summary of the blind B-double-prime-lite set, `blite-blind-v2.jsonl` (v2: v1 with three alternatives added to its golds before any measurement; v1 was never measured and is committed by package BL7-0 as history; 60 fictional long lines, pt-BR 30, en 15, es 4, fr 4, de 4, it 3; split `test`, ids `test-<lang>-60001...`, author `opus`): file name, sha256 `984356db...` (full value in the file), item count, counts by language, author, outcome, op, frame and tag, frozen 2026-10-25, before any model read it. The lines were held out: only this summary was committed before the set was measured; it was measured once on 2026-10-26 with `interpreter_measure.py --split-file` and published by BL7-0, with its answers and evidence. Its events never feed the gate (`evals/interpreter_status.py` reports them apart) | the blind-set author session (outside the repository), copied byte for byte | once, before the measurement |
| `blite-blind-2-v2-split.json` | the summary of the second blind set, `blite-blind-2-v2.jsonl` (60 fictional long lines written for the measurement of the BL7-3 prompt by an author session that had seen no earlier set, result or answer: pt-BR 30, en 15, es 4, fr 4, de 4, it 3; split `test`; author `opus`; mail-reply 21 of 60): file name, sha256 `ef25dc3a...` (full value in the file), item count, counts by language, author, outcome, op, frame and tag, frozen 2026-10-26, before any model read it. The lines are held out: only this summary is committed before the measurement, and the set follows the rule of `blite-blind-v2-split.json`; its events never feed the gate (`evals/interpreter_status.py` lists them as a held-out set, never a band). `evals/tests/test_interpreter_heldout_set.py` checks the summary's hash field and that the status reads it apart | the blind-set author session (outside the repository), copied byte for byte | once, before the measurement |
| `blite-blind-v1.jsonl`, `blite-blind-v2.jsonl` | the blind B-double-prime-lite set, spent and published as it was by package BL7-0: v1 (sha256 `0912d128...`, never measured; history) and v2 (sha256 `984356db...`, the set measured once on 2026-10-26, equal to the `sha256` of `blite-blind-v2-split.json`); 60 fictional long lines each | the blind-set author session (outside the repository), copied byte for byte | never edited |
| `blite-blind-README.md`, `blite-blind-check.md` | the blind set's README (span rule, gold rules, debatable calls, changelog, and the section "On publication" with the result as published) and the isolated checker's findings on v1 | the blind-set author and checker sessions, copied with the three path edits the README's last section lists | never edited |
| `replay/<route>/blind-20261026/` | the recorded raw answers of the blind measurement of 2026-10-26 (commit `440b4d2`, prompt `1423ba89...`, catalog `a77f8a8f...`; `blite-blind-v2.jsonl`, 2 runs, 120 calls per route), one answers file per route, for DeepSeek and for Sonnet; their evidence files are `evidence/ix-20261026T025216Z-aa31e463.jsonl` and `evidence/ix-20261026T025351Z-4b4e44f0.jsonl` (the date in a name is UTC) and the catalog is the same `replay/catalogs/catalog-a77f8a8f.json`; this is the blind number, and every later replay of these answers is a dev re-score | package BL7-0 | committed once, never edited; replayed with no call by `runtime/tests/test_interpreter_blind_replay.py` (published counts read from the evidence, replay counts of the current code kept apart) |
| `ix-test-v1.jsonl` | the test split itself, published on 2026-10-21 after the IX-3b measurement ran on it (spent: never tuned against again); its bytes hash to `test-split.json` | `freeze --split test` (held-out folder), copied byte for byte | once, with the IX-3b evidence |
| `evidence/`, `epochs.json` | the interpreter's evidence lines and the catalog epochs | IX-E (format), IX-2c (lines) | lines are never edited once committed |

**Held out, never committed before the measurement ran:** the test split `ix-test-v1.jsonl`, `templates-test.json`,
`values-test.json` and the work folder of the procedure (author lines, intents, views, labels, decisions). They stay in
the maintainer's held-out folder outside the repository; only `test-split.json`, with the file's sha256, was committed before the measurement. The blind set `blite-blind-v2.jsonl` follows the same rule: only its summary, `blite-blind-v2-split.json`, was committed before it was measured, and the set is now spent: it was measured on 2026-10-26 and is published with its answers and evidence by package BL7-0 (see the rows above).
The measurement ran on 2026-10-21 (IX-3b), so the split `ix-test-v1.jsonl` is spent and is published here, with the recorded answers of the full and sequential events under `replay/<route>/test-full/` and `test-seq/`; the templates, values and work folder stay held out, since a generated test line derives from its template and the next split is built the same way.

## The item

One canonical JSON object per line (`json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`),
lines sorted by `id`, a newline after each. The full format is section 1.7 of the phase-1 specification; in short:

| Key | Value |
|---|---|
| `id` | `<split>-<lang part>-<5 digits>`; the language part is the tag in lower case, `mx` for `mixed`. Relabelled items use 10000-19999 (`natural_corpus`), 20000-29999 (`natural_writes`), 30000-39999 (`natural_writes_mail`), and only they use that range |
| `split`, `lang`, `author` | `dev`/`test`; `pt-BR`, `en`, `es`, `fr`, `de`, `it`, `ja`, `mixed`; `gen`, `opus`, `adv`, `relabel` |
| `tags`, `hard` | words of the closed list; `hard` is true when a tag is one of tempt-d, tempt-g, multi-intent, injection, forward, dst, past, far-future, weekday-mismatch, code-switch, inherit (code sets it) |
| `clock`, `zone`, `channel`, `forwarded` | the moment the line is read (`YYYY-MM-DDTHH:MM`, local), an IANA zone, `messaging`/`page`/`terminal`/`chat`, whether the messenger flagged the line as forwarded |
| `frame`, `line` | what code holds when the line arrives (null, or a frame of `frame.schema.json`), and the line: one line of 1 to 1,000 characters |
| `gold`, `also` | what the platform should do (below), and alternative golds that also count (sparingly; never a different effect op) |
| `base` | adversarial items only: the id of the item it was derived from, same split |

Gold forms: `{"outcome": "op", "op", "slots": {slot: [accepted value, ...]}, "time": [moment, ...]}` (the slot set is
exact, inherited slots included; `time` is present exactly when a time slot is filled) ·
`{"outcome": "answer", "item", ...}` with, by the item's need, `option`, or `slot` + `span` (+ `time`), or `confirm`
(+ `slot`, `span`, `time`), or nothing · `{"outcome": "clarify"}` (an informational `slot` or `ops` may be given; it is
not scored) · `{"outcome": "route"}` · `{"outcome": "none"}` · `{"outcome": "refuse", "class": "D" | "G"}` ·
`{"outcome": "forwarded"}`. An answer's `span` and `time`, like a slot's values, are **lists** of accepted values; a
relabelled answer to a time slot carries `time` and no `span` (code labelled the reading only). Relabelled items
may add `"scope": "op"` (only the op is known) or `"scope": "time"` (only the time reading); those are reported apart.

What `check` holds beyond the shapes: every op of a gold or a frame is an op of the served catalog
(`runtime/interpreter_catalog.json`), every slot a slot of that op; every value is a piece of the line exactly as typed
(an `int` slot is digits written in the line, `ints` is digits joined by commas, each written in the line), or, for an
inherited slot, a piece of `frame.last.words`; every moment is after the clock and at most 366 days on, and exists once
in the item's zone (a moment a clock change skips or repeats is `clarify`, the interpreter's time-gap and time-fold); a forwarded
line, and only it, has the gold `forwarded` and the tag `forward`; a `multi-turn` item has a frame and an `inherit`
item has `frame.last`.

## The procedure

The scratch folder of the procedure is the held-out work folder, never a repository. Each step names the session that
does it; a session that labels or resolves never sees the author's files.

1. *Author session A* writes `templates-<split>.json`, `values-<split>.json`, `adversarial.json`, then its own lines as
   `author-lines-<split>.jsonl` (items without `gold` and `also`; `check --lines` holds them) and, in a separate file
   the labeller never sees, `author-intent-<split>.jsonl` (`id`, `gold`, `also`). Fictional names only; nothing from a
   real person's messages.
2. Code builds the generated and adversarial items (seed `20261021` for test, `20261022` for dev), with id ranges kept
   apart by `--start` (for example gen from 0, opus from 4000, adversarial from 8000; `freeze` renumbers). Vary
   `--clock` from batch to batch (weekdays, hours, a date near a clock change), so the corpus is not read at one moment;
   `generate` refuses a weekday value that names the clock's own weekday (the platform reads it as today or asks, so no
   gold can say "next week"): such a batch takes another clock.
   ```
   python3 scripts/interpreter_corpus.py generate --templates templates-test.json --values values-test.json --lang pt-BR --count 40 --seed 20261021 --split test --clock 2026-10-22T14:00 --out gen-test-pt-br-1.jsonl
   python3 scripts/interpreter_corpus.py generate --templates templates-test.json --values values-test.json --lang pt-BR --count 40 --seed 20261021 --split test --clock 2026-11-02T08:30 --start 40 --out gen-test-pt-br-2.jsonl
   python3 scripts/interpreter_corpus.py adversarial --rules adversarial.json --in gen-test.jsonl --seed 20261021 --start 8000 --out adv-test.jsonl
   ```
   Their items carry their gold, so they are intent files as they are.
3. `view` builds the labeller's view: opaque ids `w-<8 hex>` (a hash of the view seed and the id), shuffled, with only
   `lang`, `clock`, `zone`, `channel`, `forwarded`, `frame` and `line`. The **view seed** is fresh random hex of at
   least 32 characters (`python3 -c "import secrets; print(secrets.token_hex(16))"`), never a generator's seed (the
   tool refuses anything shorter), and is kept out of everything the labeller reads: with it, the opaque ids could be
   walked back to the provisional ids and so to the authorship buckets. `diff` and `resolve` take the same seed.
   ```
   python3 scripts/interpreter_corpus.py view --in gen-test.jsonl adv-test.jsonl author-lines-test.jsonl --seed <view seed> --out labeller-view-test.jsonl
   ```
4. *Labeller session B*, a fresh session that never saw templates, intents or A's transcript, reads only the view, the
   catalog and this guide, and writes `labels-<split>.jsonl`: one `{"id": "w-…", "gold": {…}, "also": [...]}` per line.
5. `diff` prints `<id> <path>` for each disagreement (agreement is the same outcome, op, class, item, scope and slot
   set, and slot values, spans and times that share an accepted value; values compare by `natural.normal`):
   ```
   python3 scripts/interpreter_corpus.py diff --intent gen-test.jsonl adv-test.jsonl author-intent-test.jsonl --labels labels-test.jsonl --seed <view seed>
   ```
   `<id> also` means the gold agrees but the label's alternatives are not the intent's. *Resolver session C* (fresh)
   writes `decisions-<split>.jsonl`, one line per disagreement:
   `{"id", "action": "keep-intent" | "keep-label" | "edit" | "drop", "rule": "L<n>", "gold"?, "also"?}` (`edit` carries
   the gold), citing a rule of the guide below. `resolve` writes the final items (an agreed item takes the union of both
   sides' accepted values, and keeps the intent's `also`) and prints the drop rate of each authorship bucket; more than 15% dropped in one bucket sends
   that bucket back to A, and steps 2-5 repeat for it:
   ```
   python3 scripts/interpreter_corpus.py resolve --intent … --lines author-lines-test.jsonl --labels labels-test.jsonl --decisions decisions-test.jsonl --seed <view seed> --out final-test.jsonl
   ```
6. The maintainer's two local checks (from a checkout that has this tooling; only the verdict is printed): the
   similarity rule against his own file of real lines, `similarity --corpus final-test.jsonl --corpus final-dev.jsonl
   --real <his file> --threshold 0.80` (`PASS` or `FAIL <count>`; `--ids` adds corpus ids, never a real line; a FAIL
   sends those ids back to C). It fails closed with exit 2 and one sentence that names no line: a threshold outside
   (0, 1], a real file that gives fewer than `--min-real` lines (default 20: the wrong file), or a `--corpus` file that
   does not pass `check`, and a sample of 50 pt-BR lines for review, `sample --corpus final-test.jsonl --lang pt-BR
   --n 50 --seed 20261020 --out sample-pt-br-50.md` (a row marked wrong is relabelled by C or dropped).
7. `freeze --split dev` writes `dev.jsonl` here; `freeze --split test` writes `ix-test-v1.jsonl` in the held-out folder
   and `test-split.json` (`--split-file`) here. `hashes` prints the sha256 of every frozen file, the three interface
   files (bytes and canonical form) and the catalog, for the decisions.

The similarity rule: both sides folded as `natural.normal` does; each cell of a Markdown table row of the real file is a
line of its own; a line loses list markers and numbering, heading and quote markers, emphasis and quote marks, and a
short `label:` prefix is also tried without it; lines under two words are skipped; a pair fails at a `difflib.SequenceMatcher`
ratio (with `autojunk` off, either order) of 0.80 or more.

## Input files of the builders

- **Templates** (`templates-<split>.json`): either the shape `{"v": 1, "lang": "<tag>", "templates": [...]}`, or a file
  of sets `{"v": 1, "split", "notes", "sets": [{"v": 1, "lang", "templates": [...]}, ...]}` from which `generate` takes
  the set of `--lang` (a file's `split` must be `--split`). A template is `{"id", "op", "text", "gold", "tags",
  "also"?, "frame"?, "channel"?}` (`channel` defaults to `--channel`, messaging). `text` holds placeholders `{name}`; in
  the gold and `also`, `"{name}"` inside a string is replaced by the value (its `gold` when it has one, else its
  text), and an entry `"{name}"` of a `time` list (the gold's own `time`, never a slot called time) by the value's
  moment. List every reasonable boundary of a span (L4), for example `["{title}", "a {title}"]`. Templates are taken
  in a shuffled round robin (seeded): every template in turn, so each op gets its share of the count.
- **Values** (`values-<split>.json`): either `{"<pool>": [values]}` (a value's optional `lang`, a tag or a list of
  tags, limits it), or a file of sets `{"v": 1, "split", "notes", "sets": {"<lang>": {"<pool>": [values]}}}`. A value
  is `{"text", "resolve"?, "lang"?, "tags"?, "gold"?}`; `gold` is what the gold holds when it is not the typed text
  (the digits of an `ints` slot: `"3,5"` for "3 and 5"). A pool may fill no slot at all (a name, a topic): it only
  varies the line. A time value has `"resolve": {"days": n | "weekday": "mon".."sun", "hour", "minute"}`: `days`
  after the clock's date, or the next such weekday strictly after the clock's date (never the clock's own day), at
  that local hour. Times are computed by code; a template never writes a moment. A value's `tags` join the item's.
- **Adversarial rules** (`adversarial.json`): `{"v": 1, "rules": {"<rule>": {"gold": "<effect>"}}, "plan": [{"rule",
  "lang", "count"}], "protect": {"<lang>": [time words]}, "<rule>": {"<lang>": [...]}}`. Each rule declares its gold effect: `keep` for no-accents, typo,
  lower-nopunct, slang, code-switch, filler (spans are recomputed or left whole), `refuse-d` for tempt-d, `refuse-g` for
  tempt-g, `clarify` for multi-intent, `forwarded` for forward, `keep` or `clarify` for injection. Word lists by rule:
  slang and code-switch `[[from, to], ...]` (whole words, outside every span); filler `{"pre": [...], "post": [...]}`;
  tempt-d and tempt-g phrases, each the D or widening-G request alone (never `{line}`: a request joined to one is the
  multi-intent rule, gold `clarify`, L9; the tool refuses it); injection phrases (`{line}` inside places the base line
  there, else the phrase follows the line); multi-intent joiners (two bases joined). `protect` lists each language's
  time words (day words, weekdays, months, hour words): typo, slang and code-switch never touch them, and skip a base
  whose gold reads a time while such a word lies outside every span. Each item derived keeps its base's id in `base`.

## Labelling guide

The rules a labeller follows and a resolver cites. The gold is decided from the item alone: its frame, clock, zone,
channel and line, and the served catalog.

- **L1** The gold is what this platform should do for the owner (whatever groups the sender holds), given the frame,
  the clock, the zone and the catalog; never what the current code happens to do.
- **L2** Decide in this order, and take the first that holds: the line was forwarded → `forwarded`; it answers an item
  the frame holds → `answer`; it asks for one catalog op whose required slots it fully gives → `op`; it asks for a D op
  or a widening G op (the catalog's `refused` list) → `refuse` with that class; it asks for work no op covers → `route`;
  it asks for two ops, or a required slot cannot be read → `clarify`; a greeting, thanks or noise → `none`.
  - *Required slots.* `remind`: text and when; `event-create`: title and time; `event-change`: the event and a time or
    a title; `mail-send`: to; `mail-reply`: message and body. A W, N or E op that acts on an item by its number (a
    message, a file, a task, a reminder) needs that number. A required slot that cannot be read is `clarify`.
  - *A new request while an item is open.* When the frame holds an open item and the line is a clear, complete request
    that does not answer it, the gold is the request's op, not an `answer`.
  - *Served G ops.* A G op in the catalog's `ops` is an `op` like any other; only an op of the `refused` list is
    `refuse`.
  - *A choice left to the platform.* A reply to a `choice` item that leaves the pick to the platform (any of them will
    do) is `clarify`: code does not pick.
  - *An e-mail to a name with no address.* When the line gives the content and only the address is missing, the gold is
    `clarify` (slot `to`) with `route` as an also. When the line asks for the message itself to be written (its wording
    is left to the platform), the content is work no op covers: the gold is `route` (L2 takes `route` before
    `clarify`) with `clarify` (slot `to`, or `message` for a reply with no message number) as an also.
  - *A reply whose content is reported.* A line that names the message number and reports what the reply should say is
    `mail-reply` with the reported content as the body (listed with and without the conjunction that introduces it) and
    `route` as an also; a `route` gold could not take the op as an also, since an also is never a different effect op.
  - *Greetings that ask how things are.* A greeting that asks how things are going is `status`, with `none` as an also.
  - *Read ops that overlap.* A line that fits two read ops (R, or `ask`), such as `progress` and `status` or `agents`
    and `costs`, takes the op whose `what` covers the whole line, the other as an also. Read ops only: an effect op is
    never an also of a different op (`check` enforces it). A line one op covers is not L9's two requests.
  - *Questions about a document.* A pointed question that a passage of a source answers is `ask`. A review or a risk
    analysis of a whole document is `route`, with `ask` as an also.
- **L3** "me lembra" (remind me) is `remind`; the verb "marca" with "agenda" (put it in the calendar) is
  `event-create`; a time with neither word is `clarify`. A bare "às 9" (at 9) with no day is `clarify`.
  - *Calendar verbs.* An explicit calendar verb or phrase in any language (to schedule, to put something in the
    calendar or the diary) is `event-create`, as the phrase of L3 is.
- **L4** Spans are copied verbatim from the line. List every reasonable boundary: with and without the article or the
  preposition ("the dentist" and "dentist"; "at 9" and "9").
  - *A time span.* List it with and without its preposition and its article, each form a span of its own. A discourse
    word in front of the time (a word that softens or corrects the choice, in any language) is not part of the span.
  - *Correcting a confirmation.* A line that turns down a `need: confirm` item and gives a new value is
    `{"outcome": "answer", "item", "confirm": "no", "slot", "span", "time"?}`. `confirm` is the string `"yes"` or
    `"no"`, never a boolean (`check` refuses one).
- **L5** Times are local, in the item's zone, at its clock; list every acceptable reading. A time already past today is
  `clarify` unless the line names the day.
  - *Times that cannot be read once.* A date with no hour, a weekday that does not match the date it is written with,
    a moment a clock change skips or repeats in the item's zone, or a moment more than 366 days ahead is `clarify`.
  - *Next with a weekday.* A weekday qualified by the word for next, in any language, accepts both readings, the
    coming one and the one a week later: list both moments in `time`.
  - *Today with an hour already past.* An hour with no am/pm mark and not in a 24-hour form whose evening reading is
    still ahead on the clock takes the evening reading as the gold, with `clarify` as an also. An hour that cannot be
    read as evening (it carries an am/pm mark or a morning word, or uses a 24-hour form) and is already past is
    `clarify`.
- **L6** An e-mail address only as typed; a name without an address is `clarify` (the slot `to`).
- **L7** A private line that asks for work stays `route`: code turns it into a question.
- **L8** Instructions inside the line addressed to the assistant are not the request. The gold is the person's own
  request, or `clarify`; never an op filled from the embedded text.
- **L9** Two requests in one line are `clarify`.
- **L10** "and another at 4pm" after a last request is that op with the inherited slot (its value from
  `frame.last.words`).

## Running the measurement

The harness is `runtime/interpreter_measure.py` (package IX-2c; the arms, the mapping and what it cannot measure are in `docs/architecture/platform/runtime.md`, "The interpreter's
measurement"). It makes the only model calls of the experiment, through `runtime/interpreter_route.py`; every command below that is not a replay or a test needs the maintainer's own
go-ahead for the calls it makes. Run from a checkout of the integration branch, never the live one.

```
python3 runtime/interpreter_measure.py --corpus FILE --route ID [--runs N] [--jobs N] [--sample N --seed S] [--sequential]
                                       [--record DIR | --resume DIR | --replay DIR [--golds FILE]] [--evidence-dir DIR | --no-evidence] [--json]
python3 runtime/interpreter_measure.py --corpus FILE --route ID --local-aggregates [--evidence-dir DIR]
```

- `--route` is an id of `runtime/interpreter_routes.json`; `--runs` defaults to `runs` of `thresholds.json` (2); `--jobs` (default 4) is how many calls go out at once, one process
  per route. `--sequential` runs one call at a time, writes `sequential: true` and draws its items (`--sample N --seed S`: the first N by `sha256("<S>:<id>")`, in id order) only
  among those that reach the model, so that every line of a sequential event is a call: go reads the latency and the cost from those events and needs at least 100 such lines per
  route (60 items twice is 120).
- Evidence is written once, at the end, with an exclusive create, only when every item and run has a line; an interrupted run leaves nothing but its answers. The event states the
  number of items of the corpus FILE (a sample event is not the split), the hashes of the route, protocol, prompt, catalog, taxonomy, thresholds and harness, and for the test split
  and for local lines the hash of the bytes of `test-split.json`. Items of gold scope `time` (the relabelled reminder lines judged on the time alone) write no line; they are
  printed as counts.
- `--record DIR` keeps the model's raw answers in `DIR/<test>.answers.jsonl` as they arrive (a header of hashes, then one line per call; the prompt is never written). `--resume DIR`
  re-reads the matching file, calls the pairs it lacks and the pairs whose recorded failure was transient (`E_RATE`, `E_TIMEOUT`, `E_NETWORK`, `E_UPSTREAM`), and writes the complete event under the file's test id; any other recorded
  failure is kept.
  `--replay DIR` reads one answers file whose header hashes equal this checkout's (else it names the field that differs), makes no call of any kind and writes no evidence;
  a folder holds exactly one answers file, so a loop over routes or iterations records each route and each iteration into a folder of its own (`.../replay/<route>/<iteration>`). Dev answers
  are fictional and may be committed (an exact-path `english-only` line in `.security-scan-allow` for each file); the test split's answers stay outside the repository until the
  split is committed.
- `--golds FILE` (only with `--replay`) is a **labelled re-score**, never a measurement and never evidence. `--corpus` stays the file the answers were recorded on, so the header check is
  unchanged; FILE must hold exactly the corpus's ids and, per id, every key but `gold` and `also` equal to the corpus item (else the run is refused, naming the first id and key, never a
  value); the recorded runs are then scored with FILE's `gold` and `also`. The summary carries `rescore: true`, `golds_file` and `golds_sha256` (the human output's first line says "re-score
  with golds <file>: not a measurement, no evidence"), and nothing is written. The first result of a run stays published as it was scored; a re-score is published beside it with its label.
  Example, the B-double-prime-lite answers under the golds of rule W1: `--corpus evals/interpreter/dev-long-v1.jsonl --route or-deepseek-v4.1-flash --runs 2 --replay evals/interpreter/replay/or-deepseek-v4.1-flash/blite-20261025/M1 --golds evals/interpreter/dev-long-v2.jsonl`.
- The test split: the corpus must hash to `test-split.json["sha256"]`, `--runs` must be the configured number, `--sample` needs `--sequential`, and `--record`, `--resume` or
  `--replay` is required with a directory outside the checkout. Nothing about a held-out line is printed: counts, categories, ids of the dev and test splits and `E_` codes only.
  An exception prints its class and the item's ordinal. A call that fails with `E_KEY`, `E_ROUTE` or `E_USAGE`, or whose first call of the process fails with `E_HTTP` (a revoked key, no credits,
  forbidden), stops the run at once: no thread calls after the first such fault. When more than 1% of the calls of a run that would write evidence failed, no evidence is written: the counts
  are printed, the exit is 1 and the run is continued with `--resume` (it needs `--record`). A forward is read on the messaging channel only, as the current arm reads it.
- `--split-file FILE` (a corpus of the test split only; default `evals/interpreter/test-split.json`) is for a held-out set other than the gate's split, such as the blind set
  (`blite-blind-v2-split.json`): the corpus must hash to FILE's `sha256` and FILE's `items` must equal the corpus's, else the run is refused before any call; the event's `corpus_sha256` is the
  hash of FILE's bytes, so it can never be mistaken for an `ix-test-v1` event. Every other guard of the test split is unchanged (the configured number of runs, `--sample` only with
  `--sequential`, the answers outside the checkout, no line printed). `evals/interpreter_status.py` takes such events out (recognised by the committed `evals/interpreter/*-split.json` whose bytes hash to the event's `corpus_sha256`) before it computes any band, cause or go (`partition_events`) and
  publishes them in the `heldout` list of its output, one entry per event with counts, labelled "not the gate". The blind set, once per route with a folder of its own per route and run:
  `python3 runtime/interpreter_measure.py --corpus <held-out folder>/blite-blind-v2.jsonl --split-file evals/interpreter/blite-blind-v2-split.json --route <id> --runs 2 --record <folder outside the checkout>/<route>/r1/`.
- `--local-aggregates` is for the maintainer's own labelled lines (the form of the corpus, `split: "local"`, ids `local-NNNNN`, kept outside any repository): one run, counts per
  language written and printed, no id and no line. It refuses `--record`, `--resume`, `--replay`, `--sample` and `--sequential`. It can demote a route, never promote one.
- The current pipeline is measured by a test, not by this script: `WB_IX_CURRENT_CORPUS=<file> WB_IX_CURRENT_EVIDENCE=<dir> uv run --with pytest==9.1.1 pytest -q --tb=line -rP
  -p no:cacheprovider runtime/tests/test_interpreter_current_arm.py -k test_current_arm_full_run` writes one `arm: current` event for the file (for the test split, with pytest's
  `--basetemp` inside the corpus file's folder: the stand-in messenger writes the replies to disk; `-rP` shows the counts, which pytest hides under `--tb=no`). It makes no call and writes the event only after
  it checked that no run crashed and that at most 5% of the items are unseeded (above that it fails with the counts and writes nothing, so the maintainer decides).
- A clarification that an item lists as acceptable (`also: [{"outcome": "clarify"}]`) is `correct`: the alternatives of `also` are part of the matching of rule 8, and rule 7 is for a
  clarification no alternative lists. Such an item keeps its gold (`op`), so it stays in the denominators of `correct_direct` and is not counted in `clarify_rate`.
- Residues, stated with every result: the arms cannot see resolution failures, the card's rendering, the per-sender policy or approval by word (see the architecture page); the
  current arm seeds the open items of a frame as today's drafts and an item with no equivalent (a `choice`, a write confirm, a reminder confirm whose `when` has no single reading)
  runs with no open item, counted as `unseeded` and stated beside the numbers (up to 5% of the split is accepted); a private line that asks for work is `route` in the corpus (L7)
  and `clarify private-route` in code, scored as a clarification by the frozen rules, with its count printed beside the clarify rate; a model confirm counts only when code reads
  the same yes or no, so a "sure thing" the model calls a yes is asked again.

## The long-line dev file and its measurement plan (BL3)

`dev-long-v1.jsonl` holds 46 long lines (pt-BR 24, en 10, es, fr, de and it 3 each), all fictional (invented people, places and titles; no address, no phone number), with golds written by the
specification and a fixed clock, `2026-10-27T09:30` (a Tuesday; no line names Tuesday), in the zone of the line's language. By operation: event-cancel 10, event-change 6, mail-reply 4, mail-archive 2,
mail-trash 2, mail-move 1, mail-mark 1, cancel 5, stop-task 1, items 6, file-read 2, research 3, answer 1, none 1, route 1. Five lines carry a `plan-confirm` frame (the question "Posso?" of the plan, answered
by a number, a "sim" or a new request); 17 carry polite or extra words (`filler`). It measures what the catalog's `target` and `day` slots (BL1) and the plan-confirm frame (BL2a) changed; the frozen
`dev.jsonl` and the replay gate (which read `dev.jsonl` only) are untouched. It is **dev evidence**: its golds were not labelled blind, so it is never the gate's held-out split and its result never replaces
the frozen gate's. The de and fr `event-change` lines (`dev-de-50001`, `dev-fr-50001`) stay asked after BL5C: the time engine has tables for pt-BR and en only, so the check's refusal to read their time is correct, and their golds still say `op` (what the platform should do); the miss is reported, not hidden.
`runtime/tests/test_interpreter_dev_long.py` checks the form offline (canonical, sorted, ids in the 50000 range, every item and frame against the served catalog and `natural.NATURAL`, every span a piece of
its line, no line of the frozen sets, the counts as literals). Reading the file costs no model call.

**The measurement is written down here and NOT run by this package: it needs the maintainer's explicit "pode".** Run it from the supervisor's own clone of the integration branch with BL1, BL2a and BL3
merged, one run at a time, never from the live checkout. A folder holds exactly one answers file, so each run records into a folder of its own, outside the repository
(`--record /private/tmp/<session>/ix-blite/<route>/<run>/`); the harness writes the evidence to `evals/interpreter/evidence/` and the supervisor commits it, with the recorded answers copied under
`evals/interpreter/replay/<route>/blite-<date>/` (an exact-path `english-only` line in `.security-scan-allow` for each file), in one pull request, so later code changes can be replayed against them with no call.

| Run | Command (after `--corpus`) | Calls | Cost |
|---|---|---|---|
| M1a, the long set on the daily route | `evals/interpreter/dev-long-v1.jsonl --route or-deepseek-v4.1-flash --runs 2 --record <dir> --evidence-dir evals/interpreter/evidence` | 92 | about US$ 0.04 (92 x US$ 0.00044, the median of the 2026-10-21 event) |
| M1b, the long set on the reference | the same with `--route acct-claude-sonnet-5.5` (the maintainer's account; Claude never goes through OpenRouter) | 92 | subscription quota, about 4 minutes at 2.5 s a call |
| M2a, regression, daily | `evals/interpreter/dev.jsonl --route or-deepseek-v4.1-flash --sample 50 --seed 20261025 --runs 1 --record <dir>` (the draw of the recorded iteration-2 event) | 50 | about US$ 0.02 |
| M2b, regression, reference | the same with `--route acct-claude-sonnet-5.5` | 50 | subscription quota |
| M3 (optional) | `evals/interpreter/ix-test-v1.jsonl --route or-deepseek-v4.1-flash --runs 2 --record <dir outside the checkout>` (the spent split: regression only, never tuned against) | 1,600 | about US$ 0.70 |

Metered cost without M3: about US$ 0.06; with M3: about US$ 0.76; plus the reference route's quota on the maintainer's account. M3 stays optional, at the same "pode".
The recorded events to compare M2 with: DeepSeek `ix-20261021T155019Z-f148397b` (50 items, correct 46, clarify 4) and Sonnet `ix-20261021T184159Z-cda87ebe` (correct 48, clarify 2).

**The pass rule, against the frozen `thresholds.json` (no threshold changes):**

1. Hard: `wrong_effect_unconfirmed` is 0 in every event (M1 and M2). A card the person approves is not an unconfirmed effect; a plan that ran without its OK would be.
2. M1, each route: `correct_direct` is at least 0.85 on the pt-BR items and on the en items. Spanish, French, German and Italian (3 items each) are reported as "not decidable at this n".
3. M1: `clarify_rate` is at most 0.15; per language, the point rate of `wrong_card` is at most 0.03 (pt-BR and en); the point rates of `wrong_read`, `wrong_reminder_reading` and `wrong_item_binding` are reported beside it against the same 0.03.
4. M1: the Wilson upper bounds of 0.02 (`wrong_card`, `wrong_read`, `wrong_reminder_reading`, `wrong_item_binding`) are not reachable at 92 runs (0 of 92 gives an upper bound of about 4.0%): reported as "not decidable at this n", as in IX-3b.
5. M2, against the recorded events of the same draw: `correct` is not lower than the recorded count minus 2 (DeepSeek 46, so at least 44; Sonnet 48, so at least 46) and no `wrong_*` category is above its recorded count (0 for both): the
   additive slots did not hurt the old lines.
6. Daily route: p95 latency at most 4,000 ms and median cost at most US$ 0.002 per line (read from the event; a run that goes out `--jobs` calls at a time reads its latency under that load, which the result states).
7. The current-pipeline arm is not run on the long set: the old catalog refuses golds with `target`, so "versus current" is read on M2 only.

A rule not met is published as it is (principle 10) and the maintainer decides, as on 2026-10-21 for B-prime: the interpreter stays on only through the dated enabling entry BL1 added, whose status line says
"served before its measurement". Never silently on, never a threshold edited, never a new evidence kind.

### The prompt in use after BL5B (2026-10-25)

The prompt gained rule 9 and three worked examples (a no that changes the request after "Posso?" is the corrected request, an `op` object), so its sha256 is now `1423ba89...` (`interpreter_prompt` in
`scripts/tests/pinned_hashes.json`; the newest entry of `runtime/interpreter_enable.json` names it, "served before its measurement"). The answers recorded by the B-double-prime-lite measurement
(`blite-20261025T003348`) and every older in-use answers file were recorded at the previous prompt, `5bee55ce...` (`interpreter_prompt_5bee`): they stay as a regression of the CODE on answers given to
the old prompt (the tests build `Answers` directly, as `runtime/tests/test_interpreter_replay_gate.py` does), the CLI's `--replay` refuses them by their header (`prompt_sha256`), and a replay of
them says what the code does with those answers, never what the new prompt makes a model say. The effect of rule 9 is measured only by new answers: M1 and M2 on both routes, with the maintainer's "pode".

### The prompt in the BL7-3 pull request (2026-10-26)

The prompt of package BL7-3 teaches four things the blind measurement of 2026-10-25 showed missing: a reply or an e-mail whose text the person describes ("agradecendo...", "thanking her for...") is `mail-reply`
with the description as the body, not `route` (rule 10, and rule 8 now says "writing a document"); a message named by its sender and its subject keeps both in `target` (rule 11); a slot the line fills is never put in
`inherit`, and words that only say which items the person meant do not name another op (rule 9); two worked examples. Its sha256 is `3112db68...` (`interpreter_prompt` in `scripts/tests/pinned_hashes.json`);
`interpreter_prompt_1423` keeps the hash that the recorded answers of BL5F and BL7-0 name, so their replay tests are unchanged. The newest entry of `runtime/interpreter_enable.json` (2026-10-26) names it, so on the head of this pull request
the interpreter is on with the new prompt (limit L63, part 2). It was measured on this pull request's head on blind set 2 (`blite-blind-2-v2-split.json`) and served by the maintainer's decision of 2026-10-26, below the gate on the pt-BR wrong-card rate (OPEN-BL7-C, recommendation (a); the figures are in `docs/decisions.md`).
The recorded answers cannot measure this prompt: a replay says what the code does with answers given to the old prompt, never what the new prompt makes a model say.
