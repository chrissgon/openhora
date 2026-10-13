# Routing table: intent → area → skill

Match the intent column, not the example words. Skills marked (planned) are not built yet, capabilities and flows alike: route to one by its name (the mark is not part of the name) with the status `pending`, say that it is not built, and propose the fallback of SKILL.md Stop rule 2. Of the flows, only `flow-fix-bug` is built; every other flow below is planned. Every built skill has a row, and a name without the mark is built.

## Business (`biz-`)

| Intent | Skill |
|--------|-------|
| Is this idea worth pursuing; who has the problem; is there a market | biz-validate-idea (planned) |
| Size the market, map competitors and alternatives | biz-market-analysis |
| Who exactly we sell to; how we position against alternatives | biz-icp-positioning |
| How we make money; pricing; unit economics; validate the business model | biz-business-model (planned) |
| How we reach and acquire the first customers | biz-gtm (planned) |
| The whole plan in one document; investor narrative | biz-business-plan (planned) |
| Validate or build a business end to end | flow-business-plan (planned) |

## Product (`product-`)

| Intent | Skill |
|--------|-------|
| Frame the problem, hypotheses and segments before deciding what to build | product-discovery (planned) |
| Product-level requirements document | product-prd |
| Feature-level spec with edge cases and acceptance criteria | product-feature-spec |
| What to build first and why; prioritization | product-roadmap |
| Break work into epics, stories, tasks | product-backlog |
| How we measure product success | product-metrics (planned) |

## Brand (`brand-`)

| Intent | Skill |
|--------|-------|
| Purpose, personality, positioning of the brand | brand-strategy |
| Logo direction, color, typography, imagery, brand tokens | brand-identity |
| How the brand speaks; tone; messaging pillars | brand-voice |
| The brand book that compiles it all | brand-guidelines |
| Find or check a name, a handle or a domain: is it free, who else uses it, is it the same everywhere | brand-name |
| The profile a personal brand stands on: who the person is, the proof, the goal, the audiences, the themes | brand-profile |
| Create a brand from nothing | flow-brand (planned) |

## Design (`design-`)

| Intent | Skill |
|--------|-------|
| Plan or synthesize research with users | design-user-research (planned) |
| User flows, information architecture, wireframes | design-ux-flows |
| Tokens and components as a system | design-system |
| Brief for any visual artifact (screen, mockup, logo, presentation, animation, image) for an AI design tool | design-brief |
| Spec for engineering: layout, tokens, states, breakpoints | design-handoff |
| Does the implementation match the design | design-implementation-validation (planned) |
| Run a brief in a design tool, a generator or a code prototype; review what a tool produced | design-execute |
| Accessibility audit | design-accessibility-review (planned) |
| Design a product's experience end to end | flow-design (planned) |

## Engineering (`eng-`)

| Intent | Skill |
|--------|-------|
| Understand an existing codebase's architecture | eng-codebase-map |
| Design the architecture for a feature or system; ADRs | eng-architecture |
| Choose between technical approaches | eng-tradeoffs |
| What does this change touch; dependencies; blast radius | eng-impact-analysis |
| Why does this bug happen (no fixing) | eng-root-cause |
| Write failing unit tests before code | eng-unit-tests |
| Make the tests pass; implement a fix or feature | eng-implement |
| Integration and end-to-end tests after implementation | eng-integration-tests |
| Improve code without changing behaviour | eng-refactor |
| Review a diff; security, edge cases, regressions, performance | eng-code-review |
| Triage dependency security alerts (advisories, vulnerable packages): update or dismiss, with evidence | eng-security-review |
| Update documentation for a change | eng-docs |
| Fix a bug end to end | flow-fix-bug |
| Build a feature end to end | flow-build-feature (planned) |
| Improve existing code end to end | flow-improve-code (planned) |
| Start a codebase from nothing | flow-new-project (planned) |
| Take a ticket and implement it ("check ticket N and implement it", any ticket id or issue link) | flow-implement-ticket (planned) |

## Delivery and operations (`ops-`)

| Intent | Skill |
|--------|-------|
| Open a pull request | ops-pull-request |
| Update my branch with its base; resolve conflicts | ops-branch-sync |
| Set up or change the CI pipeline | ops-ci-pipeline |
| Secure a repository before it is published: secret scan, pinned checks, branch rules, signed commits, security policy | ops-repo-baseline |
| Cut a release; release notes; versioning | ops-release (planned) |
| Notes for QA about a change | ops-qa-handover (planned) |

## Marketing and growth (`mkt-`)

| Intent | Skill |
|--------|-------|
| What we say and to whom; messaging framework | mkt-messaging |
| Plan a launch | mkt-launch-plan (planned) |
| Content calendar | mkt-content-plan |
| Write a social post (text only, nothing published) | mkt-social-copy |
| A script and a caption for a short video post (a Reel, a TikTok, a Short): the text only, nothing recorded, edited or published | mkt-social-copy |
| Publish or schedule a post that is already written and illustrated | mkt-publish |
| Reply to comments on the person's own posts; write an engagement policy or set up automatic replies | mkt-engage |
| An audience vote closed: write the post on the winning topic and propose the next round | mkt-vote-round |
| Landing page structure and copy | mkt-landing-page (planned) |
| SEO plan | mkt-seo (planned) |
| Email campaign or sequence | mkt-email (planned) |
| Measurement plan; experiments | mkt-analytics (planned) |
| Any request that ends in a post being published or scheduled and the post still has to be written or illustrated ("schedule a post about X", "post about our launch tomorrow") | flow-social-post (planned) |
| Launch end to end | flow-launch (planned) |

## AI inside the product (`ai-`)

| Intent | Skill |
|--------|-------|
| Where would AI add value here; build or buy; is it feasible and affordable | ai-opportunity-assessment (planned) |
| Requirements for an AI feature: quality bar, fallbacks, cost ceiling | ai-feature-requirements (planned) |
| How the interface should handle uncertainty and feedback | ai-ux-patterns (planned) |
| Integrate a model: prompts, retrieval, tool use | ai-llm-integration (planned) |
| Evaluate the product's AI: datasets, graders, thresholds | ai-evals (planned) |
| Privacy, prompt injection, compliance for AI features | ai-governance (planned) |

## Workbench and methods (`core-`)

| Intent | Skill |
|--------|-------|
| Set up a project for the workbench: docs layout, state, autonomy, project instructions | core-project-init |
| Create or update the project's instruction file | core-agents-md |
| Interrogate me about a plan until we agree | core-clarify |
| Research a question with sources | core-research |
| Find what's wrong with this plan or artifact; stress-test it; a second opinion before building | core-critique |
| Create or improve a skill of the workbench | core-skill-creator |
| Security audit of the workbench itself; vet a skill from outside before it is installed ("is this skill safe?") | core-security-audit |

## Cross-area

| Intent | Skill |
|--------|-------|
| Build a digital product from scratch, business through launch | flow-new-product (planned) |
| Where are we; what's next | read state, summarize, propose the next phase (no skill) |
