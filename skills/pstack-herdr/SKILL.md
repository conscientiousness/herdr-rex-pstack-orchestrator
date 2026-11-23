---
name: pstack-herdr
description: "Run original pstack workflows through configured workers in Rex, Herdr, or headless herdr-core. Loaded by installed pstack workflow skills to map their tools and roles to agent-workers."
---

# pstack-herdr

Loaded by installed pstack skills before upstream text. Read [agent-workers](../agent-workers/SKILL.md) for dispatch, waiting, caller context, PR-first delivery, and recovery. Precedence: user/project instructions > this adapter > upstream tools, models, config paths, and delegation. Preserve bundled text; report gaps instead of workarounds.

## Enter a workflow

1. **Siblings:** Use `../<name>/SKILL.md` ([bundle.json](references/bundle.json)); no upstream checkout needed. Missing sibling -> stop and report incomplete install ([compatibility.md#install](references/compatibility.md#install)); never fetch another revision.
2. **Read target:** Read `<name>/SKILL.md` (or [poteto-mode](../poteto-mode/SKILL.md), playbook, references, applied principle leaves). In `poteto-mode`, bare `scripts/...` and `playbooks/...` start at `../poteto-mode/`. Resolve relative links from their file; give workers absolute install paths.
3. **Controller owns workflow:** Plan, assign, QC here; delegate via `agent-workers`. Keep stopping points (Investigation/Forensics -> cited answer; Prototype -> decision + throwaway artifact; Multi-phase plan -> plan) and run required child skills (`no-comments` -> Comment Sicko).
4. **Mandatory worker brief rule** (overrides `agent-workers`'s worker-subagent allowance):
   > **Do not delegate, use native subagents, or run a whole playbook. Complete this assignment yourself; report any need for further delegation to the controller.**
5. **Skip `worker.md` kickoff:** In `poteto-mode` and routed skills, skip upstream `worker.md` kickoff; dispatch via `agent-workers` with role, scope, criteria, and rule 4.

## Core tool mapping

| Upstream | Equivalent |
|---|---|
| `Agent`/`Task`/`run_in_background` | `agent-workers run` (`--brief <file\|->`, up to `max_active_workers`), then `wait [--all]`. |
| `poteto-agent` / `comment-sicko` | Pass absolute path to [poteto-agent](references/agents/poteto-agent.md) or [comment-sicko](references/agents/comment-sicko.md) (+ `../poteto-mode/SKILL.md` for `poteto-agent`). Instructions only, not worker choice. First-output rules: [herdr-tools.md](references/herdr-tools.md). |
| `generalPurpose` | Selected worker + upstream prompt; no native registration. |
| `readonly: true` | Scoped reads; writes only to declared reports + `result.json` in task dir. Verify checkout/external state. |
| Isolated writer | Separate git worktree per concurrent writer (`--cwd`). |
| `pstack/skills/<n>/`, `cursor-team-kit/skills/<n>/` | Sibling `<n>/` dir; absolute paths for commands/scripts. |
| `Read`/`Glob`/`Grep`/edits/shell, `AskQuestion`, todos | Harness tools (or chat question / uncommitted checklist). |
| `setup-pstack`, Cursor rules | `agent-workers` setup + `[roles]` in `workers.toml`. |
| Shipping / landing / merge | Follow `agent-workers` PR-first rule. |

## Resolve roles

Run `agent-workers roles [<role>]` (`workers.toml`). Ignore Cursor model sheets, `# defaults: 3`, and upstream effort/speed/fallback rules.

- **Role-first:** Classify every assignment (incl. ad-hoc). Match a role first (`how explainer`, `feature, refactoring`, `how explorer`/`why investigators` for ad-hoc/Recall); else pick via `description`.
- **No silent substitution:** Never assume worker names or substitute defaults, `auto`, `inherit-parent`, native subagents, or auto-retries/fallbacks. Missing/invalid role or worker -> setup with user first.
- **Single vs panel:** Single -> one worker (`"glm"`). Panel (`interrogate reviewers`, `arena runners`) -> list (`["ds", "haiku"]` or `["solo", "solo"]`), one fresh task per entry; same-model != cross-model validation (disclose gaps).
- **Controller-owned:** `why`, `reflect`, `architect` sketches (large/contested -> Arena).
- **Brief provenance:** Record matched role (or none), worker, and reason in brief (blinded Eval: private record).

## Repository and host boundaries

- State exact authorized repos, hosts, worktrees, and sources in every brief. Broad-search wording stays inside that boundary; empty/thin results never authorize global/owner-wide/cross-repo/cross-host searches (record leads without fetching; ask controller).
- **Snapshots:** Disclose repo, capture time, completeness, unavailable categories; keep a real investigator for available sources even if empty; snapshot != live forge access.
- **Post-run audits:** Auditing native commands (incl. failed calls) quarantines output before synthesis, not a hard sandbox/credential boundary.

## On-demand references (read only when active)

- [review-and-arena.md](references/workflows/review-and-arena.md) (`interrogate`/`arena`/cross-judge) | [ketchup-and-visuals.md](references/workflows/ketchup-and-visuals.md) (`ketchup`/video/visuals)
- [git-and-forge.md](references/workflows/git-and-forge.md) (`Babysit`/worktrees/`Shipping`) | [skills-and-reflect.md](references/workflows/skills-and-reflect.md) (`reflect`/skills/`Eval`)
- [herdr-tools.md](references/herdr-tools.md) (stalled owners/store/MCP/transcripts/gaps) | [compatibility.md](references/compatibility.md) (install/provenance)
