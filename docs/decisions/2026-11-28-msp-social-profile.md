## 2026-11-28: A skill that reviews and rewrites a social profile, network by network (MSP; spec `SPEC-mkt-social-profile-2026-11-24.md`, sections D1 to D3 and 9)

**Status.** Built and tested. Package MSP adds the skill `mkt-social-profile` 0.1.0, extends two platform references, routes the skill in `core-orchestrator` 4.6.0 and, because the lab showed failures that predate the package, fixes `mkt-social-copy` (4.0.0).

**What was built**
- `mkt-social-profile` 0.1.0 (marketing area, capability, no requirement, no side effect). It reviews and rewrites one social profile network by network (bio, name, link, pinned posts, cover), from the text, screenshots or export the person gives; it never reads a profile online and changes nothing on any profile. It writes `docs/marketing/social-profiles.md` and checks every proposed text with `lint_social_profiles.py` (limits from the platform's data file, links, voice, sensitive topics, approvals).
- The Instagram and TikTok references gained a section `## A profile` and a `profile` key in their data files, with limits that carry the platform's own source and date (2026-11-24) or `not checked`. LinkedIn is not touched: the skill works on it with every limit `not checked`.
- `core-orchestrator` 4.6.0 (Y) routes the skill; `packs/content.txt`, the owner table and the layout tree name it.

**Decisions of the spec**
- D1. Instagram and TikTok get the profile section now; LinkedIn waits for the next battery (its reference is in the context of 20 cases of 7 skills, so changing it would cost about 240 runs), and the seven `mkt-social-copy` cases whose context the change reaches are run again with the new skill's test.
- D2. `brand-strategy` is not changed: its profile proposals stay where they are, and the new skill copies an approved proposal word for word and never rewrites it.
- D3. One artifact, `docs/marketing/social-profiles.md`, one section per network, plus the link page and a check across networks; no new placeholder.
- Section 9, after the first quick trials: an approval recorded once (a text copied from a strategy proposal whose status is approved) reads `yes, <date> (docs/brand/strategy.md, proposal <n>)` and is not asked again; what a profile shows now is the `Now:` being fixed, never a request; a piece to remove gets `Why: remove: <reason>` and no proposed text.

**`mkt-social-copy` 4.0.0 (X).** A scratch run of the same platform cases on `main` at `26ad8897`, without this package, failed the same cases and assertions, so the failures predate it (the skill had no lab test since 3.1 on 2026-11-07, while 3.2 and 3.3 were bumped by the video packages). Fixed here: Stop rule 7 and step 2 read a format named by the calendar's header or by a recorded decision (a kind of post names a format when exactly one format of the reference is of that kind); the lines and the caption add no detail, cause or result the material lacks; an announcement opener counts as an opener when the voice wants no greeting; one row of the claims table per number; the check lines copy `"ok": true` as printed. Cases: case 101 got its own calendar and brand fixtures (the shared ones record "short videos", which names a reel); case 201's network and timing assertions now read the file as the skill writes it; one assertion of case 4 accepts facts from `docs/brand/`.

**Results** (2026-11-28; adapters `claude-code` for the Claude models, on the maintainer's subscription, and `agents-dir` for the OpenRouter models; measurement version as in `evals/eval-gate.json`)
- `mkt-social-profile` 0.1.0: quick test 1.0 on all four lab models (20 runs). Full test: gate passed on `claude-sonnet-5-5`, 1.0 with the skill against a baseline of 0.39. With-skill means on the other models: DeepSeek 0.973, Haiku 0.983, Luna 1.0 (15 runs each); their own gates are not computed, because a baseline on a model other than the lead runs only on request (reliability model, "Other models get no baseline by default").
- `core-orchestrator` 4.6.0: partial test of the 13 guard cases, 156 runs, means 0.976 (Sonnet), 0.995 (DeepSeek), 0.963 (Haiku), 0.99 (Luna), no guard failure.
- `mkt-social-copy` 4.0.0: full test, gate passed on Sonnet, 0.994 against a baseline of 0.285; DeepSeek 0.991, Haiku 0.991, Luna 1.0 (18 runs each). Platform cases: Instagram 0.967, 0.967, 1.0 and 1.0, TikTok 1.0 on all four. The 3.3.0 evidence of this package, with the confirmed guard failure 6.1 on Haiku that 4.0.0 clears, stays committed as inherited.

**Open**
- `SKILL.md` of `mkt-social-copy` is over the guideline of about 5,000 tokens. It already was on `main` (3,734 words then, 3,966 now); moving depth to `references/` is a follow-up of its own.
