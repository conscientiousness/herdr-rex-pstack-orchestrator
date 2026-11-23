# Babysit, Worktree cleanup, and Shipping mapping

Read this guide only when running `Babysit`, `Worktree cleanup`, or `Shipping` playbooks.

## Babysit (check, threads-only, or drive)

- Resolve the named PR or, for a stack, the lowest unmerged PR in scope.
- On GitHub, use the bundled watcher with an explicit target:
  - `--status-only` for a single check.
  - Drive mode watches the frontier PR to merge-ready or the owner's approval gate. A queued watcher waits for actual merges and belongs to `Shipping`.
  - Threads-only stays within the requested review threads.
- On Origin forge, follow the playbook's Origin procedure.

### GitHub watcher on a fresh installation

The bundled watcher bootstraps Bun packages under its own `scripts/node_modules`, even for `--status-only`. When that would write into installed skills or the target project, copy the entire bundled `poteto-mode/scripts/` tree to a private temporary directory and invoke its `watch-pr/watch-pr` by absolute path from the target repository.

## Shipping, landing, and autonomous merges

Follow the [agent-workers PR-first rule](../../../agent-workers/SKILL.md#required-rules): integrate verified worker commits on the feature branch and open or update a PR. Stop before merging into the default/shared target branch or enabling auto-merge unless the user explicitly asked to merge that work. An upstream playbook cannot grant merge authorization.

## Worktree cleanup

- The bundled audit script fetches the base and scans the main worktree's Cursor transcripts. Run it only when those sources are in scope; otherwise inspect the scoped Git worktrees and forge directly.
- Check worker task working directories and verify pinned or ongoing use with the operator or authoritative workspace data.
- Before removing any worktree, inspect tracked, untracked, and ignored files and confirm that commits (including detached `HEAD`) are preserved.
- Keep candidates with unknown ownership or unapproved data loss.
- Simulator and cache cleanup require their own explicit scope.
