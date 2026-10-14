# Platform references

One reference per social platform: what the platform is as a medium, written once, so that a skill's procedure names no platform and adding a platform edits no skill (design rules 2 and 3 of `AGENTS.md`).

| File | Read by | Holds |
|------|---------|-------|
| `<platform>.md` | a model, at the step of a skill that says so | what a person who writes, designs or publishes for the platform must know |
| `<platform>.json` | a script, through `--platform-file <path>` | the same facts as numbers, patterns and lists, for code |

The name of a platform is lowercase letters, digits and hyphens. It is the name everywhere: the file names here, the part after the colon of `publisher:<platform>`, the value of `--platform`, the `Network:` field of a post file once lowercased. The files of a platform are found by that name, so this file lists none of them.

## Which platform a step works on

A skill's step is literal and the same in every skill: "read the reference of the platform, `../../shared/references/platforms/<platform>.md`; if there is no such file, stop and say the platform is not supported". The platform is found in this order, and the first that gives a name wins:

1. The `Network:` field of the calendar row or of the post file the step works on, lowercased.
2. The line of the request that names it. A task of the agent runtime carries it as a line of its own, `Platform: <name>`, above the data it quotes; in a person's request it is the platform they name.
3. Neither names one: the skill asks. It never takes the platform from a default, from the files that happen to be in this folder or from the provider that is installed.

A skill reads the one reference of that platform and no other file of this folder. A run that has no tool to read files (an adapter that calls a model once) is sent that reference with the task.

## What goes in a reference

What the platform is as a medium, whoever publishes to it and with whatever tool:

- the shape of a post: whether it needs text, the limits of its text, the media it takes or requires;
- how links, hashtags and mentions behave, and what the first comment is used for;
- comments and replies: how deep they nest, what a reply must name;
- the identifiers of a post and of a comment, and the shape of a post's address;
- the pieces of a profile and their sizes, and how a person exports their own profile;
- what can be read from outside, and what only the person can see.
- for a platform whose post is a video or a set of images: the post shape and the formats it accepts ("Post shape and formats", below).

Rules for writing one:

- Every fact carries where it came from and when it was checked: the platform's own documentation with its address and the date, an observation on a real case with the date, or "the limit the workbench enforces" for a bound that is the workbench's own. A fact with no origin is labelled `not checked`.
- A reference is written when the platform has a real task, never from general knowledge. It is started from what that task found out.
- It describes a medium, not a project (principle 8): no account, no handle, no person, no post of anyone. Real limits and real dates stay.
- It is prose a model reads at one step: short sections, one fact per line, no procedure. What a skill does with a fact is the skill's step.

### Post shape and formats

A reference of a platform whose post is not text with optional media (`post.shape` in its data file is `video_with_caption` or `images_with_caption`) has these sections, with these headings, because a skill that writes for the platform reads them and nothing else of this folder:

- `## Post shape`: one line `- Shape: <post.shape>`, one line `- Formats accepted: <names>`, and a line naming the formats that are described but cannot be produced or published yet.
- `## Format: <name>`, one per accepted format: the facts a person who writes the post needs, one per line, each with its origin: the aspect, the duration bounds, the caption limit, the hashtag and mention limits, what the format needs besides the caption. A value the platform's pages do not state is written `not checked`.

The format names are a closed list shared by every platform: `reel` and `video` (a vertical video; the platform's own word decides which of the two a platform accepts), `carousel` (a sequence of images) and `static` (one image). The value of a post file's `- Format:` line is one of them, and it must be one the platform's reference accepts.

## What goes in the data file

What a script needs and cannot read from prose: host names, URL patterns, the patterns of identifiers, length limits, the types, size and count of the media a post may carry, whether a post needs text, and, for a video post, the file's limits. The keys of a data file:

| Key | Value |
|-----|-------|
| `platform` | the platform's name, equal to the file's name |
| `hosts` | the host names of the platform's addresses, compared exactly, never by suffix; empty when none was checked |
| `post` | `requires_text`, `max_characters`, `scheduling` (whether the platform itself can hold a post for later), `first_comment` (`supported`, `max_characters`), `url` (`scheme`, `hosts`, `path_pattern`, `allows_query`, `allows_fragment`, `template`); and, for a video or image post, `shape`, `formats`, `max_hashtags`, `max_mentions`, `unit`, `options` |
| `media` | `max_count`, `max_bytes`, `types` (each with `name`, `extensions`, `magic_hex`, the first bytes of such a file, and `magic_offset`, the byte at which they sit, 0 when absent), `post_image` (`width`, `height`) |
| `video` | for a video post: `containers`, `codecs`, `audio_codecs`, `fps_min`, `fps_max`, `max_width`, `min_side`, `max_side`, `min_seconds`, `max_seconds`, `max_bytes`, `aspect` (`recommended`, `min`, `max`), `faststart` |
| `limits` | for a video post: `posts_per_24h`, `approximate`, `pending_shares_per_24h`, `unaudited_users_per_24h` |
| `reply` | `max_characters` |
| `comment` | `max_characters_kept` (how much of a comment's text is kept when it is read), `link` (the query parameters that carry the comment and the reply, `nesting_levels`) |
| `identifiers` | `post`, `comment` and, where a copied link uses another form, `comment_short`: each a `pattern` for the whole value |
| `notification_email` | `header_prefix` (the mail headers of the platform's own notifications), `layout_verified` |

### Keys by post shape

`post.shape` is one of `text_with_optional_media`, `video_with_caption`, `images_with_caption`. A file that has no `post.shape` is `text_with_optional_media`: a reader carries that default, so the first data file needed no change when the other shapes were added.

| Key | `text_with_optional_media` | `video_with_caption` and `images_with_caption` |
|-----|----------------------------|------------------------------------------------|
| `platform`, `hosts`, `post`, `media` | required | required |
| `post.requires_text`, `post.max_characters`, `post.scheduling` | required | required; `requires_text` may be null |
| `post.first_comment`, `post.url` | required | null |
| `post.shape`, `post.formats` | absent | required |
| `post.max_hashtags`, `post.max_mentions`, `post.unit` | optional | required; the two limits may be null |
| `post.options` | optional | required; `{}` when the platform has none |
| `video` | absent | required for `video_with_caption`, absent otherwise |
| `limits` | optional | required |
| `reply`, `comment`, `identifiers`, `notification_email` | required | null |

What the new keys mean:

- `null` is "not checked": the platform's pages do not state it, or the key does not apply. A reader does not check a null limit and says so; it never fills the gap with a number.
- `post.formats`: the format names of the shared list (see "Post shape and formats") the platform accepts, the ones its reference describes.
- `post.max_characters` is the caption's limit for a video post, and `post.scheduling` says the same thing as for a text post. `post.max_hashtags` and `post.max_mentions` count what the caption holds.
- `post.unit`: how `max_characters` counts, `characters` (the default when absent) or `utf-16` (UTF-16 code units).
- `post.options`: the closed set of options a publisher may send beyond the file and the caption, one object per option, keyed by the option's name. An option the file does not list is never sent by a caller of the data file; a flag the platform's own API requires and nobody chooses is not an option, and sending it belongs to the provider. Each object has `type` (`choice`, `boolean` or `integer`), `values` (the closed list, for `choice` and `boolean`), `unit`, `min` and `max` (for `integer`), `default`, `when_unset`, `set_by` and, where the platform states no default and a person decided one, `decided_by` and `decided_on`. `default` is the value sent when the caller gives none, and null when there is none. `when_unset` is what a request that carries no value does: `default` (send the default), `omit` (send nothing), `refuse` (the request is refused, because the person must choose). `default` is null exactly when `when_unset` is `omit` or `refuse`. `set_by` says who gives the value: `code` (the data file's default, nobody asked), `person` (asked of the person on the approval card) or `post_file` (written in the post file). `decided_by` (`maintainer`) and `decided_on` (a date) record who chose a default the platform does not state, and when. A default of that kind with neither key would be an assumption and is not written.
- `media.max_count` and `media.max_bytes` are the limits of the file a post carries; for a video post `media.max_bytes` equals `video.max_bytes`. A size the platform writes in MB or GB is stored as 10^6 or 10^9 bytes per unit, the stricter reading, when the page does not say which.
- `media.types[].magic_offset`: the signature of an MP4 or MOV file is at byte 4, not at the start. The `ftyp` prefix that identifies an MP4 also matches a MOV file, whose brand follows it: a reader decides by the extension, or tries the types with the longest signature first.
- `video`: `containers` and `codecs` are lowercase names (`mp4`, `mov`, `webm`; `h264`, `h265`, `vp8`, `vp9`, where `h265` is also written HEVC). `max_width` is the widest the platform takes; `min_side` and `max_side` bound each of the width and the height. `aspect` holds ratios written `<width>:<height>`. `faststart` says whether the platform needs the index at the front of the file. Each is null when not checked.
- `limits.posts_per_24h`: the figures the platform's pages state for the posts one account may publish through its API in 24 hours, a list because the pages may state more than one and disagree; a reader that needs the real one reads it from the platform and never picks one of the list. `limits.approximate`: true when the platform states the figures of `posts_per_24h` as typical or approximate, so that a reader never treats one as a hard cap; false when it states them as limits. `pending_shares_per_24h` and `unaudited_users_per_24h`: a number, or null.

Rules:

- A script takes `--platform <name>` and `--platform-file <path>`; the skill's step passes the path of this folder's file. A script never finds the file by a path of its own: a scheduled job runs a script from a flat folder of copies, where a relative path leads nowhere, and the job's snapshot carries the data file under its own name.
- A script holds no table of platforms and no limit of a platform as a constant. A value it needs and the file lacks is added here.
- A parser that is code for one platform's format (a copied comment link, a profile export) stays in the skill that owns it, selected by `--platform`; the data file gives it the hosts and patterns it checks, never the parsing.
- A limit is written once. The first data file holds every limit the runtime and the skills' scripts held as constants when it was written, so that moving a script to the file changes no value.
- Changing a value here changes what the skills that read the file do: it is a change of their context, and their lab evidence made with the old file becomes inherited (the reliability model, "What a change costs").

## What stays in a provider

What belongs to one implementation and not to the medium: credentials and how long they last, how the service is called, its versions and endpoints, its errors and rate limits, how text is escaped on the way in, the ledger of what was sent. One provider may serve several platforms, and most skills that need to know a platform declare no publisher. A provider's verbs name a post and a comment by generic flags (`--post-id`, `--comment-id`, `--parent-comment-id`) whose value a caller passes as it received it; what the value looks like on a platform is in that platform's reference, section "Identifiers" (`providers/CONTRACT.md`).

## Adding a platform

Add `<platform>.md` and, where a script needs data, `<platform>.json`; where something is executed, a provider that declares the platform. Add the platform's cases to the skills that have a task on it, in `skills/<name>/evals/platforms/<platform>.json`. No skill's procedure is edited and no file of this folder changes. The limit of the rule: it holds for a platform whose post is text with optional media; a platform of another shape (`post.shape`) edits the skills `AGENTS.md` names in design rule 3. Its files still follow "Keys by post shape" and "Post shape and formats" above, and a data file of the first shape needs none of the keys of the others.
