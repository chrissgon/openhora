# Tool notes

These notes apply after step 1 of SKILL.md: a brief with `Lint: ok` and Readiness `yes` exists. Without one, nothing is built in any tool, a code prototype included (Stop rule 1).

One entry per kind of tool, named by what it does and never by product (the user says which product they use; match that product to the kind below by what it does, ask when unsure, and record the product in the result's `Tool` line): what it is good at, the mode this workbench can use, and how to run a pack in it. A lesson learned on a project is recorded in that project's results document (Findings); a general lesson is proposed to the workbench maintainer, written without the project it came from.

## Choosing

| Artifact | First choice | Alternative |
|----------|--------------|-------------|
| screen, landing, documentation page | a generative design tool (with the design system onboarded) | code prototype; a prompt-to-prototype tool |
| mockup | an image generator with the real screen attached | a generative design tool |
| logo | an image generator for exploration, then a vector redraw | a design tool integration (class `integration:design-tool`) for the vector |
| presentation | a presentation generator | a generative design tool |
| animation | code prototype (CSS and HTML) | a generative design tool |
| image (social card, Open Graph) | code prototype (it becomes the build template) | an image generator |

Recommend the first choice unless the user already works in another tool.

## Code prototype

- Mode: automatic, always available when a browser can be launched.
- Good at: real components with real behaviour, animations, templates that become product code, exact sizes.
- Weak at: wide visual exploration; the agent explores fewer ideas per round than a design tool.
- Run: see `code-prototype.md`.

## Generative design tool

A tool that generates screens from a prompt and keeps a design-system project per product.

- Mode: assisted for generation (no generation interface for agents); its design-system projects can be written by an integration where the environment has one.
- Good at: screens and pages with a strong visual direction; reads a code repository to build a design system; accepts reference images; hands a chosen design back to the coding agent.
- Setup once per product: a design-system project built from the product's repository with an onboarding prompt that names the files to read, what to produce and what never to invent, ending with a verification page of every token and component. Check that page before any screen. (2026-09-24: the onboarding produced a faithful system on the first try.)
- Run: one project per direction; attach the brief file and the reference images; paste the prompt; do not attach an earlier design of the same artifact in round 1.
- Collect: screenshots at each required width, the share link, and the exported code or the hand-off to the coding agent for the chosen direction.

## Prompt-to-prototype tool

A tool inside a design platform that turns a prompt into an interactive prototype with code.

- Mode: assisted.
- Good at: interactive prototypes with code inside the design platform's ecosystem.
- Lessons (2026-09-23): an attached frame triggered its design-to-code behaviour and the result was a copy of the frame; custom skills run only when invoked by their slash command in the prompt; importing a library's variables needs a paid plan and a published library and flattens variables into raw values; a kit of the tool can bundle an npm package and guidelines. A first result of a landing page stayed well below the quality wanted.
- Run: a new prototype file per direction from the file browser; attach the brief, not the frame; start the prompt with the product skill's slash command if one was uploaded; link the product's stylesheet explicitly.

## Design tool integration (class `integration:design-tool`)

- Mode: automatic where the integration exists.
- Good at: composing screens from the file's own variables and components with bound tokens; vectors; structural references and hand-off files.
- Weak at: invention. A composed landing was judged correct but too basic (2026-09-23); use it for documentation-like screens, hand-off frames and vector clean-up, not for exploration.
- Run: follow the integration's own skills for writing to a file; sequential writes; one screenshot per frame; targeted fixes. Writes to the user's file pass the confirmation gate.
- Without a connector or a provider for the class: assisted mode; the user makes the frames and brings back screenshots and links.

## Presentation generator

- Mode: assisted.
- Good at: presentations and simple one-page documents from text.
- Run: import the brief's Slides part as the outline; attach the design system's colours and fonts as the theme; one generation per direction.

## Image generator (class `generator:image`)

- Mode: automatic when the environment has a connector for the class `generator:image`, or a provider the workbench resolves for the class and whose `--check` exits 0 (step 2 of the procedure: the skill runs the path the resolver prints, with the verb `generate --prompt-file <f> --size <W>x<H> --out <path>`); assisted otherwise (the user pastes the prompt in their image tool).
- Good at: mockup scenes, illustration, logo exploration.
- Weak at: exact text and exact brand colours; never trust it for final text or vectors.
- Run: one prompt per direction; generation spends credits, so automatic runs pass the confirmation gate.
