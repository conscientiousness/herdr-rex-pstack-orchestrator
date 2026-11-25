# Original pstack source and compatibility

Tracks [Lauren Tan's original pstack](https://github.com/cursor/plugins/tree/005d8f6e8ec057b738adcd08a08b30db0478402d/pstack) **v0.15.48** (`005d8f6e8ec057b738adcd08a08b30db0478402d`). Pinning locks instructions, not runtime verification of every playbook. See [UPSTREAM-CHANGELOG.md](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/docs/UPSTREAM-CHANGELOG.md) for sync history.

## Install

```bash
npx skills@latest add https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose your harnesses and project or global scope, review same-name skill conflicts, and start a fresh session. No separate upstream checkout is needed. Invoke workflows such as `poteto-mode`, `how`, `interrogate`, or `unslop` (`/skill:poteto-mode` in Pi). Use `-s pstack-adapter` to install only the adapter.

## Included skills and adaptations

The bundle ships **61 skills**: 56 from `pstack`, 3 from `cursor-team-kit` (`control-cli`, `control-ui`, `deslop`), and 2 local skills (`agent-workers`, `pstack-adapter`). Each upstream skill keeps its resources and `UPSTREAM-LICENSE.txt`. Bundled agent prompts live in [agents/](agents/), provenance hashes in [bundle.json](bundle.json), and pin rules in [upstream.json](upstream.json).

| Excluded skill | Reason |
|---|---|
| `make-bot-ui` | Requires Cursor Routines and secret or webhook tools. |
| `poteto-help` | Cursor-specific guides replaced by adapter docs. |
| `setup-pstack` | Writes Cursor model rules. Replaced by `agent-workers` setup and `workers.toml` `[roles]`. |

- **Verbatim copies (46 skills):** 43 non-dispatching `pstack` skills and all 3 `cursor-team-kit` skills are copied byte for byte.
- **Adapted dispatching skills (13 skills):** `arena`, `automate-me`, `figure-it-out`, `how`, `interrogate`, `ketchup`, `maintain-verification-skill`, `no-comments`, `poteto-mode`, `recall`, `show-me-your-work`, `swarm`, and `teach` normalize `name`, keep `description`, `paths`, and `disable-model-invocation`, and prepend a short `## Agent Workers runtime` preamble pointing to [pstack-adapter](../SKILL.md) (`poteto-mode` also adds a one-line worker guard).
- **Explicit-only visibility:** All 56 `pstack` skills keep `disable-model-invocation: true`, and `prepare_pstack.py` adds `agents/openai.yaml` (`allow_implicit_invocation: false`) so Codex also keeps them out of implicit model context. Only 5 skills stay implicitly visible: `agent-workers`, `pstack-adapter`, `control-cli`, `control-ui`, and `deslop`.

Unsupported Cursor features (custom modes, `/loop`, cloud agents, `/visualize`, and missing MCP or app tools) remain unresolved unless your harness supplies equivalents. Bundling does not install script prerequisites such as Bun, `gh`, `origin`, `jq`, or formal-verification tools.

## Maintainer updates

[Daily upstream check](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/.github/workflows/upstream.yml) tracks upstream drift against [upstream.json](upstream.json). To sync a reviewed revision, regenerate from a clean `cursor/plugins` checkout with `python3 scripts/prepare_pstack.py --source <checkout> --output <dir>`, replace bundled upstream dirs and generated provenance files while keeping local skills, run affected checks, and update [UPSTREAM-CHANGELOG.md](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/docs/UPSTREAM-CHANGELOG.md).
