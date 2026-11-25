---
name: pstack-adapter
description: "Run original pstack workflows through configured workers in Rex, Herdr, or headless herdr-core. Loaded by installed pstack workflow skills to map their tools and roles to agent-workers."
---

# pstack-adapter

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
| `Agent`/`Task`/`run_in_background` | `agent-workers run --wait` (parallel background calls up to `max_active_workers`), or `run` + background `wait [--all]`. |
| `poteto-agent` / `comment-sicko` | Pass absolute path to [poteto-agent](references/agents/poteto-agent.md) or [comment-sicko](references/agents/comment-sicko.md) (+ `../poteto-mode/SKILL.md` for `poteto-agent`). Instructions only, not worker choice. First-output rules: [harness-tools.md](references/harness-tools.md). |
| `generalPurpose` | Selected worker + upstream prompt; no native registration. |
| `readonly: true` | Scoped reads; writes only to declared reports + `result.json` in task dir. Verify checkout/external state. |
| Isolated writer | Separate git worktree per concurrent writer at `<main checkout>/.worktrees/<name>` (`--cwd`), so it inherits the checkout's harness trust. |
| `pstack/skills/<n>/`, `cursor-team-kit/skills/<n>/` | Sibling `<n>/` dir; absolute paths for commands/scripts. |
| `Read`/`Glob`/`Grep`/edits/shell, `AskQuestion`, todos | Harness tools (or chat question / uncommitted checklist). |
| `setup-pstack`, Cursor rules | `agent-workers` setup + `[roles]` in `workers.toml`. |
| Shipping / landing / merge | Follow `agent-workers` PR-first rule. |

## Resolve roles

Run `agent-workers roles [<role>]` (`workers.toml`, or pass `--profile <name>` / `--config <path>`). Ignore Cursor model sheets, `# defaults: 3`, and upstream effort/speed/fallback rules.

- **Profile consistency:** If the user specifies a worker profile/config, pass the same `--profile <name>` (or `--config <path>`) to `agent-workers roles` and all subsequent `run`, `wait`, `check`, and `stats` calls in that workflow, and record the profile/config in brief provenance. If the requested file is missing outside a sandbox, report the blocked dispatch and continue independent work.
- **Role-first:** Classify every assignment (incl. ad-hoc). Match a role first (`how explainer`, `feature, refactoring`, `how explorer`/`why investigators` for ad-hoc/Recall); else pick via `description`.
- **Worker recovery:** Apply the bounded [agent-workers recovery rules](../agent-workers/SKILL.md#problems) and record any switch in brief provenance and the final report. Use only eligible workers in the active config and preserve required delegation and review gates. On sandboxed `config_invalid`, retry outside the sandbox first. If a required role or worker remains missing or invalid, request setup for that step and continue independent work.
- **Single vs panel:** Single -> one worker (`"glm"`). Panel (`interrogate reviewers`, `arena runners`) -> list (`["ds", "haiku"]` or `["solo", "solo"]`), one fresh task per entry; disclose when the exact same model is reused.
- **No cross-vendor restriction:** Overrides upstream different-vendor rules for reviews, second opinions, and `arena` judging—any configured worker may review or judge another worker's output regardless of vendor (e.g., two models from the same vendor, such as `sol` implementing and `astra` reviewing). Prefer model diversity when configured, but never block or skip review/judging because models share a vendor.
- **Controller-owned:** `why`, `reflect`, `architect` sketches (large/contested -> Arena).
- **Brief provenance:** Record matched role (or none), worker, and reason in brief (blinded Eval: private record).

## Finish a workflow

1. **Worktrees:** Remove the worktrees you created per `agent-workers` step 6.
2. **Artifacts:** When the task ends (PR merged or the user confirms it is done), delete `.audit/<task-slug>/`. Keep it only when the work is paused for pickup, the user asks to keep it, or a held worktree still depends on it.
3. **Report:** List each retained worktree or artifact path with its reason. Leave no other workflow directories in the checkout.

## Repository and host boundaries

- State exact authorized repos, hosts, worktrees, and sources in every brief. Broad-search wording stays inside that boundary; empty/thin results never authorize global/owner-wide/cross-repo/cross-host searches (record leads without fetching; ask controller).
- **Snapshots:** Disclose repo, capture time, completeness, unavailable categories; keep a real investigator for available sources even if empty; snapshot != live forge access.
- **Post-run audits:** Auditing native commands (incl. failed calls) quarantines output before synthesis, not a hard sandbox/credential boundary.

## On-demand references (read only when active)

- [review-and-arena.md](references/workflows/review-and-arena.md) (`interrogate`/`arena`/cross-judge) | [ketchup-and-visuals.md](references/workflows/ketchup-and-visuals.md) (`ketchup`/video/visuals)
- [git-and-forge.md](references/workflows/git-and-forge.md) (`Babysit`/worktrees/`Shipping`) | [skills-and-reflect.md](references/workflows/skills-and-reflect.md) (`reflect`/skills/`Eval`)
- [harness-tools.md](references/harness-tools.md) (stalled owners/store/MCP/transcripts/gaps) | [compatibility.md](references/compatibility.md) (install/provenance)
