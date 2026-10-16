# Area map

Nine areas: seven form the lifecycle chain of a digital solution, two are horizontal and enter any phase. Each area holds capabilities (one skill each). Flows chain capabilities inside one area or across areas.

## Lifecycle areas

| # | Area | Prefix | Sub-areas | Typical artifacts |
|---|------|--------|-----------|-------------------|
| 1 | Business | `biz-` | idea validation, market and competition, business model, pricing and unit economics, go-to-market, business plan and investor narrative | `docs/business/*` |
| 2 | Product | `product-` | discovery, requirements and PRD, prioritization and roadmap, backlog and stories, product metrics | `docs/product/*` |
| 3 | Brand | `brand-` | brand strategy, visual identity, voice and messaging, guidelines, rollout | `docs/brand/*` |
| 4 | Design | `design-` | user research, UX (flows, information architecture, wireframes), UI, design system, accessibility, prototyping, handoff, design-vs-code validation, asset generation (image, video slot) | `docs/design/*` |
| 5 | Engineering | `eng-` | architecture, backend, frontend, mobile, data, quality (tests and review), maintenance (debug and refactor), technical documentation | code, tests, `docs/engineering/*` |
| 6 | Delivery and operations | `ops-` | git and PRs, CI/CD, infrastructure and cloud, observability, incidents, releases, operational security | pipelines, IaC, `docs/delivery/*` |
| 7 | Marketing and growth | `mkt-` | messaging and copy, landing pages, SEO, content, social and publishing, email and CRM, campaigns, analytics and experiments | `docs/marketing/*` |

## Horizontal areas

| Area | Prefix | Sub-areas | Note |
|------|--------|-----------|------|
| AI and machine learning | `ai-` | AI strategy (opportunity, build vs. buy, feasibility, cost, risk); AI product design (UX for uncertainty, feedback, human-in-the-loop, guardrails); AI engineering (LLM integration, prompts, RAG, agents and tool use, evals, cost and observability); ML (classical modelling, training data, MLOps); governance (privacy, prompt injection, compliance) | AI *inside the solution being built*. Not the workbench itself. |
| Core | `core-` | orchestration and routing; process diagnosis (planned); research method; interview and clarification method; skill and agent creation and evaluation; project `AGENTS.md` generation; project memory and state | The workbench improving and operating itself, plus methods every area reuses. |

## Optional areas

| Area | Prefix | Sub-areas | Note |
|------|--------|-----------|------|
| Assistant | `asst-` | inbox and email handling, calendar, reminders and follow-ups, notes and summaries, recurring personal or team routines | A plus, not the core. Excluded from `packs/default.txt`; installed with `--pack all` or `--pack assistant`. Built last, only for recurring tasks with a real procedure. Natural runtime: always-on assistants such as OpenClaw, which read `~/.agents/skills` and ship their own bundled skills for common tasks; write `asst-` skills only for what those do not cover or what must follow this repository's contracts. |

## Boundary test

Would a senior practitioner of area X know how to do this without expertise from area Y? If yes, the capability belongs to X. Examples:

- Landing-page copy: Marketing, even when a model writes it.
- A brand-consistent image for a post: Design (asset generation), consumed by a Marketing flow.
- How to display model uncertainty to a user: AI (AI product design), not Design.
- Evaluating a skill of this repository: Core. Evaluating a chatbot in production: AI.

## AI insertion points in flows

Assess always, build conditionally. The opportunity assessment is cheap and runs in every Business phase; it must be able to answer "no AI here", in which case the flow continues without the other AI capabilities.

| Phase | AI capability inserted | Condition |
|-------|------------------------|-----------|
| Business | opportunity assessment, build vs. buy | always |
| Product | requirements for AI features (quality metrics, fallbacks) | only if the assessment said yes |
| Design | UX patterns for AI | only if AI features exist |
| Engineering | LLM integration, RAG, agents, evals | only if AI features exist |
| Delivery | LLM observability and cost | only if AI features exist |
| Marketing | assisted content generation | optional |

## Transversal concerns

Security, accessibility, performance, privacy and documentation are references in `shared/references/`, loaded by the skills they constrain. Only `security.md` exists today; each of the others is added when a second skill needs it. They are not areas because they do not produce artifacts of their own.

## Invocation shapes

1. **Single capability**: "validate the business model of product X" → orchestrator → `biz-business-model`.
2. **Flow inside one area**: "marketing strategy for launch X" → `flow-launch` (planned, not built), reading Brand and Business artifacts as inputs. The one flow built today is `flow-fix-bug` ("fix this bug end to end").
3. **Flow across areas**: "build a digital product from scratch" → `flow-new-product` (planned, not built), one checkpoint per phase, resumable through `docs/workbench/state.md`.
4. **Actuator**: "schedule a post about X tomorrow at 9" → `flow-social-post` (planned, not built) → copy → asset → confirmation gate → publish → record.

Until a planned flow is built, the orchestrator still names it as the route, with the status `pending`, and proposes one fallback (the closest installed skill, or direct execution with its limits stated) for the user to accept; the phases are then run one capability at a time, each asked for by the user.
