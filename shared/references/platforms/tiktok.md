# TikTok

What TikTok is as a medium, for a creator account that posts through the platform's Content Posting API. A skill reads this file at the step that says "read the reference of the platform"; a script reads the same facts from `tiktok.json`, beside this file. What belongs to the tool that publishes (tokens and how long they last, the service's endpoints, upload chunks, its errors and rate limits) is in the provider, not here.

Every fact carries the tag of its source in square brackets; the sources, with their addresses and the date each was read, are at the end. `not checked` marks a value the pages read do not state, or one that was not read. "Inference" marks a conclusion drawn from stated facts that no page states. Dates are 2026-10-13.

## Post shape

- Shape: `video_with_caption`.
- Formats accepted: `video`.
- A vertical video is a `video` here. The name `reel` is not a TikTok format.
- Not accepted yet: `carousel` and `static`. The API has a photo post (the Get Started page names a photo source and a `media_type`), but its limits were not read: `not checked`.
- The format is the value of the post file's `- Format:` line.

## Format: video

- Needs: one video. The caption (the API's `title`) is optional: a post sent without one has no caption [TT-direct-ref].
- Aspect: 9:16 is the format the workbench makes for a vertical video. The pages read state no aspect rule: `not checked` [TT-media].
- Duration: at most 10 minutes (600 seconds) through the API, and the person can trim a video in the app to fit their account's limit [TT-media]. A minimum duration: not stated [TT-media].
- Caption: at most 2,200 UTF-16 runes [TT-direct-ref]. Hashtag and mention limits: not checked. Preset text, including the title and any hashtags, must be editable by the person before the post is sent [TT-guidelines].
- Container: MP4 is recommended; WebM and MOV are also supported [TT-media].
- Video: H.264 is recommended; H.265, VP8 and VP9 are also supported. 23 to 60 frames per second. Each side, width and height, from 360 to 4096 pixels [TT-media].
- Audio codec, bit rate: not stated [TT-media].
- File size: at most 4 GB [TT-media]. The data file stores 4,000,000,000 bytes, reading GB as 10^9 bytes, the stricter reading; the page does not say which.
- Cover: a frame chosen by its time in milliseconds (`video_cover_timestamp_ms`); the first frame when it is unset or invalid [TT-direct-ref].
- Privacy: a Direct Post must carry a `privacy_level`, one of `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `FOLLOWER_OF_CREATOR`, `SELF_ONLY`, and the value must be one the creator's own options allow [TT-direct-ref]. The person must choose it from a dropdown; there is no default [TT-guidelines].
- Other options of a Direct Post, each a flag the platform names: `disable_duet`, `disable_stitch`, `disable_comment`, `brand_content_toggle` (a paid partnership), `brand_organic_toggle` (the creator's own business) and `is_aigc` (AI-generated content, which adds the platform's label). The reference table marks `brand_content_toggle` as required; whether the others are required: not stated [TT-direct-ref].

## A post

- Two ways in. A Direct Post publishes the video to the creator's account. An upload to the inbox (a draft) puts the video in the creator's inbox, and the person must open the inbox notification to continue the editing flow in the app and complete the post [TT-direct-start, TT-upload].
- Direct Post needs the app to be approved for the `video.publish` scope and the creator to have authorised it. Content posted by an unaudited client is restricted to private viewing mode [TT-direct-start].
- An unaudited client: can let up to 5 users post in a 24-hour window, every account that posts must be private at the time of posting, and only `SELF_ONLY` viewership is allowed [TT-guidelines]. An audit lifts the restriction [TT-direct-start].
- The inbox upload needs the app to be approved for the `video.upload` scope. Whether it has an audit of its own: not stated [TT-upload].
- At most 5 pending shares within any 24-hour period for the inbox upload [TT-upload-ref].
- Posts per 24 hours: typically around 15 per creator account, shared across every client that uses the Direct Post API [TT-guidelines].
- Scheduling: the Direct Post reference has no scheduling parameter [TT-direct-ref]. A post that must go out at a time is published at that time by a scheduled job.
- What every client must do [TT-guidelines]:
  - show a preview of the content to be posted;
  - let the person choose the privacy status from a dropdown, with no default value;
  - start sending the content only after the person has expressly consented to the upload;
  - show the creator's nickname on the upload page;
  - let the person edit preset text;
  - add no promotional watermark or logo of its own to the creator's content.
- Inference, not a stated rule: a Direct Post sent unattended at a later time is at odds with the requirements above (the person chooses the privacy status and consents at the time of the upload). The inbox upload leaves the final step to the person.

## Links, hashtags and mentions

- Hashtags and mentions: limits not checked. Whether a link in a caption is clickable: not checked.
- A first comment as a way to carry a link: not checked. The data file holds no first-comment limit.

## Comments and replies

- Not checked. Comments on this platform are out of scope of the data file: it has no reply, comment or identifier keys, and no parser reads this platform's comment links.

## The address of a post

- The host is `www.tiktok.com`, compared exactly [TT-embed].
- The platform's embed page shows a video's address as `https://www.tiktok.com/@<username>/video/<digits>`, the video's identifier being the all-numeric part after `/video/` [TT-embed].
- Inference: a video delivered to the inbox has no address until the person posts it. The data file holds no template for an address.

## What can be read from outside

- Not checked: what a creator account can read of its own numbers or comments through the API, and what a person can see only on their own pages.

## Sources

- [TT-direct-start] Content Posting API, Get Started: https://developers.tiktok.com/doc/content-posting-api-get-started (read 2026-10-13)
- [TT-upload] Content Posting API, Get Started, upload to the inbox: https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content (read 2026-10-13)
- [TT-upload-ref] Upload Video reference: https://developers.tiktok.com/doc/content-posting-api-reference-upload-video (read 2026-10-13)
- [TT-guidelines] Content Sharing Guidelines: https://developers.tiktok.com/doc/content-sharing-guidelines (read 2026-10-13)
- [TT-direct-ref] Direct Post reference: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post (read 2026-10-13)
- [TT-media] Media Transfer Guide: https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide (read 2026-10-13)
- [TT-embed] Embed Videos: https://developers.tiktok.com/doc/embed-videos (read 2026-10-13)
