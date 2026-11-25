# Task lifecycle and recovery

Operational reference for `agent-workers` states, delivery semantics, and terminal inspection.

## Delivery and outcomes

`agent-workers wait` reports transport state, while `result.json` reports the worker's outcome. Before `state: "done"`, `result_status`, `summary`, and `question` stay `null` and `files` stays empty, even if the worker wrote an early file on disk (`result_verdict` is diagnostic only).

| Task state | `result_status` | Next action |
|---|---|---|
| `running` or `long_running` | `null` | Keep waiting. The worker may still update files. |
| `done` | `completed` | Independently verify the diff, behavior, and verdict. |
| `done` | `failed` | Read the report and apply [Problems](../SKILL.md#problems). |
| `done` | `blocked` | Answer routine questions in a fresh task, or ask the user for decisions you cannot supply. |

Normal delivery requires a finished native turn and a valid six-key `result.json` matching `task_id` and `nonce` (`settled_by: "native"`). If `submission` is `"sent"`, work was observed, native status drops to `null` (not `working`, `blocked`, or `error`), and a valid `result.json` plus any declared `files` stays untouched for at least 15 seconds across two live null-status checks, `agent-workers` delivers it with `settled_by: "result_file"`.

## Task states

| State | Meaning | Action |
|---|---|---|
| `starting` | Terminal placement or startup readiness in progress. | Wait for `run` or `check`. If interrupted, inspect the task. |
| `running` | Worker is executing. | Keep waiting. |
| `long_running` | Passed `notify_after_minutes` (emitted once). | Tell the user and keep waiting. |
| `done` | Turn finished with a valid `result.json`. | Check `result_status`, `closed`, and `message`. |
| `start_failed` | Harness did not reach idle, usually due to a startup dialog. | Follow [Problems](../SKILL.md#problems). |
| `not_started` | Submission acknowledgement was not observed. The worker may still be running. | Follow [Problems](../SKILL.md#problems). Never resend. |
| `blocked` | Harness reported a dialog or permission prompt. | Confirm on the terminal, then follow [Problems](../SKILL.md#problems). |
| `exited` | Process or terminal ended before delivery. | Follow [Problems](../SKILL.md#problems). |
| `error` | Native error reported. | Inspect without resending or switching backends. |
| `result_missing` | Turn ended without `result.json`, often after an API fault. | Follow [Problems](../SKILL.md#problems). |
| `result_invalid` | `result.json` is malformed or has the wrong `task_id` or `nonce`. | Follow [Problems](../SKILL.md#problems). |

## Problem recovery

Normal `wait` returns stored problem states immediately without re-polling. When `wait --all` stops early on one problem task, re-arm `wait` for the remaining running IDs so the stored problem does not keep interrupting them.

Run `agent-workers list --verbose` to read the stored backend binding (`backend.kind` is `rex`, `core`, or `legacy`), then inspect the recorded terminal:

- **Rex:** `<executable> --autostart=false -S <endpoint> block call -s <session> -b <block> program_status` and `... capture -s <session> -b <block> --trim`.
- **Core:** With the recorded `executable`, `HC_SESSION`, and `HC_SOCKET`, run `get <terminal_id>` or `read <terminal_id> --lines 0`.
- **Legacy Herdr:** On the original server, run `herdr agent get <agent-name>` or `herdr pane read <pane_id> --source visible`. Avoid recent-history reads because they can send scroll input to full-screen TUIs.

Recovery commands:

- **`agent-workers wait <task-id> --recheck`:** Re-polls named unclosed tasks, such as after a dialog clears or an unacknowledged task starts running. Never submits, resends, restarts, or reopens closed or `done` tasks. A `submission: "not_sent"` task stays `start_failed`, and an `exited` task is never promoted to `done`.
- **`agent-workers submit <task-id>`:** Sends the original brief once to an idle, unclosed Rex or core task with `submission: "not_sent"`. Rejects `sent`, `unknown`, historical, closed, or `done` tasks with `submission_unsafe`. Start `wait` right after submitting. Legacy tasks cannot use `submit`. Inspect, close, and start a fresh task instead.
- **`agent-workers close <task-id>`:** Closes the backend terminal and any owned viewer. Retry whenever `closed` is `false`, because the slot stays occupied until both confirm closed. Closing an unfinished worker cancels it.
- **`agent-workers verify-viewer <task-id>`:** Re-reads the live controller workspace, viewer tab, attach command, and visible output for a core task. Always run this fresh before asking the user to interact with a core window.

**Invalid task records:** `list` surfaces malformed task directories as `task_invalid`. Each unclosed invalid record holds one slot in every capacity scope until you inspect the original runtime and remove its directory manually.

## Backends and capacity

- **Backend selection:** Rex uses the verified Rex session. Herdr and headless shells prefer `herdr-core`, then a verified `hc` alias, and fall back to legacy Herdr only when neither is installed. Tasks pin their backend at launch. Wait on Rex and Herdr tasks in separate calls.
- **Worker placement:** Workers open in separate `Workers` tabs (up to 4 panes or blocks per tab) without stealing focus.
- **Capacity scopes:** `max_active_workers` counts unclosed tasks per Rex server and session, per `core_id` (plus legacy tasks in a GUI caller's workspace), or per legacy workspace. Windows in the same session or workspace share capacity even when they use different config profiles.
- **Store isolation:** Core and Rex records pin their endpoints, so one task store works across sessions. Legacy Herdr records do not store socket paths, so give separate legacy Herdr servers separate `XDG_STATE_HOME` roots.
- **`check` batching:** `agent-workers check` deduplicates worker names and batches up to `max_active_workers`. Workers that cannot start return `not_checked`. Failed check tasks leave their terminals open for inspection.
