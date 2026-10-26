# blite-blind (v1, v2): a blind held-out set of long lines for the interpreter

60 fictional long lines (pt-BR 30, en 15, es 4, fr 4, de 4, it 3), split `test`, author `opus`, ids
`test-<lang>-60001...` (a range of their own, so they never collide with `ix-test-v1.jsonl`'s ids). It was written blind:
the author did not open the earlier long set, its results, its replay answers, its evidence, the specifications made
from it, or the plan's progress files. It was frozen on 2026-10-25, before any model read it. It is measured once.

| File | What it is |
|---|---|
| `blite-blind-v1.jsonl` | the set: canonical items (the repository's `corpus_bytes`), sorted by id |
| `blite-blind-v1.jsonl.sha256` | its sha256 |
| `blite-blind-split.json` | the summary, in the shape of `evals/interpreter/test-split.json` (file, sha256, items, counts, frozen) plus counts by frame and items with `also` |
| `blite-blind-v2.jsonl`, `blite-blind-v2.jsonl.sha256`, `blite-blind-v2-split.json` | **v2, the set to measure**: v1 with the changes of the changelog below, same shape (sha256 `984356db30069dcbc64c24b925ec975c031dd9049475a8e81fbb493a73db58f0`) |
| `README.md` | this file: the span rule, the gold rules applied, the debatable calls, how to measure, the changelog |

The builder (literal items, the repository's own checks, the writer) is outside this folder and outside the repository:
a builder script kept outside the repository (`build.py` for v1, `build_v2.py` for v2, from v1).

## Moments and zones

Two clocks: `2026-11-04T10:15` (a Wednesday) for 58 lines, `2026-11-09T19:40` (a Monday) for `test-pt-br-60027` and
`-60028`. No line names its clock's own weekday. Zones by language: America/Sao_Paulo, America/New_York, Europe/Madrid,
Europe/Paris, Europe/Berlin, Europe/Rome. No moment is near a clock change. Every hour is unambiguous (a 24-hour form,
an `h`, `pm`, `Uhr`, `meio-dia`), except where the README rule "next with a weekday" applies (`test-pt-br-60003`: both
Tuesdays listed, `clarify` as an also).

## The span rule (rule B1, one rule for every span value)

1. **Core.** The shortest contiguous piece of the line that holds every content word of the value as the line writes it
   (names, nouns, adjectives, numbers, day and hour words, quoted titles). Courtesies, fillers, discourse words, the verb
   of the request, and a relative clause about the item ("que chegaram ontem", "reçus hier") are never part of it.
   A typo stays as typed; nothing is translated or fixed.
2. **Left widening.** The core is also accepted with the one or two function words (article, preposition, a contraction
   of both, possessive or demonstrative determiner, a quantifier such as "every") that stand immediately to its left in
   the line, each widening a piece of the line. Nothing is ever added at the right edge.
3. **Family noun (mail and files only).** For a mail `target` or a `file`, when a generic family noun stands immediately
   before the name or subject (e-mail, email, mail, mails, message, correo, correos, newsletters, arquivo, planilha), the
   value is also accepted with that noun, and with the noun's own function words (rule 2 again). The family noun is the
   only word that may be absent from an accepted value; a subject word ("promoção", "boletos", "palestra") is a content
   word and is never dropped. Event names have no family noun.
4. **Time and day.** A `time` or `when` span is the whole time phrase (day plus hour, as the line gives it), with and
   without its preposition; an hour alone is not accepted when the line gives the day. A `day` span is the day word, with
   and without its preposition; a part-of-day phrase that sits right after the day word ("à noite") is accepted inside or
   outside the span.
5. **Body of a reply.** The reported content, accepted with and without the words that introduce it (the verb phrase and
   the conjunction: "dizendo que", "que"; "tell him"; "diciendo que").
6. **Research question.** From the first word that says what to find out (an interrogative or auxiliary included) to the
   last place or day word of the question being asked. A place, day or value the line negates or turns down ("não em
   Morro Azul", "not the calendar") is never part of the question: the span ends before it. Rule 2 applies; a leading
   "whether" or "se" is optional.
7. **Int and ints.** Digits as written; `ints` joined by commas in the line's order.
8. **Word slots** (`service`, `folder`): the one word only.

## Gold rules applied (from `evals/interpreter/README.md` and `contracts/runtime.md` L61)

- The slot set is exact. An E op is `op` only when its required slots are readable: an event or message named by its words
  (`target`, plus `day` when the line gives one), a new time or title for a change, title and time for a create, a body
  for a reply. A write with no target is `clarify`, never an op with a guessed slot.
- **Corrections after "Posso?"** (13 lines): the frame is a `plan-confirm` item (R8) about `frame.last`; a line that says
  no and changes the request is the corrected request, an `op` gold with the op of `frame.last`, the new detail as spans
  of the line; never an `answer` with `confirm`. Ops used under plan-confirm: cancel, stop-task, research, items,
  file-read (reads, research and W ops confirm first).
- For a `plan-confirm` item, `contracts/runtime.md` L65 and the prompt's rule 9 replace L4's
  `{"outcome": "answer", "confirm": "no", "slot", "span"}` form; that form stays for the `need: confirm` items of writes.
- A reply whose content is reported is `mail-reply` with `route` as an also; a reply whose wording is left to the platform
  ("explicando com jeitinho") is `route` with `clarify` as an also.
- A bulk request that no op does (delete everything older than two years, sort a year of mail into folders) is `route`
  with `clarify` as an also; an open-ended task (plan my week, summarise my week's mail) is `route`.
- A line with no target at all ("cancela aquela lá que eu te falei", "get rid of that one", "empurrar aquilo") is `clarify`.

## Debatable calls, decided before any measurement

- `test-pt-br-60008` (`target`): "promoção" is a subject word, so "Loja Vento Sul" alone is not accepted (it would pick
  every mail from the sender).
- `test-pt-br-60007`: "newsletters" counts as a family noun, so "Livraria Sabiá" alone is accepted.
- `test-pt-br-60014`: "Para a tarefa 17" is the verb *parar*, `stop-task`, not the preposition.
- `test-pt-br-60029`: the person corrects themselves mid-line ("... digo, nos e-mails"): `items`, no also.
- `test-en-60008`: "from my drive" is not the words Google Drive or OneDrive, so no `service` slot.
- `test-de-60004`: "8 Uhr" is 08:00; the remind text accepts "daran," at its left (a contraction of preposition and
  pronoun, rule 2).
- The es, fr, de and it lines with a time: the time engine has tables for pt-BR and en only, so code may ask; the gold
  still says what the platform should do, and such a miss is reported, not hidden.

## Validation (offline, no model call)

- `python3 scripts/interpreter_corpus.py check --in <this folder>/blite-blind-v1.jsonl`: 60 items, 0 problems; the same
  for `blite-blind-v2.jsonl`: 60 items, 0 problems.
- `runtime/interpreter_measure.py`'s `load_corpus` (the pipeline's item and frame checks against the served catalog):
  60 items loaded for v1 and for v2; `split_of`: `test`.
- No line equals (after `natural.normal`) a line of `dev.jsonl`, `dev-relabelled.jsonl` or `ix-test-v1.jsonl`.

## How to measure it

Today the harness refuses it: a corpus of split `test` must hash to `evals/interpreter/test-split.json` (the spent
`ix-test-v1`), so `interpreter_measure.py` answers "the corpus is not the test split". The smallest change, for a later
package:

1. `runtime/interpreter_measure.py`: an option `--split-file FILE` (default `evals/interpreter/test-split.json`); in
   `measure()`, read `declared` from that file instead of `SPLIT_FILE`, and pass it to
   `evidence.corpus_sha256(split, args.corpus, args.split_file)`, so the event's `corpus_sha256` is the hash of this
   summary and the event can never be mistaken for an `ix-test-v1` event. Every other test-split guard stays as it is
   (runs from `thresholds.json`, answers outside the checkout, no line printed).
2. Check that `evals/interpreter_status.py` reports an event whose `corpus_sha256` is not the hash of
   `test-split.json` apart from the gate's band (a held-out long set, not the gate split), and add a test for both.

Then, with the maintainer's go-ahead for the calls, one folder per route and run, from the supervisor's clone:

```
python3 runtime/interpreter_measure.py --corpus evals/interpreter/blite-blind-v2.jsonl --split-file evals/interpreter/blite-blind-v2-split.json --route or-deepseek-v4.1-flash --runs 2 --record <a folder outside the checkout>/ix-blind/or-deepseek-v4.1-flash/r1/
python3 runtime/interpreter_measure.py --corpus evals/interpreter/blite-blind-v2.jsonl --split-file evals/interpreter/blite-blind-v2-split.json --route acct-claude-sonnet-5.5 --runs 2 --record <a folder outside the checkout>/ix-blind/acct-claude-sonnet-5.5/r1/
```

120 calls per route. Do not relabel the items as `dev` to avoid the change: that alters the bytes and the ids, and drops
the held-out guards. Once measured the set is spent, like `ix-test-v1`.

## Changelog

### v2 (2026-10-25), before any measurement

From an independent isolated checker who read all 60 items of v1 and found no wrong gold, but three alternatives that
rule B1 requires and v1 lacked. No model had read the set. v1 stays frozen and untouched
(`0912d128331db46e28a35c7e180355f19330d125af7d60c8ae0dceb9fc17dc4d`); v2 is
`984356db30069dcbc64c24b925ec975c031dd9049475a8e81fbb493a73db58f0`, and it is the set to measure.

1. `test-de-60004`, slot `text`: added "Pflanzen von Frau Kesselbach zu gießen" (the article "die" is a left widening,
   not core: B1.1, B1.2).
2. `test-en-60009`, slot `question`: added "Harborview ferry is running this Sunday" (the form without the article, as
   the other research items have: B1.6, B1.2).
3. `test-en-60005`, slot `target`: added "to the email from Gideon Farrow about the warehouse lease" (rule 3 with rule 2,
   as `test-es-60002` has "al correo de ...").
4. `test-pt-br-60005`: tag `typo` changed to `no-accents` ("to" for "tô").
5. This README: B1.6 worded so a negated place cannot end the question (`test-pt-br-60030`'s gold was already right);
   one line saying that L65 and prompt rule 9 replace L4's `confirm: no` form for plan-confirm items.

`test-pt-br-60003`'s `also` is unchanged. No other item, gold, slot set or line changed.

## On publication (2026-10-26, package BL7-0)

The set was measured once on 2026-10-26, at commit `440b4d2`, on both routes (`or-deepseek-v4.1-flash` and `acct-claude-sonnet-5.5`), 2 runs, 120 calls each, with catalog `a77f8a8f...` and
prompt `1423ba89...`. It is spent. It is published here as it was: `blite-blind-v1.jsonl` (never measured; history), `blite-blind-v2.jsonl` (the measured set), the checker's findings
(`blite-blind-check.md`), the two recorded answers files under `replay/<route>/blind-20261026/` and the two evidence files `ix-20261026T025216Z-aa31e463.jsonl` and
`ix-20261026T025351Z-4b4e44f0.jsonl` under `evidence/`.

The result, as published (SPEC-BLITE-3 section 5 pass rules, per item, worst of 2 runs; 60 items):

| Rule | DeepSeek | Sonnet |
|---|---|---|
| 1. wrong_effect_unconfirmed = 0 (hard) | pass (0) | pass (0) |
| 2. correct_direct >= 0.85, pt-BR / en | 0.857 pass / 0.786 fail | 0.893 pass / 0.929 pass |
| 3. clarify_rate <= 0.15 | 0.123 pass | 0.035 pass |
| 3. wrong_card point rate <= 0.03, pt-BR / en | 0.033 fail (1/30) / 0.133 fail (2/15) | 0.067 fail (2/30) / 0.000 pass |
| 4. Wilson upper bounds (<= 0.02) | not reachable at n = 60 (wrong_card 0.137) | not reachable (0.114) |

Totals: DeepSeek correct 48, clarify 7, wrong_card 3, wrong_read 1, wrong_route 1 (correct_direct 0.807); Sonnet correct 54, clarify 2, wrong_card 2, wrong_read 2 (correct_direct 0.895).
0 errors, 0 parse failures, 0 private-route leaks. Below the gate; the maintainer decides. This is the blind number: every later replay of these answers is a dev re-score, never a blind
number.

Three edits were made for publication, and no other byte of the set, its README or its check file changed (no item, gold or line was changed):

1. The builder's absolute scratch path in the "Files" section is replaced by "a builder script kept outside the repository".
2. The two measuring commands in "How to measure it" name the committed paths (`evals/interpreter/blite-blind-v2.jsonl`, `evals/interpreter/blite-blind-v2-split.json`) and
   `--record <a folder outside the checkout>/...`. That section is now history: package BL6 built `--split-file`, and the set was measured with it.
3. In `blite-blind-check.md`, the absolute path of v1 is replaced by `evals/interpreter/blite-blind-v1.jsonl`.
