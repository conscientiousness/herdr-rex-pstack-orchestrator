#!/usr/bin/env python3
"""Cold-start agent migration of old skill names, following docs/MIGRATE.md.

Builds a project scope with the pre-rename bundle (pstack-herdr) plus an
unrelated skill, and an isolated global scope (fake HOME) with the old
herdr-orchestrator core skill. A fresh Claude Code session with no prior
context is told only to follow MIGRATE.md. The checks then inspect both
scopes, the agent links, the unrelated skill, and workers.toml.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
OLD_BUNDLE = "d772e90"  # last main revision with pstack-herdr
OLD_CORE = "88533b5^"  # last revision with herdr-orchestrator
GUIDE = "https://github.com/conscientiousness/herdr-rex-pstack-orchestrator/blob/main/docs/MIGRATE.md"
OLD = {"pstack-herdr", "herdr-orchestrator"}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout


def listing(env, cwd, scope):
    out = run(["npx", "--yes", "skills@latest", "ls", "--json", *(["-g"] if scope == "global" else [])],
              cwd=cwd, env=env)
    return {s["name"]: sorted(s["agents"]) for s in json.loads(out)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--keep", action="store_true", help="keep the scratch directory")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="migration-"))
    home, project = work / "home", work / "project"
    home.mkdir()
    project.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude/.credentials.json").symlink_to(Path.home() / ".claude/.credentials.json")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "AGENT_WORKERS_", "CLAUDE"))}
    env.update(HOME=str(home), DISABLE_TELEMETRY="1")

    checkouts = {}
    for name, rev in (("bundle", OLD_BUNDLE), ("core", OLD_CORE)):
        checkouts[name] = work / f"old-{name}"
        run(["git", "-C", ROOT, "worktree", "add", "--detach", checkouts[name], rev])
    try:
        unrelated = work / "unrelated/skills/house-style"
        unrelated.mkdir(parents=True)
        (unrelated / "SKILL.md").write_text(
            "---\nname: house-style\ndescription: Unrelated project skill that must survive.\n---\n\nKeep it.\n")
        run(["git", "init", "-q"], cwd=project)
        npx = ["npx", "--yes", "skills@latest", "add"]
        run([*npx, checkouts["bundle"] / "skills", "-s", "*", "-a", "claude-code", "-a", "codex", "-y"],
            cwd=project, env=env)
        run([*npx, unrelated.parent, "-s", "house-style", "-a", "claude-code", "-a", "codex", "-y"],
            cwd=project, env=env)
        run([*npx, checkouts["core"] / "skills", "-s", "herdr-orchestrator", "-g",
             "-a", "claude-code", "-a", "pi", "-y"], cwd=project, env=env)
        config = home / ".config/herdr-orchestrator/workers.toml"
        config.parent.mkdir(parents=True)
        shutil.copy(ROOT / "skills/agent-workers/references/workers.example.toml", config)
        config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
        before = {s: listing(env, project, s) for s in ("project", "global")}

        prompt = f"Follow {GUIDE} to migrate my installation. Report what you changed."
        started = time.time()
        agent = subprocess.run(
            ["claude", "-p", prompt, "--model", args.model, "--permission-mode", "bypassPermissions",
             "--output-format", "json"],
            cwd=project, env=env, text=True, capture_output=True, timeout=1800)
        duration = round(time.time() - started)
        try:
            result = json.loads(agent.stdout)
        except json.JSONDecodeError:
            result = {"result": agent.stdout[-2000:], "is_error": True}

        after = {s: listing(env, project, s) for s in ("project", "global")}
        proj, glob = after["project"], after["global"]
        leftover_dirs = [str(p.relative_to(work)) for base in (project, home)
                         for d in (".agents/skills", ".claude/skills", ".codex/skills", ".pi/agent/skills")
                         for p in (base / d).glob("*") if p.name in OLD]
        checks = {
            "agent_exit_zero": agent.returncode == 0 and not result.get("is_error"),
            "setup_had_old_names": "pstack-herdr" in before["project"] and "herdr-orchestrator" in before["global"],
            "project_old_names_removed": not OLD & proj.keys(),
            "global_old_names_removed": not OLD & glob.keys(),
            "no_old_directories_left": not leftover_dirs,
            "project_bundle_current": {"agent-workers", "pstack-adapter", "poteto-mode"} <= proj.keys(),
            "project_agents_kept": all(set(before["project"]["pstack-herdr"]) <= set(proj.get(n, []))
                                       for n in ("agent-workers", "pstack-adapter")),
            "global_core_current": "agent-workers" in glob,
            "global_agents_kept": set(before["global"]["herdr-orchestrator"]) <= set(glob.get("agent-workers", [])),
            "global_stays_core_only": "pstack-adapter" not in glob,
            "unrelated_skill_kept": "house-style" in proj,
            "workers_toml_unchanged": hashlib.sha256(config.read_bytes()).hexdigest() == config_sha,
            "new_adapter_has_cleanup_rule": "## Finish a workflow" in
                (project / ".agents/skills/pstack-adapter/SKILL.md").read_text()
                if (project / ".agents/skills/pstack-adapter/SKILL.md").exists() else False,
        }
        evidence = {
            "scenario": "cold-start agent migration via docs/MIGRATE.md",
            "verdict": "pass" if all(checks.values()) else "fail",
            "checks": checks,
            "model": args.model,
            "agent": "claude-code " + run(["claude", "--version"]).split()[0],
            "duration_seconds": duration,
            "old_revisions": {"bundle": OLD_BUNDLE, "core": OLD_CORE},
            "guide": GUIDE,
            "before": before,
            "after": after,
            "leftover_dirs": leftover_dirs,
            "agent_report": result.get("result", "")[-4000:]
                .replace(str(work), "<work>").replace(str(Path.home()), "~"),
        }
        out = ROOT / "e2e/evidence/migration.json"
        out.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"verdict": evidence["verdict"], "checks": checks, "evidence": str(out)}, indent=2))
    finally:
        for path in checkouts.values():
            subprocess.run(["git", "-C", ROOT, "worktree", "remove", "--force", path], capture_output=True)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("kept", work)


if __name__ == "__main__":
    main()
