---
name: agent-workers
description: "Delegate tasks to Pi, Codex, Claude Code, or Antigravity CLI (agy) workers through agent-workers and wait for their file results. Use for Rex or Herdr delegation, headless herdr-core, multi-model tasks, worker setup, or worker efficiency review."
---

# agent-workers

Controller: plan, assign, verify; delegate substantial work to fresh workers via `agent-workers`. Keep main context small—verify claims against diffs/artifacts and check JSON keys/counts before dumping payloads.

## Required rules

- **PR-first:** Deliver repo changes via PR on a feature branch. Never merge to `main`/default/shared branch, push directly, or auto-merge without explicit user request (checks/completion/playbooks never grant merge authority). Include this limit in worker briefs.
- **No native subagents** as controller (workers may use subagents unless restricted by brief).
- **Delegation recovery:** Follow [Problems](#problems) when a worker fails. Use configured workers for required delegation and keep review gates open while recovery is in progress. Retry a sandbox-blocked call outside the sandbox before treating its configuration as missing.
- **Verify controller location:** Rex -> `Workers` tabs in verified session; Herdr core -> `Workers` viewers in verified workspace; legacy Herdr -> `Workers` tabs (separate tab, preserve focus; headless core outside both). Recover missing/conflicting context first.
- **Harness input:** Use the `agent-workers` commands for task submission and recovery. Never answer dialogs or send raw keys/text to worker panes. Trust, permissions, and sign-in decisions stay with the user.
- **Wait for `state: "done"`:** Never consume early files as a delivered result. Closing an unfinished worker cancels its attempt and leaves its review gate unresolved.
- **Never yield without an active wait:** `agent-workers run` (without `--wait`) exits immediately and creates no harness wakeup—external Rex/Herdr panes never wake the controller. After dispatching any worker, do not end your turn with a status message until a background `agent-workers run --wait` or `agent-workers wait` covering every running task is active.
- **`done` != verified:** Check `result_status` (`completed`/`failed`/`blocked`) and verify independently.

## Run agent-workers

`python3 <skill-dir>/scripts/agent-workers.py <cmd> ...` (Python 3.11+, JSON/NDJSON stdout—one JSON object per line for multi-item `wait`/`list`/`check` and `run --wait`; errors exit 1 `{"error","message"}`). Tasks pin backend—wait Rex/Herdr separately. `run`/`detect`/`check` accept caller opts. `run`/`roles`/`stats`/`detect`/`check`/`wait` accept `--profile <name>` (`workers.<name>.toml`) or `--config <path>` (mutually exclusive; env: `AGENT_WORKERS_PROFILE` / `AGENT_WORKERS_CONFIG`, overridden by CLI).

| Command | Purpose |
|---|---|
| `run <worker> --brief <file\|-> [--cwd <dir>] [--wait [--max-seconds <n>]]` | Launch worker (`-`=stdin); `--wait` flushes launch JSON then waits for settlement (2 NDJSON lines). |
| `wait [<id>...] [--all] [--max-seconds <n>] [--recheck]` | Wait for change (`--all`: until all settle; returns immediately on problems, `long_running`, unclosed `done`). |
| `list [--active] [--limit <n>] [--verbose]` | Compact list (`--verbose` adds full backend bindings). |
| `roles [<role>]` | Resolve `workers.toml` roles/workers; flag issues. |
| `stats [--workspace <id>] [--days <n>] [--no-samples]` | Store metrics (`--no-samples` omits `duration_samples`). |
| `close <id>` / `verify-viewer <id>` | Close terminal+viewer; live-verify core viewer/output. |
| `submit <id>` | Send the brief once on a retained Rex/core `not_sent` task after readiness is confirmed. |
| `detect` / `check [<w>...] [--cwd <dir>] [--max-seconds <n>]` | Route/harnesses/Pi status; verify workers (300s cap). |

**Sandboxed controllers (`agy`, `codex`):** `agent-workers` accesses `~/.config/herdr-orchestrator/`, `~/.local/state/herdr-orchestrator/`, and local Rex/Herdr sockets outside the workspace. If a sandboxed call fails with `config_invalid`, permission, or backend socket errors, rerun `agent-workers` outside the sandbox (e.g., `BypassSandbox: true` in `agy`) before assuming setup is missing.

**Caller context:** Pass `--caller-text '<16+ unique visible chars>'` (prefer unwrapped plain text fixed on screen, e.g. the status line, avoiding markdown syntax) on `run`/`check` to auto-resolve the unique Rex block/Herdr pane (fails closed on 0/>1); add `--caller-block`/`--caller-pane` to disambiguate. Focus/inherited IDs never prove location ([setup.md#caller-context](references/setup.md#caller-context)).

## Delegate and verify

1. **Select & isolate:** Role-first (`roles`), else `description`. When the user specifies a profile/config, pass the same `--profile`/`--config` consistently to `roles`, `run`, `wait`, `check`, and `stats`; if the requested file is missing (outside a sandbox), report failure and never silently fall back to default `workers.toml`. Separate git worktree per writer at `<main checkout>/.worktrees/<name>` (`--cwd`; [placement](references/setup.md#worktree-placement)); read-only workers may share checkout (writes only to declared reports + `result.json` in task dir).
2. **Brief:** Goal, criteria, PR-first limit, absolute paths, ownership, verification, outputs, commit rule (`agent-workers` appends rules/schema).
3. **Dispatch:** Start up to `max_active_workers` in parallel before waiting. Check `state` on every `run` response—if `state != "running"` (`not_started`, `start_failed`, `blocked`), handle immediately per `Problems` rather than waiting. In reactive-wakeup harnesses (Claude Code, `agy`, Codex), prefer background `run --wait` (one parallel background call per worker) so dispatch and waiting are atomic and you cannot yield without a wakeup; if splitting `run` and `wait`, immediately start a background `wait --all` before ending your turn. On core viewer failure, report `warning` + `viewer_verification_error` immediately while monitoring.
4. **Wait & read:** Unbounded `run --wait` / `wait` (`--all` for batches) in background/yielded shells (Claude Code, `agy`, Codex); `--max-seconds 300` (timeout >300s) in blocking-only shells (Pi); never `--max-seconds 1`. Report `long_running` once and keep waiting. On `done`, check `result_status` and read `result_path`/`files` (relative to result dir). Handle `blocked` and `failed` per [Problems](#problems). Follow-ups are fresh tasks.
5. **Verify & close:** Verify diffs/behavior/verdicts. If `closed: false`, read `message` and retry `close`.
6. **Remove your worktrees:** After a writer is closed and its commits are integrated, remove only the worktrees you created this session: `git worktree remove` (no `--force`) if `git status --porcelain --ignored` is empty, then `git branch -d` (refusal keeps the branch). Keep and report any worktree with uncommitted changes, ongoing use, or unknown ownership; leave leftovers to the `Worktree cleanup` playbook ([commands](references/setup.md#worktree-placement)).

## Problems

1. **Diagnose:** Inspect task state, `submission`, and the [recorded backend](references/lifecycle.md#problem-recovery) before acting. Use `wait --recheck` to observe a problem task when it may have resumed or receipt is uncertain. Verify that native `blocked` corresponds to an actual prompt before acting on it. Never resend `sent` or `unknown`, or start a replacement while receipt or side effects are unresolved.
2. **Recover within the assignment:**
   - If a retained Rex/core task is ready and `submission: "not_sent"`, call `submit <id>` and start a wait for it.
   - Make one fresh recovery attempt for a safely replayable assignment after a confirmed unsent startup failure, an exited process, a confirmed end of turn with a missing or invalid result, a diagnosed worker-specific service or harness failure, or a confirmed informational prompt that requires no authorization. Retry the same worker for a transient failure or use an eligible worker in the active config for a persistent worker-specific blocker.
   - For confirmed quota exhaustion, try eligible workers in the active config that have not yet been tried for this assignment. Confirm quota exhaustion on each failed attempt before switching again.
   - For a delivered `blocked` result, resolve routine choices from the existing brief and repository conventions, then start a fresh continuation. Ask the user for missing input or authorization that the controller cannot supply. Escalate a repeated blocker if no new information is available.
   - Before a fresh attempt, confirm `closed: true` on the prior task using `close <id>` if needed. For writers, reconcile the worktree and any external effects, then carry forward verified work. Keep the role, scope, worker restrictions, and permissions of the original assignment. Start a fresh wait, and record both task IDs, the reason, and any worker change.
3. **Escalate only what's unresolved:** Leave interactive prompts untouched. An already authorized, eligible worker may take over a confirmed unsent task within the existing scope and permissions. Never use a switch to bypass a denial or required authorization. If recovery is exhausted or unsafe, report the task, state, submission, and specific blocker. Require fresh `verify-viewer <id>` with `viewer_verified: true` before directing the user to a core window.
4. **Keep the batch moving:** Maintain waits for other running tasks while recovering one, and continue independent work when a task needs the user. Wait for normal verified delivery on any replacement before counting its review seat or advancing a dependent step. A `long_running` reminder alone does not justify restarting a worker.

## Read when needed

- [setup.md](references/setup.md): setup (`workers.toml`, `config_invalid`, 1 question/turn), permissions, dialogs (read on any `start_failed`), worktree placement, caller context.
- [lifecycle.md](references/lifecycle.md): states/internals/recovery | [stats.md](references/stats.md): metrics | [workers.example.toml](references/workers.example.toml) (state: `$XDG_STATE_HOME/herdr-orchestrator/tasks/`).
