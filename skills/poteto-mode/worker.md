<!-- Adapted by prepare_pstack.py for agent-workers + pstack-adapter. -->
Follow the assignment and `## Worker rules` appended at the end of your `brief.md`.

- **No nested workers:** Do not delegate, use native subagents, or run a whole playbook. Complete this assignment yourself, and report any need for further delegation to the controller.
- The bar in your brief is the whole bar. Add no check, gate, sign-off, or review round above it.
- Never open an interactive question for the user. Resolve routine, reversible choices from the brief and repository conventions; report missing required input or authorization in `result.json` with `status: "blocked"`.
- For repository delivery tasks that open a PR (not read-only research or audit tasks): follow PR-first rules in the brief, open PRs ready for review (never draft), use `type(scope): subject` titles, keep PR bodies concise (`Why`, `What changed`, `Scope`, `Tradeoffs`, `Blast Radius`, `Verification`), and link long logs or tables from files or comments.
