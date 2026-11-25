---
name: pstack-adapter
description: "Run original pstack workflows through configured workers in Rex, Herdr, or headless herdr-core. Loaded by installed pstack workflow skills to map their tools and roles to agent-workers."
---

# pstack-adapter

Loaded by installed pstack skills before upstream text. Use [agent-workers](../agent-workers/SKILL.md) for dispatch, waiting, caller context, config profiles, PR-first delivery, worktrees, and failure recovery. Precedence: user and project instructions override this adapter, and this adapter overrides upstream tools, model defaults, setup, and Cursor paths. Preserve bundled text and report missing capabilities instead of faking them.

## Enter a workflow

1. **Load siblings:** Read sibling skills from `../<name>/SKILL.md` ([bundle.json](references/bundle.json)). No upstream checkout is needed. If a sibling is missing, stop and report an incomplete install ([compatibility.md#install](references/compatibility.md#install)). Never fetch another revision.
2. **Resolve paths:** Read the target `<name>/SKILL.md`, plus any playbook or applied principle leaves. In `poteto-mode`, bare `scripts/...` and `playbooks/...` live under `../poteto-mode/`. Give workers absolute install paths.
3. **Own the workflow here:** Plan, assign, and verify in the controller. Keep playbook stopping points (Investigation and Forensics end in a cited answer, Prototype ends in a decision and throwaway artifact, Multi-phase plan ends in a plan) and run required child skills such as `no-comments` with Comment Sicko.
4. **No nested workers (mandatory in every brief, overrides `agent-workers`):**
   > **Do not delegate, use native subagents, or run a whole playbook. Complete this assignment yourself, and report any need for further delegation to the controller.**
5. **Skip `worker.md` kickoff:** In `poteto-mode` and routed skills, skip upstream `worker.md` kickoff. Dispatch via `agent-workers` with role, scope, criteria, exact authorized repos, hosts, and paths, and rule 4.

## Tool mapping

| Upstream | Equivalent |
|---|---|
| `Agent`, `Task`, `run_in_background` | `agent-workers run --wait` (or `run` plus background `wait --all`). |
| `poteto-agent`, `comment-sicko` | Pass absolute paths to [poteto-agent.md](references/agents/poteto-agent.md) or [comment-sicko.md](references/agents/comment-sicko.md) (plus `../poteto-mode/SKILL.md` for `poteto-agent`). Instructions only, not worker selection. See first-output rules in [harness-tools.md](references/harness-tools.md). |
| `generalPurpose` / `readonly: true` | Configured worker plus upstream prompt. Read-only workers write only to declared reports and `result.json` in the task directory. |
| Isolated writer | Separate worktree at `<main checkout>/.worktrees/<name>` (`--cwd`). |
| `pstack/skills/<n>/`, `cursor-team-kit/skills/<n>/` | Sibling `<n>/` folder. Pass absolute paths for scripts. |
| `setup-pstack`, Cursor model rules | `agent-workers` setup and `[roles]` in `workers.toml`. |
| Shipping, landing, merge | [agent-workers PR-first rule](../agent-workers/SKILL.md#required-rules). |

Use your harness's native file, search, shell, question, and checklist tools for `Read`, `Glob`, `Grep`, `AskQuestion`, and todos.

## Resolve roles

Run `agent-workers roles [<role>]` with the workflow's `--profile` or `--config`. Ignore Cursor model sheets, `# defaults: 3`, and upstream effort or fallback rules.

- **Match roles first:** Classify every assignment, including ad-hoc work, against `[roles]` (`how explainer`, `feature, refactoring`, `how explorer`, `why investigators`). Fall back to worker `description` when no role matches. Record role, worker, profile or config if set, and reason in the brief (private record for blinded `Eval`).
- **Panels:** Single roles name one worker. Panel roles (`interrogate reviewers`, `arena runners`) start one fresh task per entry, including repeated names. Disclose when the exact same model is reused.
- **Same-vendor allowed:** Overrides upstream different-vendor rules for reviews, second opinions, and `arena` judging. Prefer model diversity when configured, but never block or skip review or judging because models share a vendor.
- **Controller-owned:** Run `why`, `reflect`, and small `architect` sketches here. Route large or contested designs to `arena`.
- **Recovery and gaps:** Follow [agent-workers recovery](../agent-workers/SKILL.md#problems) with eligible workers in the active config and record any switch. If a required role or worker is missing outside a sandbox, ask to configure it and continue independent work.

## Artifacts and cleanup

Store controller artifacts (verification evidence, review reports, decision logs) under `<main checkout>/.audit/<task-slug>/` and add `.audit/` to `.git/info/exclude`. Do not create other top-level directories such as `verification/`. Pass affected workers its absolute path. When the task finishes (PR merged or user confirms done), remove your session worktrees per `agent-workers` step 6 and delete `.audit/<task-slug>/` unless work is paused for pickup, the user asks to keep it, or a retained worktree depends on it. Report any retained paths and why they stay.

## References

- [harness-tools.md](references/harness-tools.md): First-output rules, Cursor gaps, and workflow deltas (`interrogate`, `arena`, `Babysit`, `Worktree cleanup`, `ketchup`, `reflect`, `Eval`).
- [compatibility.md](references/compatibility.md): Install command, catalog, and pinned upstream version.
