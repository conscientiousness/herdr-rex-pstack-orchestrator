# Original playbook scenarios

## Sub-features

Live Pi controller drivers that exercise original pstack playbooks against local fixtures or authorized private repositories:

- `e2e/playbook_loop.py`: Investigation, Trace forensics, and Prototype scenarios.
- `e2e/pause_pickup.py`: Two-session Pause safely and Session pickup handoff.
- `e2e/runtime_loop.py`: Runtime forensics against a live owned Node process.
- `e2e/forge_loop.py`, `design_loop.py`, `perf_loop.py`, `hillclimb_loop.py`, `authoring_loop.py`: Writable PR workflows (Bug fix, Feature, Refactoring, Perf issue, Hillclimb, Authoring a skill) against private fixture repositories.
- `e2e/babysit_loop.py`: One Babysit `--status-only` check against a private PR chain.

Full scenario inventory, historical receipts, and audit contracts live in [e2e/PLAYBOOKS.md](../../../../e2e/PLAYBOOKS.md). For release adoption checks, prefer [e2e/ADOPTION.md](../../../../e2e/ADOPTION.md).

## How to get to it (user POV)

Configure an authenticated Pi controller and any worker roles required by the chosen scenario. Run `agent-workers detect`, confirm the caller pane and visible text, and stop other isolated dispatchers in the same workspace. Writable PR drivers additionally require a prepared private fixture repository, an unmerged ready parent PR, and existing `gh` authentication (`GH_CONFIG_DIR` is preserved automatically). `babysit_loop.py` requires Bun and a real stacked PR chain. `runtime_loop.py` requires Node with Inspector and WebSocket support.

## Driving it with existing scripts

Read-only scenario example:

```bash
python3 e2e/playbook_loop.py --controller <configured-pi-worker> \
  --scenario trace-forensics --repo "$repo" --caller-pane <verified-pane> \
  --caller-text '<16+ unique visible chars>' \
  --output "$proof" --max-seconds 1200
```

Two-session pause and pickup example:

```bash
python3 e2e/pause_pickup.py --controller <configured-pi-worker> \
  --repo "$repo" --caller-pane <verified-pane> \
  --output "$proof" --max-seconds 2400
```

For writable PR, Runtime, Hillclimb, and Babysit commands and flags, run `<driver> --help` and follow [e2e/PLAYBOOKS.md](../../../../e2e/PLAYBOOKS.md#continuity-and-writable-workflows).

Read each receipt's behavior, stage, workflow, native-audit, and cleanup verdicts separately. Inspect retained worktrees under `handoff/<run>/worktree`, then remove only the exact owned worktree with `git worktree remove` while keeping external receipts.

## Gotchas

- Missing native session evidence fails closed. A partial stage pass does not complete a playbook.
- Never promote an older failed receipt after fixing an evaluator. Run a fresh immutable execution instead.
- When a driver quarantines a worker delivery on a scope or tool breach, leave its quarantined payloads unread and preserve the `FAIL` receipt.
- Never publish configs, profiles, raw native session logs, or pane text.
