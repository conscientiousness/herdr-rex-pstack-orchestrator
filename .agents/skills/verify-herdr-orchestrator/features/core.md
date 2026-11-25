# Core lifecycle and viewers

## Sub-features

Deterministic checks for `herdr-core` task lifecycle, startup recovery, duplicate-submit refusal, config profiles, `run --wait`, `agy` startup banner guards, restricted `result_file` fallback, and Herdr viewer placement. None of these drivers make model calls.

## How to get to it (user POV)

Install Python 3.11 or later and `herdr-core`. Confirm `herdr-core --version` works. Each driver creates its own `HC_SESSION` and XDG paths and leaves user config, trust, and running sessions untouched. Keep `--output` outside the checkout.

## Driving it with existing scripts

Core lifecycle and startup recovery:

```bash
python3 e2e/core_backend.py --horch skills/agent-workers/scripts/agent-workers.py \
  --output "$proof" --core-only
```

Targeted deterministic feature drivers (run only the one matching your change):

```bash
python3 e2e/config_profiles.py --output "$proof"
python3 e2e/run_wait.py --output "$proof"
python3 e2e/result_fallback.py --output "$proof"
python3 e2e/startup_guards.py --output "$proof"
```

Read each printed `evidence.json` and require `verdict: "pass"`, all assertions true, and clean teardown. For `core_backend.py`, verify early-result gating, completed-turn delivery, missing and invalid results, native `blocked`, cancellation, observation-only `wait --recheck`, one-time `submit`, duplicate `submission_unsafe`, and cleanup.

## Viewer placement

From inside Herdr with `HERDR_ENV=1`, a reachable `HERDR_SOCKET_PATH`, and the `herdr` CLI:

```bash
python3 e2e/core_backend.py --horch skills/agent-workers/scripts/agent-workers.py \
  --output "$proof" --viewer
```

This runs all core lifecycle checks plus live viewer attachment in an owned, unfocused workspace. Require `controller_verification`, `viewer_verified: true`, two separate attach panes in a shared `Workers` tab, failure and recovery of `verify-viewer` when the tab is renamed, unchanged focus, and owned workspace cleanup.

## Gotchas

- These drivers use deterministic fixtures. They do not verify real model execution, harness authentication, trust prompts, or legacy Herdr runtime.
- `startup_guards.py` also checks Rex `--caller-text` unwrapping if `rex` is available.
- Never restart or upgrade the user's running `herdr-core` instance for verification.
- See [e2e/README.md](../../../../e2e/README.md#verify-the-preferred-core-backend) for detailed check inventories.
