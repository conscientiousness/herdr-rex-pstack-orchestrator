#!/usr/bin/env python3
"""Build the committed skills bundle from a reviewed original pstack checkout."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


ADAPTER = Path(__file__).resolve().parents[1] / "skills/pstack-adapter"
OPENAI_POLICY = "policy:\n  allow_implicit_invocation: false\n"
RUNTIME_PREAMBLE = (
    "## Agent Workers runtime\n\n"
    "Read [pstack-adapter](../pstack-adapter/SKILL.md) first (overrides upstream tools, "
    "model defaults, setup, and Cursor paths). Resolve siblings via `../<name>/SKILL.md` "
    "and relative paths from this folder. Delegate only via `agent-workers` + `workers.toml`; "
    "no nested workers. User/project rules win; keep unavailable steps unresolved.\n"
)
POTETO_WORKER_GUARD = (
    "**Worker guard:** If you are a worker running from a `brief.md`, skip this runtime "
    "section and the Subagents/Playbooks sections; follow only Non-negotiables and Principles.\n\n"
)


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def split_frontmatter(text, path):
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"Missing frontmatter: {path}")
    return parts[1], parts[2]


def frontmatter_field(frontmatter, key):
    return re.search(rf"^{re.escape(key)}:.*(?:\n[ \t]+[^\n]*)*", frontmatter, re.MULTILINE)


def has_disable_model_invocation(text, path):
    frontmatter, _ = split_frontmatter(text, path)
    return bool(re.search(r"^disable-model-invocation:\s*true\s*$", frontmatter, re.MULTILINE))


def skill_preamble(name):
    if name == "poteto-mode":
        body = RUNTIME_PREAMBLE.removeprefix("## Agent Workers runtime\n\n")
        return "## Agent Workers runtime\n\n" + POTETO_WORKER_GUARD + body
    return RUNTIME_PREAMBLE


def portable_skill(path, preamble):
    frontmatter, body = split_frontmatter(path.read_text(), path)
    match = frontmatter_field(frontmatter, "description")
    if not match:
        raise ValueError(f"Missing description: {path}")
    lines = [f"name: {path.parent.name}", match.group()]
    for key in ("paths", "disable-model-invocation"):
        field = frontmatter_field(frontmatter, key)
        if field:
            lines.append(field.group())
    header = "---\n" + "\n".join(lines) + "\n---"
    return header + ("\n\n" + preamble if preamble else "") + body


def prepare(source, output):
    manifest = json.loads((ADAPTER / "references/upstream.json").read_text())
    if git(source, "rev-parse", "HEAD") != manifest["revision"]:
        raise ValueError("Source revision differs from references/upstream.json")
    if git(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Source checkout has local changes; preserve them and use a clean checkout")
    metadata = json.loads((source / "pstack/.cursor-plugin/plugin.json").read_text())
    if metadata["version"] != manifest["version"]:
        raise ValueError("Source version differs from references/upstream.json")
    if output.exists():
        raise ValueError("Output already exists; use a new directory and inspect before reinstalling")

    original = list(sorted((source / "pstack/skills").glob("*/SKILL.md")))
    excluded = manifest["excluded_skills"]
    if not set(excluded) <= {path.parent.name for path in original}:
        raise ValueError("Excluded skill missing from the pinned source")
    selected = [path for path in original if path.parent.name not in excluded]
    selected += [source / "cursor-team-kit/skills" / name / "SKILL.md"
                 for name in manifest["team_kit_skills"]]
    adapted = set(manifest["adapted_skills"])
    names = [path.parent.name for path in selected]
    if len(names) != len(set(names)) or not adapted <= set(names):
        raise ValueError("Duplicate skill name or missing adapted skill in source")

    entries = []
    for path in selected:
        name = path.parent.name
        preamble = skill_preamble(name) if name in adapted else ""
        entries.append((path, portable_skill(path, preamble) if preamble else None))

    for name in ("agent-workers", "pstack-adapter"):
        if not (ADAPTER.parent / name / "SKILL.md").is_file():
            raise ValueError(f"Missing local adapter: skills/{name}/SKILL.md")

    output.mkdir(parents=True)
    records = []
    explicit_only = 0
    for path, content in entries:
        target = output / "skills" / path.parent.name
        shutil.copytree(path.parent, target)
        if content is not None:
            (target / "SKILL.md").write_text(content)
        skill_md = target / "SKILL.md"
        if has_disable_model_invocation(skill_md.read_text(), skill_md):
            openai_yaml = target / "agents/openai.yaml"
            if openai_yaml.exists() and openai_yaml.read_text() != OPENAI_POLICY:
                raise ValueError(f"Conflicting upstream openai.yaml: {path.parent.name}")
            openai_yaml.parent.mkdir(parents=True, exist_ok=True)
            openai_yaml.write_text(OPENAI_POLICY)
            explicit_only += 1
        group = path.relative_to(source).parts[0]
        shutil.copyfile(source / group / "LICENSE", target / "UPSTREAM-LICENSE.txt")
        records.append({"name": path.parent.name, "adapted": content is not None,
                        "source": path.relative_to(source).as_posix(),
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in ("agent-workers", "pstack-adapter"):
        shutil.copytree(ADAPTER.parent / name, output / "skills" / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    resources = output / "skills/pstack-adapter/references/agents"
    if resources.exists():
        shutil.rmtree(resources)
    shutil.copytree(source / "pstack/agents", resources)
    shutil.copyfile(source / "pstack/LICENSE", resources / "UPSTREAM-LICENSE.txt")
    receipt = {"repository": manifest["repository"], "revision": manifest["revision"],
               "version": manifest["version"], "excluded_skills": excluded,
               "skills": records,
               "agents": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted((source / "pstack/agents").glob("*.md"))}}
    (output / "skills/pstack-adapter/references/bundle.json").write_text(
        json.dumps(receipt, indent=2) + "\n")
    return {"output": str(output), "upstream_skills": len(records),
            "adapted_skills": sum(row["adapted"] for row in records),
            "explicit_only_skills": explicit_only,
            "companion_skills": 2, "revision": manifest["revision"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Maintainer-only clean pinned cursor/plugins checkout")
    parser.add_argument("--output", type=Path, required=True, help="New local skill package directory")
    args = parser.parse_args()
    try:
        result = prepare(args.source.expanduser().resolve(), args.output.expanduser().resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"prepare failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
