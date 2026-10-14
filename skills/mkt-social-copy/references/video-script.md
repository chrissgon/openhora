# Writing the script of a video or images post

Read at step 4 of `SKILL.md`, after `../../shared/references/video-presets.md` (the preset vocabulary). The script is the ```script block of the output template.

## Syntax

One `key: value` per line, a key in lowercase, one space after the colon, beats separated by a blank line, `beat:` numbered 1, 2, 3 and so on. A video script opens with a **header** (below), then the beats. The beat keys are `beat`, `line`, `role`, `emphasis`, `on-screen`, `preset` and the parameters of the chosen preset. The main text parameter of the preset is the beat's `on-screen` line and is never written under its own name as well; `check_script.py` refuses a parameter the preset does not declare, a main parameter written twice and any field that carries a time.

The header, at the top of the block, before `beat: 1`: one line each, each key at most once, in any order.

```
hook_type: number
title: Three habits that matter
cta_kind: send
send_to: a friend who wants to save
loop: no
pattern: list
```

`hook_type` (one of contrarian, mistake, result, curiosity, number, question, story) and `title` are always written for a `reel` or `video`. `cta_kind` (save, send, comment, follow-up-video) is written because the script has a `cta` beat; `send_to` (at most 40 characters) only when `cta_kind` is `send`. `loop` (yes or no) and `pattern` (list, myth, story, problem-solution, before-after, steps) are optional: write them only when the script is built that way. A carousel or static post has no header.

Every beat of a video script also carries `role:` (hook, setup, point, proof, turn, payoff or cta), and `emphasis: punch` only where a punch-in is wanted (otherwise leave `emphasis` out). Beat 1 is the `hook`; the `cta` is the last beat.

Example of a `number` beat: the label is the on-screen text and the figure is `value`.

```
beat: 3
line: That habit saved me 340 euros in one month.
on-screen: euros saved in one month
preset: number
value: 340
```

Writing `on-screen: 340` is wrong: the label is the text, `value` holds the figure.

## The block's template

A `reel` or `video` script, header first. Remove the header lines that do not apply (`send_to` unless `cta_kind` is `send`; `loop`, `pattern` and `emphasis` unless the script is built that way). `check_script.py` refuses an unfilled placeholder as an unknown value.

```script
hook_type: <contrarian | mistake | result | curiosity | number | question | story>
title: <3 to 5 words, each a word of beat 1's line>
cta_kind: <save | send | comment | follow-up-video>
send_to: <only when cta_kind is send: who to send it to, at most 40 characters>

beat: 1
role: hook
line: <the exact words the person says>
on-screen: <the preset's main text, written here and nowhere else>
preset: <keyword | list | number | quote | cutaway | pip>
<parameter>: <value, one line per parameter the preset declares besides its main one>

beat: 2
role: <setup | point | proof | turn | payoff>
line: <the exact words>
preset: cutaway
asset: <what to show, in words: a screenshot of ..., never a path or a link>
fit: <cover | contain>

beat: 3
role: proof
line: <the exact words, with a figure from step 3's list written as digits>
on-screen: <the label of the figure, not the figure>
preset: number
value: <the figure as the material gives it>

beat: 4
role: cta
line: <a beat with no animation has only its role and its line>
```

A `carousel` or `static` script has no header, no role and no emphasis: each beat holds `beat` and the `line` the image carries, and nothing else.

## Video formats (`reel`, `video`)

- A beat is one spoken thought, written as the exact words the person says, in the slot's language, in short spoken sentences. The lines together are everything the person says. Every fact in a line is on step 3's list.
- Length: as long as the user says, and inside the format's `Duration:` line of the reference. **One speech rate everywhere: 2.5 words per second** (150 words a minute). The default target is 60 to 90 seconds, 150 to 225 words, 120 seconds (300 words) at the most; when the user gives no length, aim at that and list it under Assumptions. A shorter or longer script is allowed and `check_script.py` only warns.
- Order: the voice's post structure, hook first.

## The roles

| Role | What the beat does | Example line (the function matters, not the wording) |
|------|--------------------|------------------------------------------------------|
| `hook` | the first beat: the promise or the claim | "Most people rehearse the wrong interview answer." |
| `setup` | the context the point needs | "I have coached engineers through hiring loops for years, and one habit sinks them." |
| `point` | one idea that keeps the hook's promise | "First, answer in the order the interviewer asked." |
| `proof` | an example, a number or a quoted verse that backs a point | "In one mock round, switching the order made the answer half as long." |
| `turn` | the reversal or the twist | "But the real problem is not the order." |
| `payoff` | the answer the hook opened; sits late | "Lead with the decision, then give the reason, and the answer stays short." |
| `cta` | the one ask, the last beat | "Send this to someone preparing for an interview this week." |

## The eleven rules: what the checker enforces, what you judge

The checker reads a **closed predicate**: a count, a digit token (a run that starts with a digit, with `.` or `,` inside), a word of a language list in `../../shared/references/video-presets.json`, a quoted span. It never judges taste: the quality half of each rule is yours, at step 11. A script with a header or a role is a version 2 script and every rule below is a refusal (`"problems"`), except where it says warning; a script with neither is a version 1 script, and the same rules are warnings, so that it keeps passing.

| # | The checker enforces | You judge |
|---|----------------------|-----------|
| 1 Open with the promise | beat 1 has role `hook`; its line has at most 18 words and starts with no opener phrase of the language list; by `hook_type`: `number` has a digit token in its first sentence, `question` ends with `?`, `mistake` and `contrarian` hold a negation word | the line makes a claim a viewer wants resolved; a `result` or `curiosity` hook withholds the method |
| 2 The title mirrors the key phrase | `title` has 3 to 5 words, each a word of beat 1's line; beat 1's on-screen text, if any, holds 2 to 5 words of that line | the title is the phrase a viewer would remember |
| 3 Open a loop, close it late | a `payoff` beat exists, comes after more than half of the beats, and holds a word of the title that is not a stop word | the payoff answers the hook, not merely repeats it |
| 4 One idea per beat | a line over 30 words is refused; a line under 8 words warns, except a `turn` | one idea per beat |
| 5 A visual event at least every 6 s | a warning when a run of beats with no preset and no `emphasis: punch` holds more than 15 words | events fall where the idea changes |
| 6 Vary presets | no preset on more than half of the beats; a `list` has 2 to 4 items; a `number` beat's `value` is a digit token of its own `line` and of the material | each preset serves its idea |
| 7 Match the pattern to the roles | when `pattern` is written, the roles (or presets) its row needs are present | the `turn` really states the truth |
| 8 End on one CTA | exactly one `cta` beat, the last, of at most 20 words; `cta_kind` written; `send_to` written for `send` | the line before it is the payoff, not a recap; the ask is specific |
| 9 The register leaves room | with `--register calm`: at most one preset per 20 words, no `emphasis: punch` on a `turn` or a `payoff`, and a quoted span of 3 words or more is a `quote` beat with its `author` | the script fits the voice file |
| 10 No invented facts | every digit token of a spoken line is a digit token of the material | every name and every quoted verse exists in the material, or is left out (a number or a name the material lacks is Stop rule 4, not a rule of this table) |
| 11 Length | a warning, never a refusal, when the spoken words are outside 150 to 225 (300 is the most) | the length fits the content |

Also checked: `emphasis: punch` at most once in any three beats and at least 25 words (10 seconds) between two; with `loop: yes` the last line holds no goodbye word of the language list (the video ends where it begins, with no end card).

## What to pass to the checker

- `--language <the slot's language, as the calendar writes it: EN, PT-BR>`: without it the checks that read the word lists are skipped with a warning.
- `--register calm` when the voice guide's `## Register`, `## Spoken register` or `## In one sentence` section holds the word calm, quiet, gentle, devotional, reverent or serene; `--register neutral` otherwise. When the guide has none of those sections or says nothing of register, pass `neutral` and list `Assumption: neutral register (the voice guide does not state one)` under Assumptions.
- `--material <file>` once for each file of step 3's material, and `--figure <token>` for each figure the user stated that no file holds: without them rule 10 and the material half of rule 6 are skipped with a warning.

A warning is read, never ignored: fix it when you can, and list what stayed in the reply.

## Each beat's picture

- From the vocabulary only. A beat carries one preset with its parameters as the vocabulary declares them, or none (the person just talks, and the beat has only its `line`).
- The on-screen text goes in `on-screen` and nowhere else. It is the few words worth reading, not a second copy of the spoken line. On the hook beat, the on-screen text, when there is one, repeats 2 to 5 words of the hook line.
- A `number` beat is only for a number on step 3's list, with the value written as the material gives it and the unit in the label, and with that figure written in the beat's own `line` as digits.
- A layout preset (`cutaway`, `pip`) only when the user or the material says the person has something to show. Its `asset` is a description in words of what to show, never a file name, a path or a link.
- Vary the presets: not every beat is a `keyword`. Leave optional parameters (`icon`, `color`) out unless the voice or the strategy asks for them.

## What the vocabulary does not offer

A colour that is not a palette token, a font, a transition that is not listed, a sound, a position that is not listed: not written. Use the nearest allowed value or none, and say what was not available in the reply's `Left out`.

## No time of any kind

No timestamp, no duration, no "at 0:05", no "for 3 seconds" as a beat's timing, in any field. The program places each preset over the words of its beat's line. A figure the person says as a fact ("it took me 10 minutes") is content and stays in the line.

## Image formats (`carousel`, `static`)

- A beat is one image: its `line` is the exact text the image carries, in the slot's language, within the reference's limits. The beats have no preset, no `on-screen` and no asset. A static post has one beat.
- The number of beats stays inside the format's `Items:` line of the reference (a static post has one image); when the reference marks a limit `not checked`, say so under Assumptions.
- When the reference says the format is described but not yet produced, write it anyway and say in the reply that nothing makes its images yet.
