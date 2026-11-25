# Interrogate and Arena mapping

Read only when running `interrogate` or `arena` (including contested designs routed from `architect` or `feature`).

## Interrogate review loop

For review-only requests, start at step 2 with the captured target and finish with verified findings and dropped counts. Implementation and fixes require an authorized change.

1. **Implement (authorized changes only):** State intended behavior, create a git worktree, write a complete brief (base revision, scope, constraints, verification, outputs), dispatch via `agent-workers run`, wait for `state: "done"`, and verify diff and behavior.
2. **Fan out adversaries:** Read sibling `interrogate/SKILL.md` and required Arena phases. State and capture exact intent, base revision, target head, and in-scope uncommitted changes before dispatch.
   - Run the entire configured `interrogate reviewers` panel; never relabel formal `interrogate` as ad-hoc to omit reviewers (a single-worker audit must be reported as limited).
   - Start one fresh task per entry (including repeated names). Reviewers do not need to come from a different vendor than the implementer or controller (e.g., two models from the same vendor are valid); disclose when the exact same model is reused.
   - Give each adversary its own writable git worktree with in-scope uncommitted and relevant untracked changes copied in.
   - Give every adversary the same scope, intent, and brief. Allow scoped repros/tests only in its own worktree; forbid product fixes, delivery-branch edits, and unauthorized external writes (do not mark whole assignment read-only).
   - Launch all tasks with separate `agent-workers run` calls before waiting (respecting `max_active_workers`).
3. **Wait and verify:** Wait (`agent-workers wait <ids...> --all`) until every adversary is `state: "done"` (early files do not finish a running task; never close an unfinished reviewer). Require `result_status: "completed"` (`blocked`/`failed` leaves that seat unresolved).
   - Rerun each finding's exact command against the captured target in an isolated worktree.
   - Keep only reproduced failures breaking stated intent, merge duplicate root causes, and report dropped counts/reasons. Skip Arena Phases C, D, and E as Interrogate directs.
4. **Fix and re-review (authorized changes only):** After the prior writer stops, start a fresh implementer on the same branch with original goal, accepted findings, prior reports, and current revision. Verify behavior, then run a fresh reviewer panel on the new revision (never reuse a session).
5. **Finish:** Stop when no blocking finding remains; report final revision, verification, reviewer outcomes, and remaining concerns. On worker problems, follow [Problems](../../../agent-workers/SKILL.md#problems) and keep the gate open.

Writers never share a worktree concurrently; Interrogate adversaries each need writable worktrees (other reviewers may share a checkout only if read-only). These are instruction boundaries, not an enforced sandbox.

## Arena runners and cross-judge

- **`arena runners`** (panel): launch one fresh task per configured entry (including repeated names) in separate worktrees; do not silently drop seats or use unconfigured upstream fallbacks (if a seat hits usage/quota exhaustion, close it and replace it with another configured worker without stopping, disclosing the switch).
- **`arena cross-judge pool`** (single pick after candidates finish): select **one** configured worker from the pool (overrides upstream's different-vendor restriction).
  - Prefer a different model or vendor when available in the pool, but same-vendor judges are allowed (e.g., another model from the same vendor); never skip judging solely because pool workers share a vendor with the controller or implementer.
  - If none in the pool can run, skip judging and disclose as Arena permits (never substitute unconfigured models or edit `workers.toml`).
