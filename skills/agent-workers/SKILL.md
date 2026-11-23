---
name: agent-workers
description: "Delegate tasks to Pi, Codex, Claude Code, or Antigravity CLI (agy) workers through agent-workers and wait for their file results. Use for Rex or Herdr delegation, headless herdr-core, multi-model tasks, worker setup, or worker efficiency review."
---

# agent-workers

Controller: plan, assign, verify; delegate substantial work to fresh workers via `agent-workers`. Keep main context small—verify claims against diffs/artifacts and check JSON keys/counts before dumping payloads.

## Required rules

- **PR-first:** Deliver repo changes via PR on a feature branch. Never merge to `main`/default/shared branch, push directly, or auto-merge without explicit user request (checks/completion/playbooks never grant merge authority). Include this limit in worker briefs.
- **No native subagents** as controller (workers may use subagents unless restricted by brief).
- **Verify controller location:** Rex -> `Workers` tabs in verified session; Herdr core -> `Workers` viewers in verified workspace; legacy Herdr -> `Workers` tabs (separate tab, preserve focus; headless core outside both). Recover missing/conflicting context first.
- **No intervention:** Never answer dialogs, send keys/text to panes, or send `/model`.
- **Wait for `state: "done"`:** Never consume early files; closing an unfinished worker cancels it and fails review gates.
- **`done` != verified:** Check `result_status` (`completed`/`failed`/`blocked`) and verify independently.
- **User-directed recovery:** Inspect/report problems; never restart, resend, or switch workers without approval. Close only `agent-workers` panes via `close`.

## Run agent-workers

`python3 <skill-dir>/scripts/agent-workers.py <cmd> ...` (Python 3.11+, JSON stdout, errors exit 1 `{"error","message"}`). Tasks pin backend—wait Rex/Herdr separately. `run`/`detect`/`check` accept caller opts.

| Command | Purpose |
|---|---|
| `run <worker> --brief <file\|-> [--cwd <dir>]` | Launch worker (`-`=stdin); check state, submission, viewer warning. |
| `wait [<id>...] [--all] [--max-seconds <n>] [--recheck]` | Wait for change (`--all`: until all settle; returns immediately on problems, `long_running`, unclosed `done`). |
| `list [--active] [--limit <n>] [--verbose]` | Compact list (`--verbose` adds full backend bindings). |
| `roles [<role>]` | Resolve `workers.toml` roles/workers; flag issues. |
| `stats [--workspace <id>] [--days <n>] [--no-samples]` | Store metrics (`--no-samples` omits `duration_samples`). |
| `close <id>` / `verify-viewer <id>` | Close terminal+viewer; live-verify core viewer/output. |
| `submit <id>` | Send brief once on retained Rex/core `not_sent` task (approved). |
| `detect` / `check [<w>...] [--cwd <dir>] [--max-seconds <n>]` | Route/harnesses/Pi status; verify workers (300s cap). |

**Caller context:** Pass `--caller-text '<16+ unique visible chars>'` on `run`/`check` to auto-resolve the unique Rex block/Herdr pane (fails closed on 0/>1); add `--caller-block`/`--caller-pane` to disambiguate. Focus/inherited IDs never prove location ([setup.md#caller-context](references/setup.md#caller-context)).

## Delegate and verify

1. **Select & isolate:** Role-first (`roles`), else `description`. Separate git worktree per writer (`--cwd`); read-only workers may share checkout (writes only to declared reports + `result.json` in task dir).
2. **Brief:** Goal, criteria, PR-first limit, absolute paths, ownership, verification, outputs, commit rule (`agent-workers` appends rules/schema).
3. **Dispatch:** Start up to `max_active_workers` in parallel before waiting. On core viewer failure, report `warning` + `viewer_verification_error` immediately while monitoring.
4. **Wait & read:** Unbounded `wait` (`--all` for batches) in background/yielded shells (Claude Code, `agy`, Codex); `--max-seconds 300` (timeout >300s) in blocking-only shells (Pi); never `--max-seconds 1`. Report `long_running` once; never cancel to end wait. On `done`, check `result_status`, read `result_path`/`files` (relative to result dir), relay `blocked` `question`; follow-ups are fresh tasks.
5. **Verify & close:** Verify diffs/behavior/verdicts. If `closed: false`, read `message` and retry `close`.

## Problems

1. Inspect [recorded backend](references/lifecycle.md#problem-recovery) (`list --verbose`) before closing.
2. Report task, state, submission, pane text. Require fresh `verify-viewer <id>` (`viewer_verified: true`) before directing user to a core window (else report unconfirmed; do not direct them).
3. Follow user decision: `submit` only for retained Rex/core `not_sent`; `wait --recheck` observes only; never resend `sent`/`unknown`; retry fresh.

## Read when needed

- [setup.md](references/setup.md): setup (`workers.toml`, `config_invalid`, 1 question/turn), permissions, dialogs, caller context.
- [lifecycle.md](references/lifecycle.md): states/internals/recovery | [stats.md](references/stats.md): metrics | [workers.example.toml](references/workers.example.toml) (state: `$XDG_STATE_HOME/herdr-orchestrator/tasks/`).
