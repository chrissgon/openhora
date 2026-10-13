# Instagram

What Instagram is as a medium, for a professional account (Business or Creator) that publishes through the platform's API. A skill reads this file at the step that says "read the reference of the platform"; a script reads the same facts from `instagram.json`, beside this file. What belongs to the tool that publishes (tokens and how long they last, permissions, the service's endpoints, its container states and errors) is in the provider, not here.

Every fact carries the tag of its source in square brackets; the sources, with their addresses and the date each was read, are at the end. `not checked` marks a value the pages read do not state, or one that was not read. "The maintainer's choice" marks a value the maintainer decided because the platform states none. Dates are 2026-10-13.

## Post shape

- Shape: `video_with_caption`.
- Formats accepted: `reel`, `carousel`, `static`.
- Described, not yet produced or published: `carousel` and `static`. Nothing makes the images of a carousel or of a static post yet, so only `reel` is produced and published.
- A vertical video is a `reel` here. The name `video` is not an Instagram format.
- The format is the value of the post file's `- Format:` line.

## Format: reel

- Needs: one vertical video and a caption. Whether the platform requires a caption: not stated [IG-media]; the workbench always writes one.
- Aspect: 9:16. The platform accepts ratios between 0.01:1 and 10:1 and recommends 9:16 so that nothing is cropped and no blank space is added [IG-media].
- Duration: at least 3 seconds, at most 15 minutes (900 seconds) [IG-media].
- Media type: a reel is made with the `media_type` value `REELS`; the values the page accepts are `CAROUSEL`, `REELS` and `STORIES` [IG-media].
- Caption: at most 2,200 characters, 30 hashtags and 20 @ mentions [IG-media]. How a character is counted: not stated.
- Container: MP4 or MOV, with no edit lists and the index (the moov atom) at the front of the file [IG-media].
- Video: H.264 or HEVC, progressive scan, closed GOP, 4:2:0 chroma, 23 to 60 frames per second, at most 1920 pixels wide (a minimum width: not stated), variable bit rate of at most 25 Mbps [IG-media].
- Audio: AAC, mono or stereo, at most 48 kHz, 128 kbps [IG-media].
- File size: at most 300 MB [IG-media]. The data file stores 300,000,000 bytes, reading MB as 10^6 bytes, the stricter reading; the page does not say which.
- Cover: by default the first frame. A cover frame is chosen by an offset in milliseconds into the video (`thumb_offset`, its maximum: not stated), or by a JPEG image of at most 8 MB in the sRGB colour space, ideally 9:16; an image of another ratio is cropped to its middle 9:16 rectangle. If both are given, the image wins [IG-media].
- Feed: a reel can appear in the Feed tab as well as the Reels tab (`share_to_feed`). Setting it does not guarantee placement. The platform's default: not stated [IG-media]. The maintainer's choice (2026-10-13): `true`. It is the default in the data file, with the decision recorded beside it (`decided_by`, `decided_on`).

## Format: carousel

- Needs: a sequence of images, videos or a mix, and one caption. Not produced yet.
- Aspect: not checked.
- Items: at most 10 [IG-publishing, IG-media]; the minimum: not stated [IG-media]. A reel cannot be an item [IG-media].
- Images: JPEG is the only format; MPO and JPS are not supported [IG-publishing]. Size and aspect of an image: not checked.
- Caption: on the carousel as a whole, at most 2,200 characters, 30 hashtags and 20 @ mentions; the caption of an item is not supported [IG-media].
- Posts per 24 hours: the page that describes carousels states 50 published posts per account in 24 hours, where its rate limit section states 100, and it does not reconcile the two [IG-publishing].

## Format: static

- Needs: one image and a caption. Not produced yet.
- Aspect: not checked.
- Image: JPEG is the only format; MPO and JPS are not supported [IG-publishing]. Size, aspect and safe areas of the platform's own screens: not checked.
- Caption: at most 2,200 characters, 30 hashtags and 20 @ mentions, as stated for a media container in general [IG-media].

## A post

- A post is published by an account that is a professional account, for a business or a creator [IG-overview].
- Access: an app that serves only accounts it owns or manages needs the default (Standard) access. An app that serves accounts it does not own or manage needs Advanced access, which requires app review and business verification [IG-overview].
- Hosting: the video must be hosted on a publicly accessible server at the time of the attempt, whatever the login used [IG-publishing, IG-media]. The one exception is a resumable upload of a local file, offered only to an app that implemented the platform's business login through Facebook, with the account linked to a Facebook Page [IG-publishing, IG-overview].
- Scheduling: the pages read state no scheduling parameter, and tell an app that lets people schedule posts to enforce the posting limit itself [IG-publishing]. A third-party page claims one; that claim was not confirmed on a platform page. A post that must go out at a time is published at that time by a scheduled job.
- Posts per 24 hours through the API: the rate limit section states 100 published posts in a moving 24-hour period; the carousel section of the same page states 50, and the page does not explain the difference [IG-publishing]. The live figure for an account is read from the platform's `content_publishing_limit` endpoint [IG-publishing]; a plan never picks 100 or 50.
- A container made for a post expires after 24 hours [IG-media].

## Links, hashtags and mentions

- Hashtags: at most 30 in a caption. Mentions: at most 20 @ tags [IG-media].
- Whether a link in a caption is clickable: not checked.
- Whether a hashtag or a mention written in a caption becomes a link once published: not stated [IG-media].
- A first comment as a way to carry a link: not checked. The data file holds no first-comment limit.

## Comments and replies

- Not checked. Comments on this platform are out of scope of the data file: it has no reply, comment or identifier keys, and no parser reads this platform's comment links.

## The address of a post

- The host is `www.instagram.com`, compared exactly [IG-oembed].
- The platform's embed page shows a post's address as `https://www.instagram.com/p/<shortcode>/` and lists the reel shape as `https://www.instagram.com/reel/<media-shortcode>/` [IG-oembed]. A shortcode is not the identifier the API returns for a published post: the address a publisher prints comes from the platform's answer, and the data file holds no template for it.
- The permanent address of a published post is a field of the media the API returns [IG-media-node: "Permanent URL to the media"]; an example value was not shown on that page.

## What can be read from outside

- Not checked: what a professional account can read of its own numbers or comments through the API, and what a person can see only on their own pages.

## Sources

- [IG-publishing] Instagram Platform, Content Publishing: https://developers.facebook.com/docs/instagram-platform/content-publishing (read 2026-10-13)
- [IG-overview] Instagram Platform, Overview: https://developers.facebook.com/docs/instagram-platform/overview (read 2026-10-13)
- [IG-media] IG User Media reference: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media (read 2026-10-13)
- [IG-media-node] IG Media reference: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media (read 2026-10-13)
- [IG-oembed] Instagram oEmbed: https://developers.facebook.com/docs/instagram-platform/oembed (read 2026-10-13)
