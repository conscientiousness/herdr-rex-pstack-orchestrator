---
name: agent-workers
description: "Delegate tasks to Pi, Codex, Claude Code, or Antigravity CLI (agy) workers through agent-workers and wait for their file results. Use for Rex or Herdr delegation, headless herdr-core, multi-model tasks, worker setup, or worker efficiency review."
---

# agent-workers

Plan, assign, and verify work in the controller. Delegate substantial work to fresh workers through `agent-workers`, and keep the main context small by checking diffs and summaries instead of dumping raw payloads.

## Required rules

- **PR-first:** Put repository changes on a feature branch and open or update a PR. Never merge to `main` or a shared branch, push directly, or enable auto-merge without explicit user approval. Put this limit in every worker brief.
- **No native subagents as controller:** Delegate only through `agent-workers`. Workers may use their own subagents unless the brief forbids it.
- **Never type into worker panes:** Use `agent-workers` commands for submission and recovery. Trust, permission, and sign-in prompts belong to the user.
- **Wait for `state: "done"`:** Never consume early files on disk. Closing an unfinished worker cancels it and leaves any review gate open.
- **Keep an active wait:** `agent-workers run` without `--wait` exits immediately, and external Rex or Herdr panes never wake you. Never end your turn with running workers unless a background `run --wait` or `wait` covers all of them.
- **Verify every delivery:** `state: "done"` only means the turn ended with a valid `result.json`. Check `result_status` (`completed`, `failed`, or `blocked`) and verify diffs and behavior yourself.

## Run agent-workers

Run `python3 <skill-dir>/scripts/agent-workers.py <command>` (Python 3.11+, JSON or NDJSON stdout, errors exit 1 with `{"error", "message"}`). Run `<command> --help` for flags. Wait on Rex and Herdr tasks in separate calls.

| Command | Purpose |
|---|---|
| `run <worker> --brief <file\|-> [--cwd <dir>] [--wait] [--continue-on-long-running]` | Start a worker (`-` reads stdin). `--wait` prints launch JSON then waits for settlement. |
| `wait [<id>...] [--all] [--max-seconds <n>] [--recheck] [--continue-on-long-running]` | Wait for a state change. `--all` waits until all targets settle, returning early on problems, `long_running` (unless `--continue-on-long-running`), or unclosed `done`. |
| `inspect <id> [--lines <n>]` | Read-only live status, elapsed time, and trailing visible lines from the task's pinned terminal (never types or mutates state). |
| `list` / `roles` / `stats` | List tasks (`--active`, `--verbose`), resolve config roles, or view store metrics. |
| `submit <id>` / `close <id>` / `verify-viewer <id>` | Send a `not_sent` brief once, close terminal and viewer, or re-verify a live core viewer. |
| `detect` / `check [<worker>...]` | Show backend and harnesses, or run a live delivery check (300s cap). |

Quick dispatch example (inside Rex or Herdr):

```bash
python3 <skill-dir>/scripts/agent-workers.py run <worker> --brief <file> --cwd <dir> \
  --caller-text '<16+ unique visible chars>' --wait
```

- **Profiles:** Pass the same `--profile <name>` (`workers.<name>.toml`) or `--config <path>` across the workflow. If the file is missing outside a sandbox, fail and never fall back to `workers.toml`.
- **Sandboxed controllers:** `agent-workers` reads `~/.config/herdr-orchestrator/`, writes `~/.local/state/herdr-orchestrator/`, and uses local Rex or Herdr sockets. In `agy` or Codex, rerun outside the sandbox (such as `BypassSandbox: true`) on `config_invalid`, `rex_error`, `core_error`, `herdr_error`, `hint: "sandbox_or_socket_blocked"`, permission, or socket errors before treating setup or Rex/Herdr as broken.
- **Caller context:** Inside Rex or Herdr, pass `--caller-text '<16+ unique visible chars>'` from an untruncated visible snippet (such as the left side of the status line or a unique phrase in the current turn; avoid the right edge of a narrow status bar). Add `--caller-block` or `--caller-pane` if ambiguous, and never guess from focus ([setup.md#caller-context](references/setup.md#caller-context)).

## Delegate and verify

1. **Select and isolate:** Match a role with `roles`, or choose by worker `description`. Give each concurrent writer its own worktree at `<main checkout>/.worktrees/<name>` (`--cwd`). Read-only workers may share a checkout if they write only to declared reports and `result.json` in the task directory.
2. **Brief:** State the goal, criteria, PR-first limit (for repository changes), absolute paths, file ownership, verification commands, outputs, and commit rule. `agent-workers` appends worker rules and the `result.json` schema.
3. **Dispatch:** Start up to `max_active_workers` in parallel before waiting. Handle any non-running `run` state per [Problems](#problems) right away. In reactive-wakeup harnesses (Claude Code, `agy`, Codex), prefer one background `run --wait` per worker, or follow `run` immediately with a background `wait --all`. Report any core `warning` and `viewer_verification_error` right away while keeping the task monitored.
4. **Wait and read:** Use unbounded waits in background-capable shells (add `--continue-on-long-running` if your harness already wakes you via timeout notifications and you want `long_running` flushed as NDJSON without exiting). In blocking-only shells such as Pi, use `--max-seconds 300` (with shell timeout over 300s) and never `--max-seconds 1`. Use `inspect <id>` to check live progress without touching the terminal. Report `long_running` once and keep waiting. On `done`, check `result_status` and read `result_path` and `files` (normalized absolute paths). Run follow-ups as fresh tasks.
5. **Verify and close:** Verify diffs, behavior, and verdicts. If `closed` is `false`, read `message` and retry `close <id>`.
6. **Clean up worktrees:** After a writer closes and its commits are integrated, remove only worktrees you created this session: check that `git status --porcelain --ignored` is empty, run `git worktree remove` (no `--force`), then `git branch -d` (keep the branch if Git refuses). Keep and report any worktree with leftover files, active use, or unknown ownership ([commands](references/setup.md#worktree-placement)).

## Problems

Inspect task state, `submission`, and the terminal ([lifecycle.md#problem-recovery](references/lifecycle.md#problem-recovery)) before acting. Use `wait <id> --recheck` when a worker may have resumed or receipt is uncertain. Confirm native `blocked` matches a real prompt before acting.

- **Ready and unsent (`submission: "not_sent"`):** Run `submit <id>` on an unclosed Rex or core task and wait for it.
- **Retryable failure:** Make one fresh attempt for a replayable task after an unsent startup failure, crash, missing or invalid result, worker or harness fault, or informational banner that needs no approval. Reuse the worker for transient errors, or switch to another eligible configured worker for persistent worker faults.
- **Quota exhaustion:** After confirming quota exhaustion on each failed attempt, try remaining eligible configured workers one by one.
- **Delivered `blocked` result:** Answer routine questions from the brief and repo conventions in a fresh task. Ask the user only for input or authorization you cannot supply, and escalate if the blocker repeats with no new information.
- **Replacing a task:** Confirm `closed: true` with `close <id>` first. For writers, reconcile the worktree and carry forward verified work. Keep the original role, scope, restrictions, and permissions, start a fresh wait, and record both task IDs, the reason, and any worker switch.
- **Hard limits:** Never resend `sent` or `unknown` tasks, never replace while receipt or side effects are uncertain, never switch workers to bypass a permission denial, and never restart solely for `long_running`.
- **Keep moving and escalate:** Keep waiting on other running tasks and continue independent work while one task waits on the user. Count a replacement seat only after verified delivery. Escalate with task ID, state, `submission`, and blocker. Run a fresh `verify-viewer <id>` (`viewer_verified: true`) before directing the user to a core window.

## References

- [setup.md](references/setup.md): Interactive setup, permission flags, caller context, startup dialogs, and worktree commands.
- [lifecycle.md](references/lifecycle.md): Task states, `wait` semantics, terminal inspection, and capacity scopes.
- [stats.md](references/stats.md): Reading `agent-workers stats` before editing `workers.toml`.
- [workers.example.toml](references/workers.example.toml): Starter config (state lives under `$XDG_STATE_HOME/herdr-orchestrator/tasks/`).
