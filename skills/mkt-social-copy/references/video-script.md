# Writing the script of a video or images post

Read at step 4 of `SKILL.md`, after `../../shared/references/video-presets.md` (the preset vocabulary). The script is the ```script block of the output template.

## Syntax

One `key: value` per line, a key in lowercase, one space after the colon, beats separated by a blank line, `beat:` numbered 1, 2, 3 and so on. The keys are `beat`, `line`, `on-screen`, `preset` and the parameters of the chosen preset. The main text parameter of the preset is the beat's `on-screen` line and is never written under its own name as well; `check_script.py` refuses a parameter the preset does not declare, a main parameter written twice and any field that carries a time.

Example of a `number` beat: the label is the on-screen text and the figure is `value`.

```
beat: 3
line: That habit saved me 340 euros in one month.
on-screen: euros saved in one month
preset: number
value: 340
```

Writing `on-screen: 340` is wrong: the label is the text, `value` holds the figure.

## Video formats (`reel`, `video`)

- A beat is one spoken thought, written as the exact words the person says, in the slot's language, in short spoken sentences. The lines together are everything the person says. Every fact in a line is on step 3's list.
- Length: as long as the user says, and inside the format's `Duration:` line of the reference; about 150 spoken words a minute. When the user gives no length, aim at 30 seconds (about 75 words) and list that under Assumptions.
- Order: the voice's post structure, hook first.

## Each beat's picture

- From the vocabulary only. A beat carries one preset with its parameters as the vocabulary declares them, or none (the person just talks, and the beat has only its `line`).
- The on-screen text goes in `on-screen` and nowhere else. It is the few words worth reading, not a second copy of the spoken line.
- A `number` beat is only for a number on step 3's list, with the value written as the material gives it and the unit in the label.
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
