#!/usr/bin/env python3
"""Verify restricted result_file fallback (native_status=null) and result_verdict diagnostics on isolated herdr-core."""

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
    print("agy fallback-e2e-fixture 1")
    sys.exit(0)

def osc(payload):
    os.write(1, ("\x1b]7501;" + payload + "\x07").encode())

tty.setraw(0)
os.write(1, b"FALLBACK_E2E_READY\r\n")
osc("state=idle:app=agy")
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
        mode = re.search(r"^MODE=(\w+)$", text, re.MULTILINE).group(1)
        gate_match = re.search(r"^GATE=(.+)$", text, re.MULTILINE)
        osc("state=working:app=agy")
        (brief.with_name("report.md")).write_text("report ok\n", encoding="utf-8")
        result = brief.with_name("result.json")
        tmp = result.with_suffix(".new")
        tmp.write_text(json.dumps({
            "task_id": task_id,
            "nonce": nonce,
            "status": "completed",
            "summary": f"done via {mode}",
            "files": ["report.md"],
            "question": None,
        }))
        tmp.replace(result)
        if mode == "clear_status":
            # Clear OSC 7501 status so native_status becomes null while process stays live
            osc("state=clear:app=agy")
            osc("")
        if gate_match:
            gate = pathlib.Path(gate_match.group(1).strip())
            while not gate.exists():
                select.select([], [], [], 0.05)
        if mode == "working_then_idle":
            osc("state=idle:app=agy")
'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_cli(horch, args, *, env, timeout=60):
    return subprocess.run(
        [sys.executable, str(horch), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horch", type=Path, default=HORCH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    core_bin = shutil.which("herdr-core")
    if not core_bin:
        print(json.dumps({"verdict": "FAIL", "error": "herdr-core binary not found on PATH"}))
        return 1

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="horch-fallback-e2e-"))
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

    (bin_dir / "agy").write_text(FIXTURE, encoding="utf-8")
    (bin_dir / "agy").chmod(0o755)
    os.symlink(core_bin, bin_dir / "herdr-core")

    (cfg_dir / "workers.toml").write_text(
        'max_active_workers = 4\n'
        'notify_after_minutes = 180\n\n'
        '[workers.agy-w]\n'
        'harness = "agy"\n'
        'model = "gemini-4-neon"\n',
        encoding="utf-8",
    )

    session = f"fallback-{os.getpid()}-{int(time.time())}"
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("HERDR", "HC_", "REX_", "ANTIGRAVITY_", "AGENT_WORKERS_"))
        and k not in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "PI_SESSION_ID", "CLAUDECODE")
    }
    env.update(
        PATH=f"{bin_dir}:{os.environ.get('PATH', os.defpath)}",
        XDG_CONFIG_HOME=str(scratch / "config"),
        XDG_STATE_HOME=str(scratch / "state"),
        XDG_RUNTIME_DIR=str(run_dir),
        HC_SESSION=session,
        HC_SOCKET=str(run_dir / f"{session}.sock"),
    )

    cleanup_ok = False
    try:
        # 1. Early valid result while native_status == 'working' must NOT settle, even with old mtime
        gate1 = work_dir / "gate1.release"
        brief1 = work_dir / "brief1.md"
        brief1.write_text(f"MODE=working_then_idle\nGATE={gate1}\n", encoding="utf-8")
        r1 = json.loads(run_cli(args.horch, ["run", "agy-w", "--brief", str(brief1), "--cwd", str(work_dir)], env=env).stdout)
        t1_dir = Path(r1["task_dir"])
        deadline = time.monotonic() + 10
        while not (t1_dir / "result.json").is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        old = time.time() - 60
        os.utime(t1_dir / "result.json", (old, old))
        os.utime(t1_dir / "report.md", (old, old))

        w1_early = json.loads(run_cli(args.horch, ["wait", "--max-seconds", "1", r1["task_id"]], env=env).stdout.strip())
        check("early_result_while_working_withheld_with_diagnostic_verdict",
              w1_early["state"] == "running"
              and w1_early["native_status"] == "working"
              and w1_early["result_verdict"] == "valid"
              and w1_early["result_status"] is None
              and w1_early["summary"] is None
              and w1_early["settled_by"] is None
              and w1_early["closed"] is False)

        # Release gate -> native idle settles normally with settled_by='native'
        gate1.touch()
        w1_done = json.loads(run_cli(args.horch, ["wait", "--max-seconds", "15", r1["task_id"]], env=env).stdout.strip())
        check("native_completion_sets_settled_by_native",
              w1_done["state"] == "done"
              and w1_done["settled_by"] == "native"
              and w1_done["result_verdict"] == "valid"
              and w1_done["result_status"] == "completed"
              and w1_done["closed"] is True)

        # 2. native_status drops to null after working + valid result.json
        gate2 = work_dir / "gate2.release"
        brief2 = work_dir / "brief2.md"
        brief2.write_text(f"MODE=clear_status\nGATE={gate2}\n", encoding="utf-8")
        r2 = json.loads(run_cli(args.horch, ["run", "agy-w", "--brief", str(brief2), "--cwd", str(work_dir)], env=env).stdout)
        t2_dir = Path(r2["task_dir"])
        deadline = time.monotonic() + 10
        while not (t2_dir / "result.json").is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(0.3)

        # While mtime is fresh (<15s), must remain running with native_status=null and result_verdict='valid'
        w2_fresh = json.loads(run_cli(args.horch, ["wait", "--max-seconds", "1", r2["task_id"]], env=env).stdout.strip())
        check("null_status_with_fresh_result_waits_for_stability",
              w2_fresh["state"] == "running"
              and w2_fresh["native_status"] is None
              and w2_fresh["result_verdict"] == "valid"
              and w2_fresh["settled_by"] is None
              and w2_fresh["closed"] is False)

        # Once result.json + declared files mtimes are >= 15s old, fallback settles cleanly as done
        old2 = time.time() - 20
        os.utime(t2_dir / "result.json", (old2, old2))
        os.utime(t2_dir / "report.md", (old2, old2))
        w2_done = json.loads(run_cli(args.horch, ["wait", "--max-seconds", "10", r2["task_id"]], env=env).stdout.strip())
        check("null_status_with_stable_result_settles_via_result_file",
              w2_done["state"] == "done"
              and w2_done["settled_by"] == "result_file"
              and w2_done["result_verdict"] == "valid"
              and w2_done["result_status"] == "completed"
              and w2_done["summary"] == "done via clear_status"
              and w2_done["closed"] is True)
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
        "rerun": shlex.join(["python3", "e2e/result_fallback.py", "--output", "/tmp/horch-fallback-proof"]),
        "checks": checks,
    }
    receipt = output_dir / "evidence.json"
    receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "passed": evidence["passed"], "total": evidence["total"], "receipt": str(receipt)}))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
