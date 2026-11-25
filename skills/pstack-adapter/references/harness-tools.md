# Agent Workers tool mapping for pstack

On-demand reference for Cursor-specific instructions not covered in the [pstack-adapter hot path](../SKILL.md) or [agent-workers](../../agent-workers/SKILL.md).

## Workflow-specific guides

Read only the guide matching the active workflow:

| Workflow | Reference |
|---|---|
| `interrogate`, `arena`, design/review panels, cross-judge | [workflows/review-and-arena.md](workflows/review-and-arena.md) |
| `ketchup`, `ketchup-video`, reply visuals, `/visualize` | [workflows/ketchup-and-visuals.md](workflows/ketchup-and-visuals.md) |
| `Babysit`, `Worktree cleanup`, `Shipping`, GitHub watcher | [workflows/git-and-forge.md](workflows/git-and-forge.md) |
| `reflect`, `Authoring a skill`, `Eval`, skill paths | [workflows/skills-and-reflect.md](workflows/skills-and-reflect.md) |

## Additional Cursor-to-harness mappings

| Upstream instruction | Current harness equivalent |
|---|---|
| Follow up, steer, or replace a stalled owner | Follow up on delivered work with a fresh task and the prior report. For stalled or failed tasks, inspect the [recorded backend](../../agent-workers/references/lifecycle.md#problem-recovery) and follow user-directed recovery. Confirm the previous writer has stopped before transferring ownership of its branch, PR, or shared target. |
| Named agent with first-output rules (`poteto-agent`, `comment-sicko`) | Named-agent files are not preloaded native agents. Include their resolved absolute paths in the brief and instruct the worker to read the agent file and required skill via tools before emitting any assistant text, then follow its first-output rule. Do not paraphrase or copy the agent's rules; a preamble before those reads violates the contract. |
| Root/current agent store in system prompt | Use the controller-owned artifact directory `<main checkout>/.audit/<task-slug>/` and pass affected workers its resolved absolute path. Add `.audit/` to `.git/info/exclude` when creating it. Verification evidence, review reports, and decision logs go there; never create other top-level directories such as `verification/`. Keep private records and transcripts outside commits and available to replacement controllers, and outside the internal `agent-workers` store. Delete it as described in [Finish a workflow](../SKILL.md#finish-a-workflow). `show-me-your-work` may deliver a sanitized decision log when reviewers need the trail and project policy permits it. |
| `deslop`, `control-cli`, `control-ui`, or `cursor-team-kit/skills/<name>/` | Read sibling `<name>/SKILL.md` and resolve scripts/resources from that installed directory. Apply instructions only with tools actually available in this harness. |
| MCP discovery | Inspect tools available in the current session. Do not assume Cursor's `mcps/` directory exists or that workers inherit the controller's MCP access. |
| Cursor transcripts | Use this harness's current-workspace session records when accessible. Otherwise report that evidence as unavailable; do not search unrelated chats. |
| `/loop`, custom modes, cloud agents | Not supplied by this adapter (`agent-workers` runs local processes). Use a corresponding capability only if the current environment provides it. |

## Gaps and prerequisites

If a required step has no available equivalent, report the specific gap, keep that step unresolved, and do not claim the complete playbook ran. Upstream scripts may require Bun, `gh` or `origin` CLI, `jq`, or app-specific tools; check prerequisites before running them and do not install dependencies merely to read a skill.
