# Pi integration and startup

## Sub-features

Two focused live-model drivers for legacy Herdr Pi edge cases: rejecting missing Pi integration before allocating slots (`pi_preflight.py`), and preserving a Pi 1.1.0+ project trust dialog without sending a brief (`pi_startup.py`).

## How to get to it (user POV)

Use authenticated Pi workers on legacy Herdr with Herdr's Pi integration installed. Run `agent-workers detect` first. See [e2e/startup-findings.md](../../../../e2e/startup-findings.md) for background on Pi trust dialogs.

## Driving it with existing scripts

Missing-integration preflight (needs two Pi workers, one non-Pi worker, two free slots, and a trusted checkout):

```bash
python3 e2e/pi_preflight.py --pi "$pi_a" --pi "$pi_b" --other "$other" \
  --cwd "$repo" --output "$proof"
```

Uses an isolated empty `PI_CODING_AGENT_DIR` without uninstalling your integration. Require immediate rejection before allocation, successful non-Pi and normal Pi deliveries, unchanged user settings, and pane cleanup.

Project trust dialog check (needs a Pi 1.1.0+ worker without `--approve` or `--no-approve`, one free slot, and an untrusted output parent):

```bash
python3 e2e/pi_startup.py --worker "$pi_worker" --output "$proof"
```

The intentional startup block takes the full 90-second startup budget. The driver then runs a run-local `--no-approve` worker to confirm delivery. Require preserved dialog, unchanged trust, delivery, and pane cleanup.

## Gotchas

- Both drivers make real model calls and write a child `evidence.json` under `$proof`. Keep diagnostics private.
- If every configured worker is Pi, report the missing non-Pi prerequisite instead of editing `workers.toml`.
- Never accept a trust dialog or change user integration settings to force a pass. Run only the scenario you are investigating.
