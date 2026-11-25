# Verification feature map

Run commands from the repository root using `repo` and `proof` from [Launch](../SKILL.md#launch). Pick only the driver that matches the change or failure.

| Feature | Driver | Scope and prerequisites |
|---|---|---|
| [Skill installation and discovery](discovery.md) | `e2e/skill_catalogs.py` | Bundled skills, npm, Pi, and Codex. No model calls. |
| [Practical delivery and removal](../../../../e2e/ADOPTION.md) | `agent-workers.py` and fixture oracle | Two configured workers, private fixture PR, and full project uninstall check. |
| [Cold-start rename migration](../../../../docs/MIGRATE.md) | `e2e/migration_loop.py` | Cold-start upgrade from `herdr-orchestrator` and `pstack-herdr` to current names. |
| [Core lifecycle and deterministic guards](core.md) | `e2e/core_backend.py --core-only`, `config_profiles.py`, `run_wait.py`, `startup_guards.py`, `result_fallback.py` | Installed `herdr-core` (plus `rex` for `startup_guards.py`). Deterministic fixtures, no models. |
| [Core viewer placement](core.md#viewer-placement) | `e2e/core_backend.py --viewer` | Adds live attach panes in an owned Herdr workspace. Needs `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `herdr`. |
| [Rex backend placement and delivery](../../../../e2e/README.md#verify-the-rex-backend) | `e2e/rex_backend.py` | Real `rex` CLI on an isolated Unix-socket server. Deterministic fixtures, no models. |
| [Worker review loop](workers.md) | `e2e/review_loop.py` | Authenticated writer and two distinct reviewers, two free slots. Six real tasks. |
| [Worker setup checks](workers.md#worker-setup-checks) | `e2e/check_workers.py` | Two authenticated workers, owned workspace, one-slot batching, `stats`, and injected exit. |
| [Live worker replacement](workers.md#live-worker-replacement) | `e2e/check_workers.py --hot-swap-only` | Two distinct configured worker definitions in an owned workspace. |
| [Workspace worker limits](workers.md#workspace-worker-limits) | `e2e/workspace_limits.py` | One authenticated worker, two owned workspaces, shared isolated task store. |
| [AI controller loop](controller.md) | `e2e/controller_loop.py` | Configured Codex controller plus writer and two reviewers, with local transcript audit. |
| [Caller and config preflight](controller.md#caller-context-preflight) | `e2e/caller_context.py` | Verified live Herdr pane and visible text. Read-only checks, no models. |
| [Caller identity](controller.md#caller-identity) | `e2e/caller_identity.py` | Verified live Herdr pane and visible text. Scratch tab and workspace, no models. |
| [Original playbook scenarios](playbooks.md) | `e2e/playbook_loop.py`, `pause_pickup.py`, `runtime_loop.py`, `forge_loop.py`, `design_loop.py`, `perf_loop.py`, `hillclimb_loop.py`, `authoring_loop.py`, `babysit_loop.py` | Configured Pi controller and scenario-specific fixtures or private PRs. See [e2e/PLAYBOOKS.md](../../../../e2e/PLAYBOOKS.md). |
| [Pi integration and startup](pi.md) | `e2e/pi_preflight.py`, `e2e/pi_startup.py` | Legacy Herdr Pi integration preflight and Pi 1.1.0+ trust dialog preservation. |
| [Upstream update detection](upstream.md) | `scripts/check_upstream.py` | Git and network access. No model calls. |

This map lists reproducible drivers, not complete coverage. Approval denials, turns longer than 30 minutes, native Claude Code catalog discovery, and macOS runtime remain unverified.
