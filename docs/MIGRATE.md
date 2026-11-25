# Migrate an existing installation

Brings an older installation to the current skill names in one pass. Written
for a coding agent starting with no prior context. Ask it:

> Follow https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/docs/MIGRATE.md
> to migrate my installation. Report what you changed.

| Old name | Current name |
| --- | --- |
| `herdr-orchestrator` | `agent-workers` |
| `pstack-herdr` | `pstack-adapter` |

The worker configuration (`~/.config/herdr-orchestrator/workers.toml`, profiles)
and the task store keep their paths. Do not move, edit, or delete them. The
`herdr-orchestrator` strings left in `agent-workers` name those paths and are
expected.

## Steps for the agent

Set `DISABLE_TELEMETRY=1` for every `npx skills` command. Never use `--all`,
`-s '*'` with `remove`, or unfiltered `skills update`: other repositories'
skills must stay untouched.

1. **Find installations.** In the user's project directory run
   `npx skills@latest ls --json`, then `npx skills@latest ls -g --json`. In each
   scope, note entries named `herdr-orchestrator`, `pstack-herdr`,
   `agent-workers`, `pstack-adapter`, or `poteto-mode`, with their `agents` and
   `source`. A scope needs migration when it has an old name. If neither scope
   has one, also check step 5 before reporting that nothing needs migration.
2. **Pick the package per scope.** If the scope has `pstack-herdr`,
   `pstack-adapter`, or `poteto-mode`, it has the pstack bundle:

   ```bash
   npx skills@latest add https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/tree/main/skills --skill '*' -a <agents> -y
   ```

   Otherwise install only the core skill:

   ```bash
   npx skills@latest add conscientiousness/herdr-rex-pstack-orchestrator -s agent-workers -a <agents> -y
   ```

   Add `-g` for the global scope. `<agents>` repeats `-a` for each agent the old
   entry listed, as lowercase hyphenated IDs (`Claude Code` -> `claude-code`,
   `Antigravity CLI` -> `antigravity-cli`, `Codex` -> `codex`, `Pi` -> `pi`).
   When the source is a local checkout, run `git -C <checkout> pull --ff-only`
   and install from `<checkout>/skills` instead.
3. **Remove the old names** from the same scope, listing only old names that
   step 1 found: `npx skills@latest remove herdr-orchestrator pstack-herdr -y`
   (add `-g` for global). Omit `-a`: selecting agents leaves shared copies.
4. **Verify.** Rerun both `ls --json` commands. Require no old names, and
   `agent-workers` (plus `pstack-adapter` for a bundle) in every migrated scope.
   Run `python <agent-workers path>/scripts/agent-workers.py detect` and confirm
   it reads the existing `workers.toml`.
5. **Manual installs.** `skills ls` does not show links or copies the user made
   by hand. Look for directories named `herdr-orchestrator` or `pstack-herdr`
   under `.agents/skills`, `.claude/skills`, and `.codex/skills` in the project
   and home directory. A symlink into a clone of this repository: pull the
   clone, then point a link with the current name at the current directory and
   remove the old link. A copy: report it with its path and do not delete it,
   since it may hold local edits.
6. **Report** each scope's before and after names, the commands run, and any
   manual install left for the user. Tell the user to start a fresh agent
   session so the new skill names load.
