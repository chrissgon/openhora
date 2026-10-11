// The fixtures the world starts from: the answers of the real operations, written by scripts/demo_fixtures.py (python3 scripts/demo_fixtures.py --write).
// JSON modules, so that the demo reads them with no network call of its own. The world copies them and never changes them.

import projects from "./fixtures/projects.json" with { type: "json" };
import versions from "./fixtures/versions.json" with { type: "json" };
import version from "./fixtures/version.json" with { type: "json" };
import status from "./fixtures/status.json" with { type: "json" };
import statusRouting from "./fixtures/status-routing.json" with { type: "json" };
import statusLive from "./fixtures/status-live.json" with { type: "json" };
import pending from "./fixtures/pending.json" with { type: "json" };
import pendingPlan from "./fixtures/pending-plan.json" with { type: "json" };
import pendingQuestion from "./fixtures/pending-question.json" with { type: "json" };
import pendingReview from "./fixtures/pending-review.json" with { type: "json" };
import pendingEffect from "./fixtures/pending-effect.json" with { type: "json" };
import pendingAcceptance from "./fixtures/pending-acceptance.json" with { type: "json" };
import task from "./fixtures/task.json" with { type: "json" };
import taskLive from "./fixtures/task-live.json" with { type: "json" };
import agents from "./fixtures/agents.json" with { type: "json" };
import conversation from "./fixtures/conversation.json" with { type: "json" };
import skills from "./fixtures/skills.json" with { type: "json" };
import costs from "./fixtures/costs.json" with { type: "json" };
import connections from "./fixtures/connections.json" with { type: "json" };
import artifacts from "./fixtures/artifacts.json" with { type: "json" };
import artifact from "./fixtures/artifact.json" with { type: "json" };
import commands from "./fixtures/commands.json" with { type: "json" };
import flows from "./fixtures/flows.json" with { type: "json" };
import progress from "./fixtures/progress.json" with { type: "json" };
import job from "./fixtures/job.json" with { type: "json" };
import errors from "./fixtures/errors.json" with { type: "json" };
import writes from "./fixtures/writes.json" with { type: "json" };

export const F = Object.freeze({
  "projects": projects,
  "versions": versions,
  "version": version,
  "status": status,
  "status-routing": statusRouting,
  "status-live": statusLive,
  "pending": pending,
  "pending-plan": pendingPlan,
  "pending-question": pendingQuestion,
  "pending-review": pendingReview,
  "pending-effect": pendingEffect,
  "pending-acceptance": pendingAcceptance,
  "task": task,
  "task-live": taskLive,
  "agents": agents,
  "conversation": conversation,
  "skills": skills,
  "costs": costs,
  "connections": connections,
  "artifacts": artifacts,
  "artifact": artifact,
  "commands": commands,
  "flows": flows,
  "progress": progress,
  "job": job,
  "errors": errors,
  "writes": writes,
});
