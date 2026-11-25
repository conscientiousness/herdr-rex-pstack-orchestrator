---
name: verify-herdr-orchestrator
description: Verify herdr-rex-pstack-orchestrator through its existing local E2E drivers. Use when checking skill discovery, worker or controller execution, Pi startup, or upstream monitoring in this repository.
---

# Verify agent-workers

Run only the existing E2E driver for the behavior you changed or observed failing. Start with the [feature map](features/README.md). Do not run model E2Es for documentation changes. This skill is repository tooling, not part of the published package.

## Launch

Run commands from the repository root with Python 3.11 or later. There is no build step or application server. Create an artifact directory outside the checkout:

```bash
repo=$(git rev-parse --show-toplevel)
cd "$repo"
proof=$(mktemp -d "${TMPDIR:-/tmp}/verify-herdr-XXXXXXXX")
git rev-parse HEAD > "$proof/revision.txt"
git diff --stat > "$proof/working-tree.txt"
```

Record the exact command and CLI versions beside the receipt. Model runs need authenticated harnesses and configured workers in `${XDG_CONFIG_HOME:-$HOME/.config}/herdr-orchestrator/workers.toml`. Check actual `harness` and `model` values rather than assuming from worker names. Read [agent-workers](../../../skills/agent-workers/SKILL.md) before any model run.

## Doctor

Before model or backend runs, run this read-only check:

```bash
python3 skills/agent-workers/scripts/agent-workers.py detect
```

Confirm required CLIs, the selected backend, available slots, and the driver's prerequisites. Inside Herdr or Rex, pass `--caller-text` (at least 16 visible characters unique to this conversation) on `run` and `check`, plus `--caller-pane` or `--caller-block` when disambiguating. Ordinary shell scripts can rely on process ancestry. Legacy Pi requires `herdr integration install pi`, while Rex and `herdr-core` do not. `agent-workers check` makes real model calls and is not a read-only doctor. Treat missing config, auth, or trust as a prerequisite gap, and never modify user settings silently.

For discovery and upstream checks, follow that feature's CLI checks. Herdr, Rex, and model credentials are not needed.

## Drive

Follow only the selected [feature guide](features/README.md). Keep long-running driver commands alive while reporting progress. Run Herdr evaluations in owned tabs and Rex evaluations on an isolated server. Stop other dispatchers in the same workspace during isolated-state model E2Es.

Use [core lifecycle and viewers](features/core.md) for deterministic core, profile, fallback, banner-guard, and viewer checks. Do not run model E2Es to cover a deterministic fix.

On a failure, preserve the receipt and inspect the recorded backend before cleanup. Read `startup_ready`, `submission`, `execution_observed`, and `native_status` separately. Follow [agent-workers recovery](../../../skills/agent-workers/SKILL.md#problems) within the scenario's declared worker choices, and preserve the original verdict if recovery would change scenario conditions. Run a fresh `verify-viewer <id>` with `viewer_verified: true` before directing a user to a core window.

## Evidence

The printed receipt path is authoritative. Most drivers write a child directory under `--output`, while `skill_catalogs.py` creates its own temporary directory. Check `verdict`, individual assertions, observed outputs, and cleanup results rather than only the exit code. Keep failed receipts as failures, and distinguish fresh runs from historical evidence in [e2e/README.md](../../../e2e/README.md#evidence-and-source-attribution). Sanitize any artifact before publishing so private paths, configs, transcripts, or pane text never leak.

## Cleanup

Drivers clean up only their own subprocesses, panes, or blocks. Verify cleanup in the receipt, and never kill by process name or close unrelated panes. For drivers that retain worktrees, inspect first, then remove the exact printed path with `git worktree remove` while keeping sibling receipts. After teardown, reopen the receipt to confirm cleanup did not delete it, and record any incomplete cleanup.

## Helpers

Do not add new helper scripts. Use the existing drivers listed in the [feature map](features/README.md) and documented in [e2e/README.md](../../../e2e/README.md). Use `maintain-verification-skill` when these procedures drift from the codebase.
