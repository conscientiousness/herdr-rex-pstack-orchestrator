---
name: verify-task-lifecycle
description: Check concurrent agent-workers submission, settlement, delivery, and batch wait when changing the task state lock, recovery guards, or native observation paths.
---

# Verify the task lifecycle

## Run the check

Run from the repository root on Linux with Python 3.11 or newer. The explorer needs only the standard library.

```sh
python3 .agents/skills/verify-task-lifecycle/explore.py
```

Each line gives a case and its completed schedule count. Exit 0 means all five properties held within the bounds below. Exit 1 with a property ID means the checker found a violation. A traceback means the exploration itself failed. CI runs this command on Python 3.11 and 3.14 with a 120-second limit.

Read the `seed` line first. `unknown, sends=1` represents an accepted pointer whose acknowledgement was lost. Each following line names the actor and its backend call, durable write, or public `wait_line`. The last line states the harm. Append the printed `--case` and `--schedule` arguments to replay that interleaving on a fresh task directory.

## Bounds and coverage

`explore.py` imports `skills/agent-workers/scripts/agent-workers.py` by path. Each schedule starts in a new `XDG_STATE_HOME`. Each command reads its own task snapshot. Atomic file replacement, `flock`, state merges, result validation, file timestamps, polling, and public wait lines run through the product code.

`scheduler.py` explores choices depth-first by replaying actor prefixes. It can switch at actor entry, before each fake backend operation, before a state transaction, between the worker's result write and native completion, and at an ACK sleep. The whole lock-held transaction runs as one step. A preemption spends one unit of the bound when the scheduler changes away from a runnable actor. Choosing the next actor after another finishes is free. Every eligible choice runs to completion. The bound limits preemptions, not the number of events in a schedule.

| Cases in `cases()` | Actors per case | Preemptions |
| --- | --- | ---: |
| Recovery | `recheck`, `submit`, second `submit` | 2 |
| Uncertain send | `recheck`, `submit`, worker writes result then ends turn | 2 |
| Closure | `submit`, `close` | 2 |
| Run | post-placement startup submitter, worker writes result then ends turn, `wait` | 2 |
| Two observers | `wait`, `wait --recheck`, worker writes result then ends turn | 2 |
| Exit or resumed native status | `wait`, worker exits or resumes `working` | 1 |
| Individual guard and delivery cases, batch with and without `--recheck` | One command | 0 |

At the sync commit the catalog has 44 cases and 2,200 schedules. It covers one task per case, except for two independent core endpoints in a batch. Each wait uses explicit IDs and `max_seconds=0` for at most one poll. Worker facts cover idle, working, blocked, error, done, a live terminal with null status, and disappearance. The file clock gives result and declared output files ages of 0 or 16 seconds around the 15-second gate. Recovery uses an accepted send that leaves the endpoint idle through the ACK timeout. Normal startup uses an acknowledged send.

| File under `skills/agent-workers/scripts/` | Functions and boundary |
| --- | --- |
| `agent-workers.py` | `cmd_submit`, `submit_core_task`, `rex_ready`, `submit_rex_task`, `cmd_close`, `close_task_resources`, `cmd_wait`, `make_info`, `wait_until_change`, `poll_round`, `evaluate_task`, `turn_ended`, `result_verdict`, `validate_result`, `result_stable_for_fallback`, `wait_line`, `task_state_lock`, `load_state`, `save_state`, and `write_json` |
| `core_backend.py` | Real `validate` and `status`. The fake returns the public shapes of `ready`, `get`, `call(terminal.send)`, and `close`, including the idle guard and offline `CoreError`. |
| `rex_backend.py` | Real `validate`. The fake implements `get`, baseline-checked `send`, and `close` at the module boundary. Live status includes the owner and update time. |

The `run` actor starts at the call to `submit_core_task` or `submit_rex_task` in `start_core_task` or `start_rex_task`, after allocation and placement. Fake backend operations are atomic, and thread-local command stacks represent separate processes. The interval between scheduler points runs uninterrupted. Legacy Herdr, viewer setup, crash recovery inside a write, changes within a Rex paste, the event subscription loop, and arbitrary command sequences beyond the catalog are outside this bound. Use the repository's backend E2E drivers for server and terminal behavior.

## Check a finding

1. Replay the printed schedule. Match each read, lock, send, and write to the functions above.
2. Check that the endpoint can return the listed facts in that order. A legal status change after `get` and before `task_state_lock` is a race even when the stored `native_status` still matches the old sample.
3. If the seed or response contradicts the backend contract, correct that fixture and rerun. If the order is reachable, keep the witness and report the property violation. An intended contract change needs an explicit decision about the harm before updating the property.

At sync commit `a6f845408d261d5fc2d40debd63aab288d7a42af`, `core-recovery` and `rex-recovery` find P1. A recheck replaces a live submitter's `starting` reservation with `start_failed`, letting another submitter through. `core-resume` and `rex-resume` find P4. The worker resumes `working` between a null sample and fallback settlement. Both waits close the live worker and deliver its summary.

Mutation evidence covers the batch filter (`9f2942a`), both submission guards (PR #46), the native-status fallback guard (PR #63), and both `save_state` protections (P3). Removing `current["state"] == "done"` from the merge preference makes `core-run` report `done` reverting to `running`. Losing the `closed` OR makes `core-close` reopen a reservation. Drop the scratch mutation after replay and rerun the full command to recover the baseline findings.

After a change to the covered code, compare it with the sync commit, check the scheduler points and fake contracts, and rerun a breaking mutation and the restored tree. Advance the sync commit only after that comparison and verification. Use `/maintain-formal-verification-skill` when updating coverage after a change.

## Failure inventory

| Property | Failure and user harm | Where to look in `skills/agent-workers/scripts/agent-workers.py` |
| --- | --- | --- |
| P1 | A retry, a second submitter, or a recheck racing a reservation can send the same brief twice, including after a lost send reply. | `cmd_submit`, `submit_core_task`, `submit_rex_task`, `evaluate_task` |
| P2 | Treating native activity as receipt lets `wait --recheck` promote an unsent task to running or sent, leaving the controller waiting for work it never assigned. | `cmd_wait`, `poll_round`, `evaluate_task` |
| P3 | A stale submitter or waiter can overwrite `done` or clear `closed`, losing a delivery or reopening a released reservation. | `save_state`, `poll_round`, `cmd_close` |
| P4 | Delivering a summary before native completion or an eligible result-file fallback can close a worker that is still working, blocked, or reporting an error. | `turn_ended`, `evaluate_task`, `result_stable_for_fallback`, `wait_line` |
| P5 | Observing an offline, settled task during ordinary batch wait can abort delivery for its healthy neighbor. | `cmd_wait`, `wait_until_change`, `poll_round` |

For P1, count accepted pointers at the backend, including a send whose reply was lost. For P2, distinguish a `recheck` write from a concurrent `submit` write. For P3, inspect successive durable writes, including the write between settlement and resource cleanup. For P4, distinguish a fresh status from a stale sample, a new native turn from an old idle observation, and a stable result from one whose declared file is still changing. A missing worker, a missing result, a mismatched nonce, unobserved execution, and a known unsent task cannot supply fallback evidence. For P5, explicit recheck of the offline task can contact it and report the backend error.
