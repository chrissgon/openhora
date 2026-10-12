// The words and the numbers of the demo world: three fictional projects, their agents, their requests, the documents they hold and the story
// of the request "Spring sale page". Everything here is invented: the shop, the people ("Demo Person"), the costs and the post. The one
// exception is the skills list of the Control room, which is the workbench's own (fixtures/skills.json, from docs/inventory.md).
// An age is in minutes before the world started.

export const PERSON = "Demo Person";

export const FLOWS = [
  { flow: "launch-page", title: "Launch a page", tasks: 2 },
  { flow: "fix-bug", title: "Fix a bug", tasks: 3 },
  { flow: "write-docs", title: "Write documentation", tasks: 2 },
];

const STATE_MD = (name) => `# Workbench state

- Project: ${name}
- Docs in git: none
- Autonomy: milestones

## Decisions

- ${PERSON} chose the demo's fictional data: nothing here is a real project.
`;

export const PROJECTS = [
  {
    id: "3f9a1c07d2b4",
    name: "northwind-shop",
    folder: "/home/demo/northwind-shop",
    agents: [
      { name: "planning", pack: "planning", mode: "supervised", maxRuns: 12, maxUsd: 5, runs: 2, usd: 0 },
      { name: "design", pack: "design", mode: "supervised", maxRuns: 6, maxUsd: 3, runs: 1, usd: 0 },
      { name: "engineering", pack: "engineering", mode: "milestones", maxRuns: 8, maxUsd: 4, runs: 1, usd: 0, maxParallel: 2 },
      { name: "marketing", pack: "marketing", mode: "supervised", maxRuns: 6, maxUsd: 2, runs: 0, usd: 0.35 },
    ],
    requests: [
      {
        id: 1, title: "Refresh the alt text of the product photos", flow: "launch-page", state: "done", ago: 240,
        tasks: [
          { id: 2, key: "write-alt-text", title: "Write the alt text", skill: "design-handoff", agent: "design", state: "done", ago: 235, text: "Write the alt text of the twelve product photos." },
          { id: 3, key: "apply-alt-text", title: "Apply it to the templates", skill: "eng-implement", agent: "engineering", state: "done", after: ["write-alt-text"], ago: 235, text: "Put the alt text into the product templates." },
        ],
      },
    ],
    runs: [
      { task: 2, status: "ok", ending: "done", ago: 150, minutes: 4, tokens: 18200 },
      { task: 3, status: "ok", ending: "done", ago: 100, minutes: 7, tokens: 24100 },
    ],
    pending: [],
    messages: [
      { id: 1, role: "user", text: "Refresh the alt text of the product photos", ago: 242 },
      { id: 2, role: "assistant", text: "Recorded as request 1. The planning agent planned it from the flow launch-page. The plan was approved.", task: 1, ago: 241 },
    ],
    docs: [
      { path: "docs/workbench/state.md", owner: null, agent: null, kind: "markdown", ago: 50, text: STATE_MD("northwind-shop") },
      { path: "docs/design/alt-text.md", owner: "design-handoff", agent: "design", kind: "markdown", ago: 50, text: "# Alt text of the product photos\n\n- Status: draft\n\n| Photo | Alt text |\n|---|---|\n| red-cap.jpg | A red baseball cap on a white table |\n| canvas-bag.jpg | A canvas shoulder bag with two leather straps |\n| white-sneaker.jpg | A white low-top sneaker seen from the side |\n" },
      { path: "docs/brand/voice.md", owner: "brand-voice", agent: null, kind: "markdown", ago: 4000, text: "# Voice of Northwind Shop\n\n- Plain and warm, never loud.\n- Prices are written with the currency sign and no decimals when they are round.\n- One exclamation mark per post, at most.\n" },
    ],
  },
  {
    id: "a84e6b2f0c19",
    name: "tinykv-docs",
    folder: "/home/demo/tinykv-docs",
    agents: [
      { name: "planning", pack: "planning", mode: "supervised", maxRuns: 10, maxUsd: 4, runs: 1, usd: 0 },
      { name: "engineering", pack: "engineering", mode: "supervised", maxRuns: 6, maxUsd: 3, runs: 1, usd: 0 },
    ],
    requests: [
      {
        id: 1, title: "Document the TTL option", flow: "write-docs", state: "planned", ago: 180,
        tasks: [
          { id: 2, key: "draft-ttl", title: "Draft the TTL section", skill: "eng-docs", agent: "engineering", state: "waiting", ago: 175, text: "Write the section that explains the ttl option of the store." },
          { id: 3, key: "check-examples", title: "Check the examples", skill: "eng-unit-tests", agent: "engineering", state: "planned", after: ["draft-ttl"], ago: 175, text: "Run the examples of the new section." },
        ],
      },
    ],
    runs: [{ task: 2, status: "ok", ending: "done", ago: 40, minutes: 6, tokens: 21400 }],
    pending: [
      {
        id: 1, kind: "review", task: 2, agent: "engineering", ago: 35, run: 1, title: "eng-docs: done",
        body: "- Section: `docs/ttl.md` (Status: draft)\n- Explains the `ttl` option, its unit (seconds) and what happens to a key that expires while it is read.\n- Next: the examples are run\n",
        returned: [{ class: "document", path: "docs/ttl.md" }],
      },
    ],
    messages: [
      { id: 1, role: "user", text: "Document the TTL option", ago: 182 },
      { id: 2, role: "assistant", text: "Recorded as request 1. The planning agent planned it from the flow write-docs. The plan was approved.", task: 1, ago: 181 },
    ],
    docs: [
      { path: "docs/workbench/state.md", owner: null, agent: null, kind: "markdown", ago: 40, text: STATE_MD("tinykv-docs") },
      { path: "docs/ttl.md", owner: "eng-docs", agent: "engineering", kind: "markdown", ago: 40, text: "# The ttl option\n\n`ttl` is the number of seconds a key lives. A key that expires while it is being read is returned once more, then removed.\n" },
    ],
  },
  {
    id: "5c27d90e81fa",
    name: "lumen-notes",
    folder: "/home/demo/lumen-notes",
    agents: [
      { name: "planning", pack: "planning", mode: "supervised", maxRuns: 10, maxUsd: 4, runs: 1, usd: 0 },
      { name: "design", pack: "design", mode: "supervised", maxRuns: 6, maxUsd: 3, runs: 0, usd: 0 },
    ],
    requests: [{ id: 1, title: "Name the app", flow: null, state: "requested", ago: 70, tasks: [] }],
    runs: [],
    pending: [
      {
        id: 1, kind: "question", task: 1, agent: null, ago: 65, run: null, title: "planning: question",
        body: "Nothing was named yet: the audience is your decision.\n\n1. Which audience should the name speak to first: students or teams? Recommended: students, because the notes app is free for them.\n",
        returned: [],
      },
    ],
    messages: [
      { id: 1, role: "user", text: "Name the app", ago: 72 },
      { id: 2, role: "assistant", text: "Recorded as request 1. The planning agent has a question before it can plan it.", task: 1, ago: 70 },
    ],
    docs: [{ path: "docs/workbench/state.md", owner: null, agent: null, kind: "markdown", ago: 70, text: STATE_MD("lumen-notes") }],
  },
];

// The story of the request "Spring sale page" in northwind-shop (request 4: task numbers 5 and 6).
export const SPRING = {
  title: "Spring sale page",
  flow: "launch-page",
  planTasks: [
    { key: "build-page", skill: "eng-implement", agent: "engineering", title: "Build the sale page", milestone: false, web: false, depends_on: [],
      text: "Build the Spring sale page: a banner, three product cards and a countdown to the sale's last day." },
    { key: "sale-post", skill: "mkt-social-copy", agent: "marketing", title: "Publish the sale post", milestone: true, web: false, depends_on: ["build-page"],
      text: "Write one short post that announces the sale, and stop at the gate to publish it." },
  ],
  reply: "Recorded as request 4. The planning agent proposes a plan from the flow launch-page: two tasks.",
  review: {
    title: "eng-implement: done",
    body: "- Page: `docs/engineering/spring-sale-page.md` (Status: draft)\n- Built the Spring sale page: a banner, three product cards and a countdown that ends on Sunday.\n- Next: mkt-social-copy writes the sale post\n- Open question: should the banner show the discount as a percentage or as a price?\n",
    returned: [{ class: "document", path: "docs/engineering/spring-sale-page.md" }, { class: "state", path: "docs/workbench/state.md" }],
    doc: "# Spring sale page\n\n- Status: draft\n- Banner: \"Spring sale: 20% off until Sunday\"\n- Three product cards: red cap, canvas bag, white sneaker\n- Countdown: ends on the sale's last day at midnight\n",
  },
  effect: {
    title: "Publish the sale post",
    account: "northwind-shop",
    text: "Spring sale at Northwind Shop: 20% off caps, bags and sneakers until Sunday. The new page is live: northwind.example/spring",
    doc: "# Sale post\n\n- Status: waiting for approval\n- Account: northwind-shop\n\nSpring sale at Northwind Shop: 20% off caps, bags and sneakers until Sunday. The new page is live: northwind.example/spring\n",
  },
  acceptance: {
    title: "Accept request 4: Spring sale page",
    body: "Both tasks of the request are done: the page is built and the post is published.\n\nAccept it to close the request.",
  },
  productDoc: "# Spring sale: brief\n\n- Goal: sell last season's caps, bags and sneakers before the new ones arrive.\n- Discount: 20% until Sunday.\n- Owner: " + PERSON + "\n",
};
