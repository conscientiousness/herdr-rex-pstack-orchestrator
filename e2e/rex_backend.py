#!/usr/bin/env python3
"""Verify agent-workers placement and delivery on an isolated, real Rex server."""

import argparse
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
LEDGERS = {"alpha": [37, -12, 60, -5], "beta": [41, 7, -70, 19]}
MUX_PREFIXES = ("REX_", "HERDR", "HC_", "ANTIGRAVITY_")
AGENT_SESSION_KEYS = {"CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "ANTIGRAVITY_CONVERSATION_ID"}
FIXTURE = r'''import json, os, pathlib, re, select, sys, tty
root = pathlib.Path(__file__).resolve().parents[1]
if "--version" in sys.argv or "--list-models" in sys.argv:
    print("pi rex-e2e-fixture 1" if "--version" in sys.argv else "provider model")
    sys.exit(0)

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=pi\x07").encode())

tty.setraw(0)
os.write(1, b"\x1b[?2004hREX_E2E_READY\r\n")
report("idle")
buffer = b""
mode = None
finished = False
while True:
    if mode and not finished and (root / f"{mode}.release").is_file():
        report("done")
        finished = True
    if not select.select([0], [], [], 0.05)[0]:
        continue
    data = os.read(0, 4096)
    if not data:
        break
    lines = re.split(rb"[\r\n]", buffer + data)
    buffer = lines.pop()
    for line in lines:
        match = re.search(rb"Read (/[^\x1b]+?/brief\.md) in full", line)
        if not match:
            continue
        if mode:
            (root / f"{mode}.duplicate").touch()
            continue
        brief = pathlib.Path(os.fsdecode(match.group(1)))
        text = brief.read_text()
        mode = re.search(r"^REX_E2E_MODE=(\w+)$", text, re.MULTILINE).group(1)
        charges = json.loads(re.search(r"^REX_E2E_CHARGES=(.*)$", text, re.MULTILINE).group(1))
        task_id = re.search(r'"task_id"\s*:\s*"([^"]+)"', text).group(1)
        nonce = re.search(r'"nonce"\s*:\s*"([^"]+)"', text).group(1)
        result = brief.with_name("result.json")
        report("working")
        os.write(1, f"REX_WORKER_PROGRESS {mode} {task_id}\r\n".encode())
        running_total = 0
        balances = []
        for charge in charges:
            running_total += charge
            balances.append(running_total)
        (result.parent / "balances.json").write_text(json.dumps(balances))
        temporary = result.with_suffix(".new")
        temporary.write_text(json.dumps({"task_id": task_id, "nonce": nonce, "status": "completed",
                                         "summary": f"Computed {mode} balances.",
                                         "files": ["balances.json"], "question": None}))
        temporary.replace(result)
'''

CODEX_FIXTURE = r'''import json, os, pathlib, re, select, sys, time, tty
if "--version" in sys.argv:
    print("codex rex-e2e-fixture 1")
    sys.exit(0)

task_dir = None
for i, arg in enumerate(sys.argv):
    if arg == "--add-dir" and i + 1 < len(sys.argv):
        task_dir = pathlib.Path(sys.argv[i + 1])

startup_jitter = "--startup-jitter" in sys.argv
pre_paste_jitter = "--pre-paste-jitter" in sys.argv
post_paste_idle = "--post-paste-idle" in sys.argv
post_paste_block = "--post-paste-block" in sys.argv

def report(state):
    os.write(1, ("\x1b]7501;state=" + state + ":app=codex\x07").encode())

events = {
    "received_during_jitter": False,
    "pre_paste_fired": False,
    "saw_retry_starting": False,
    "received_during_pre_paste_working": False,
    "post_paste_idle_sent": False,
    "post_paste_block_sent": False,
    "enter_received": False,
    "duplicate": False,
}

def save_events():
    if task_dir is None:
        return
    path = task_dir / "events.json"
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(events))
    tmp.replace(path)

def read_state():
    if task_dir is None:
        return None
    try:
        return json.loads((task_dir / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None

tty.setraw(0)
os.write(1, b"\x1b[?2004hCODEX_E2E_READY\r\n")
report("idle")

buffer = b""
handled = False

if startup_jitter:
    started = time.monotonic()
    switched_working = False
    while time.monotonic() - started < 0.30:
        if not switched_working and time.monotonic() - started >= 0.12:
            report("working")
            switched_working = True
        if select.select([0], [], [], 0.01)[0]:
            chunk = os.read(0, 4096)
            if not chunk:
                sys.exit(0)
            events["received_during_jitter"] = True
            buffer += chunk
    report("idle")
    save_events()

pre_paste_working_until = None
while True:
    if pre_paste_jitter:
        st = read_state()
        if not events["pre_paste_fired"] and st and st.get("submission") == "unknown":
            report("working")
            events["pre_paste_fired"] = True
            pre_paste_working_until = time.monotonic() + 0.25
            save_events()
        elif events["pre_paste_fired"] and st and st.get("state") == "starting" and st.get("submission") == "not_sent":
            if not events["saw_retry_starting"]:
                events["saw_retry_starting"] = True
                save_events()
        if pre_paste_working_until is not None and time.monotonic() >= pre_paste_working_until:
            report("idle")
            pre_paste_working_until = None
            save_events()

    if not select.select([0], [], [], 0.005)[0]:
        continue
    data = os.read(0, 4096)
    if not data:
        break
    if pre_paste_working_until is not None:
        events["received_during_pre_paste_working"] = True
        save_events()
    combined = buffer + data
    lines = re.split(rb"[\r\n]", combined)
    buffer = lines.pop()

    if not lines and b"brief.md" in buffer:
        if post_paste_idle and not events["post_paste_idle_sent"]:
            report("idle")
            events["post_paste_idle_sent"] = True
            save_events()
        if post_paste_block and not events["post_paste_block_sent"]:
            report("blocked")
            events["post_paste_block_sent"] = True
            save_events()

    for line in lines:
        if not line and not handled:
            continue
        events["enter_received"] = True
        save_events()
        match = re.search(rb"Read (/[^\x1b]+?/brief\.md) in full", line)
        if not match:
            continue
        if handled:
            events["duplicate"] = True
            save_events()
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
            "summary": "Codex jitter ok.",
            "files": [],
            "question": None,
        }))
        tmp.replace(result)
        time.sleep(0.1)
        report("done")
        save_events()
'''


def write_json(path, data):
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def rows(proc):
    if proc.returncode:
        raise RuntimeError((proc.stdout or proc.stderr).strip()[:1000])
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def horch(path, *args, env=None, timeout=100):
    return subprocess.run([sys.executable, str(path), *args], env=env, timeout=timeout,
                          capture_output=True, text=True)


def controller(root, program):
    """Run inside Rex so the public CLI sees the actual terminal's environment."""
    env = os.environ.copy()
    observation = {"session": env.get("REX_SESSION"), "block": env.get("REX_BLOCK")}
    try:
        observation["detected"] = rows(horch(program, "detect"))[0]["backend"]
        if observation["detected"] != "rex":
            raise RuntimeError(f"Rex controller reported backend {observation['detected']!r}")
        cli = ["rex", "--autostart=false", "-S", env["REX_SERVER"]]
        if not observation["session"]:
            def query(*args):
                proc = subprocess.run([*cli, *args, "--json"], check=True, capture_output=True,
                                      text=True, timeout=15)
                return json.loads(proc.stdout)

            sessions = [row["session_id"] for row in query("session", "ls")["sessions"]]
            matches = [session for session in sessions if any(
                row["block_id"] == observation["block"]
                for row in query("block", "ls", "-s", session)["blocks"])]
            if len(matches) != 1:
                raise RuntimeError("Expected exactly one Rex session for the controller block")
            observation["session"] = env["REX_SESSION"] = matches[0]
        manual_tab = subprocess.run(
            [*cli, "window", "new", "-s", observation["session"], "Workers", "--focus=false", "--json",
             "--shell=none", "--", "/bin/sleep", "300"],
            check=True, capture_output=True, text=True, timeout=15)
        observation["manual_window"] = json.loads(manual_tab.stdout)["window_id"]
        observation["runs"] = {}
        for mode, charges in LEDGERS.items():
            brief = root / f"{mode}.md"
            brief.write_text(f"REX_E2E_MODE={mode}\nREX_E2E_CHARGES={json.dumps(charges)}\n")
            observation["runs"][mode] = rows(horch(program, "run", "fixture", "--brief", str(brief), env=env))[0]
        mixed = horch(program, "detect", env=dict(env, HERDR_ENV="1"))
        observation["mixed_context_rejected"] = (mixed.returncode == 1
                                                  and json.loads(mixed.stdout)["error"] == "caller_context_conflict")
    except Exception as exc:
        observation["error"] = str(exc)
    write_json(root / "controller.json", observation)
    while not (root / "codex.start").exists() and not (root / "controller.release").exists():
        time.sleep(0.05)
    if (root / "codex.start").exists():
        codex_obs = {"runs": {}}
        try:
            codex_brief = root / "codex.md"
            codex_brief.write_text("# Codex jitter probe\nWrite result.json.\n")
            for worker in ("codex-settle", "codex-retry", "codex-block"):
                codex_obs["runs"][worker] = rows(horch(program, "run", worker, "--brief", str(codex_brief), env=env))[0]
                if worker != "codex-block":
                    task_id = codex_obs["runs"][worker]["task_id"]
                    codex_obs["runs"][worker]["waited"] = rows(
                        horch(program, "wait", task_id, "--max-seconds", "15", env=env)
                    )[0]
                else:
                    task_id = codex_obs["runs"][worker]["task_id"]
                    codex_obs["runs"][worker]["closed_result"] = rows(
                        horch(program, "close", task_id, env=env)
                    )[0]
        except Exception as exc:
            codex_obs["error"] = str(exc)
        write_json(root / "codex.json", codex_obs)
    while not (root / "controller.release").exists():
        time.sleep(0.1)


class Scenario:
    def __init__(self, args, rex, root, listener):
        self.args, self.root = args, root
        self.endpoint = f"unix://{listener}"
        self.cli = [rex, "--autostart=false", "-S", self.endpoint]
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(MUX_PREFIXES) and key not in AGENT_SESSION_KEYS}
        bindir = root / "bin"
        bindir.mkdir()
        # Like mise's node for Pi: the worker runtime is only on the controller's PATH,
        # never on the Rex server's PATH (a GUI-started server lacks shell shims).
        runtime = root / "controller-runtime"
        runtime.mkdir()
        (runtime / "fixture-node").symlink_to(Path(sys.executable).resolve())
        self.env.update(PATH=str(bindir) + os.pathsep + os.defpath,
                        XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"))
        self.controller_path = str(runtime) + os.pathsep + self.env["PATH"]
        (bindir / "rex").symlink_to(Path(rex).resolve())
        fixture = bindir / "pi"
        fixture.write_text("#!/usr/bin/env fixture-node\n" + FIXTURE)
        fixture.chmod(0o700)
        codex_fixture = bindir / "codex"
        codex_fixture.write_text("#!/usr/bin/env fixture-node\n" + CODEX_FIXTURE)
        codex_fixture.chmod(0o700)
        for name in ("herdr", "herdr-core", "hc"):
            guard = bindir / name
            guard.write_text('#!/bin/sh\ntouch "$(dirname "$0")/../herdr-invoked"\nexit 97\n')
            guard.chmod(0o700)
        config = root / "config/herdr-orchestrator/workers.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            'max_active_workers = 2\n'
            '[workers.fixture]\nharness = "pi"\nmodel = "fixture"\n'
            '[workers.codex-settle]\nharness = "codex"\nmodel = "fixture"\n'
            'args = ["--startup-jitter", "--post-paste-idle"]\n'
            '[workers.codex-retry]\nharness = "codex"\nmodel = "fixture"\n'
            'args = ["--pre-paste-jitter"]\n'
            '[workers.codex-block]\nharness = "codex"\nmodel = "fixture"\n'
            'args = ["--post-paste-block"]\n'
        )
        self.init = root / "init.lua"
        self.init.touch()
        self.checks = {}
        self.evidence = {"schema": "horch/rex-backend-e2e/v1", "verdict": "fail", "checks": self.checks,
                         "scope": "real Rex; deterministic interactive Pi and Codex jitter workers; no model calls",
                         "deliveries": {},
                         "rerun": shlex.join([sys.executable, str(Path(__file__).resolve()),
                                               "--horch", str(args.horch), "--output", str(args.output)])}

    def rx(self, *args):
        proc = subprocess.run([*self.cli, *args], env=self.env, timeout=15, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError((proc.stdout or proc.stderr).strip()[:1000])
        return json.loads(proc.stdout)

    def check(self, name, fact):
        self.checks[name] = bool(fact)
        if not fact:
            raise AssertionError(name)

    def until_file(self, path, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if path.is_file():
                return json.loads(path.read_text())
            time.sleep(0.1)
        raise TimeoutError(f"no {path.name} after {seconds} seconds")

    def session(self, label, *argv):
        result = self.rx("new", label, "--cwd", str(self.root), "--shell=none", "--keep-open", "--json", "--", *argv)
        first = result["initial_windows"][0]
        return result["session_id"], first["window_id"], first["block_ids"][0]

    def windows(self, session):
        return self.rx("session", "inspect", session, "--json")

    def blocks(self, session):
        return self.rx("block", "ls", "-s", session, "--json")["blocks"]

    def verify(self):
        self.evidence["rex_version"] = self.rx("whoami", "--json")["rex_version"]
        other, _, other_block = self.session("unrelated", "/bin/sleep", "300")
        baseline = self.windows(other)
        session, controller_window, controller_block = self.session(
            "project", "/usr/bin/env", f"REX_SERVER={self.endpoint}", f"PATH={self.controller_path}", sys.executable,
            str(Path(__file__).resolve()), "--horch", str(self.args.horch), "--controller", str(self.root))
        observed = self.until_file(self.root / "controller.json", 200)
        if observed.get("error"):
            raise RuntimeError(observed["error"])
        self.check("inherited Rex environment routes dispatch", observed["detected"] == "rex"
                   and observed["session"] == session and observed["block"] == controller_block)
        self.check("simultaneous Rex and Herdr context is rejected", observed["mixed_context_rejected"])
        runs = observed["runs"]
        tasks = {mode: json.loads((Path(row["task_dir"]) / "task.json").read_text())
                 for mode, row in runs.items()}
        bindings = [task["backend"] for task in tasks.values()]
        self.check("both tasks were submitted on the same Rex session", len(bindings) == 2 and all(
            binding["kind"] == "rex" and binding["session"] == session and binding["endpoint"] == self.endpoint
            for binding in bindings) and all(row["backend"] == "rex" and row["startup_ready"]
                                             and row["submission"] == "sent" for row in runs.values()))
        worker_window = bindings[0]["window"]
        worker_blocks = {binding["block"] for binding in bindings}
        manual_window = observed["manual_window"]
        manual_blocks = {row["block_id"] for row in self.blocks(session) if row["window_id"] == manual_window}
        live_layout = self.windows(session)
        self.check("both workers share their own background Workers tab", worker_window not in (controller_window, manual_window)
                   and len(worker_blocks) == 2 and all(binding["window"] == worker_window for binding in bindings)
                   and live_layout["active_window_id"] == controller_window
                   and any(row["window_id"] == worker_window and row["label"] == "Workers"
                           for row in live_layout["windows"]))
        self.check("new blocks show the configured worker and its harness", {
            row["block_id"]: row["label"] for row in self.blocks(session) if row["window_id"] == worker_window
        } == {task["backend"]["block"]: f"fixture · Pi · {task['nonce']}" for task in tasks.values()})
        self.check("manual Workers tab has only its original block", len(manual_blocks) == 1
                   and worker_blocks.isdisjoint(manual_blocks))
        self.evidence["layout"] = {"session": session, "controller": controller_window,
                                   "worker": worker_window, "worker_blocks": sorted(worker_blocks),
                                   "manual_workers": manual_window}

        wait_env = dict(self.env, REX_SERVER=self.endpoint + ".absent", REX_SESSION=other, REX_BLOCK=other_block)
        bad_sock = horch(self.args.horch, "run", "fixture", "--brief", str(self.root / "alpha.md"), env=wait_env)
        bad_sock_json = json.loads(bad_sock.stdout) if bad_sock.stdout.strip() else {}
        self.check("unreachable Rex socket reports sandbox_or_socket_blocked hint",
                   bad_sock.returncode == 1
                   and bad_sock_json.get("error") == "rex_error"
                   and bad_sock_json.get("hint") == "sandbox_or_socket_blocked"
                   and "sandbox" in (bad_sock_json.get("message") or "").lower())
        for mode, run in runs.items():
            task = tasks[mode]
            result = self.until_file(Path(task["result_path"]), 15)
            early, = rows(horch(self.args.horch, "wait", run["task_id"], "--max-seconds", "0", env=wait_env))
            self.check(f"{mode} stays running with a result but without turn completion",
                       early["state"] == "running" and not early["closed"] and early["summary"] is None)
            inspected_live, = rows(horch(self.args.horch, "inspect", run["task_id"], "--lines", "5", env=wait_env))
            self.check(f"{mode} inspect reports live Rex status and tail by stored binding",
                       inspected_live["backend"] == "rex"
                       and inspected_live["terminal_state"] == "live"
                       and inspected_live["native_status"] == "working"
                       and isinstance(inspected_live["elapsed_seconds"], int)
                       and any(f"REX_WORKER_PROGRESS {mode} {run['task_id']}" in line
                               for line in inspected_live["tail_lines"]))
            if mode == "alpha":
                probe_session, _, probe_block = self.session(
                    "caller-probe",
                    "/bin/bash", "-c",
                    'exec -a agy python3 -c "import time; print(\'AGY_TRUNC_PROBE_UNIQUE_LINE_12345\', flush=True); time.sleep(60)"',
                )
                time.sleep(0.5)
                trunc_env = dict(self.env, REX_SERVER=self.endpoint, REX_SESSION=probe_session, REX_BLOCK=probe_block)
                trunc = subprocess.run(
                    [sys.executable, str(self.args.horch), "run", "fixture", "--brief", str(self.root / "missing.md"),
                     "--caller-text", "AGY_TRUNC_PROBE_UNIQUE_LINE_12345_TRUNCATED_TAIL"],
                    cwd=self.root, env=trunc_env, timeout=30, capture_output=True, text=True,
                )
                trunc_json = json.loads(trunc.stdout) if trunc.stdout.strip() else {}
                ok_caller = subprocess.run(
                    [sys.executable, str(self.args.horch), "run", "fixture", "--brief", str(self.root / "missing.md"),
                     "--caller-text", "AGY_TRUNC_PROBE_UNIQUE_LINE_12345"],
                    cwd=self.root, env=trunc_env, timeout=30, capture_output=True, text=True,
                )
                ok_caller_json = json.loads(ok_caller.stdout) if ok_caller.stdout.strip() else {}
                self.rx("api", "call", "-s", probe_session, "block.close", json.dumps({"block_id": probe_block}))
                self.check("truncated caller-text reports truncation hint without leaking screen",
                           trunc.returncode == 1
                           and trunc_json.get("error") == "caller_context_invalid"
                           and "truncated" in (trunc_json.get("message") or "").lower()
                           and "AGY_TRUNC_PROBE_UNIQUE_LINE_12345" not in (trunc_json.get("message") or "")
                           and ok_caller.returncode == 1
                           and ok_caller_json.get("error") == "brief_not_found")
            (self.root / f"{mode}.release").touch()
            done, = rows(horch(self.args.horch, "wait", run["task_id"], "--max-seconds", "15", env=wait_env))
            balances = json.loads(Path(done["result_path"]).with_name("balances.json").read_text())
            charges = LEDGERS[mode]
            expected_file = str(Path(done["result_path"]).with_name("balances.json"))
            self.check(f"{mode} delivers exact output and closes by stored Rex binding", done["state"] == "done"
                       and done["closed"] and done["summary"] == f"Computed {mode} balances."
                       and done["files"] == [expected_file] and result["files"] == ["balances.json"]
                       and result["task_id"] == run["task_id"]
                       and result["nonce"] == task["nonce"] and result["status"] == "completed"
                       and balances == [sum(charges[:index + 1]) for index in range(len(charges))])
            inspected_closed, = rows(horch(self.args.horch, "inspect", run["task_id"], env=wait_env))
            self.check(f"{mode} inspect reports closed after delivery",
                       inspected_closed["closed"] is True
                       and inspected_closed["terminal_state"] == "closed"
                       and inspected_closed["tail_lines"] == [])
            self.evidence["deliveries"][mode] = {"state": done["state"], "closed": done["closed"],
                                                  "balances": balances}
            worker_blocks.remove(task["backend"]["block"])
            self.check(f"{mode} leaves all unrelated blocks and remaining workers", {
                row["block_id"] for row in self.blocks(session)} == worker_blocks | manual_blocks | {controller_block})
        self.check("last block closure removes only the worker tab", {
            row["window_id"] for row in self.windows(session)["windows"]} == {controller_window, manual_window})

        (self.root / "codex.start").touch()
        codex_obs = self.until_file(self.root / "codex.json", 120)
        if codex_obs.get("error"):
            raise RuntimeError(codex_obs["error"])
        codex_runs = codex_obs["runs"]
        settle_run = codex_runs["codex-settle"]
        settle_events = json.loads((Path(settle_run["task_dir"]) / "events.json").read_text())
        self.check("codex startup jitter settles and post-paste idle refresh still sends Enter",
                   settle_run["submission"] == "sent" and settle_run["startup_ready"]
                   and settle_run["waited"]["state"] == "done" and settle_run["waited"]["closed"]
                   and settle_run["waited"]["summary"] == "Codex jitter ok."
                   and not settle_events["received_during_jitter"]
                   and settle_events["post_paste_idle_sent"]
                   and settle_events["enter_received"]
                   and not settle_events["duplicate"])
        retry_run = codex_runs["codex-retry"]
        retry_events = json.loads((Path(retry_run["task_dir"]) / "events.json").read_text())
        self.check("codex pre-paste transient not_sent retries automatically without manual submit",
                   retry_run["submission"] == "sent" and retry_run["startup_ready"]
                   and retry_run["waited"]["state"] == "done" and retry_run["waited"]["closed"]
                   and retry_run["waited"]["summary"] == "Codex jitter ok."
                   and retry_events["pre_paste_fired"]
                   and retry_events["saw_retry_starting"]
                   and not retry_events["received_during_pre_paste_working"]
                   and retry_events["enter_received"]
                   and not retry_events["duplicate"])
        block_run = codex_runs["codex-block"]
        block_events = json.loads((Path(block_run["task_dir"]) / "events.json").read_text())
        self.check("codex post-paste non-idle change still withholds Enter",
                   block_run["submission"] == "unknown"
                   and block_run["state"] == "not_started"
                   and block_run["native_status"] == "blocked"
                   and "Enter was withheld" in (block_run.get("message") or "")
                   and block_events["post_paste_block_sent"]
                   and not block_events["enter_received"]
                   and block_run["closed_result"]["closed"] is True)
        self.check("codex worker tab cleaned up after jitter checks", {
            row["window_id"] for row in self.windows(session)["windows"]} == {controller_window, manual_window})

        after = self.windows(other)
        self.check("unrelated Rex session stayed intact", baseline["windows"] == after["windows"]
                   and baseline["active_window_id"] == after["active_window_id"])
        self.check("no Herdr command or duplicate prompt", not (self.root / "herdr-invoked").exists()
                   and not list(self.root.glob("*.duplicate")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horch", type=Path, default=HORCH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--controller", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.horch = args.horch.resolve()
    if args.controller:
        controller(args.controller, args.horch)
        return 0
    rex = shutil.which("rex")
    if not rex or args.output is None:
        parser.error("an installed Rex CLI and --output outside the checkout are required")
    args.output = args.output.resolve()
    if args.output.is_relative_to(HORCH.parents[3]):
        parser.error("keep Rex evidence outside the checkout")
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="rex-backend-", dir=args.output))
    receipt = root / "evidence.json"
    with tempfile.TemporaryDirectory(prefix="rx-", dir="/tmp") as runtime:
        listener = Path(runtime) / "server.sock"
        scenario = Scenario(args, rex, root, listener)
        with (root / "server.log").open("w") as log:
            server = subprocess.Popen([rex, "server", "run", "--listen", scenario.endpoint,
                                       "--state-dir", str(Path(runtime) / "state"), "--restore=false",
                                       "--config", str(scenario.init)], env=scenario.env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while not listener.exists() and server.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                scenario.check("isolated Rex server ready", listener.exists())
                scenario.verify()
                scenario.evidence["verdict"] = "pass"
            except Exception as exc:
                scenario.evidence["problem"] = str(exc)
            finally:
                (root / "controller.release").touch()
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
                        scenario.evidence["verdict"] = "fail"
                        scenario.evidence["problem"] = "isolated Rex required forced shutdown"
                scenario.evidence["server_stopped"] = server.poll() is not None
                write_json(receipt, scenario.evidence)
    print(receipt)
    return 0 if scenario.evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
