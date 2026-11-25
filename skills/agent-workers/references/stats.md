# Worker statistics

Run `agent-workers stats` before proposing changes to `workers.toml`, or when the user asks whether workers are slow, failing, or worth keeping.

```bash
python3 <skill-dir>/scripts/agent-workers.py stats [--workspace <id>] [--days <n>] [--no-samples] [--profile <name> | --config <path>]
```

This command is read-only. It inspects only the selected worker config and the task store, with no terminal calls, locks, or writes. `--profile` or `--config` selects the reference worker list, roles, and `notify_after_minutes` while still scanning the shared task store. Pass `--no-samples` to omit the per-task `duration_samples` array.

## Caveats when interpreting the JSON

- **Current config vs. history:** `harness`, `model`, `effort`, and `provider` reflect the current config, not necessarily the model used for older tasks.
- **Cancelled tasks:** Unsettled tasks closed early appear under `states.closed_before_done` and are excluded from `problem_rate`. `problem_rate` divides settled problems by `done` plus settled problems, and returns `null` when there are no settled outcomes.
- **Durations:** `duration_minutes` covers `done` tasks with valid results and includes startup, polling, and wait latency. Newer records use `first_done_at`, while older records fall back to `result.json` mtime (trends across the two sources are not strictly comparable).
- **Reminders vs. duration tails:** `reminder_fired` counts tasks where a `wait` actually observed the task past `notify_after_minutes`. `delivered_duration_estimate` estimates how many timed tasks finished past the current threshold and fixed buckets (15, 30, 45, 60, and 90 minutes).
- **Context matters:** Small samples mislead, `blocked` may be a genuine spec question, provider outages can cause `result_missing`, and the store does not measure review quality or cost.

The user owns `workers.toml`. Present the numbers and propose edits to `notify_after_minutes`, `max_active_workers`, worker definitions, or roles, and edit the file only with user consent.
