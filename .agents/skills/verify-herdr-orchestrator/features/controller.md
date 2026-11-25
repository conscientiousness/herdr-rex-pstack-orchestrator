# AI controller loop

## Sub-features

A live Codex controller drives the six-task invoice scenario (`controller_loop.py`), and two deterministic no-model drivers test Herdr caller-context preflight (`caller_context.py`) and caller identity verification (`caller_identity.py`).

## How to get to it (user POV)

For `controller_loop.py`, pick a configured worker with `harness = "codex"`, plus a writer and two distinct reviewers. Ensure two free slots plus the controller pane, access to the controller's local Codex transcript, and no other dispatchers in that workspace.

For `caller_context.py` and `caller_identity.py`, confirm your live Herdr pane ID and at least 16 unique visible characters from this conversation.

## Driving it with existing scripts

### Codex controller loop

```bash
python3 e2e/controller_loop.py --controller "$controller" \
  --writer "$writer" --reviewer "$reviewer_a" --reviewer "$reviewer_b" \
  --repo "$repo" --output "$proof"
```

Require the fresh run's scenario assertions, transcript audit (delivery-before-read ordering, wait handles, delegation, and cleanup), and teardown to pass together. Inspect and remove the printed worktree while keeping sibling evidence. See [e2e/README.md](../../../../e2e/README.md) for the transcript audit contract.

## Caller context preflight

```bash
python3 e2e/caller_context.py --controller-pane <verified-pane> \
  --controller-text '<16+ unique visible chars>' --output "$proof"
```

Runs read-only Herdr checks and config validation without creating panes or launching workers. Require all assertions true and zero allocated task state.

## Caller identity

```bash
python3 e2e/caller_identity.py --controller-pane <verified-pane> \
  --controller-text '<16+ unique visible chars>' --output "$proof"
```

Creates and removes one scratch tab and one scratch workspace to test stale inherited panes, contradictory claims, detached environments, screen-text proof, and moved-pane aliases, without launching models. Require `verdict: "pass"`, every check true, and `cleanup_ok: true`.

## Gotchas

- A Pi worker using an OpenAI model is not a Codex controller. Report a missing Codex worker as a prerequisite gap instead of editing `workers.toml`.
- Missing or ambiguous transcript evidence fails `controller_loop.py` even if the code fix is right.
- Do not type into the user's controller pane to manufacture a `--caller-text` match.
- Caller preflight does not verify core viewer rendering. Use [core.md#viewer-placement](core.md#viewer-placement) for that.
