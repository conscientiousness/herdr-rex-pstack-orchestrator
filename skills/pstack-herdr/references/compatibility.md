# Original pstack source and compatibility

Tracks [Lauren Tan's original pstack](https://github.com/cursor/plugins/tree/005d8f6e8ec057b738adcd08a08b30db0478402d/pstack) **v0.15.48** (`005d8f6e8ec057b738adcd08a08b30db0478402d`). Pinning locks instructions, not runtime verification of every playbook. Full sync history (0.15.25–0.15.48): [UPSTREAM-CHANGELOG.md](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/docs/UPSTREAM-CHANGELOG.md).

## Install

```bash
npx skills@latest add https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/tree/main/skills --skill '*'
```

Choose harnesses and project/global scope; review skill-name conflicts first. Installs the bundled catalog and both adapters (excluding repo-dev skills); `-s pstack-herdr` installs only that adapter. No upstream checkout needed. Start a fresh session and invoke `poteto-mode`, `how`, `interrogate`, or standalone skills like `unslop` (`/skill:poteto-mode` in Pi).

## Included skills and adaptations

**61 entries:** 56 pstack skills, 3 team-kit skills (`control-cli`, `control-ui`, `deslop`), and 2 adapters (`agent-workers`, `pstack-herdr`), each retaining resources and `UPSTREAM-LICENSE.txt`. Original agents: [agents/](agents/). Provenance/hashes: [bundle.json](bundle.json); pin/adaptations/exclusions: [upstream.json](upstream.json).

| Excluded skill | Reason |
|---|---|
| `make-bot-ui` | Requires Cursor Routines and secret-request/webhook tools. |
| `poteto-help` | Cursor-specific external guides; replaced by adapter docs. |
| `setup-pstack` | Writes Cursor model rules; replaced by `agent-workers` setup + `workers.toml` `[roles]`. |

Non-adapted upstream `SKILL.md` files (43 of 56 pstack skills—including non-dispatching `architect`, `blast-radius`, `create-verification-skill`, `principle-guard-the-context-window`, `reflect`, `why`—plus all 3 team-kit skills and standalone guidance like `unslop`, `sharpen`, `reframe`, and all 24 principles) are copied byte for byte. Only **13** dispatching/runtime skills in `adapted_skills` (`arena`, `automate-me`, `figure-it-out`, `how`, `interrogate`, `ketchup`, `maintain-verification-skill`, `no-comments`, `poteto-mode`, `recall`, `show-me-your-work`, `swarm`, `teach`) normalize `name`, preserve `description`, `disable-model-invocation`, and `paths:`, and prepend the concise `## Agent Workers runtime` preamble linking to [the adapter](../SKILL.md) (`poteto-mode` also leads with a 1-line worker guard so `poteto-agent` workers skip controller-only sections). Upstream plugin manifests and generated harness trees are excluded.

**Explicit-only skills (`disable-model-invocation: true` & Codex `agents/openai.yaml`):** All 56 upstream pstack skills retain `disable-model-invocation: true`, and `prepare_pstack.py` generates `agents/openai.yaml` (`policy.allow_implicit_invocation: false`) for each so Codex also excludes them from implicit model context. Only 5 skills remain implicitly visible across Pi, Claude Code, and Codex (`agent-workers`, `pstack-herdr`, `control-cli`, `control-ui`, `deslop`). `paths:` is preserved without translation. Receipt: [upstream-frontmatter.json](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/e2e/evidence/upstream-frontmatter.json).

## Resource and runtime mapping

| Original path / setting | Installed equivalent |
|---|---|
| `pstack/skills/<name>/` and relative links | Sibling `<name>/` dir; resolve scripts to absolute paths. |
| `pstack/agents/` | `pstack-herdr/references/agents/`; pass absolute paths in briefs. |
| `cursor-team-kit/skills/{control-cli,control-ui,deslop}/` | Sibling skill dirs with supporting files. |
| `interrogate/SKILL.md` + Arena phases | Inline adversarial brief, isolated writable worktrees, controller replay. |
| Upstream roles, model/effort defaults, `# defaults: 3` | `[roles]` and `[workers]` in `workers.toml` across all harnesses. |

See [pstack-herdr/SKILL.md](../SKILL.md) and [herdr-tools.md](herdr-tools.md) for mappings. Cursor modes, `/loop`, cloud agents, `/visualize`, and missing MCP/app tools remain unsupported unless the environment supplies equivalents; required unsupported steps stay unresolved. Bundling never installs script prerequisites (Bun, `gh`, `origin`, `jq`, `mise`/TLC/Java/`pele`).

**Verification:** 0.15.43 sync passed install, regeneration, and Pi 1.5.2 / Codex 0.169.1 catalog checks (60 entries, 584 files; [receipt](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/e2e/evidence/upstream-sync-0.15.43.json), [workflow review](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/e2e/PLAYBOOKS.md#workflow-review-for-pstack-01543)). 0.15.48 sync passed regeneration, install, and Pi 1.5.2 / Codex 0.172.0 catalog checks (61 entries, 651 files). Native Claude Code discovery and unexecuted playbooks (formal verification, `statechart` rendering, `ketchup-video`) remain runtime unverified.

## Maintainer updates

[Daily upstream check](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/.github/workflows/upstream.yml) compares `pstack/` and `cursor-team-kit/` against the pin without mutating installs.

1. Review upstream changes; update adapter mappings, `upstream.json`, exclusions, and README badge if needed.
2. Regenerate from a clean checkout at the reviewed revision (`python3 scripts/prepare_pstack.py --source /path/to/cursor-plugins --output /tmp/pstack-next`), replace bundled upstream dirs and generated agent/provenance files, and preserve local adapters. CI verifies `skills/` matches regeneration.
3. Run affected E2E checks, commit, append notes to [UPSTREAM-CHANGELOG.md](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/docs/UPSTREAM-CHANGELOG.md), and open a PR using the [upstream sync template](https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/.github/PULL_REQUEST_TEMPLATE/upstream-sync.md).
