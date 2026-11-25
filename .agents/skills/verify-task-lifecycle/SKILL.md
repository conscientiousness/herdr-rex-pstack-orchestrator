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

Each line gives a case and its completed schedule count. Exit 0 means all six properties held within the bounds below. Exit 1 with a property ID means the checker found a violation. A traceback means the exploration itself failed. CI runs this command on Python 3.11 and 3.14 with a 120-second limit.

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

At the sync commit the catalog has 46 cases and 2,202 schedules. It covers one task per case, except for two independent core endpoints in a batch. Each wait uses explicit IDs and `max_seconds=0` for at most one poll. Worker facts cover idle, working, blocked, error, done, a live terminal with null status, and disappearance. The file clock gives result and declared output files ages of 0 or 16 seconds around the 15-second gate. Recovery uses an accepted send that leaves the endpoint idle through the ACK timeout. Normal startup uses an acknowledged send.

| File under `skills/agent-workers/scripts/` | Functions and boundary |
| --- | --- |
| `agent-workers.py` | `cmd_submit`, `submit_core_task`, `rex_ready`, `submit_rex_task`, `cmd_close`, `close_task_resources`, `cmd_wait`, `make_info`, `wait_until_change`, `poll_round`, `evaluate_task`, `turn_ended`, `result_verdict`, `validate_result`, `result_stable_for_fallback`, `wait_line`, `task_state_lock`, `load_state`, `save_state`, and `write_json` |
| `core_backend.py` | Real `validate` and `status`. The fake models `ready`, `get`, `call(terminal.send)`, and `close` at the module boundary, including idle readiness and the offline `CoreError`. |
| `rex_backend.py` | Real `validate`. The fake implements `get`, baseline-checked `send`, and `close` at the module boundary. Live status includes the owner and update time. |

The `run` actor starts at the call to `submit_core_task` or `submit_rex_task` in `start_core_task` or `start_rex_task`, after allocation and placement. Fake backend operations are atomic, and thread-local command stacks represent separate processes. The interval between scheduler points runs uninterrupted.

### Omitted preemption points

| Interval | Effect within these cases |
| --- | --- |
| `poll_round` return to the fresh `load_state` in `wait_line` | Another writer could change which line the caller sees. P3 checks every durable write. P4 checks settlement evidence at the write, cleanup, and public delivery. This bound leaves out the exact freshness of line selection. P1, P2, P5's offline read, and P6 are decided at other events. |
| `make_info` to the first backend `get` | The scheduling point immediately before `get` lets another actor run after the waiter takes its snapshot. Snapshots that skip observation still reach a lock point if polled. Batch setup has a single actor. There is no intervening send, write, backend result, or close for P1–P6 to distinguish in these cases. |
| Inside `core.close` | The real helper gets, kills, checks for `finished`, removes, and checks for absence. P6 checks authorization at entry and P4 requires confirmation by then. A worker observed as finished or absent yields `exited` on these paths. The helper's internal reads cannot authorize fallback. |
| Inside `rex.send` | The fake counts acceptance once. A real change between paste and Enter withholds Enter (`worker_changed`) and leaves receipt uncertain. The `unknown` cases cover the durable guard for that outcome. P1 counts submitted pointers. P2–P6 act on public observations, command writes, and cleanup. Partial input in the terminal is outside this check. |
| Readiness and ACK loops | `core.ready` is one success or error. Rex `get` and sleep are scheduling points, but the fake clock skips repeated waits for the same status. In this catalog only readiness success reaches a send attempt, and the ACK loop records its outcome before returning. The properties inspect those events. They make no timing or liveness claim about the loops. |

### What is not covered

Legacy Herdr, viewer setup, crash recovery inside a write, event subscription, and arbitrary command sequences are outside this bound. Use the repository's backend E2E drivers for server and terminal behavior. The following fake contracts have not been verified against the backends:

- A non-idle guarded `terminal.send` raises `CoreError` in the fake. A real `started: false` reply would record `sent`, while a raise records `unknown`. Both double-send witnesses use idle acceptance.
- Fake `core.close` returns `terminal: closed`. Real success returns `removed` or `already_gone`. The covered cleanup path ignores that string.
- Core `reported` follows the current status in the fake. It can become false even after the worker previously reported work. The fixture uses it for idle readiness.
- The Rex fixture keeps one owner for reported statuses. A harness restart can replace the owner and trigger guards outside this catalog.
- All non-idle Rex samples use a single later `updated_at`. The fixture does not independently vary status and timestamp to exercise a change without timestamp advancement.

## Check a finding

1. Replay the printed schedule. Match each read, lock, send, and write to the functions above.
2. Check that the endpoint can return the listed facts in that order. A legal status change after `get` and before `task_state_lock` is a race even when the stored `native_status` still matches the old sample.
3. If the seed or response contradicts the backend contract, correct that fixture and rerun. If the order is reachable, keep the witness and report the property violation. An intended contract change needs an explicit decision about the harm before updating the property.

At sync commit `a6f845408d261d5fc2d40debd63aab288d7a42af`, `core-recovery` and `rex-recovery` find P1. A recheck replaces a live submitter's `starting` reservation with `start_failed`, letting another submitter through. `core-resume` and `rex-resume` find P4. The waiter reads null once, writes `done`, and closes. The worker can resume before the write or between the write and close. Both orders lack re-confirmation. The single-actor `*-delivery-None` controls also find P4 because even an uninterrupted fallback takes just one sample.

Mutation evidence covers the batch filter (`9f2942a`), both submission guards (PR #46), the native-status fallback guard (PR #63), and both `save_state` protections (P3). Removing `current["state"] == "done"` from the merge preference makes `core-run` report `done` reverting to `running`. Losing the `closed` OR makes `core-close` reopen a reservation. For the review mutations, unconditionally setting `cleanup = True` closes a `running` worker (P6). Dropping the `result_verdict` guard promotes `unknown` on missing and wrong-nonce results (P2). Removing the recheck exception from the `observing` filter silently skips the offline task (P5). Drop the scratch mutation after replay and rerun the full command to recover the baseline findings.

After a change to the covered code, compare it with the sync commit, check the scheduler points and fake contracts, and rerun a breaking mutation and the restored tree. Advance the sync commit only after that comparison and verification. Use `/maintain-formal-verification-skill` when updating coverage after a change.

## Failure inventory

| Property | Failure and user harm | Where to look in `skills/agent-workers/scripts/agent-workers.py` |
| --- | --- | --- |
| P1 | A retry, a second submitter, or a recheck racing a reservation can send the same brief twice, including after a lost send reply. | `cmd_submit`, `submit_core_task`, `submit_rex_task`, `evaluate_task` |
| P2 | A recheck must leave `not_sent` unpromoted. Any wait that writes `unknown` to `sent` needs a valid result bound to this task and nonce, or the controller may wait for work the worker never received. | `cmd_wait`, `poll_round`, `evaluate_task` |
| P3 | A stale submitter or waiter can overwrite `done` or clear `closed`, losing a delivery or reopening a released reservation. | `save_state`, `poll_round`, `cmd_close` |
| P4 | Deliver a summary only after native completion or eligible result-file settlement. Fallback based on a single null sample can close a worker that resumed between observation and cleanup. | `turn_ended`, `evaluate_task`, `result_stable_for_fallback`, `poll_round`, `wait_line` |
| P5 | An ordinary batch wait must deliver its healthy neighbor despite a settled offline task. Explicit recheck of that offline task must surface its endpoint error, or the controller can mistake a skipped check for success. | `cmd_wait`, `wait_until_change`, `poll_round` |
| P6 | Closing a terminal requires a durable `done` write for that task or an explicit close command for it. Premature cleanup can kill work before a result exists. | `poll_round`, `close_task_resources`, `cmd_close` |

For P1, count accepted pointers, including a send whose reply was lost. P2 uses the active wait command and its `--recheck` flag. A sender can record its own successful send. P3 inspects successive durable writes, including the write between settlement and cleanup. P6 checks the target at the backend close call, before the endpoint disappears.

For P4, a fallback needs `sent`, observed work, a valid stable result and a live null-status sample. The settling waiter must re-confirm live null status for that same task before closing it or exposing its summary. A non-null or gone observation breaks the chain of null observations. The worker can resume after re-confirmation and before close. The user accepts that residual window. A quiet worker still requires the second read.
