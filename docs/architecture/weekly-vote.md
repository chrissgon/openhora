# Weekly vote to published post: the contract (backlog PB15)

A vote held in a public repository picks the topic of one post a week. The runtime turns the closed round into a post the person approves once, publishes it at the calendar's time and records it in the repository. This document is the contract between the three parts: the repository that runs the vote, the runtime's vote step, and the skill `mkt-vote-round`.

- Status: built (`runtime/handlers/social_vote.py`, `runtime/handlers/social_vote_job.py`, tests in `runtime/tests/test_social_vote.py`; first built as scripts under `scripts/`, deleted by T6 on 2026-10-27); not yet run for one real week from end to end.
- Target: any repository that holds the files below, named in the project's `runtime.json` (`vote` section: `repo`, `branch`, `pillars`; `contracts/runtime.md`).
- What belongs to a project and is not described here: which repository it is, how it shows the vote and the winner to visitors, how visitors pick, the day and time of the round, the wording of its pages. Those live in that project.

## What the target repository holds

The step reads and writes three data files, at these paths:

- `data/pick.json`: the open round (`round`, `closes`, `pillar`, `options` A/B/C, `picks` as hashed account ids) and `history` (closed rounds, newest first: `round`, `pillar`, `options`, `counts`, `winner`, `post_url`).
- `data/pick-queue.json`: the next rounds, each `{pillar, options}`.
- `data/posts.json`: the published posts the repository shows, each `{date, lang, title, url, image}`, with images under `assets/posts/`.

What the repository does by itself, outside the workbench:

- It closes the round that ended and records the winner in `history` with `post_url` empty: most picks win, a tie goes to the earlier letter, no picks means no winner. It then opens the next queued round.
- It does so on a schedule of its own, before the runtime's vote step looks at it.
- How it collects picks is its own matter. The step needs only the counts and the winner; it never reads what a visitor wrote.

## Rules of the step

1. A round with no winner: the agent proposes one of the three options with its reasons, inside the weekly approval.
2. No answer before the slot: the slot is skipped and the topic waits; nothing is published without the yes.
3. The weekly approval is asked right after the round closes.
4. The step commits directly to the branch named in `runtime.json`, only the vote data files, only after the weekly yes.
5. Only the vote post carries an image: HTML in the brand identity rendered to PNG, contrast checked.
6. Topics already in the content calendar, in the queue or in the history are never proposed again. Without this rule a round's three options can all be topics the calendar already carries.
7. The vote post takes the first free row of the round's pillar after the round closes; a row that already carries a post (drafted or later) keeps it, so the calendar is never rewritten by the vote. Without this rule a round could take the slot of an already scheduled post.

## The weekly run

```text
round closes   the repository closes round R (winner W, post_url empty) and opens the next queued round
next tick      runtime tick: vote step
               1. read pick.json, pick-queue.json, posts.json from the repository (vcs read-file, read only)
               2. vote_state.py: is there a closed round with post_url empty that was not handled? which slot of the
                  content calendar carries its pillar in the coming week? which pillar comes next in the queue's
                  rotation? which topics are already used (calendar, queue, history)?
               3. agent run (read only): a vote-proposal block: the post on W (or the proposed topic when there is no
                  winner, with reasons) in the slot's language, first comment, sources; the 3 topics of the round
                  after the queued ones, for the next pillar, each with its material and source
               4. code: content file from the proposal, check_post.py, the post image (HTML piece rendered to PNG,
                  contrast.py), payload.py build (post, first comment, image), the change set for the queue (new round
                  appended), one payload file with everything and its sha256; inbox item + notification
then           the person approves once (social.py approve --id N --confirmed --sha256 H)
               5. code: schedules the publish job at the slot time (the scheduler provider, with the digest), and
                  commits the queue change to the repository (vcs commit-files, confirmed under the same approval)
slot time      6. the job publishes the post and its first comment, then records it: post_url into history[R], the
                  post into posts.json with its image, committed to the repository (the same approval covers it; the
                  files written are computed by vote_update.py from the published URL, nothing else)
```

## Pieces

| Piece | Where | Notes |
|-------|-------|-------|
| Reading and committing files in a repository | `providers/vcs/github.py`: `read-file` (read only) and `commit-files` (a private clone, the given files, a signed commit with the user's git configuration, a push to the named branch; idempotency key; `--dry-run` prints the diff) | the requirement class is `integration:vcs`; the skill never names the host |
| Vote state and updates | skill `mkt-vote-round`: `scripts/vote_state.py` (what is pending, the slot, the next pillar, used topics), `scripts/vote_update.py` (the new JSON files, computed, never written by a model) | capability; runtime mode returns the `vote-proposal` block |
| The post image | `brand-identity/scripts/render.py`: an HTML piece rendered to PNG at an exact size with a headless browser; `contrast.py` for the colours | degrade: no browser, no image, the post goes text-only and the approval says so |
| The weekly step | `runtime/handlers/social_vote.py`, imported by `runtime/handlers/social.py`: a `vote` section in `runtime.json`, run once per closed round (cursor `vote:<round>`) | the model proposes; code builds, checks, queues and commits |
| Publish and record | `runtime/handlers/social_vote_job.py`, which the scheduled job calls: publish, then `vote_update.py` with the post URL, then `commit-files` | its files are in the job's snapshot like any job |

## Safety

- Visitors write the picks; picks are counts. The agent never reads their text; the vote data holds letters and hashed ids only.
- The approval's hash covers the post text, first comment, image, time, and the change set of the repository. A change to any of them is a new approval.
- `commit-files` refuses paths outside a list the runtime passes (`data/pick-queue.json`, `data/pick.json`, `data/posts.json`, `assets/posts/<slug>.png|webp`).
- A push that is rejected (the repository committed meanwhile) is retried once after a fresh clone; a second rejection goes to the inbox.

## A round whose topics are already in the calendar

When a round's options are all topics the calendar already carries (a round opened before the vote step was configured), its winner's `post_url` is the calendar post of that topic, recorded once that post is out; the vote step is told the round is handled (cursor `vote:<round>`), and new topics start with the next round.
