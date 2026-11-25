#!/usr/bin/env python3
"""Verify agy startup banner recovery and Rex --caller-text soft-unwrap."""

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
REX_BACKEND = Path(__file__).resolve().parents[1] / "skills/agent-workers/scripts/rex_backend.py"

AGY_FIXTURE = r'''#!/usr/bin/env python3
import json, os, pathlib, re, select, sys, tty

if "--version" in sys.argv:
    print("agy startup-guard-fixture 1")
    sys.exit(0)

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=agy\x07").encode())

tty.setraw(0)
banner_gate = None
for i, arg in enumerate(sys.argv):
    if arg == "--banner-gate" and i + 1 < len(sys.argv):
        banner_gate = pathlib.Path(sys.argv[i + 1])

if banner_gate is not None:
    os.write(1, b"Introducing Gemini 4 Neon\r\nesc to dismiss\r\n")
else:
    os.write(1, b"AGY_CLEAN_IDLE_READY\r\n")
report("idle")

buf = b""
handled = False
dismissed = banner_gate is None
while True:
    if not dismissed and banner_gate.exists():
        dismissed = True
        os.write(1, b"\x1b[2J\x1b[HAGY_BANNER_DISMISSED_READY\r\n")
        report("idle")
    if not select.select([0], [], [], 0.05)[0]:
        continue
    chunk = os.read(0, 4096)
    if not chunk:
        break
    if not dismissed:
        (banner_gate.parent / "received_while_banner_open").write_bytes(chunk)
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
        result = brief.with_name("result.json")
        tmp = result.with_suffix(".new")
        tmp.write_text(json.dumps({
            "task_id": task_id,
            "nonce": nonce,
            "status": "completed",
            "summary": "agy ok",
            "files": [],
            "question": None,
        }))
        tmp.replace(result)
        report("idle")
'''

PI_FIXTURE = r'''#!/usr/bin/env python3
import json, os, pathlib, re, select, sys, tty

if "--version" in sys.argv:
    print("pi startup-guard-fixture 1")
    sys.exit(0)
if "--list-models" in sys.argv:
    print("provider model")
    sys.exit(0)

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=pi\x07").encode())

tty.setraw(0)
# Non-agy harness showing 'esc to dismiss' must NOT be falsely blocked by agy guard
os.write(1, b"PI_READY (esc to dismiss)\r\n")
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
        result = brief.with_name("result.json")
        tmp = result.with_suffix(".new")
        tmp.write_text(json.dumps({
            "task_id": task_id,
            "nonce": nonce,
            "status": "completed",
            "summary": "pi ok",
            "files": [],
            "question": None,
        }))
        tmp.replace(result)
        report("idle")
'''

REX_WRAP_CONTROLLER = r'''#!/usr/bin/env python3
import os, pathlib, sys, time
token = sys.argv[1]
release = pathlib.Path(sys.argv[2])
# Print a long continuous token so an 80-column Rex block soft-wraps it mid-token.
sys.stdout.write(token + "\n")
sys.stdout.flush()
while not release.exists():
    time.sleep(0.05)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horch", type=Path, default=HORCH)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    core_bin = shutil.which("herdr-core")
    rex_bin = shutil.which("rex")
    if not core_bin or not rex_bin:
        print(json.dumps({"verdict": "FAIL", "error": "herdr-core and rex binaries are required"}))
        return 1

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="horch-guards-e2e-"))
    checks = []

    def check(name, ok, detail=None):
        entry = {"name": name, "ok": bool(ok)}
        if detail is not None:
            entry["detail"] = detail
        checks.append(entry)

    # Part 1: agy startup banner guard on isolated herdr-core
    core_root = scratch / "core"
    bin_dir = core_root / "bin"
    cfg_dir = core_root / "config" / "herdr-orchestrator"
    run_dir = core_root / "run"
    work_dir = core_root / "work"
    for d in (bin_dir, cfg_dir, run_dir, work_dir):
        d.mkdir(parents=True, exist_ok=True)

    (bin_dir / "agy").write_text(AGY_FIXTURE, encoding="utf-8")
    (bin_dir / "agy").chmod(0o755)
    (bin_dir / "pi").write_text(PI_FIXTURE, encoding="utf-8")
    (bin_dir / "pi").chmod(0o755)
    os.symlink(core_bin, bin_dir / "herdr-core")

    banner_gate = work_dir / "dismiss-banner.release"
    (cfg_dir / "workers.toml").write_text(
        'max_active_workers = 1\n'
        'notify_after_minutes = 180\n\n'
        '[workers.agy-banner]\n'
        'harness = "agy"\n'
        'model = "gemini-4-neon"\n'
        f'args = ["--banner-gate", {json.dumps(str(banner_gate))}]\n\n'
        '[workers.agy-clean]\n'
        'harness = "agy"\n'
        'model = "gemini-4-neon"\n\n'
        '[workers.pi-esc]\n'
        'harness = "pi"\n'
        'model = "pi-model"\n',
        encoding="utf-8",
    )

    session = f"guards-{os.getpid()}-{int(time.time())}"
    core_env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("HERDR", "HC_", "REX_", "ANTIGRAVITY_", "AGENT_WORKERS_"))
        and k not in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "PI_SESSION_ID", "CLAUDECODE")
    }
    core_env.update(
        PATH=f"{bin_dir}:{os.environ.get('PATH', os.defpath)}",
        XDG_CONFIG_HOME=str(core_root / "config"),
        XDG_STATE_HOME=str(core_root / "state"),
        XDG_RUNTIME_DIR=str(run_dir),
        HC_SESSION=session,
        HC_SOCKET=str(run_dir / f"{session}.sock"),
    )

    core_cleanup_ok = False
    rex_cleanup_ok = False
    try:
        brief = work_dir / "brief.md"
        brief.write_text("# Guard probe\nWrite result.json.\n", encoding="utf-8")

        # 1A. agy banner ('esc to dismiss') blocks send and retains submission='not_sent'
        p_banner = run_cli(
            args.horch,
            ["run", "agy-banner", "--brief", str(brief), "--cwd", str(work_dir)],
            env=core_env,
        )
        res_banner = json.loads(p_banner.stdout)
        check("agy_banner_blocked_before_send",
              p_banner.returncode == 0
              and res_banner["state"] == "start_failed"
              and res_banner["submission"] == "not_sent"
              and "esc to dismiss" in (res_banner.get("message") or "").lower()
              and not (work_dir / "received_while_banner_open").exists())

        # 1B. Dismiss banner -> submit recovers cleanly without relaunching
        banner_gate.touch()
        time.sleep(0.3)
        p_submit = run_cli(args.horch, ["submit", res_banner["task_id"]], env=core_env)
        sub_res = json.loads(p_submit.stdout)
        p_wait = run_cli(args.horch, ["wait", "--max-seconds", "30", res_banner["task_id"]], env=core_env)
        wait_res = json.loads(p_wait.stdout.strip())
        check("agy_banner_submit_recovers_after_dismiss",
              p_submit.returncode == 0
              and sub_res["submission"] == "sent"
              and p_wait.returncode == 0
              and wait_res["state"] == "done"
              and wait_res["closed"] is True)

        # 1C. Replace a blocked worker without dismissing its banner.
        banner_gate.unlink()
        p_blocked = run_cli(
            args.horch,
            ["run", "agy-banner", "--brief", str(brief), "--cwd", str(work_dir)],
            env=core_env,
        )
        blocked = json.loads(p_blocked.stdout)
        clean_args = ["run", "agy-clean", "--brief", str(brief), "--cwd", str(work_dir), "--wait"]
        p_limit = run_cli(args.horch, clean_args, env=core_env)
        check("agy_undismissed_banner_reserves_the_only_slot",
              p_blocked.returncode == 0
              and blocked["state"] == "start_failed"
              and blocked["submission"] == "not_sent"
              and "esc to dismiss" in (blocked.get("message") or "").lower()
              and p_limit.returncode != 0
              and json.loads(p_limit.stdout).get("error") == "worker_limit")
        p_close = run_cli(args.horch, ["close", blocked["task_id"]], env=core_env)
        closed = json.loads(p_close.stdout)
        check("agy_undismissed_banner_closed_without_input",
              p_close.returncode == 0
              and closed["task_id"] == blocked["task_id"]
              and closed["closed"] is True
              and not banner_gate.exists()
              and not (work_dir / "received_while_banner_open").exists()
              and not (Path(blocked["task_dir"]) / "result.json").exists())

        p_clean = run_cli(
            args.horch,
            clean_args,
            env=core_env,
        )
        clean_lines = [json.loads(line) for line in p_clean.stdout.splitlines() if line.strip()]
        check("agy_replacement_delivers_and_closes",
              p_clean.returncode == 0
              and len(clean_lines) == 2
              and clean_lines[0]["task_id"] != blocked["task_id"]
              and clean_lines[0]["task_id"] == clean_lines[1]["task_id"]
              and clean_lines[1]["state"] == "done"
              and clean_lines[1]["result_status"] == "completed"
              and clean_lines[1]["result_verdict"] == "valid"
              and clean_lines[1]["closed"] is True)

        # 1D. Non-agy harness (pi) showing 'esc to dismiss' is NOT falsely blocked
        p_pi = run_cli(
            args.horch,
            ["run", "pi-esc", "--brief", str(brief), "--cwd", str(work_dir), "--wait"],
            env=core_env,
        )
        pi_lines = [json.loads(line) for line in p_pi.stdout.splitlines() if line.strip()]
        check("non_agy_harness_not_blocked_by_agy_guard",
              p_pi.returncode == 0
              and len(pi_lines) == 2
              and pi_lines[1]["state"] == "done"
              and pi_lines[1]["closed"] is True)

        # Part 2: Rex caller proof and agy startup banner guard on an isolated server.
        with tempfile.TemporaryDirectory(prefix="rx-guards-", dir="/tmp") as rx_tmp:
            rx_root = Path(rx_tmp)
            listener = rx_root / "server.sock"
            endpoint = f"unix://{listener}"
            init_lua = rx_root / "init.lua"
            init_lua.touch()
            rx_bin = rx_root / "bin"
            rx_work = rx_root / "work"
            rx_cfg = rx_root / "config" / "herdr-orchestrator"
            for d in (rx_bin, rx_work, rx_cfg):
                d.mkdir(parents=True, exist_ok=True)
            os.symlink(rex_bin, rx_bin / "rex")
            # Symlink python3 as 'pi' so Rex foreground process argv0/invoked_path is 'pi'
            fake_pi = rx_bin / "pi"
            os.symlink(Path(sys.executable).resolve(), fake_pi)
            ctrl_script = rx_root / "ctrl.py"
            ctrl_script.write_text(REX_WRAP_CONTROLLER, encoding="utf-8")
            rex_gate = rx_work / "dismiss-banner.release"
            rex_agy = rx_bin / "agy"
            rex_agy.write_text(AGY_FIXTURE, encoding="utf-8")
            rex_agy.chmod(0o755)
            (rx_cfg / "workers.toml").write_text(
                'max_active_workers = 2\n[workers.agy-banner]\nharness = "agy"\nmodel = "fixture"\n'
                f'args = ["--banner-gate", {json.dumps(str(rex_gate))}]\n', encoding="utf-8",
            )

            rx_env = {
                k: v for k, v in os.environ.items()
                if not k.startswith(("HERDR", "HC_", "REX_", "ANTIGRAVITY_", "AGENT_WORKERS_"))
                and k not in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "PI_SESSION_ID", "CLAUDECODE")
            }
            rx_env.update(
                PATH=f"{rx_bin}:{os.environ.get('PATH', os.defpath)}",
                XDG_CONFIG_HOME=str(rx_root / "config"),
                XDG_STATE_HOME=str(rx_root / "state"),
            )
            server = subprocess.Popen(
                [rex_bin, "server", "run", "--listen", endpoint,
                 "--state-dir", str(rx_root / "rex-state"), "--restore=false",
                 "--config", str(init_lua)],
                env=rx_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 10
                while not listener.exists() and server.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                check("isolated_rex_server_ready", listener.exists())

                long_token = "SOFTWRAP_UNIQUE_TOKEN_" + ("X" * 95) + "_END"
                secret_marker = "SECRET_OTHER_CONTENT_DO_NOT_LEAK"
                ctrl_release = rx_root / "ctrl.release"
                new_proc = subprocess.run(
                    [rex_bin, "--autostart=false", "-S", endpoint, "new", "ctrl",
                     "--cwd", str(rx_work), "--shell=none", "--keep-open", "--json",
                     "--", str(fake_pi), str(ctrl_script), f"{long_token} {secret_marker}", str(ctrl_release)],
                    env=rx_env, capture_output=True, text=True, timeout=15, check=True,
                )
                created = json.loads(new_proc.stdout)
                rx_session = created["session_id"]
                rx_block = created["initial_windows"][0]["block_ids"][0]
                time.sleep(0.4)

                # Verify raw capture really soft-wrapped the token (so raw split wouldn't match!)
                raw_cap = subprocess.run(
                    [rex_bin, "--autostart=false", "-S", endpoint, "capture",
                     "-s", rx_session, "-b", rx_block],
                    env=rx_env, capture_output=True, text=True, timeout=15, check=True,
                ).stdout
                raw_broken = long_token not in " ".join(raw_cap.split())
                check("rex_raw_capture_actually_wrapped_token", raw_broken)

                call_env = dict(rx_env, REX_SERVER=endpoint, REX_SESSION=rx_session, REX_BLOCK=rx_block)
                # Calling run with wrapped --caller-text must pass caller verification and reach unknown_worker!
                p_wrap = run_cli(
                    args.horch,
                    ["run", "nonexistent", "--brief", str(brief), "--caller-text", long_token],
                    env=call_env, cwd=rx_work,
                )
                wrap_err = json.loads(p_wrap.stdout)
                check("rex_caller_text_matches_soft_wrapped_line",
                      p_wrap.returncode == 1 and wrap_err["error"] == "unknown_worker")

                # Calling run with non-matching --caller-text must report candidate count and NOT leak screen text
                p_nomatch = run_cli(
                    args.horch,
                    ["run", "nonexistent", "--brief", str(brief), "--caller-text", "DEFINITELY_NOT_ON_SCREEN_12345"],
                    env=call_env, cwd=rx_work,
                )
                nomatch_err = json.loads(p_nomatch.stdout)
                msg = nomatch_err.get("message", "")
                check("rex_caller_text_failure_reports_count_without_leaking_screen",
                      p_nomatch.returncode == 1
                      and nomatch_err["error"] == "caller_context_invalid"
                      and "checked 1 candidate block(s)" in msg
                      and secret_marker not in msg
                      and long_token not in msg)

                p_rex_banner = run_cli(
                    args.horch,
                    ["run", "agy-banner", "--brief", str(brief), "--caller-text", long_token],
                    env=call_env, cwd=rx_work,
                )
                rex_banner = json.loads(p_rex_banner.stdout)
                check("rex_agy_banner_blocked_before_send",
                      p_rex_banner.returncode == 0
                      and rex_banner.get("state") == "start_failed"
                      and rex_banner.get("submission") == "not_sent"
                      and "esc to dismiss" in (rex_banner.get("message") or "").lower()
                      and not (rx_work / "received_while_banner_open").exists(),
                      {key: rex_banner.get(key) for key in ("state", "submission", "message")})
            finally:
                (rx_root / "ctrl.release").touch()
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                rex_cleanup_ok = server.poll() is not None
    finally:
        stop = subprocess.run([core_bin, "server", "stop"], env=core_env, capture_output=True, text=True, timeout=15)
        core_cleanup_ok = stop.returncode == 0 or not (run_dir / f"{session}.sock").exists()
        shutil.rmtree(scratch, ignore_errors=True)

    check("isolated_servers_cleanup", core_cleanup_ok and rex_cleanup_ok)
    verdict = "PASS" if all(c["ok"] for c in checks) else "FAIL"
    evidence = {
        "verdict": verdict,
        "passed": sum(c["ok"] for c in checks),
        "total": len(checks),
        "horch_sha256": sha256(args.horch),
        "rex_backend_sha256": sha256(args.horch.with_name(REX_BACKEND.name)),
        "rerun": shlex.join(["python3", "e2e/startup_guards.py", "--output", "/tmp/horch-guards-proof"]),
        "checks": checks,
    }
    receipt = output_dir / "evidence.json"
    receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "passed": evidence["passed"], "total": evidence["total"], "receipt": str(receipt)}))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
