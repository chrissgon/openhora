# Video presets

The closed list of animations a short video's script may ask for, one per beat. A beat of a script names one preset below and gives its parameters; nothing else is allowed. The same list, as data, is `video-presets.json` in this folder: a checker reads it through a flag, and so does the program that draws the video. This file is the prose a model reads when it writes a script; the two are held equal by a test.

Read by: `mkt-social-copy`, at the step that writes the script.

## What a beat can and cannot ask for

- A beat names at most one preset. A beat that needs nothing drawn (the person just talks) names none and has only its spoken line, so that the script holds everything the person says.
- **Captions are always on.** Every spoken word is captioned by the program; `caption` is not a preset and no beat asks for it.
- A beat writes the parameters its preset declares, and no other. A look that no parameter offers (a colour that is not in the palette, a font, a transition, a sound, a position that is not in the list) is not available: write the nearest allowed value or none, and tell the person it was not available.
- **One on-screen text per beat.** Every preset has one main text parameter (the `Main` line of its section). The beat's `on-screen` field IS that parameter: write it there and never again as another parameter.
- **No time anywhere.** A beat has no start, end, duration, delay or timestamp, and a slot description holds none. The program places each preset over the words of the beat's spoken line.
- **Texts are short and plain**: no line break and no control or invisible character. A text longer than its bound is shortened by the writer, never cut by the program.
- **An asset slot is described in words, never named by a file.** A parameter of type `image` or `clip` takes a short description of what to show ("a screenshot of the budgeting dashboard"). It holds no file name, no path and no link. The person uploads one file per slot after recording; for a clip, the person sets which part of it to show, so a description never says "the first five seconds".

## Parameter types and their bounds

| Type | Value | Bounds |
|------|-------|--------|
| `text` | plain text | `max` characters; `max_items` (above 1: that many texts on one line, each within `max`, see below); `pattern` (the whole text matches it) |
| `icon` | one name | one of: check, star, bolt, arrow-up, heart, flag, clock, coin |
| `color` | one token | one of: bg, text, muted, accent, chip_fill, chip_text, chip_border (the tokens of the brand identity's palette; a hex code or a colour name is refused) |
| `image` | an asset slot | a description of 3 to 80 characters: a picture the person uploads (PNG, JPEG or WebP) |
| `clip` | an asset slot | a description of 3 to 80 characters: a clip the person uploads (MP4 or MOV) |
| `choice` | one value | one of the values the parameter lists |

The texts of a parameter with several items are written on one line, separated by a vertical bar with a space on each side: `Review | Adjust | Celebrate`. An item holds no vertical bar.

A parameter of type `image or clip` takes either: the description says which ("a screenshot", "a short screen recording").

A script has at most 12 beats and a spoken line of at most 240 characters.

## The presets

### keyword

- **Shows:** one short phrase that pops on screen while the person says it, the way a creator underlines the rule of the video.
- **Use when:** the beat states a rule, a name or a takeaway in a few words. The most common preset; use it for the hook and for the line the video ends on.
- **Main:** `text`.

| Parameter | Type | Bounds | Required |
|-----------|------|--------|----------|
| `text` | text | up to 24 characters | yes |
| `icon` | icon | the list above | no |
| `color` | color | the palette above | no |

### list

- **Shows:** up to four short items that appear one after the other.
- **Use when:** the spoken line names two to four parallel things (steps, habits, tools). Not for one thing: use `keyword`.
- **Main:** `items`.

| Parameter | Type | Bounds | Required |
|-----------|------|--------|----------|
| `items` | text | 1 to 4 texts, each up to 30 characters | yes |
| `icon` | icon | the list above, drawn beside every item | no |
| `color` | color | the palette above | no |

### number

- **Shows:** one figure that counts up, with a short label under it.
- **Use when:** the line states one measured number that the material gives. The value is written as the material gives it; a unit or a sign goes in the label, never in the value. Never for a number the material does not have.
- **Main:** `label`.

| Parameter | Type | Bounds | Required |
|-----------|------|--------|----------|
| `value` | text | up to 10 characters: digits, with `.` or `,` inside | yes |
| `label` | text | up to 40 characters | yes |
| `color` | color | the palette above | no |

### quote

- **Shows:** a sentence someone said, with the name of who said it.
- **Use when:** the line repeats someone else's words that the material records, with their name.
- **Main:** `text`.

| Parameter | Type | Bounds | Required |
|-----------|------|--------|----------|
| `text` | text | up to 120 characters | yes |
| `author` | text | up to 40 characters | no |
| `color` | color | the palette above | no |

### cutaway

- **Shows:** the whole frame shows a picture or a clip the person uploads while the line is spoken; the speaker is not on screen, only heard.
- **Use when:** the line talks about something that is better seen than said and the person has it (a screenshot, a chart, a screen recording, a photo of the result). Not when the person has nothing to show: use another preset.
- **Main:** `label`, optional: a few words shown over the picture.

| Parameter | Type | Bounds | Required |
|-----------|------|--------|----------|
| `asset` | image or clip | a description in words | yes |
| `fit` | choice | `cover` (fills the frame, crops the edges) or `contain` (whole picture, bars around it) | no, default `cover` |
| `label` | text | up to 40 characters | no |

### pip

- **Shows:** a picture or a clip the person uploads in a bubble over the speaker, who stays on screen.
- **Use when:** the person talks through something they show at the same time (a chart while explaining it).
- **Main:** `label`, optional: a few words shown beside the bubble.

| Parameter | Type | Bounds | Required |
|-----------|------|--------|----------|
| `asset` | image or clip | a description in words | yes |
| `position` | choice | `top` or `bottom` | no, default `top` |
| `label` | text | up to 40 characters | no |

## Choosing

- One preset per beat; a script of a 30-second video holds about three to six beats, not one per sentence.
- Do not use the same preset for every beat: a script of only keywords is flat. Prefer the preset the content calls for (a number for a measured figure, a list for parallel things).
- A layout preset (`cutaway`, `pip`) is only written when the person has the material to show. Ask when it is not known.

## The script's own vocabulary (version 2 of the data file)

Besides the presets, the data file's `script` section lists what a script means. **No field here is a time**; code turns roles into timing.

- **Beat `role`**, one per beat: `hook` (the first beat: the promise or the claim), `setup` (the context the point needs), `point` (one idea that keeps the hook's promise), `proof` (an example, a number or a quoted verse that backs a point), `turn` (the reversal or the twist), `payoff` (the answer the hook opened; sits late), `cta` (the one ask, the last beat).
- **Beat `emphasis`**: `none` or `punch` (a punch-in on that beat, drawn by the renderer's framing layer). At most one `punch` in any three beats, and at least 25 words, 10 seconds at the speech rate, between two.
- **The header**, at the top of the script block, before the first beat: one `key: value` line each, each key at most once, in any order. `hook_type` (contrarian, mistake, result, curiosity, number, question, story) and `title` (3 to 5 words, at most 40 characters) are required for a `reel` or `video`; `cta_kind` (save, send, comment, follow-up-video) is required when a `cta` beat exists; `send_to` (text, at most 40 characters) is required when `cta_kind` is `send` and refused otherwise; `loop` (yes or no); `pattern` (list, myth, story, problem-solution, before-after, steps), optional.
- **One speech rate: 2.5 words per second** (150 words a minute). 6 seconds are 15 words, 10 seconds are 25 words, 60 to 90 seconds (the default target) are 150 to 225 words, 120 seconds (the most) are 300 words. A word is a whitespace-separated token with at least one letter or digit.
- **Thresholds** (all in the data file's `script.limits`): a hook of at most 18 words; a line of 8 to 30 words (shorter warns, except a `turn`; longer is refused); a `cta` of at most 20 words; no preset on more than half of the beats; a `list` of 2 to 4 items; at most one preset per 20 words in the `calm` register; a quoted span is 3 words or more.
- **Language data** (`script.languages`, one entry per language: `en`, `pt-BR`): opener phrases (a hook that starts with one draws a warning, never a refusal), negation words, number words, stop words and goodbye words (a loop that ends with one draws a warning). A language with no entry skips the checks that read these lists, with a warning.
- **Patterns** (`script.patterns`): the roles, and the presets, each declared pattern needs. `list` and `steps`: a hook, a `payoff` or a `cta`, and as many `point` beats as the hook's number promises; `myth`: a hook, a `turn`, a `proof`; `story`: a hook, a `turn`, a `payoff`; `problem-solution`: a hook, a `point`, a `payoff`; `before-after`: two `compare` beats, a preset the list does not offer yet.

A script with none of these (no header and no role) is a version 1 script and keeps passing, with warnings. How the checker uses the section is in the post-writing skill's `references/video-script.md`.
