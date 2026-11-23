# Task lifecycle and recovery

`run` and `check` verify [caller context](setup.md#caller-context) before allocation. With explicit task IDs, `wait` and `close` follow each task's stored backend binding. Wait on Rex and Herdr tasks in separate calls.

## Rex API boundary

Rex launches interactive harnesses directly in `Workers` tabs (separate from controller tab, up to 4 blocks/tab, focus preserved) inside the verified session. Each task pins its local Unix endpoint, executable, host/server instance, full session/window/block IDs, and owned block label (`<worker>` + harness + unique suffix). A changed or unavailable endpoint leaves the task unresolved.

`agent-workers` reads [native program status](https://www.superlogical.com/rex/docs/build/program-status) from the owned block: waits for idle, saves process + timestamp baseline, persists uncertain submission state before writing input, pastes the brief pointer once, waits for terminal input to settle, then sends Enter. Lost responses retain the task for inspection and `wait --recheck`. Delivery requires both a new native turn completion and a valid nonce-bound result. Lost creation responses reconcile only by exact owned label in the recorded session; closure targets only the owned block, verifies absence, and removes the tab when empty.

## Core API boundary

Herdr and headless launches prefer `herdr-core`, then a verified `hc` alias (no GUI or `HERDR_ENV` required); absence of both selects legacy Herdr. Failures stay on the selected route.

- **Task binding (`task.json.backend`):** `kind: "core"` pins `executable`, `session`, `endpoint`, permanent `core_id`, `terminal`, owned `name`/`nonce`, and CLI affinity XDG paths; `kind: "rex"` pins the Rex binding above; `kind: "legacy"` (or absent `backend`) uses the legacy pane/agent path. Optional `viewer` records legacy pane/tab IDs and pinned legacy socket path separately.
- **Protocol & waits:** Core uses the official JSON-RPC protocol over the pinned local endpoint, checking core identity via `hello` on every connection. Full `terminal.get` facts drive lifecycle (`ls --json` summaries omit fields). `events.subscribe` snapshots close the get/subscribe race; core-only waits use bounded check-ins for reminders, while mixed waits use legacy polling. No screen text or private transcript drives lifecycle.
- **Startup & submission:** Launches the interactive harness without a task; requires native OSC 7501 idle before saving the turn baseline and sending the brief once with an idle guard (no hooks, extensions, global config, or permission changes added). Codex gets `--no-daemon` (conflicting daemon args fail). A task-local exec wrapper clears inherited legacy Herdr and controller session vars. Missing idle reporting or trust dialogs leave `start_failed` unsent.
- **State fields:** Tracks `startup_ready`, `submission` (`not_sent`, `unknown`, `sent`), `execution_observed`, and `native_status`. Persists `unknown` before sending so interrupted callers never double-send; native activity alone does not prove receipt, though a valid nonce-bound result resolves `unknown`. Historical records have null `submission` and cannot use `submit`.
- **Delivery:** Requires native idle/done, `turn` strictly greater than the saved baseline, and a valid nonce-bound `result.json`. Because core increments `turn` on any departure from working (including `blocked`/`error`), an advanced turn alone never delivers, and early result files cannot deliver.
- **Reconciliation & closure:** Creation/send failures reconcile only by owned name/nonce at the same endpoint; uncertain outcomes retain the reservation without auto-resend or fallback. Closure verifies `core_id`, kills only its terminal, observes `finished`, removes it, confirms absence, and closes any owned viewer separately (`closed: true` only when both succeed). Connection/namespace/identity errors never imply absence. Headless tasks never call legacy Herdr.
- **Herdr viewers:** Require caller verification + nonblank `HERDR_SOCKET_PATH` before launch (pinned for cleanup). Owned attach panes use separate `Workers` tabs (up to 4 panes, no focus steal). `viewer_verified: true` requires re-reading live controller/workspace, viewer pane/tab, pinned attach argv, and recognizable rendered output; failures emit `viewer_verification_error` + warning while preserving the task. Ambiguous placement sets `viewer_unresolved` (reservation held until reconciled, even after core terminal removal). Historical tasks without a controller record fail `verify-viewer`.

## Legacy Herdr API boundary

Follows Herdr 0.9.5 [agent automation](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/agent-automation.mdx) and [socket API guidance](https://github.com/herdrdev/herdr/blob/v0.9.5/docs/next/website/src/content/docs/socket-api.mdx): CLI wrappers, response IDs, `agent start`, `agent prompt --wait` (timeouts do not prove input was unsent), `--no-focus`, and separate `Workers` tabs. A single 2-second `agent list` poll covers all waited tasks and reminder timers without invoking a model. Use `--source visible` for passive reads (recent-history reads can send mouse-scroll input to full-screen TUIs) and Herdr agent metadata rather than private harness session files.

For legacy Pi workers, `agent-workers` also requires the Herdr Pi integration to report an idle/done session within the startup budget (guarding against Herdr 0.9.3 misclassifying Pi 1.1.0's trust dialog as `interactive_ready`). Without it, startup returns `start_failed` unsent and retains the pane.

## Delivery, outcome, and review verdict

`agent-workers wait` reports transport state; `result.json` reports worker outcome; the controller verifies work independently.

| Task state | Result status | Meaning and next action |
|---|---|---|
| `running` / `long_running` | Any file on disk | Keep waiting; worker may still update it. |
| `done` | `completed` | Delivered; independently verify diff/behavior/verdict. |
| `done` | `failed` | Delivered; worker reports failure. Read report and inform user. |
| `done` | `blocked` | Delivered; relay `question` to user, then launch fresh task with answer. |

`done` means finished turn + valid result (kept for v0.1.0 compatibility), not verified success. `check` returns `ok: true` only for `done` + `status: "completed"` + confirmed closure.

Each `wait` line includes `task_id`, `state`, `result_status` (`"completed"` | `"blocked"` | `"failed"` | null; non-null only when `state == "done"` and `result.json` is valid), `summary`, `result_path`, `files`, `question`, `closed`, `message`, readiness/submission/execution fields, and viewer verification facts. Before `done`, `result_status`/`summary`/`question` are null and `files` is empty (`result_path` always names the target path; `files` entries are relative to its directory). Passing `wait --all` waits until all targeted tasks settle and close, while still returning immediately if any task transitions to a problem state (`blocked`, `error`, `exited`, `start_failed`, `not_started`, `result_missing`, `result_invalid`), `long_running`, or `done` with `closed: false`.

A valid `result.json` has exactly six keys: matching `task_id` and `nonce`, `status` (`completed` | `failed` | `blocked`), string `summary`, list of string `files`, and `question` (nonempty string iff `blocked`, else null). Legacy tasks additionally require turn-end evidence (`completion_seq` newer than baseline, or observed working-to-idle fallback).

## States

| State | Meaning | Action |
|---|---|---|
| `starting` | Placement or readiness in progress. | Wait for `run`/`check`; if interrupted, inspect reserved task. |
| `running` | Worker is executing. | Keep waiting. |
| `long_running` | Exceeded `notify_after_minutes` (emitted once). | Tell user and keep waiting. |
| `done` | Turn ended with valid `result.json`. | Inspect result and `closed`/`message`. |
| `start_failed` | Harness failed to reach idle (usually a dialog). | Follow [Problems](../SKILL.md#problems). |
| `not_started` | Prompt acknowledgement not observed; may still be running. | Follow [Problems](../SKILL.md#problems). |
| `blocked` | Waiting at dialog or permission prompt. | Follow [Problems](../SKILL.md#problems). |
| `exited` | Process/terminal ended before delivery. | Follow [Problems](../SKILL.md#problems). |
| `error` | Native error reported. | Inspect without resending or switching backend. |
| `result_missing` | Turn ended without valid `result.json` (often API error). | Follow [Problems](../SKILL.md#problems). |
| `result_invalid` | Malformed `result.json` or wrong `task_id`/`nonce`. | Follow [Problems](../SKILL.md#problems). |

## Problem recovery

Follow [Problems](../SKILL.md#problems) before cleanup. Normal `wait` returns stored problem states immediately without re-polling.

Use `agent-workers list --verbose` (or `--active` / `--limit <n>` for filtered listings; default `list` is compact) to locate the full stored backend binding, then inspect the recorded terminal:

- **Rex:** `<executable> --autostart=false -S <endpoint> block call -s <session> -b <block> program_status` and `... capture -s <session> -b <block> --trim`.
- **Core:** with recorded executable, `HC_SESSION`, and `HC_SOCKET`, run `get <terminal_id>` or `read <terminal_id> --lines 0`.
- **Legacy Herdr:** on the original server, run `herdr agent get <agent-name>` or `herdr pane read <pane_id> --source visible`.

Recovery commands:
- **`agent-workers wait <task-id> --recheck`:** Re-observes explicit task IDs (e.g., after user clears a dialog or an unacknowledged task starts). Never submits, resends, restarts, or reopens closed/completed tasks; `submission: "not_sent"` stays `start_failed`. Exited task results remain on disk for inspection and are never promoted to `done` without turn-completion evidence.
- **`agent-workers submit <task-id>`:** After user resolves readiness and approves recovery, sends the original brief once on an unclosed Rex/core task with `submission: "not_sent"`, rechecking native idle and saving a new baseline. Rejects `sent`, `unknown`, historical, closed, or completed tasks with `submission_unsafe`. Legacy recovery requires inspection, closure, and a fresh task. Require fresh `verify-viewer` before asking the user to interact with a core window.
- **`agent-workers close <task-id>`:** Retry whenever `closed: false` (slot stays occupied until confirmed). Closing an unfinished worker cancels it. Only explicit not-found responses prove a legacy pane is already gone; other errors leave cleanup unresolved.

**Invalid records & lost placements:** A lost legacy placement can leave an empty pane—inspect the original server before removal. `list` shows `task_invalid` records alongside healthy history; each unclosed invalid record reserves one slot in **every** scope (since owner/terminal is unknown). Full `run` returns `worker_limit` naming invalid IDs; `wait` without IDs skips them; targeted `wait`/`close` returns `task_invalid`. Inspect the original runtime before removing an invalid task directory manually.

## Task store and concurrency

- **Reservation scopes:** Rex counts unclosed tasks per server+session. Core counts all unclosed tasks with the same permanent `core_id` in this store plus legacy reservations in the GUI caller's workspace (session-wide, including headless). Legacy counts per `workspace_id` (older records without `workspace_id` count if present in live pane list; pane-list errors leave admission unresolved). Invalid unclosed records count in every scope.
- **Locking & atomicity:** Controllers sharing a state store hold `.start.lock` only during capacity check, task reservation (`state: "starting"`, `submission: "not_sent"`), and terminal/pane placement, releasing it before readiness wait, `verify-viewer`, and prompt submission so parallel `run` launches proceed concurrently across Rex, core, and legacy. Short per-task locks prevent concurrent waits from overwriting closure, and JSON updates replace files atomically.
- **Store isolation:** Core and Rex records pin endpoints/identities, so one store supports multiple sessions. Legacy records do not store socket paths—scope each task store to **one** legacy Herdr server (give separate servers/machines separate `XDG_STATE_HOME` to avoid closing unrelated panes with matching IDs).
- **`check` batching:** Deduplicates worker names and batches up to `max_active_workers`. Rows include `worker`, `task_id`, `state`, `ok`, `pane_id`, `seconds`, and `message`. Unstarted workers return `not_checked` (null task/pane/duration, naming any blocking invalid IDs). Unfinished/problem tasks keep their terminals open for inspection.
