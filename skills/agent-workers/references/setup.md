# Setup and configuration

Run setup when the user asks, or when `agent-workers run` fails with `config_invalid` because `workers.toml` does not exist. Ask one question per turn.

## Set up workers.toml

1. Run `agent-workers detect` to show the backend, installed harnesses, Pi providers, and legacy Herdr Pi integration status.
2. Ask which workers to define: name, `harness`, `model`, optional `effort`, optional `args`, and optional `description`. One worker is enough, and multiple roles may share it.
   - **Pi:** Run `pi --list-models <text>`. Set `provider` and model ID. `effort` accepts `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`.
   - **Codex:** Use a model accepted by `codex -m`. `effort` sets `model_reasoning_effort`, such as `medium` or `high`.
   - **Claude Code:** Use an alias (`opus`, `sonnet`, `haiku`) or full model ID. `effort` sets `claude --effort`, such as `high` or `max`.
   - **Antigravity CLI (`agy`):** Run `agy models`. Pass either an effort-suffixed ID (such as `gemini-3.8-flash-high`) without `effort`, or a base model name with `effort` (`low`, `medium`, `high`, `xhigh`, `max`). Conflicting `effort` fails.
3. Ask for each worker's permission flags. These flags set the worker's authorization for unattended runs:

   | Harness | Arguments | Behavior |
   |---|---|---|
   | `pi` | none | No per-tool prompts. Pi 1.1.0 and later can still ask for project trust on startup. |
   | `codex` | `-s workspace-write -a on-request -c approvals_reviewer='"auto_review"'` | Recommended. Auto-reviews approvals for shell commands and task-directory writes. |
   | `codex` | `-s workspace-write -a never` | Writes in cwd and task directory without prompting. |
   | `claude` | `--permission-mode auto` | Recommended. Auto-reviews actions, including config and result reads outside the project. |
   | `claude` | `--permission-mode acceptEdits` | Auto-approves file edits. Shell commands and outside reads can still prompt. |
   | `agy` | `--mode auto` | Recommended. Auto-approves edits and checks outside-sandbox commands. Unavailable on business or enterprise accounts or without a sandbox. |
   | `agy` | `--dangerously-skip-permissions` | Auto-approves all tools. Use when `--mode auto` is unavailable. |
   | `agy` | `--mode accept-edits` | Auto-approves workspace edits. Shell commands and other tools can still prompt. |

   Auto-approval can still deny an action, and startup trust dialogs are separate from tool approvals.
4. Ask for `max_active_workers` (default 4) and `notify_after_minutes` (default 180).
   The controller needs access to `~/.config/herdr-orchestrator/`, `~/.local/state/herdr-orchestrator/`, and local Rex or Herdr Unix sockets. With Claude Code modes other than `--permission-mode auto`, add both directories to `permissions.additionalDirectories`. In sandboxed controllers such as `agy` or Codex, rerun `agent-workers` outside the sandbox if a call fails with `config_invalid`, `rex_error`, `core_error`, `herdr_error`, `hint: "sandbox_or_socket_blocked"`, permission, or socket errors.
5. Write `~/.config/herdr-orchestrator/workers.toml` (or `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml`) based on [workers.example.toml](workers.example.toml), then show the file to the user.
6. Run `agent-workers check --cwd <worker-dir>` with caller options to verify delivery. For legacy Herdr Pi workers, install the integration first with `herdr integration install pi`. On any `ok: false` row, read `message`, inspect the terminal per [Problems](../SKILL.md#problems), and inform the user. After they clear a dialog, close the check task and rerun `agent-workers check <worker>`.

## Caller context

`run` and `check` verify where this conversation lives before launching any worker. Never guess from window focus or strip inherited multiplexer variables to force headless mode. Outside both Rex and Herdr, `agent-workers` uses headless `herdr-core`.

Pass `--caller-text '<unique visible text>'` (at least 16 characters currently visible and untruncated on screen, such as the left portion of the harness status line or a distinctive visible phrase from the current turn; avoid the right-hand tail of narrow status bars or text that tool output has scrolled off-screen):

```bash
python3 <skill-dir>/scripts/agent-workers.py run <worker> --brief <file> --cwd <worker-dir> \
  --caller-text '<unique visible conversation text>'
```

`agent-workers` scans live Rex blocks or Herdr panes running an expected harness in this conversation's working directory and accepts only when exactly one matches. If zero or multiple match, or if both Rex and Herdr environment variables are inherited (`caller_context_conflict`), identify the exact terminal manually and pass it alongside `--caller-text`:

- **Rex:** List sessions and blocks with `rex ls --json` and `rex block ls -s <session> --json`. Confirm the running harness, working directory, and screen text with `rex block call -s <session> -b <block> process` and `rex capture -s <session> -b <block> --trim`. Pass `--caller-block <full-block-id>` with `--caller-text`.
- **Herdr:** Check `herdr pane list` and `herdr pane process-info --pane <id>` for the harness and working directory, then read candidates with `herdr pane read <id> --source visible`. Pass `--caller-pane <pane-id>` with `--caller-text`.
- **Plain shell scripts:** Ordinary shell automation without controller session variables can rely on process-tree ancestry from `REX_SESSION`/`REX_BLOCK` or `HERDR_PANE_ID`. Agent controllers always need `--caller-text` because shared daemons can inherit another conversation's pane.

If no unique terminal can be confirmed, report the candidates and stop dispatch. In Herdr with `herdr-core`, `HERDR_SOCKET_PATH` must be set so owned viewer tabs can attach and close cleanly. Run a fresh `agent-workers verify-viewer <task-id>` before asking the user to interact with a core window.

## Startup dialogs

When a harness blocks on startup, `agent-workers` leaves the brief unsent (`state: "start_failed"`, `submission: "not_sent"`) and keeps the terminal open for inspection.

- **Codex:** "Trust this folder?" per untrusted git root. Worktrees of a trusted repo inherit trust, but nested repos do not. Codex also runs with `--no-daemon`, and conflicting daemon flags in `args` fail.
- **Claude Code:** First-time folder trust, external `CLAUDE.md` `@` import prompts, and per-task `--add-dir` prompts ("Adding a new directory"). Trust the shared tasks directory once per machine so every task directory underneath it is covered:
  ```bash
  mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/herdr-orchestrator/tasks"
  ```
  Start `claude` in that directory, accept trust, and run `/exit`.
- **Pi:** "Trust project folder?" whenever an untrusted directory or ancestor contains project resources (even an empty `.agents/skills`). Trust is path-based and ignores git worktree links, so create worktrees inside the trusted main checkout. Only the user may add `--approve` or `--no-approve` to `args`.
- **Antigravity CLI (`agy`):** Project trust prompts report persistent native `blocked` (brief startup sign-in `blocked` states are tolerated before failing). Modal banners showing `esc to dismiss` without a visible framed `>` input prompt can intercept input while `agy` reports `idle`, so `agent-workers` keeps the brief unsent; non-modal inline `esc to dismiss` notices above the active `>` prompt do not block submission. Workers should always write outputs inside the task directory or workspace, never inside `agy`'s artifact directory.
- **First run on a new machine:** Start each harness once by hand in a trusted checkout and let startup finish (Pi downloads `fd` and `ripgrep` on first launch).

After the user clears a startup dialog on Rex or core, use `agent-workers wait <id> --recheck` to confirm idle, then `agent-workers submit <id>`. On legacy Herdr, close the task and start a fresh one.

## Worktree placement

Create each concurrent writer's worktree inside the trusted main checkout and exclude `.worktrees/` locally:

```bash
root=$(git rev-parse --show-toplevel)
grep -qxF '.worktrees/' "$root/.git/info/exclude" || echo '.worktrees/' >> "$root/.git/info/exclude"
git worktree add "$root/.worktrees/<name>" -b <branch>
```

After the writer is closed and its commits are on your feature branch, remove only the worktree you created:

```bash
wt="$root/.worktrees/<name>"
[ -z "$(git -C "$wt" status --porcelain --ignored)" ] && git worktree remove "$wt" &&
  git branch -d <branch>
```

Without `--force`, `git worktree remove` deletes ignored files silently, so check `--ignored` first. If `git status` prints anything, keep the worktree and report its path. Keep the branch if `git branch -d` refuses.

## Configuration

Default config path: `$XDG_CONFIG_HOME/herdr-orchestrator/workers.toml` (defaults to `~/.config/herdr-orchestrator/workers.toml`). Named profiles live beside it as `workers.<profile>.toml` where `<profile>` matches `[a-z0-9][a-z0-9-]{0,31}`.

Config selection resolves in this order and fails closed with `config_invalid` if the selected file is missing or invalid:

1. `--config <path>` (expands `~`, resolves relative paths against cwd)
2. `--profile <name>` (`workers.<name>.toml` in the config directory)
3. `AGENT_WORKERS_CONFIG` or `AGENT_WORKERS_PROFILE` (setting both fails closed unless a CLI flag overrides them)
4. Default `workers.toml`

Run `agent-workers detect` to list discovered profiles under `config.profiles`. Prefer explicit `--profile` or `--config` flags over environment variables when running multiple windows under a shared daemon. Worker launch wrappers strip `AGENT_WORKERS_*` from worker environments.

See [workers.example.toml](workers.example.toml) for a complete example and [stats.md](stats.md) before proposing worker edits.

| Key | Meaning |
|---|---|
| `max_active_workers` | Maximum open tasks in one capacity scope. Default 4. |
| `notify_after_minutes` | Minutes before `wait` emits `long_running` once. Default 180. |
| `workers.<name>.harness` | `pi`, `codex`, `claude`, or `agy`. Names match `[a-z][a-z0-9-]{0,15}`. |
| `workers.<name>.model` | Model ID or alias accepted by the harness CLI. |
| `workers.<name>.provider` | Pi only (`--provider`). |
| `workers.<name>.effort` | Optional reasoning effort level. |
| `workers.<name>.description` | Optional scope guidance for the controller when no role applies. Not passed to harnesses. |
| `workers.<name>.args` | Optional extra CLI flags appended last. |
| `roles` | Optional role-to-worker mappings used by `pstack-adapter` and `agent-workers roles`. |
