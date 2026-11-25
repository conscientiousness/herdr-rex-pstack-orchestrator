# Worker review loop

## Sub-features

Four live-model drivers test `agent-workers` directly (without an AI controller): a six-task implementation and review loop (`review_loop.py`), setup verification and `stats` (`check_workers.py`), hot-swapping worker config during live runs (`check_workers.py --hot-swap-only`), and per-workspace slot limits (`workspace_limits.py`).

## How to get to it (user POV)

Configure authenticated workers in `workers.toml`, ensure the checkout is trusted, and install Herdr's Pi integration for legacy Pi workers. Run `agent-workers detect` first.

## Driving it with existing scripts

### Six-task review loop

Pick `writer` and two reviewers (`reviewer_a`, `reviewer_b`) with distinct model definitions and two free slots:

```bash
python3 e2e/review_loop.py --writer "$writer" \
  --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Require `verdict: "pass"`, expected initial FAIL and final PASS reviews, verified invoice CLI outputs, and pane cleanup. Inspect and remove the printed worktree with `git worktree remove` while keeping sibling receipts.

## Worker setup checks

Pick at least two distinct configured workers:

```bash
python3 e2e/check_workers.py --worker "$worker_a" --worker "$worker_b" \
  --cwd "$repo" --output "$proof"
```

The driver creates an isolated workspace and state store, exercises deduplication, one-slot batching, zero-slot skips, an injected worker exit, budget skips, cleanup, and read-only `agent-workers stats` checks (including cancelled tasks, duration percentiles, threshold estimates, and dangling roles). Require `verdict: "pass"`, all assertions true, and clean teardown.

## Live worker replacement

Pick two configured workers with distinct execution definitions (identical definitions skip rather than pass):

```bash
python3 e2e/check_workers.py --hot-swap-only \
  --worker "$worker_a" --worker "$worker_b" \
  --cwd "$repo" --output "$proof" --max-seconds 1200
```

This replaces a worker alias while a task is running and removes it while two tasks remain live. Require valid deliveries, unchanged launch snapshots on in-flight tasks, new tasks picking up the replacement, refusal after removal without allocation, unchanged real config, and cleanup.

## Workspace worker limits

Pick one configured worker:

```bash
python3 e2e/workspace_limits.py --worker "$worker" --output "$proof"
```

This creates two temporary workspaces sharing an isolated task store with a two-slot limit per workspace, verifies local refusals, tests legacy records without `workspace_id`, and checks recovery after delivery and cleanup.

## Gotchas

- All four drivers make real model calls and test `agent-workers` directly, not an AI controller or pstack playbook.
- Never clear worker dialogs, retry with a different model, or change user config to force a pass.
- Preserve failed receipts and private diagnostics outside the checkout. See [e2e/README.md](../../../../e2e/README.md) for scenario details.
