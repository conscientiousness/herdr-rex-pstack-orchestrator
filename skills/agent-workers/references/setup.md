# Setup and configuration

Run setup when the user asks, or when `agent-workers run` fails with `config_invalid` because `workers.toml` does not exist. Ask one question at a time.

1. Run `agent-workers detect` to show the selected `backend`, installed harnesses, Pi providers, and (for legacy Herdr) `pi_integration` status/version. Rex and core use native status reporting. Recover missing or conflicting caller context before launching.
2. Ask which workers to define (name, `harness`, `model`, optional `effort`, optional `args`, optional `description`). One worker/model is enough; multiple roles may share it, and additional models are optional for extra review perspectives.
   - **Pi:** run `pi --list-models <text>`; set `provider` and model ID. `effort`: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
   - **Codex:** model name accepted by `codex -m`. `effort`: `model_reasoning_effort` (e.g., `medium`, `high`).
   - **Claude Code:** alias (`opus`, `sonnet`, `haiku`) or full model ID. `effort`: `claude --effort` (e.g., `high`, `max`).
   - **Antigravity CLI (`agy`):** run `agy models`. Either use an effort-suffixed ID (`gemini-3.8-flash-high`, `gemini-4-neon-high`) without `effort`, or a base model name (`gemini-3.8-flash`) with `effort` (`low`, `medium`, `high`, `xhigh`, `max`). Passing a conflicting `effort` alongside an effort-suffixed ID fails.
3. Ask for each worker's permission arguments. Because controllers never answer dialogs, a worker that stops at a permission prompt stays stuck. Remind the user that chosen flags are their authorization for that worker, and recommend automatic approval modes (verified on real tasks):

   | Harness | Arguments | Effect |
   |---|---|---|
   | `pi` | none | No per-tool approval by default; Pi 1.1.0 can still prompt for project trust on startup. |
   | `codex` | `-s workspace-write -a on-request -c approvals_reviewer='"auto_review"'` | Recommended. Auto-reviews approvals; verified for shell commands and writes in the task dir outside cwd. |
   | `codex` | `-s workspace-write -a never` | Writes in cwd and task dir without prompting. Verified. |
   | `claude` | `--permission-mode auto` | Recommended. Auto-reviews actions; verified for workers and controllers reading config/results outside project. |
   | `claude` | `--permission-mode acceptEdits` | Auto-approves file edits; shell commands and out-of-project reads can still prompt. Verified for file writes. |
   | `agy` | `--mode auto` | Recommended. Auto-approves edits, runs commands in terminal sandbox, auto-checks outside sandbox; verified for task dir via `--add-dir`. Unavailable on business/enterprise accounts or without sandbox (falls back to default mode). |
   | `agy` | `--dangerously-skip-permissions` | Auto-approves all tool permissions without prompting. Use when `--mode auto` is unavailable. |
   | `agy` | `--mode accept-edits` | Auto-approves workspace file edits; shell commands and other tools can still prompt. |

   Automatic approval can still deny an action (runs verified normal workflows, not deliberate denials). Startup trust dialogs are separate from action approval.

4. Ask for `max_active_workers` (default 4) and `notify_after_minutes` (default 180). Reservation scopes: Rex per server+session; core per core ID (plus legacy tasks in a GUI caller's workspace); legacy per workspace.
   The controller needs access to `$XDG_CONFIG_HOME/herdr-orchestrator/` (`~/.config/herdr-orchestrator/`) and `$XDG_STATE_HOME/herdr-orchestrator/` (`~/.local/state/herdr-orchestrator/`). Claude Code `--permission-mode auto` reads both without prompting; with other permission modes, the user can add these paths to `permissions.additionalDirectories` in Claude Code settings.
5. Write `~/.config/herdr-orchestrator/workers.toml` (or `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`) per [Configuration](#configuration) and show the user the file.
6. Verify delivery with `agent-workers check --cwd <worker-dir>` (with caller options). Rex and core require native OSC 7501 idle readiness; Codex runs interactively with `--no-daemon` (conflicting daemon args are rejected). Startup trust dialogs remain the user's decision.

   For legacy Pi workers, run `herdr integration install pi`. `agent-workers` requires its ready-session signal before submission: missing integration fails `run` and Pi `check` batches with `pi_integration_missing` before allocation; unknown status still enforces the live ready-session guard. Each `check` row reports `ok`; on `ok: false`, read `message`, inspect the pane per [Problems](../SKILL.md#problems), and inform the user. After they clear a dialog, run `agent-workers close <task-id>` and rerun `agent-workers check <worker>`.

## Caller context

`agent-workers detect` reports the indicated route; `run` and `check` verify it before creating anything. When both Rex and Herdr hints are inherited (e.g., from a shared daemon retaining an older conversation's env), pass the explicit caller option for the terminal hosting **this** conversation. Controllers outside both multiplexers use headless core.

### Rex caller

Ordinary shell callers may use `REX_SESSION` and `REX_BLOCK` when the block's process tree contains `agent-workers`. Set `REX_SERVER` only to a nondefault local Unix-socket server. Workers launch in separate `Workers` tabs (up to 4 blocks/tab) without stealing focus.

For agent controllers or tools outside the caller's process tree, passing `--caller-text '<distinctive visible conversation text>'` (>= 16 chars) on `run` or `check` automatically scans live blocks running an expected harness in this cwd and accepts iff **exactly one** matches (failing closed with `caller_context_invalid` on 0 or >1 matches):

```bash
python3 <skill-dir>/scripts/agent-workers.py run <worker> --brief <file> --cwd <worker-dir> \
  --caller-text '<distinctive visible conversation text>'
```

When disambiguating `caller_context_conflict` (both Rex and Herdr hints present) or multiple matching blocks, locate the full block ID via `rex ls --json` and `rex block ls -s <session> --json`, confirm live harness, cwd, and visible text with `rex block call -s <session> -b <block> process` and `rex capture -s <session> -b <block> --trim`, and pass explicit `--caller-block <confirmed-block-id>` alongside `--caller-text`. Installed CLIs, the first listed session, and app focus are insufficient. If no unique block can be confirmed, report the missing context and stop dispatch. See the [Rex CLI guide](https://www.superlogical.com/rex/docs/automate/cli).

### Herdr caller

In Herdr, core workers attach in owned `Workers` viewer panes in the verified caller's live workspace; legacy workers use `Workers` tabs there. Both preserve the caller's tab and focus.

Legacy execution requires `HERDR_ENV=1`. Core requires caller verification whenever `--caller-pane` or `--caller-text` is passed, `HERDR_ENV=1`, or any nonempty `HERDR_PANE_ID`, `HERDR_TAB_ID`, `HERDR_WORKSPACE_ID`, or `HERDR_SOCKET_PATH` is inherited (preserving viewer placement even if a tool drops `HERDR_ENV`), and requires `HERDR_SOCKET_PATH` before launch to pin cleanup. Pane ID comes from `--caller-pane`, auto-resolved `--caller-text`, or `HERDR_PANE_ID` (note: Herdr `--current` reads `HERDR_PANE_ID` without verifying ownership). Before task allocation, `agent-workers` verifies:

1. **Ordinary shell automation** (no controller session vars or harness ancestor): the named pane's `shell_pid` (`herdr pane process-info`) must be an ancestor of `agent-workers`; its live workspace and tab are used. Contradictory claims are rejected.
2. **Agent controllers and external tools:** always require `--caller-text` (even if a pane shell is an ancestor, because a shared daemon such as Codex 0.162 `codex app-server` with PPID 1 retains the spawning pane's env and hooks across conversations). Passing `--caller-text` alone scans live panes running an expected harness in this conversation's cwd (matching exported session env when present) and accepts iff **exactly one** pane matches, failing closed (`caller_context_invalid`) on 0 or >1 matches. Pass explicit `--caller-pane <id>` alongside `--caller-text` to disambiguate `caller_context_conflict` or multiple candidates.
3. **Live screen proof:** the pane's foreground must run the controller's harness in the conversation's cwd (not a plain shell). `--caller-text` (>= 16 chars, whitespace-normalized) must match **only** that pane among live panes running that harness. If `CODEX_THREAD_ID`, `CLAUDE_CODE_SESSION_ID`, or `ANTIGRAVITY_CONVERSATION_ID` is exported and reported by the pane, they must match (session metadata alone never replaces the screen check).

Missing/unavailable panes return `caller_context_invalid`; an unavailable Herdr service returns `herdr_error`. Never substitute the focused pane, treat lost Herdr env as headless, or strip inherited context to bypass failure.

If auto-resolution fails or both multiplexers are inherited, locate the pane manually:
- Inspect `herdr pane list` and `herdr pane process-info --pane <id>` for a pane running the controller's harness in this conversation's cwd.
- If multiple candidates match, read each via `herdr pane read <id> --source visible` for unique conversation text (e.g., your latest command). If no single pane matches, report the candidates and stop dispatch.

```bash
python3 <skill-dir>/scripts/agent-workers.py run <worker> --brief <file> --cwd <worker-dir> \
  --caller-pane <confirmed-id> --caller-text '<distinctive visible conversation text>'
```

`agent-workers` verifies process info and visible screens itself, rejecting missing, wrong, or ambiguous evidence before allocation, and saves `controller_verification` (live IDs, cwd, PIDs, method, timestamp, SHA-256 screen hash—never full pane text). Recheck after resuming the controller; do not manually relocate workers or edit task records.

After core viewer creation, `agent-workers` re-reads live workspace, viewer pane/tab, foreground attach argv, and visible output. `viewer_verified: true` confirms a separate `Workers` tab in that workspace, exact pinned executable/terminal attach argv, and recognizable rendered output at that timestamp (not that the user has focused the tab). Always run a fresh `agent-workers verify-viewer <task-id>` before asking the user to operate a worker window; on failure, report `viewer_verification_error` and do not direct them there.

Moved panes keep their launch-time ID as an alias and keep their shell PID, so verification still succeeds against the live workspace/tab. See the [Herdr CLI reference](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/cli-reference.mdx).

## Dialogs that stop a worker before it starts

Rex and core require native idle before submission, tracking `startup_ready`, `submission`, and `execution_observed` separately. After `start_failed` with `submission: "not_sent"`, `wait --recheck` observes idle without sending; once the user resolves readiness and approves recovery, `agent-workers submit <task-id>` sends the original brief once (rejects `sent`, `unknown`, historical, closed, or completed tasks; send timeouts leave `unknown`). Legacy recovery requires inspection, closure, and a fresh task.

Common pre-task trust dialogs (`agent-workers` reports `start_failed` and leaves the pane open for the user to clear once):

- **Codex:** "Trust this folder?" per untrusted git root (trusted parent does not cover nested repos; worktrees of a trusted repo are covered).
- **Claude Code:** First-time folder trust; also "Allow external CLAUDE.md file imports?" when cwd is under a project whose `CLAUDE.md` uses `@` imports.
- **Pi 1.1.0:** "Trust project folder?" when an untrusted dir or ancestor has project resources (even an empty `.agents/skills`). Because Herdr 0.9.3 can misclassify this as idle, legacy `agent-workers` requires the Pi integration session signal before sending. Trust is path-based (worktrees outside trusted paths may prompt). Only the user may add `--approve` or `--no-approve` to worker `args`—never add them automatically.
- **Antigravity CLI (`agy`):** "Do you trust the contents of this project?" (saved under `trustedWorkspaces` in `~/.gemini/antigravity-cli/settings.json`). Natively reports `blocked` via OSC 7501, so `agent-workers` leaves `start_failed` with `submission: "not_sent"`.

## Reviewing configured workers

Run `agent-workers stats [--workspace <id>] [--days <n>] [--no-samples]` before proposing edits to `workers.toml`, and `agent-workers roles [<role>]` to validate role-to-worker mappings. See [worker statistics](stats.md).

## Configuration

User-owned config path: `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml` (default `~/.config/herdr-orchestrator/workers.toml`).

Optional `description` guides controller selection when no role applies; role mappings take precedence, and descriptions are not passed to harnesses. Describe task scope rather than unverified capability or cost claims. Upgrade all installed `agent-workers` instances sharing a config before adding `description` (older versions reject unknown keys).

```toml
# If you are the controller (you start workers with agent-workers), delegate only
# through the agent-workers skill. Never use native subagents.

max_active_workers = 4
notify_after_minutes = 180

[workers.glm]
description = "Bounded tooling changes and mechanical edits."
harness = "pi"
provider = "zai"
model = "glm-5.3-flash"
effort = "max"

[workers.gpt]
description = "Implementation, ordinary fixes, and refactoring."
harness = "codex"
model = "gpt-6.1-sol"
effort = "medium"
args = ["-s", "workspace-write", "-a", "on-request", "-c", 'approvals_reviewer="auto_review"']

[workers.haiku]
description = "Independent review of a bounded diff and its evidence."
harness = "claude"
model = "haiku"
effort = "max"
args = ["--permission-mode", "auto"]

[workers.flash]
description = "Fast investigation and bounded fixes."
harness = "agy"
model = "gemini-3.8-flash-high"
args = ["--mode", "auto"]
```

| Key | Meaning |
|---|---|
| `max_active_workers` | Default 4. Scoped per Rex server+session, per core ID (+ legacy GUI workspace), or per legacy workspace. |
| `notify_after_minutes` | Default 180. Threshold after which `wait` emits `long_running` once. |
| `workers.<name>.harness` | `pi`, `codex`, `claude`, or `agy`. |
| `workers.<name>.model` | Model ID/alias accepted by the harness CLI. |
| `workers.<name>.provider` | Pi only (`--provider`). |
| `workers.<name>.effort` | Optional reasoning effort. |
| `workers.<name>.description` | Optional controller guidance describing intended scope/boundaries. |
| `workers.<name>.args` | Optional extra CLI args (e.g., permission flags), appended last. |
| `roles` | Optional. Used by `pstack-herdr` routing and `agent-workers stats`. |

Worker names match `[a-z][a-z0-9-]{0,15}`. Task state lives in `$XDG_STATE_HOME/herdr-orchestrator/tasks/` (default `~/.local/state/herdr-orchestrator/tasks/`) until deleted by the user.
