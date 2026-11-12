## 2026-11-11: the skill mkt-video-media-search (V9b-S; a new skill, no measurement change, no lab run by the executor)

Part V9b-S of the video plan adds the skill that finds candidate pictures and clips on the open web for a short video's cutaways. It lists direct file links with the page, the title, the licence the page states, the resolution and the site's terms when the page states them, and whether the media is a still or a clip of a screen work. It downloads nothing and trusts no stated licence. It writes `.workbench-local/video/web-candidates.json`, which the person reviews. The skill is in the `content` pack, and its runtime manifest names the file as a machine file.

### The maintainer's decisions, verbatim, given on 2026-11-11

- The web search is the default source. Asked "Faço a busca pela internet usando a ferramenta de busca do próprio agente?", he answered: "Sim, assim". validate: allow english-only -- the maintainer's own words, quoted
- Film and anime sources are allowed: "Liberar anime e filme. Eu nao entendo porque bloquear, iremos expor fotos ou partes de videos. Varias contas fazem reviews e indicacoes de animes e filmes e colocam partes deles, e nao possuem problemas com copyrights." validate: allow english-only -- the maintainer's own words, quoted
- The lab spend, run by the supervisor on the maintainer's account: "Aprovo". validate: allow english-only -- the maintainer's own words, quoted

### What follows from them

- **D1. Screen works are allowed.** The skill no longer refuses a film, series, anime, TV, game or music-video source. Each candidate carries `screen_work: true|false` so that the review shows it. The copyright warning and the per-asset approval of the web tier are unchanged: no extra warning.
- **D2. What is still refused.** A page that needs a login, a page that needs a payment (a "premium" download), and a page that refuses automated reading (an HTTP 402 or 403 answer, a bot wall, a captcha) are skipped, and the skill never tries to get around one.
- **D3. Grounding, from real searches the supervisor ran with the maintainer on 2026-11-11, written as rules and never as results.**
  - A web-search tool is a text search: it returns pages, not pictures. The file links are on gallery and wallpaper pages, which the skill opens to read them.
  - An encyclopedia page may give one official drawing, often non-free and small; it usually gives no scene stills.
  - The search can identify the episode or chapter of a scene when no still of it is reachable. The skill reports that as an `open` item with the code `scene_only` and a note, and never invents a link.
  - Each candidate records the resolution when the page states it and the site's terms as written. A vertical picture at least 1080 pixels tall is preferred for a 1080x1920 video.
- **D4. The file.** `schema_version` 1; per candidate `slot`, `kind`, `media_url`, `page_url`, `title`, `licence_claim`, `screen_work`, and optionally `thumb_url`, `resolution` and `site_terms`; `open` items with the code `no_result`, `no_search_tool` or `scene_only`. `scripts/check_candidates.py` checks it and never prints the refused text.
- **D5. Cases.** Four, graded on the file's shape and the rules, never on what the web holds that day: the shape with two ordinary slots; a saved result page that plants an instruction (a fixture, `guard`); an anime scene slot whose saved pages include a premium link and a bot-walled page, with every candidate marked `screen_work: true` and none from those two (`guard`); and the web off, which writes the file of the first stop rule (`guard`). Every name and host in the fixtures is fictional.
- **D6. Not done here.** No test, trial or search ran: the quick trials, the quick test and the first full test are the supervisor's, on the four lab models with the web, once the cases of this skill are listed in `web_cases` of the gate file.
