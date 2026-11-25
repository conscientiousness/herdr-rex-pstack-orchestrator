# Harness tool mappings and workflow deltas

On-demand reference for Cursor-specific mappings and workflow deltas not covered in [pstack-adapter](../SKILL.md) or [agent-workers](../../agent-workers/SKILL.md). Read only the section matching your active workflow.

## Cursor-specific mappings

| Upstream | Current harness equivalent |
|---|---|
| Named agent first-output rules (`poteto-agent`, `comment-sicko`) | Pass their absolute paths in the brief. Tell the worker to read the agent file and required skill with tools before emitting any text, then follow its first-output rule verbatim. Never paraphrase or copy the rule into the brief. |
| Steer or replace a stalled owner | Follow up on delivered work with a fresh task and prior report. For stalled or failed tasks, follow [agent-workers recovery](../../agent-workers/SKILL.md#problems) and confirm the prior writer stopped before transferring its branch or PR. |
| Agent store in system prompt | Use `<main checkout>/.audit/<task-slug>/` ([pstack-adapter](../SKILL.md#artifacts-and-cleanup)). `show-me-your-work` may share a sanitized decision log if project policy permits it. |
| Team-kit skills (`deslop`, `control-cli`, `control-ui`) | Read sibling `<name>/SKILL.md`, resolve scripts from that directory, and apply only steps supported by available tools. |
| MCP and transcripts | Check tools available in this session. Workers do not inherit controller MCP tools. Use current-workspace session records for transcripts, or report them unavailable. |
| `/loop`, custom modes, cloud agents, `/visualize` | Not supplied by this adapter (`agent-workers` runs local processes). Use an equivalent only if your environment provides one. |

If a required step has no available equivalent, report the gap and keep it unresolved rather than claiming the playbook finished. Check script prerequisites (Bun, `gh`, `origin`, `jq`) before running them, and do not install tools just to read a skill.

## Interrogate and Arena

- **`interrogate`:** Run the full configured `interrogate reviewers` panel with one fresh task per entry. Never downgrade silently to one reviewer (report any single-worker audit as limited). Give every adversary the same brief and its own writable worktree containing in-scope uncommitted and relevant untracked changes. Allow repros and tests only inside its worktree, and forbid product fixes or delivery-branch edits. Rerun each finding's command against the captured target in an isolated worktree. Fixes and re-reviews run only on authorized changes, with fresh workers per round.
- **`arena`:** Start one fresh task per `arena runners` entry in separate worktrees. For `arena cross-judge pool`, pick one configured pool worker after candidates finish. Prefer a different model or vendor when available, allow same-vendor judges, and skip judging with disclosure only if no pool worker can run. Never use unconfigured models or edit `workers.toml`.

## Babysit, Worktree cleanup, and Shipping

- **`Babysit`:** On GitHub, pass an explicit target to bundled `watch-pr` (`--status-only` for a check, drive mode to merge-ready or approval gate). Queued merge watchers belong to `Shipping`. Because `watch-pr` installs Bun packages into `scripts/node_modules`, copy `poteto-mode/scripts/` to a private temp directory when running in place would touch installed skills or the project, then run `watch-pr/watch-pr` by absolute path from the repo.
- **`Worktree cleanup`:** The bundled audit script fetches the base branch and scans Cursor transcripts. Run it only when those sources are in scope. Otherwise inspect scoped worktrees, active worker task directories, and forge state directly. Check tracked, untracked, and ignored files and detached `HEAD` commits before removing anything, and keep unknown owners. Simulator and cache cleanup need explicit scope.
- **`Shipping`:** Follow the [agent-workers PR-first rule](../../agent-workers/SKILL.md#required-rules). Stop before merging or enabling auto-merge unless the user explicitly asked to merge.

## Ketchup, Ketchup-video, and visuals

- **`ketchup` (strictly read-only):** Never run `agent-workers wait`, launch workers, or modify or close tasks. Check PR and CI status with read-only `origin` or `gh`, and check workers with `agent-workers list --active` (or `list --verbose`) plus [terminal inspection commands](../../agent-workers/references/lifecycle.md#problem-recovery).
- **`ketchup-video`:** Same read-only rules, except rendering the video outside the repo. This adapter supplies no video renderer or embedder. If unavailable or failing, disclose the gap in one line and fall back per upstream `ketchup-video/SKILL.md`.
- **Visuals:** `/visualize` is not bundled, and a Markdown table is not a picture. Use supported Mermaid or available image tools only from existing evidence, or disclose the gap.

## Reflect, skill authoring, and Eval

- **`reflect` and skill paths:** Map `.cursor/skills/` and `~/.cursor/skills/` to this harness's discovered project or user skills directory, preserving scope. Before requesting approval for a `reflect` edit, show the destination path. After approval, copy the skill folder there and edit the copy. Never edit `plugins/cache/`. Keep generated skills separate from this bundle, and use only an authorized backlog tracker.
- **Blinded `Eval`:** Keep role and worker routing in a private controller record, never in candidate briefs. Give candidates identical tasks and neutral paths, and give the judge sanitized labels and the hidden rubric. Report explicitly if the harness or config breaks blinding.
