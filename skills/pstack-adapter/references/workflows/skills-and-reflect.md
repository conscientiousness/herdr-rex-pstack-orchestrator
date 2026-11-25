# Reflect, Skill authoring, and Eval mapping

Read this guide only when running `reflect`, `Authoring a skill`, `Eval`, or skill-maintenance workflows (`create-verification-skill`, `maintain-verification-skill`).

## Approved skill edits from `reflect`

- Before requesting approval, show the destination path inside the active harness's discovered project or user skills directory.
- After explicit user approval, copy the target skill folder there and edit the copy. Never edit `plugins/cache/`.
- Retain the upstream instruction against opening a PR or pushing (user and project instructions still take precedence).
- Use only an available, authorized backlog tracker.

## Skill discovery, creation, and maintenance

- **Cursor's built-in `create-skill`:** Use the current harness's skill-authoring guidance and write project skills to that harness's discovered skills directory.
- **Paths under `.cursor/skills/` or `~/.cursor/skills/`:** Resolve project and personal locations through the active harness's discovered skill directories. Preserve the user's chosen scope: personal installs stay in the user's skill directory, PR delivery applies only to project changes, and generated skills stay separate from this bundle.

## Blinded Eval

- Keep role/worker routing metadata in the controller's private record, never in candidate briefs.
- Give candidates the exact same organic task and neutral paths; give the judge sanitized output labels and the hidden rubric.
- Verify which files, skill names, and model identities are visible before dispatch. If the available harness or configured roles break blinding, report that gap explicitly.
