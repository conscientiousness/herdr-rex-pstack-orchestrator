# Skill installation and discovery

## Sub-features

Install the committed `skills/` bundle into a disposable project, delete the temporary source copy, and verify installed file hashes, Claude Code links, explicit-only `agents/openai.yaml` policies, and live Pi and Codex skill catalogs. Complete project removal has a separate [adoption procedure](../../../../e2e/ADOPTION.md#verify-complete-project-removal).

## How to get to it (user POV)

Users run the [bundle install command](../../../../skills/pstack-adapter/references/compatibility.md#install) with no separate upstream checkout. This procedure tests the local `skills/` tree in a disposable directory without touching global installs.

## Driving it with existing scripts

Doctor: check `python3 --version`, `npx --version`, `npx --yes skills@latest --version`, `pi --version`, and `codex --version`. No Herdr, Rex, or model authentication is needed.

```bash
scratch=$(mktemp -d "${TMPDIR:-/tmp}/herdr-install-XXXXXXXX")
mkdir "$scratch/consumer"
cp -R skills "$scratch/source"
(cd "$scratch/consumer" && npx --yes skills@latest add \
  "$scratch/source" -s '*' -a codex -a claude-code -a pi -a antigravity-cli -y) \
  > "$proof/install.log" 2>&1
```

After installation succeeds, remove the temporary source copy and verify the installed bundle:

```bash
rm -rf "$scratch/source"
python3 e2e/skill_catalogs.py "$scratch/consumer" > "$proof/catalog-result.json"
cat "$proof/catalog-result.json"
```

Read the printed `evidence` JSON path. Require `verdict: "pass"`, `all_files_preserved`, `claude_entries`, `explicit_only_openai_policy` (all 56 explicit-only skills carry `agents/openai.yaml` with `allow_implicit_invocation: false`), `pi_catalog`, `codex_catalog`, and `codex_no_errors`. Use `--installation-only` when Pi and Codex CLIs are absent (as in CI).

For a remote-install check, pass the GitHub `tree/<commit>/skills` URL in place of `$scratch/source` and record the commit with the receipt.

After all subprocesses exit, remove `$scratch` and reopen the receipt at its printed path outside `$scratch`.

## Gotchas

- Do not install globally for this check.
- Never create `.agents/skills` in a shared temporary ancestor, because even an empty folder triggers Pi trust dialogs for child worktrees.
- `skill_catalogs.py` writes to its own temporary directory and has no `--output` flag.
- This proves portable installation and Pi/Codex catalog discovery, not model execution or native Claude Code runtime discovery.
