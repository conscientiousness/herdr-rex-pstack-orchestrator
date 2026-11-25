---
name: verify-task-lifecycle
description: Check concurrent agent-workers submission, settlement, delivery, and batch wait when changing the task state lock, recovery guards, or native observation paths.
---

# Verify the task lifecycle

## Run the check

Run from the repository root on Linux with Python 3.11 or later (standard library only):

```sh
python3 .agents/skills/verify-task-lifecycle/explore.py
```

Each line reports one case and how many schedules ran. Exit `0` means all six properties held within the preemption bounds. Exit `1` prints a property ID and counterexample trace. A traceback means the explorer itself failed. CI runs this on Python 3.11 and 3.14 with a 120-second limit.

To read a counterexample, start at the `seed` line (`unknown, sends=1` means an accepted send whose acknowledgement was lost). Each line names the actor and its backend call, state write, or `wait_line`. The last line states the violated property. Pass the printed `--case` and `--schedule` flags to replay that exact schedule on a fresh task directory.

## Bounds and coverage

`explore.py` imports `skills/agent-workers/scripts/agent-workers.py` directly and runs each schedule in a fresh `XDG_STATE_HOME`. Atomic file writes, `flock`, state merges, result validation, file timestamps, polling, and public `wait_line` output all execute the real product code.

`scheduler.py` explores interleavings depth-first by replaying actor prefixes. Preemption points sit at actor entry, before each fake backend call, before each `task_state_lock`, between a worker's `result.json` write and native turn end, and at ACK sleeps. Each lock-held transaction runs as one atomic step. Switching away from a runnable actor costs one preemption unit, while picking the next actor after one finishes is free.

| Case group | Actors | Preemptions |
|---|---|---:|
| Recovery | `recheck`, `submit`, second `submit` | 2 |
| Uncertain send | `recheck`, `submit`, worker writes result then ends turn | 2 |
| Closure | `submit`, `close` | 2 |
| Run | post-placement submitter, worker writes result then ends turn, `wait` | 2 |
| Two observers | `wait`, `wait --recheck`, worker writes result then ends turn | 2 |
| Exit or resumed status | `wait`, worker exits or resumes `working` | 1 |
| Guard, delivery, and batch checks | One command | 0 |

Last verified sync commit: `f40c407c0a15fb76c913519396452dc56ad80813` (46 cases, 2,204 schedules, 0 findings). Each case covers one task, except the batch cases which pair one healthy core task with one offline core endpoint. Waits pass explicit IDs with `max_seconds=0` (at most one poll). File ages are 0 or 16 seconds around the 15-second fallback gate.

| Covered file | Functions and fake boundary |
|---|---|
| `skills/agent-workers/scripts/agent-workers.py` | `cmd_submit`, `prepare_send`, `submit_core_task`, `rex_ready`, `submit_rex_task`, `cmd_close`, `close_task_resources`, `cmd_wait`, `make_info`, `wait_until_change`, `poll_round`, `confirm_result_fallback`, `evaluate_task`, `turn_ended`, `result_verdict`, `validate_result`, `result_stable_for_fallback`, `wait_line`, `task_state_lock`, `load_state`, `save_state`, `write_json` |
| `skills/agent-workers/scripts/core_backend.py` | Real `validate`, `status`, and `fingerprint`. Fake `ready`, `get`, `call(terminal.send)`, and `close`. |
| `skills/agent-workers/scripts/rex_backend.py` | Real `validate`. Fake `get`, baseline-checked `send`, and `close`. |

### Scope limits and omitted points

- **Outside this bound:** Legacy Herdr, viewer setup, event subscriptions, crash recovery mid-write, `agy` banner text checks in `prepare_send` (the fixture uses `harness="pi"`), and arbitrary command sequences. Use the repository's E2E drivers for real server and terminal behavior.
- **Unchecked intervals:** Between `poll_round` returning and `wait_line` reloading state (P3 and P4 still check durable writes and delivery), between `make_info` and the first backend `get`, internal steps inside `core.close` and `rex.send` (partial paste before Enter), and loop timing inside readiness or ACK waits.
- **Unverified fake differences:** Fake guarded `terminal.send` raises `CoreError` when non-idle (real `started: false` records `sent`). Fake `core.close` returns `closed` instead of `removed` or `already_gone`. Fake Rex keeps one constant owner and one later `updated_at` across non-idle states.

## Check a finding or update coverage

1. Replay the printed `--case` and `--schedule`, and map each step to the functions above.
2. Confirm the real backend can return those facts in that order. A legal status change between `get` and `task_state_lock` is a real race even when stored `native_status` still matches the old sample.
3. If the fixture contradicts the backend contract, fix the fixture and rerun. Otherwise report the property violation, and only change a property after an explicit decision about the user harm.
4. After changing covered code, compare against the sync commit, update fake boundaries if needed, prove the check can still fail on a scratch mutation (then drop the mutation), and only then advance the sync commit. Use `/maintain-formal-verification-skill` to resync after skipped checks.

## Failure inventory

| Property | Invariant and user harm | Where to look in `agent-workers.py` |
|---|---|---|
| P1 | Never send the same brief twice, including across retries, concurrent submitters, recheck races, or lost send replies. | `cmd_submit`, `submit_core_task`, `submit_rex_task`, `poll_round` |
| P2 | `wait --recheck` never promotes `not_sent`, and no wait promotes `unknown` to `sent` without a valid nonce-bound result. | `cmd_wait`, `poll_round`, `evaluate_task` |
| P3 | A stale writer never reverts `state: "done"` or clears `closed: true`, which would lose a delivery or reopen a released slot. | `save_state`, `poll_round`, `cmd_close` |
| P4 | Deliver a summary only after native turn completion or confirmed `result_file` fallback (two live null-status reads for the same task, with `sent`, observed work, and a stable valid result). | `turn_ended`, `confirm_result_fallback`, `evaluate_task`, `result_stable_for_fallback`, `poll_round`, `wait_line` |
| P5 | A normal batch wait still delivers healthy neighbors when another task's endpoint is offline, while explicit `--recheck` on that offline task surfaces the error. | `cmd_wait`, `wait_until_change`, `poll_round` |
| P6 | Close a terminal only after a durable `done` write or an explicit `close` command for that task, so cleanup never kills active work. | `poll_round`, `close_task_resources`, `cmd_close` |

For P4, a non-null or gone observation breaks the null-status chain. The small window where a worker resumes after the second confirmation read and before `close` is an accepted residual limit.
