## 2026-11-28: The task of an imported skill goes to the agent of its area (I2b)

Package I2b, a follow-up of I2 (`docs/decisions/2026-11-28-i2-imported-skill-runtime.md`). Asked to approve assumption 3 of that entry ("the planning agent owns an imported task"), the maintainer answered, on 2026-11-28: "When a skill is imported, we must be able to associate it with an area." This entry replaces assumption 3; the I2 entry is not edited.

**Decided.** When area agents are configured, `plan.agent_for` gives a task of an imported skill (`imported_owner`) to:

1. The agent the person named: the optional key `agent` in the skill's entry of `imported_skills` (`{"agent": "<agent name>"}`, beside `without_external_line`), validated by `project_config` as an agent name (`autonomy.AGENT_KEY`). At plan time it must be an enabled agent of `area_agents`; otherwise the task is refused with a sentence that names the skill, the agent and the fix (enable the agent, or change the key and accept the configuration again).
2. Else the area of the name: its prefix, which `scripts/skill_import.py normalize` already requires. The candidates are the enabled agents, other than the planning agent, whose resolved pack holds at least one workbench skill with that prefix. Exactly one candidate owns the task. Several candidates: the task is refused, naming the area, the candidates and the key `imported_skills.skills.<name>.agent`. None: the planning agent owns it, and the plan's reason says "no agent covers the area <area>: the planning agent owns it"; with no enabled planning agent either, the refusal of I2 stands.
3. Without area agents the task has no agent, as before; a step task is unchanged.

**The area is read from the prefix, not from `metadata.area`.** The name of an imported skill carries its prefix and the import tool enforces it, while an imported skill's own `metadata.area` is the author's claim; for the workbench skills in a pack the validator already proves prefix and `metadata.area` agree, and an area has exactly one prefix, so comparing prefixes needs no copy of the table of areas.

**Why several candidates are refused, not picked.** Choosing by name order or by pack size would be a guess about which agent should carry a foreign skill's task, and an agent owns the task's daily limits, its mode and its profile. Principle 5: a decision that belongs to the person is asked (through the refusal, with the key to set), never guessed.

**What did not change.** Who owns the task changes none of its limits: it stays supervised, without the web, its review never released (`autonomy.review_action`), with every refusal of `imported.refusals`, whatever the agent's mode, consent or proof. No skill folder, fingerprinted file or measurement changes.
