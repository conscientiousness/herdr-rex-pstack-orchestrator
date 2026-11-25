# Ketchup, Ketchup-video, and Visuals mapping

Read this guide only when running `ketchup`, `ketchup-video`, or reply-visual steps.

## Progress recap (`ketchup`)

- Check PR and CI status with read-only commands from the workflow's resolved forge (`origin` when usable, otherwise `gh`).
- Inspect worker state with `agent-workers list --active` (or `list --verbose` for full stored backend bindings), then use the [recorded terminal inspection commands](../../../agent-workers/references/lifecycle.md#problem-recovery). Use accessible reports for completed tasks and disclose unavailable live checks.
- Embed existing screenshots or videos when applicable and draw explanatory reply visuals only from existing evidence.
- Keep status and action items in plain bullets, following sibling `ketchup/SKILL.md`.
- **Read-only boundary:** Do not run `agent-workers wait`, dispatch workers, or modify or close tasks and panes.

## Video recap (`ketchup-video`)

- Follow sibling `ketchup` read-only forge, worker-status, and evidence rules.
- The single write exception is creating and rendering the silent subtitled video **outside the repository**.
- Retain upstream subtitle-strip, measured hold-time, and rendered-frame inspection requirements.
- Use available harness/system video rendering and embedding tools; this adapter supplies neither. If rendering or embedding is unavailable or fails, disclose the gap in one line and return only the waiting calls, per upstream fallback.
- Do not change worker tasks, panes, or project files.

## Reply visuals and `/visualize`

- Use supported Mermaid rendering or available chart/image tools strictly from existing evidence within the skill's read-only constraints.
- `/visualize` is not bundled. A Markdown table is not a picture.
- When `ketchup` calls for a visual to explain a change or compare choices, disclose unavailable artifacts or rendering capabilities instead of claiming they were produced.
