#!/usr/bin/env python3
"""Verify agent-workers run --wait [--max-seconds] on an isolated herdr-core server."""

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

FIXTURE = r'''#!/usr/bin/env python3
import json, os, pathlib, re, select, sys, tty

if "--version" in sys.argv:
    print("pi run-wait-e2e-fixture 1")
    sys.exit(0)
if "--list-models" in sys.argv:
    print("provider model")
    sys.exit(0)

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=pi\x07").encode())

tty.setraw(0)
if "fail-startup" in sys.argv:
    report("blocked")
    while True:
        if select.select([0], [], [], 0.1)[0]:
            if not os.read(0, 4096):
                break
    sys.exit(0)

os.write(1, b"RUN_WAIT_E2E_READY\r\n")
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
        gate_match = re.search(r"^GATE=(.+)$", text, re.MULTILINE)
        report("working")
        if gate_match:
            gate = pathlib.Path(gate_match.group(1).strip())
            while not gate.exists():
                time_wait = select.select([], [], [], 0.05)
        result = brief.with_name("result.json")
        tmp = result.with_suffix(".new")
        tmp.write_text(json.dumps({
            "task_id": task_id,
            "nonce": nonce,
            "status": "completed",
            "summary": "run-wait ok",
            "files": [],
            "question": None,
        }))
        tmp.replace(result)
        report("idle")
'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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


def run_cli(horch, args, *, env, input_text=None, timeout=60):
    return subprocess.run(
        [sys.executable, str(horch), *args],
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def readline_timeout(stream, timeout):
    import select
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([stream], [], [], 0.1)
        if ready:
            return stream.readline()
    return ""


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
    scratch = Path(tempfile.mkdtemp(prefix="horch-run-wait-e2e-"))
    session = f"runwait-{os.getpid()}-{int(time.time())}"
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
    os.symlink(core_bin, bin_dir / "herdr-core")

    # Intentionally NO default workers.toml: only named profile workers.only-prof.toml
    (cfg_dir / "workers.only-prof.toml").write_text(
        'max_active_workers = 4\n'
        'notify_after_minutes = 180\n\n'
        '[workers.ok-w]\n'
        'harness = "pi"\n'
        'model = "ok-model"\n\n'
        '[workers.bad-w]\n'
        'harness = "pi"\n'
        'model = "fail-startup"\n',
        encoding="utf-8",
    )

    env = clean_env(scratch, bin_dir, session)
    cleanup_ok = False

    try:
        brief_plain = work_dir / "plain.md"
        brief_plain.write_text("# Simple task\nWrite result.json.\n", encoding="utf-8")

        # 1. Fail-closed CLI validation
        p_no_wait = run_cli(
            args.horch,
            ["run", "ok-w", "--brief", str(brief_plain), "--cwd", str(work_dir),
             "--profile", "only-prof", "--max-seconds", "5"],
            env=env,
        )
        check("reject_max_seconds_without_wait",
              p_no_wait.returncode == 1 and json.loads(p_no_wait.stdout)["error"] == "invalid_arguments")

        p_neg = run_cli(
            args.horch,
            ["run", "ok-w", "--brief", str(brief_plain), "--cwd", str(work_dir),
             "--profile", "only-prof", "--wait", "--max-seconds", "-1"],
            env=env,
        )
        check("reject_negative_max_seconds",
              p_neg.returncode == 1 and json.loads(p_neg.stdout)["error"] == "invalid_arguments")

        # 2. Parallel run --wait with real-time pipe flush before worker completes (no default workers.toml)
        gate_a = work_dir / "gate-a.release"
        gate_b = work_dir / "gate-b.release"
        brief_a = work_dir / "a.md"
        brief_b = work_dir / "b.md"
        brief_a.write_text(f"GATE={gate_a}\n", encoding="utf-8")
        brief_b.write_text(f"GATE={gate_b}\n", encoding="utf-8")

        proc_a = subprocess.Popen(
            [sys.executable, str(args.horch), "run", "ok-w", "--brief", str(brief_a),
             "--cwd", str(work_dir), "--profile", "only-prof", "--wait"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        proc_b = subprocess.Popen(
            [sys.executable, str(args.horch), "run", "ok-w", "--brief", str(brief_b),
             "--cwd", str(work_dir), "--profile", "only-prof", "--wait"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            line_a1 = readline_timeout(proc_a.stdout, 30)
            line_b1 = readline_timeout(proc_b.stdout, 30)
            launch_a = json.loads(line_a1) if line_a1.strip() else {}
            launch_b = json.loads(line_b1) if line_b1.strip() else {}
            still_waiting = proc_a.poll() is None and proc_b.poll() is None
            check("parallel_launch_lines_flushed_while_workers_running",
                  launch_a.get("state") == "running"
                  and launch_b.get("state") == "running"
                  and bool(launch_a.get("task_id"))
                  and bool(launch_b.get("task_id"))
                  and launch_a["task_id"] != launch_b["task_id"]
                  and still_waiting)

            gate_a.touch()
            gate_b.touch()
            rest_a, _ = proc_a.communicate(timeout=30)
            rest_b, _ = proc_b.communicate(timeout=30)
            done_a = json.loads(rest_a.strip()) if rest_a.strip() else {}
            done_b = json.loads(rest_b.strip()) if rest_b.strip() else {}
            check("parallel_run_wait_settled_and_closed",
                  proc_a.returncode == 0 and proc_b.returncode == 0
                  and done_a.get("task_id") == launch_a.get("task_id")
                  and done_a.get("state") == "done" and done_a.get("result_status") == "completed" and done_a.get("closed") is True
                  and done_b.get("task_id") == launch_b.get("task_id")
                  and done_b.get("state") == "done" and done_b.get("result_status") == "completed" and done_b.get("closed") is True)
        finally:
            for p in (proc_a, proc_b):
                if p.poll() is None:
                    p.kill()

        # 3. run --wait --max-seconds timeout does not cancel worker; follow-up wait delivers
        gate_t = work_dir / "gate-t.release"
        brief_t = work_dir / "t.md"
        brief_t.write_text(f"GATE={gate_t}\n", encoding="utf-8")
        p_timeout = run_cli(
            args.horch,
            ["run", "ok-w", "--brief", str(brief_t), "--cwd", str(work_dir),
             "--profile", "only-prof", "--wait", "--max-seconds", "1"],
            env=env,
        )
        t_lines = [json.loads(line) for line in p_timeout.stdout.splitlines() if line.strip()]
        check("run_wait_max_seconds_returns_running_without_cancelling",
              p_timeout.returncode == 0
              and len(t_lines) == 2
              and t_lines[0]["state"] == "running"
              and t_lines[1]["state"] == "running"
              and t_lines[1]["closed"] is False)
        gate_t.touch()
        p_followup = run_cli(
            args.horch,
            ["wait", "--profile", "only-prof", "--max-seconds", "30", t_lines[0]["task_id"]],
            env=env,
        )
        followup = json.loads(p_followup.stdout.strip()) if p_followup.stdout.strip() else {}
        check("followup_wait_after_timeout_delivers",
              p_followup.returncode == 0 and followup.get("state") == "done" and followup.get("closed") is True)

        # 4. start_failed returns immediately with 2 NDJSON lines (no hang)
        p_bad = run_cli(
            args.horch,
            ["run", "bad-w", "--brief", str(brief_plain), "--cwd", str(work_dir),
             "--profile", "only-prof", "--wait"],
            env=env,
            timeout=30,
        )
        bad_lines = [json.loads(line) for line in p_bad.stdout.splitlines() if line.strip()]
        check("run_wait_returns_immediately_on_start_failed",
              p_bad.returncode == 0
              and len(bad_lines) == 2
              and bad_lines[0]["state"] == "start_failed"
              and bad_lines[1]["state"] == "start_failed"
              and bad_lines[1]["submission"] == "not_sent"
              and bad_lines[1]["closed"] is False)
        p_close = run_cli(args.horch, ["close", bad_lines[0]["task_id"]], env=env)
        check("start_failed_task_closed_cleanly",
              p_close.returncode == 0 and json.loads(p_close.stdout)["closed"] is True)

        # 5. run --brief - --wait reads brief from stdin
        p_stdin = run_cli(
            args.horch,
            ["run", "ok-w", "--brief", "-", "--cwd", str(work_dir), "--profile", "only-prof", "--wait"],
            env=env,
            input_text="# Stdin brief\nWrite result.json.\n",
        )
        stdin_lines = [json.loads(line) for line in p_stdin.stdout.splitlines() if line.strip()]
        check("run_wait_with_stdin_brief",
              p_stdin.returncode == 0
              and len(stdin_lines) == 2
              and stdin_lines[1]["state"] == "done"
              and stdin_lines[1]["closed"] is True)

    finally:
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
        "rerun": shlex.join(["python3", "e2e/run_wait.py", "--output", "/tmp/horch-run-wait-proof"]),
        "checks": checks,
    }
    receipt = output_dir / "evidence.json"
    receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "passed": evidence["passed"], "total": evidence["total"], "receipt": str(receipt)}))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
