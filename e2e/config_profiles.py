#!/usr/bin/env python3
"""Verify multi-profile and --config support on an isolated herdr-core server."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


HORCH = Path(__file__).resolve().parents[1] / "skills/agent-workers/scripts/agent-workers.py"
CORE_BACKEND = Path(__file__).resolve().parents[1] / "skills/agent-workers/scripts/core_backend.py"

FIXTURE = r'''#!/usr/bin/env python3
import json, os, pathlib, re, select, sys, tty

if "--version" in sys.argv:
    print("pi profile-e2e-fixture 1")
    sys.exit(0)
if "--list-models" in sys.argv:
    print("provider model")
    sys.exit(0)

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=pi\x07").encode())

tty.setraw(0)
os.write(1, b"PROFILE_E2E_READY\r\n")
report("idle")
buf = b""
handled = False
while True:
    if not select.select([0], [], [], 0.05)[0]:
        continue
    chunk = os.read(0, 4096)
    if not chunk:
        break
    lines = re.split(rb"[\r\n]", buf + chunk)
    buf = lines.pop()
    for line in lines:
        match = re.search(rb"Read (/[^\x1b]+?/brief\.md) in full", line)
        if not match or handled:
            continue
        handled = True
        brief = pathlib.Path(os.fsdecode(match.group(1)))
        text = brief.read_text()
        task_id = re.search(r'"task_id"\s*:\s*"([^"]+)"', text).group(1)
        nonce = re.search(r'"nonce"\s*:\s*"([^"]+)"', text).group(1)
        report("working")
        info = {
            "argv": sys.argv[1:],
            "leaked_env": sorted(k for k in os.environ if k.startswith("AGENT_WORKERS_")),
        }
        (brief.with_name("probe.json")).write_text(json.dumps(info))
        result = brief.with_name("result.json")
        tmp = result.with_suffix(".new")
        tmp.write_text(json.dumps({
            "task_id": task_id,
            "nonce": nonce,
            "status": "completed",
            "summary": "check ok",
            "files": ["probe.json"],
            "question": None,
        }))
        tmp.replace(result)
        report("idle")
'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_cli(horch, args, *, env, cwd=None, timeout=60):
    return subprocess.run(
        [sys.executable, str(horch), *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_json_lines(stdout):
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def clean_env(root, bin_dir, session):
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("HERDR", "HC_", "REX_", "ANTIGRAVITY_", "AGENT_WORKERS_"))
        and k not in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "PI_SESSION_ID", "CLAUDECODE")
    }
    env["PATH"] = f"{bin_dir}:{os.environ.get('PATH', os.defpath)}"
    env["XDG_CONFIG_HOME"] = str(root / "config")
    env["XDG_STATE_HOME"] = str(root / "state")
    env["XDG_RUNTIME_DIR"] = str(root / "run")
    env["HC_SESSION"] = session
    env["HC_SOCKET"] = str(root / "run" / f"{session}.sock")
    return env


def write_toml(path, workers, roles, max_active=4, notify=180):
    lines = [
        f"max_active_workers = {max_active}",
        f"notify_after_minutes = {notify}",
        "",
    ]
    for name, spec in workers.items():
        lines.append(f"[workers.{name}]")
        for key, value in spec.items():
            lines.append(f"{key} = {json.dumps(value)}")
        lines.append("")
    if roles:
        lines.append("[roles]")
        for role, target in roles.items():
            lines.append(f"{json.dumps(role)} = {json.dumps(target)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horch", type=Path, default=HORCH, help="Path to agent-workers.py")
    parser.add_argument("--output", type=Path, required=True, help="Output directory for evidence.json")
    args = parser.parse_args()

    core_bin = shutil.which("herdr-core")
    if not core_bin:
        print(json.dumps({"verdict": "FAIL", "error": "herdr-core binary not found on PATH"}))
        return 1

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="horch-profiles-e2e-"))
    session = f"profiles-{os.getpid()}-{int(time.time())}"
    checks = []

    def check(name, ok, detail=None):
        entry = {"name": name, "ok": bool(ok)}
        if detail is not None:
            entry["detail"] = detail
        checks.append(entry)

    bin_dir = scratch / "bin"
    cfg_dir = scratch / "config" / "herdr-orchestrator"
    run_dir = scratch / "run"
    work_dir = scratch / "work"
    for d in (bin_dir, cfg_dir, run_dir, work_dir):
        d.mkdir(parents=True, exist_ok=True)

    pi_fixture = bin_dir / "pi"
    pi_fixture.write_text(FIXTURE, encoding="utf-8")
    pi_fixture.chmod(0o755)
    # Symlink real herdr-core into bin_dir so PATH resolution finds it deterministically
    os.symlink(core_bin, bin_dir / "herdr-core")

    default_cfg = cfg_dir / "workers.toml"
    gpt_cfg = cfg_dir / "workers.gpt.toml"
    nogpt_cfg = cfg_dir / "workers.no-gpt.toml"
    custom_cfg = work_dir / "custom-workers.toml"

    write_toml(
        default_cfg,
        {"default-w": {"harness": "pi", "model": "default-model"}},
        {"impl": "default-w"},
    )
    write_toml(
        gpt_cfg,
        {"coder": {"harness": "pi", "model": "gpt-model", "effort": "high"}},
        {"impl": "coder"},
        max_active=4,
    )
    write_toml(
        nogpt_cfg,
        {
            "coder": {"harness": "pi", "model": "claude-model", "effort": "medium"},
            "alt": {"harness": "pi", "model": "alt-model"},
        },
        {"impl": "coder", "review": "alt"},
        max_active=4,
    )
    write_toml(
        custom_cfg,
        {"custom-w": {"harness": "pi", "model": "custom-model"}},
        {"impl": "custom-w"},
    )
    # Noise files that detect must ignore
    (cfg_dir / "workers.Bad_Name.toml").write_text("max_active_workers = 1\n")
    (cfg_dir / "workers..toml").write_text("max_active_workers = 1\n")
    (cfg_dir / "workers.gpt.toml.bak").write_text("max_active_workers = 1\n")
    (cfg_dir / "workers.dir.toml").mkdir()

    env = clean_env(scratch, bin_dir, session)
    cleanup_ok = False

    try:
        # 1. detect discovery and filtering
        p = run_cli(args.horch, ["detect"], env=env)
        det = json.loads(p.stdout)
        check("detect_default_profiles",
              p.returncode == 0
              and det["config"]["profile"] is None
              and det["config"]["exists"] is True
              and det["config"]["profiles"] == ["gpt", "no-gpt"]
              and det["config"]["path"].endswith("workers.toml"))

        p = run_cli(args.horch, ["detect", "--profile", "gpt"], env=env)
        det_gpt = json.loads(p.stdout)
        check("detect_named_profile",
              p.returncode == 0
              and det_gpt["config"]["profile"] == "gpt"
              and det_gpt["config"]["exists"] is True
              and det_gpt["config"]["path"].endswith("workers.gpt.toml"))

        p = run_cli(args.horch, ["detect", "--profile", "missing"], env=env)
        det_miss = json.loads(p.stdout)
        check("detect_missing_profile_nonfatal",
              p.returncode == 0
              and det_miss["config"]["profile"] == "missing"
              and det_miss["config"]["exists"] is False
              and det_miss["config"]["profiles"] == ["gpt", "no-gpt"])

        # Unreadable config dir must not crash detect
        cfg_dir.chmod(0o000)
        try:
            p = run_cli(args.horch, ["detect"], env=env)
            det_perm = json.loads(p.stdout)
            check("detect_unreadable_dir_safe",
                  p.returncode == 0
                  and det_perm["config"]["exists"] is False
                  and det_perm["config"]["profiles"] is None)
        finally:
            cfg_dir.chmod(0o755)

        # 2. Fail-closed validation & precedence
        p = run_cli(args.horch, ["roles", "--profile", "../etc"], env=env)
        err = json.loads(p.stdout)
        check("reject_path_traversal",
              p.returncode == 1 and err["error"] == "config_invalid" and "sandbox" not in err["message"])

        p_empty_prof = run_cli(args.horch, ["roles", "--profile", ""], env=env)
        p_empty_cfg = run_cli(args.horch, ["roles", "--config", ""], env=env)
        check("reject_empty_cli_flags",
              p_empty_prof.returncode == 1 and json.loads(p_empty_prof.stdout)["error"] == "config_invalid"
              and p_empty_cfg.returncode == 1 and json.loads(p_empty_cfg.stdout)["error"] == "config_invalid")

        p_mutex = run_cli(args.horch, ["roles", "--profile", "gpt", "--config", str(custom_cfg)], env=env)
        check("reject_mutually_exclusive_cli", p_mutex.returncode == 2)

        conflict_env = dict(env, AGENT_WORKERS_PROFILE="gpt", AGENT_WORKERS_CONFIG=str(custom_cfg))
        p_conflict = run_cli(args.horch, ["roles"], env=conflict_env)
        check("reject_conflicting_env_vars",
              p_conflict.returncode == 1 and json.loads(p_conflict.stdout)["error"] == "config_invalid")

        p_override_prof = run_cli(args.horch, ["roles", "impl", "--profile", "no-gpt"], env=conflict_env)
        r_override_prof = json.loads(p_override_prof.stdout)
        check("cli_profile_overrides_conflicting_env",
              p_override_prof.returncode == 0
              and r_override_prof["profile"] == "no-gpt"
              and r_override_prof["workers"][0]["model"] == "claude-model")

        p_override_cfg = run_cli(
            args.horch, ["roles", "impl", "--config", "./custom-workers.toml"], env=conflict_env, cwd=work_dir
        )
        r_override_cfg = json.loads(p_override_cfg.stdout)
        check("cli_relative_config_overrides_conflicting_env",
              p_override_cfg.returncode == 0
              and r_override_cfg["profile"] is None
              and r_override_cfg["config_path"] == str(custom_cfg.resolve())
              and r_override_cfg["workers"][0]["model"] == "custom-model")

        p_env_prof = run_cli(args.horch, ["roles", "impl"], env=dict(env, AGENT_WORKERS_PROFILE="gpt"))
        check("env_profile_resolves",
              p_env_prof.returncode == 0
              and json.loads(p_env_prof.stdout)["workers"][0]["model"] == "gpt-model")

        p_env_empty = run_cli(args.horch, ["roles", "impl"], env=dict(env, AGENT_WORKERS_PROFILE=""))
        check("empty_env_falls_back_to_default",
              p_env_empty.returncode == 0
              and json.loads(p_env_empty.stdout)["workers"][0]["model"] == "default-model")

        p_miss = run_cli(args.horch, ["roles", "--profile", "missing"], env=env)
        err_miss = json.loads(p_miss.stdout)
        check("missing_profile_lists_available_and_sandbox_hint",
              p_miss.returncode == 1
              and err_miss["error"] == "config_invalid"
              and "gpt, no-gpt" in err_miss["message"]
              and "outside the sandbox" in err_miss["message"])

        # 3. Real concurrent dispatch across profiles + relative --config on isolated herdr-core
        brief = work_dir / "brief.md"
        brief.write_text("# Profile probe\nWrite result.json.\n", encoding="utf-8")

        run_a = run_cli(
            args.horch, ["run", "coder", "--brief", str(brief), "--cwd", str(work_dir), "--profile", "gpt"],
            env=dict(env, AGENT_WORKERS_PROFILE="no-gpt", AGENT_WORKERS_CONFIG=""),
        )
        run_b = run_cli(
            args.horch, ["run", "coder", "--brief", str(brief), "--cwd", str(work_dir), "--profile", "no-gpt"],
            env=env,
        )
        run_c = run_cli(
            args.horch,
            ["run", "custom-w", "--brief", str(brief), "--cwd", str(work_dir), "--config", "./custom-workers.toml"],
            env=env,
            cwd=work_dir,
        )
        check("all_three_runs_started", run_a.returncode == run_b.returncode == run_c.returncode == 0)
        ta, tb, tc = json.loads(run_a.stdout), json.loads(run_b.stdout), json.loads(run_c.stdout)

        wait_p = run_cli(
            args.horch,
            ["wait", "--all", "--profile", "gpt", "--max-seconds", "30", ta["task_id"], tb["task_id"], tc["task_id"]],
            env=env,
        )
        wait_rows = parse_json_lines(wait_p.stdout)
        check("all_three_tasks_delivered_and_closed",
              wait_p.returncode == 0
              and len(wait_rows) == 3
              and all(r["state"] == "done" and r["result_status"] == "completed" and r["closed"] for r in wait_rows))

        probe_a = json.loads((Path(ta["task_dir"]) / "probe.json").read_text())
        probe_b = json.loads((Path(tb["task_dir"]) / "probe.json").read_text())
        probe_c = json.loads((Path(tc["task_dir"]) / "probe.json").read_text())
        check("distinct_models_launched_per_profile",
              "gpt-model" in probe_a["argv"]
              and "claude-model" in probe_b["argv"]
              and "custom-model" in probe_c["argv"])
        check("worker_env_scrubbed_of_agent_workers_vars",
              probe_a["leaked_env"] == [] and probe_b["leaked_env"] == [] and probe_c["leaked_env"] == [])

        # Verify list --verbose provenance
        list_p = run_cli(args.horch, ["list", "--verbose"], env=env)
        by_id = {row["task_id"]: row for row in parse_json_lines(list_p.stdout)}
        check("list_verbose_records_profile_and_config_path",
              list_p.returncode == 0
              and by_id[ta["task_id"]]["profile"] == "gpt"
              and by_id[ta["task_id"]]["config_path"].endswith("workers.gpt.toml")
              and by_id[tb["task_id"]]["profile"] == "no-gpt"
              and by_id[tb["task_id"]]["config_path"].endswith("workers.no-gpt.toml")
              and by_id[tc["task_id"]]["profile"] is None
              and by_id[tc["task_id"]]["config_path"] == str(custom_cfg.resolve()))

        # Verify stats with --profile
        st_gpt = json.loads(run_cli(args.horch, ["stats", "--profile", "gpt", "--no-samples"], env=env).stdout)
        st_nogpt = json.loads(run_cli(args.horch, ["stats", "--profile", "no-gpt", "--no-samples"], env=env).stdout)
        check("stats_echoes_profile_and_reference_config",
              st_gpt["profile"] == "gpt"
              and st_gpt["workers"]["coder"]["model"] == "gpt-model"
              and "alt" not in st_gpt["workers"]
              and st_nogpt["profile"] == "no-gpt"
              and st_nogpt["workers"]["coder"]["model"] == "claude-model"
              and st_nogpt["workers"]["alt"]["configured"] is True)

        # Verify check with --profile
        chk_p = run_cli(
            args.horch, ["check", "alt", "--profile", "no-gpt", "--cwd", str(work_dir), "--max-seconds", "30"],
            env=env,
        )
        chk_rows = parse_json_lines(chk_p.stdout)
        check("check_with_profile_succeeds",
              chk_p.returncode == 0 and len(chk_rows) == 1 and chk_rows[0]["worker"] == "alt" and chk_rows[0]["ok"])

    finally:
        # Stop isolated herdr-core server and clean up scratch
        stop = subprocess.run([core_bin, "server", "stop"], env=env, capture_output=True, text=True, timeout=15)
        cleanup_ok = stop.returncode == 0 or not (run_dir / f"{session}.sock").exists()
        shutil.rmtree(scratch, ignore_errors=True)

    check("isolated_core_cleanup", cleanup_ok)
    verdict = "PASS" if all(c["ok"] for c in checks) else "FAIL"
    evidence = {
        "verdict": verdict,
        "passed": sum(c["ok"] for c in checks),
        "total": len(checks),
        "horch_sha256": sha256(args.horch),
        "core_backend_sha256": sha256(CORE_BACKEND),
        "rerun": shlex.join(["python3", "e2e/config_profiles.py", "--output", "/tmp/horch-profiles-proof"]),
        "checks": checks,
    }
    receipt = output_dir / "evidence.json"
    receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "passed": evidence["passed"], "total": evidence["total"], "receipt": str(receipt)}))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
