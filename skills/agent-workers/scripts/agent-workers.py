#!/usr/bin/env python3
"""agent-workers - start, watch, and close worker agents in Herdr or Rex.

Core of the agent-workers skill. Subcommands: run, wait, list, roles, close, submit, verify-viewer, detect, check, stats.
Python 3.11+, standard library only. Every command prints JSON on stdout;
errors are one {"error": code, "message": text} object with exit status 1.
"""

from __future__ import annotations

import argparse
import core_backend as core
import fcntl
import hashlib
import json
import math
import os
import re
import rex_backend as rex
import secrets
import shlex
import shutil
import stat
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core_backend import fingerprint as core_fingerprint
from worker_runtime import ALL_HARNESS_PROCESS_NAMES, CONTROLLER_SESSION_ENV, HARNESSES, WORKER_UNSET_ENV, worker_environment

CONFIG_TOP_KEYS = {"max_active_workers", "notify_after_minutes", "workers", "roles"}
WORKER_KEYS = {"harness", "model", "provider", "effort", "args", "description"}
WORKER_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,15}")
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
CONFIG_PROFILE_ENV = "AGENT_WORKERS_PROFILE"
CONFIG_PATH_ENV = "AGENT_WORKERS_CONFIG"
TASK_ID_RE = re.compile(r"t-[0-9a-f]{6}")
MISSING_PANE_CODES = {"pane_not_found", "tab_not_found", "workspace_not_found"}
HERDR_CONTEXT_ENV = ("HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID", "HERDR_SOCKET_PATH")
REX_CONTEXT_ENV = ("REX_SESSION", "REX_BLOCK")

SETTLED_STATES = {
    "done",
    "blocked",
    "not_started",
    "start_failed",
    "exited",
    "result_missing",
    "result_invalid",
    "error",
}
PROBLEM_STATES = SETTLED_STATES - {"done"}

POLL_SECONDS = 2.0
RESULT_FALLBACK_STABLE_SECONDS = 15.0
ACK_TIMEOUT_MS = 15000
START_TIMEOUT_MS = 90000
WORKER_TAB_LABEL = "Workers"
HISTORICAL_CORE_TAB_LABEL = "hcOrch"
PANES_PER_TAB = 4

WORKER_RULES = """\
## Worker rules

- Write your output files first in the task directory or assigned workspace (not harness artifact directories). Write `result.json` last.
- Do not ask the user questions. If something is unclear, write `result.json` with status `blocked` and the question, then stop.
- Do not run `herdr`, `rex`, `agent-workers`, or its `horch` alias.
- You may use your own subagents unless the assignment restricts delegation. Complete a no-delegation assignment yourself.

Write `result.json` at exactly this path:

    {result_path}

It must be one JSON object with exactly these keys:

    {{
      "task_id": "{task_id}",
      "nonce": "{nonce}",
      "status": "completed",
      "summary": "One or two sentences.",
      "files": [],
      "question": null
    }}

`status` is `completed`, `blocked`, or `failed`. `files` lists the output files you wrote, relative to the directory of `result.json`. `question` is required when `status` is `blocked`, else null.
"""


# ---------------------------------------------------------------------------
# output and errors
# ---------------------------------------------------------------------------


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def fail(code, message, herdr_payload=None):
    obj = {"error": code, "message": message}
    if herdr_payload is not None:
        obj["herdr"] = herdr_payload
    emit(obj)
    sys.exit(1)


def require_herdr_env():
    if os.environ.get("HERDR_ENV") != "1":
        fail("not_in_herdr", "agent-workers must run inside a herdr pane (HERDR_ENV is not 1)")


# ---------------------------------------------------------------------------
# herdr CLI
# ---------------------------------------------------------------------------


class HerdrError(Exception):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload


def _read_json_text(text):
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _herdr_message(payload, returncode, stderr):
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message")
            if code and message:
                return f"{code}: {message}"
            return str(code or message or "herdr command failed")
        if isinstance(err, str):
            return err
    return (stderr or "").strip()[:500] or f"herdr exited with status {returncode}"


def herdr(*args, timeout=120.0, env=None, expect_json=True):
    """Run a Herdr command, parsing JSON unless its output is requested as text."""
    argv = ["herdr", *[str(a) for a in args]]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise HerdrError("herdr CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr {args[0]} {args[1]} timed out after {timeout:g}s") from exc
    if proc.returncode != 0:
        parsed = _read_json_text(proc.stderr) or _read_json_text(proc.stdout)
        payload = parsed if isinstance(parsed, dict) else {"raw": (proc.stderr or proc.stdout).strip()[:2000]}
        raise HerdrError(_herdr_message(payload, proc.returncode, proc.stderr), payload)
    if not expect_json:
        return proc.stdout
    parsed = _read_json_text(proc.stdout)
    if not isinstance(parsed, dict):
        raise HerdrError(f"herdr {' '.join(str(a) for a in args)} did not return a JSON object")
    return parsed


def notify(title, body):
    try:
        herdr("notification", "show", title, "--body", body, "--sound", "request", timeout=30.0)
    except HerdrError:
        pass  # a lost notice must never break task handling


# ---------------------------------------------------------------------------
# herdr response accessors (fixed field paths; herdr ids are opaque strings)
# ---------------------------------------------------------------------------


def herdr_path(doc, *path):
    """Follow a known field path into a herdr response, e.g. result.layout.panes."""
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise HerdrError(f"herdr response has no {'.'.join(path)}")
        node = node[key]
    return node


def herdr_id(doc, *path, id_key):
    """Read an id herdr reports either as a plain string or as an object holding id_key."""
    node = herdr_path(doc, *path)
    if isinstance(node, str):
        return node
    if isinstance(node, dict) and isinstance(node.get(id_key), str):
        return node[id_key]
    raise HerdrError(f"herdr response has no {'.'.join(path)} ({id_key})")


# ---------------------------------------------------------------------------
# paths and task store
# ---------------------------------------------------------------------------


# Keep this storage namespace for upgrades from the herdr-orchestrator skill.
def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "herdr-orchestrator"


def config_path(profile=None, config=None):
    if profile is not None and config is not None:
        fail("config_invalid", "cannot pass both --profile and --config")
    if config is not None:
        if not isinstance(config, str) or not config.strip():
            fail("config_invalid", "--config must be a non-empty file path")
        return Path(config).expanduser().resolve()
    if profile is not None:
        if not isinstance(profile, str) or not PROFILE_NAME_RE.fullmatch(profile):
            fail(
                "config_invalid",
                f"invalid profile name {profile!r}; must match [a-z0-9][a-z0-9-]{{0,31}}",
            )
        return config_dir() / f"workers.{profile}.toml"
    return config_dir() / "workers.toml"


def resolve_config(args):
    """Resolve (path, profile) from CLI flags, env vars, or default workers.toml."""
    cli_config = getattr(args, "config", None)
    cli_profile = getattr(args, "profile", None)
    if cli_config is not None and cli_profile is not None:
        fail("config_invalid", "cannot pass both --profile and --config")
    if cli_config is not None:
        return config_path(config=cli_config), None
    if cli_profile is not None:
        return config_path(profile=cli_profile), cli_profile
    env_config = os.environ.get(CONFIG_PATH_ENV)
    env_profile = os.environ.get(CONFIG_PROFILE_ENV)
    if env_config and env_profile:
        fail(
            "config_invalid",
            f"both {CONFIG_PATH_ENV} and {CONFIG_PROFILE_ENV} are set; "
            "unset one or pass --config/--profile",
        )
    if env_config:
        return config_path(config=env_config), None
    if env_profile:
        return config_path(profile=env_profile), env_profile
    return config_path(), None


def list_profiles():
    """Return sorted valid profile names from workers.<name>.toml, or None if unreadable."""
    directory = config_dir()
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return []
    except OSError:
        return None
    profiles = []
    for entry in entries:
        name = entry.name
        if not (name.startswith("workers.") and name.endswith(".toml")):
            continue
        profile = name[len("workers."):-len(".toml")]
        if not PROFILE_NAME_RE.fullmatch(profile):
            continue
        try:
            if entry.is_file():
                profiles.append(profile)
        except OSError:
            continue
    return sorted(profiles)


def tasks_root():
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / "herdr-orchestrator" / "tasks"


def validate_task_id(task_id):
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        fail("invalid_task_id", f"task ID must match t-[0-9a-f]{{6}}: {task_id!r}")


def task_dir(task_id):
    validate_task_id(task_id)
    return tasks_root() / task_id


def worker_label(worker, harness):
    return f"{worker} · {HARNESSES[harness].label}"


@contextmanager
def task_store_lock():
    """Serialize allocation and startup across run/check processes on this store."""
    root = tasks_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".start.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_json(path, obj):
    path = Path(path)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_state():
    return {
        "state": "running",
        "baseline_seq": None,
        "baseline_status_at": None,
        "baseline_status_owner": None,
        "completion_status_at": None,
        "saw_working": False,
        "long_notified": False,
        "closed": False,
        "problem": None,
        "settled_at": None,
        "first_done_at": None,
        "startup_ready": False,
        "submission": None,
        "native_status": None,
        "settled_by": None,
    }


def mark_settled(state):
    """Retain independent first settlement and delivery observations across recheck."""
    observed = iso_now()
    if state["state"] in SETTLED_STATES and not state.get("settled_at"):
        state["settled_at"] = observed
    if state["state"] == "done" and not state.get("first_done_at"):
        state["first_done_at"] = observed


def load_state(directory):
    stored = read_json(directory / "state.json")
    state = default_state()
    if isinstance(stored, dict):
        state.update({key: value for key, value in stored.items() if key in state})
    return state


@contextmanager
def task_state_lock(directory):
    """Serialize short state transactions; never hold across herdr calls."""
    with (directory / ".state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save_state(directory, state):
    with task_state_lock(directory):
        current = load_state(directory)
        merged = dict(current if current["closed"] or current["state"] == "done" else state)
        for key in ("closed", "saw_working", "long_notified"):
            merged[key] = bool(current[key] or state[key])
        for key in ("settled_at", "first_done_at", "settled_by"):
            merged[key] = current[key] or state.get(key)
        mark_settled(merged)
        write_json(directory / "state.json", merged)
        state.update(merged)


class TaskInvalidError(Exception):
    pass


class TaskMissingError(Exception):
    pass


def load_task(directory, task_id):
    path = directory / "task.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TaskMissingError(f"no such task: {task_id}") from exc
    except (OSError, UnicodeDecodeError):
        text = ""
    task = _read_json_text(text)
    required = ("nonce", "worker", "agent", "pane_id", "result_path", "created_at")
    if (not isinstance(task, dict) or task.get("task_id") != task_id
            or any(not isinstance(task.get(key), str) or not task[key] for key in required)
            or ("workspace_id" in task and (
                not isinstance(task["workspace_id"], str) or not task["workspace_id"].strip()))):
        raise TaskInvalidError(f"task {task_id} has an invalid task.json")
    try:
        created = datetime.fromisoformat(task["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as exc:
        raise TaskInvalidError(f"task {task_id} has an invalid created_at in task.json") from exc
    binding = task.get("backend", {"kind": "legacy"})
    if not isinstance(binding, dict) or binding.get("kind") not in ("legacy", "core", "rex"):
        raise TaskInvalidError(f"task {task_id} has an unknown backend")
    if binding["kind"] == "core":
        try:
            core.validate(binding)
            viewer = task.get("viewer")
            if viewer is not None and (not isinstance(viewer, dict) or any(
                    not isinstance(viewer.get(k), str) or not viewer[k]
                    for k in ("pane_id", "tab_id", "socket_path"))
                    or viewer.get("tab_label", HISTORICAL_CORE_TAB_LABEL)
                    not in (WORKER_TAB_LABEL, HISTORICAL_CORE_TAB_LABEL)):
                raise ValueError("invalid core viewer binding")
        except ValueError as exc:
            raise TaskInvalidError(f"task {task_id}: {exc}") from exc
    elif binding["kind"] == "rex":
        try:
            rex.validate(binding)
            agent = "horch-" + task_id[2:]
            branded_label = f"{worker_label(task['worker'], binding['harness'])} · {task['nonce']}"
            if (task["pane_id"] != (binding["block"] or binding["label"])
                    or task.get("workspace_id") != binding["session"]
                    or task.get("harness") != binding["harness"] or task["agent"] != agent
                    or binding["label"] not in (f"{agent}-{task['nonce']}", branded_label)):
                raise ValueError("inconsistent Rex task binding")
        except ValueError as exc:
            raise TaskInvalidError(f"task {task_id}: {exc}") from exc
    return task


def is_core(task):
    return task.get("backend", {}).get("kind") == "core"


def is_rex(task):
    return task.get("backend", {}).get("kind") == "rex"


def all_task_ids():
    root = tasks_root()
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if TASK_ID_RE.fullmatch(d.name) and d.is_dir() and (d / "task.json").is_file()
    )


def active_task_count(workspace_id):
    """Unclosed reservations owned by one workspace, including live legacy panes."""
    return task_capacity(workspace_id)[0]


def task_capacity(workspace_id, binding=None):
    """Count reservations and collect reusable worker tabs in one store scan."""
    active = 0
    legacy_panes = []
    invalid = []
    owned_tabs = {}
    rex_scope = binding is not None and binding["kind"] == "rex"
    herdr_socket = os.environ.get("HERDR_SOCKET_PATH") if workspace_id and not rex_scope else None
    for task_id in all_task_ids():
        directory = task_dir(task_id)
        if load_state(directory)["closed"]:
            continue
        try:
            task = load_task(directory, task_id)
        except TaskMissingError:
            continue  # manual recovery removed the record after enumeration
        except TaskInvalidError:
            active += 1  # unknown owner and pane; reserve a slot in every workspace
            invalid.append(task_id)
            continue
        if rex_scope:
            if not is_rex(task):
                continue
            other = task["backend"]
            if all(other[key] == binding[key] for key in ("host_id", "instance_id", "session")):
                active += 1
                if other["window"] and other["block"]:
                    owned_tabs.setdefault(other["window"], set()).add(other["block"])
        elif is_rex(task):
            continue
        elif binding is not None and is_core(task):
            if task["backend"]["core_id"] == binding["core_id"]:
                active += 1
                viewer = task.get("viewer")
                if (viewer and herdr_socket and viewer["socket_path"] == herdr_socket
                        and task.get("workspace_id") == workspace_id
                        and viewer.get("tab_label") == WORKER_TAB_LABEL):
                    owned_tabs.setdefault(viewer["tab_id"], set()).add(viewer["pane_id"])
        elif binding is not None and workspace_id is None:
            continue
        elif is_core(task):
            if task.get("workspace_id") == workspace_id:
                active += 1
        elif "workspace_id" not in task:
            legacy_panes.append(task["pane_id"])
        elif task["workspace_id"] == workspace_id:
            active += 1
            tab_id = task.get("tab_id")
            legacy = task.get("backend", {})
            if (binding is None and isinstance(tab_id, str)
                    and "socket_path" in legacy and legacy["socket_path"] == herdr_socket):
                owned_tabs.setdefault(tab_id, set()).add(task["pane_id"])
    if legacy_panes:
        panes = {pane_id for pane_id, _ in workspace_panes(workspace_id)}
        active += sum(pane_id in panes for pane_id in legacy_panes)
    return active, invalid, owned_tabs


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def load_config(path=None, *, profile=None):
    path = config_path(profile=profile) if path is None else Path(path)
    try:
        st = path.stat()
    except PermissionError:
        fail(
            "config_invalid",
            f"cannot access {path.name} at {path} (permission denied; if running inside a "
            "terminal sandbox, rerun agent-workers outside the sandbox)",
        )
    except FileNotFoundError:
        extra = ""
        if profile is not None:
            available = list_profiles()
            if available:
                extra = f" (available profiles: {', '.join(available)})"
            elif available == []:
                extra = " (no profiles found in config directory)"
        fail(
            "config_invalid",
            f"{path.name} not found at {path}{extra} (if running inside a terminal sandbox that "
            "restricts access outside the workspace, rerun agent-workers outside the sandbox "
            "before assuming setup is missing)",
        )
    except OSError as exc:
        fail("config_invalid", f"cannot access {path}: {exc}")
    if not stat.S_ISREG(st.st_mode):
        fail("config_invalid", f"{path.name} is not a regular file at {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except PermissionError:
        fail(
            "config_invalid",
            f"cannot read {path.name} at {path} (permission denied; if running inside a "
            "terminal sandbox, rerun agent-workers outside the sandbox)",
        )
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        fail("config_invalid", f"cannot parse {path}: {exc}")

    unknown = sorted(set(data) - CONFIG_TOP_KEYS)
    if unknown:
        fail("config_invalid", f"unknown top-level keys in {path.name}: {', '.join(unknown)}")

    def int_key(key, default, minimum):
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            fail("config_invalid", f"{key} must be an integer >= {minimum}")
        return value

    max_active = int_key("max_active_workers", 4, 0)
    notify_minutes = int_key("notify_after_minutes", 180, 1)

    workers_table = data.get("workers", {})
    if not isinstance(workers_table, dict):
        fail("config_invalid", "[workers] must be a table")
    workers = {}
    for name, spec in workers_table.items():
        if not isinstance(spec, dict):
            fail("config_invalid", f"worker {name!r} must be a table")
        if not WORKER_NAME_RE.fullmatch(name):
            fail("config_invalid", f"worker name {name!r} must match [a-z][a-z0-9-]{{0,15}}")
        unknown = sorted(set(spec) - WORKER_KEYS)
        if unknown:
            fail("config_invalid", f"worker {name!r} has unknown keys: {', '.join(unknown)}")
        if "description" in spec and not isinstance(spec["description"], str):
            fail("config_invalid", f"worker {name!r} description must be a string")
        harness = spec.get("harness")
        if not isinstance(harness, str) or harness not in HARNESSES:
            fail("config_invalid", f"worker {name!r} needs harness set to one of: {', '.join(HARNESSES)}")
        model = spec.get("model")
        if not isinstance(model, str) or not model.strip():
            fail("config_invalid", f"worker {name!r} needs a non-empty model")
        provider = spec.get("provider")
        if provider is not None:
            if not isinstance(provider, str) or not provider.strip():
                fail("config_invalid", f"worker {name!r} provider must be a non-empty string")
            if not HARNESSES[harness].provider_flag:
                fail("config_invalid", f"worker {name!r} sets provider, which only the pi harness accepts")
        effort = spec.get("effort")
        if effort is not None and (not isinstance(effort, str) or not effort.strip()):
            fail("config_invalid", f"worker {name!r} effort must be a non-empty string")
        extra = spec.get("args", [])
        if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
            fail("config_invalid", f"worker {name!r} args must be a list of strings")
        workers[name] = {
            "harness": harness,
            "model": model,
            "provider": provider,
            "effort": effort,
            "args": extra,
            "description": spec.get("description"),
        }
    return {"max_active_workers": max_active, "notify_after_minutes": notify_minutes,
            "workers": workers, "roles": data.get("roles", {}),
            "config_path": str(path), "profile": profile}


# ---------------------------------------------------------------------------
# agents, panes, placement
# ---------------------------------------------------------------------------


def agent_index():
    """Map live agent name to its herdr entry, or None when herdr cannot be polled."""
    try:
        agents = herdr_path(herdr("agent", "list", timeout=30.0), "result", "agents")
    except HerdrError:
        return None
    if not isinstance(agents, list):
        return None
    index = {}
    for agent in agents:
        name = agent.get("name") if isinstance(agent, dict) else None
        if isinstance(name, str):  # herdr also lists unnamed pane agents
            index[name] = agent
    return index


def workspace_panes(workspace):
    """(pane_id, tab_id) pairs for every pane of a workspace, read from result.panes."""
    panes = herdr_path(herdr("pane", "list", "--workspace", workspace, timeout=30.0), "result", "panes")
    pairs = []
    for pane in panes:
        pane_id = pane.get("pane_id") if isinstance(pane, dict) else None
        tab_id = pane.get("tab_id") if isinstance(pane, dict) else None
        if not isinstance(pane_id, str) or not isinstance(tab_id, str):
            raise HerdrError("herdr pane list has a pane without pane_id or tab_id")
        pairs.append((pane_id, tab_id))
    return pairs


def herdr_error_code(exc):
    error = exc.payload.get("error") if isinstance(exc.payload, dict) else None
    return error.get("code") if isinstance(error, dict) else None


def close_pane(pane_id, *, socket_path=None):
    """Close the authoritative pane, independent of the caller's workspace."""
    env = dict(os.environ, HERDR_SOCKET_PATH=socket_path) if socket_path else None
    try:
        pane = herdr_path(herdr("pane", "get", pane_id, timeout=30.0, env=env), "result", "pane")
    except HerdrError as exc:
        if herdr_error_code(exc) in MISSING_PANE_CODES:
            return "already_gone"
        raise
    target = pane.get("pane_id") if isinstance(pane, dict) else None
    if not isinstance(target, str) or not target:
        raise HerdrError("herdr pane get has a pane without pane_id")
    try:
        herdr("pane", "close", target, timeout=30.0, env=env)
    except HerdrError as exc:
        if herdr_error_code(exc) in MISSING_PANE_CODES:
            return "already_gone"  # it vanished after pane get
        raise
    return "closed"


def widest_pane_id(any_pane_id):
    """Pane with the largest rect area of that tab; first in list order on a tie."""
    panes = herdr_path(herdr("pane", "layout", "--pane", any_pane_id, timeout=30.0), "result", "layout", "panes")
    best_id, best_area = None, -1
    for pane in panes:
        pane_id = pane.get("pane_id") if isinstance(pane, dict) else None
        rect = pane.get("rect") if isinstance(pane, dict) else None
        width = rect.get("width") if isinstance(rect, dict) else None
        height = rect.get("height") if isinstance(rect, dict) else None
        if not isinstance(pane_id, str) or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            raise HerdrError("herdr pane layout has a pane without pane_id or rect size")
        if width * height > best_area:
            best_id, best_area = pane_id, width * height
    if best_id is None:
        raise HerdrError("herdr pane layout lists no panes")
    return best_id


def split_pane(source, direction, cwd):
    doc = herdr("pane", "split", source, "--direction", direction, "--cwd", str(cwd), "--no-focus", timeout=60.0)
    return herdr_id(doc, "result", "pane", id_key="pane_id")


def place_pane(workspace, cwd, caller_tab, owned_tabs):
    """Place a fresh worker pane in a tab owned by this backend."""
    tabs = herdr_path(herdr("tab", "list", "--workspace", workspace, timeout=30.0), "result", "tabs")
    panes = workspace_panes(workspace)
    for tab in tabs:
        tab_id = tab.get("tab_id") if isinstance(tab, dict) else None
        if (not isinstance(tab_id, str) or tab_id == caller_tab or tab_id not in owned_tabs
                or tab.get("label") != WORKER_TAB_LABEL):
            continue
        count = tab.get("pane_count")
        if not isinstance(count, int) or count < 1 or count >= PANES_PER_TAB:
            continue
        ids = [pane_id for pane_id, pane_tab in panes if pane_tab == tab_id]
        if len(ids) != count or not set(ids).issubset(owned_tabs[tab_id]):
            continue
        if count == 1:
            return split_pane(ids[0], "right", cwd), tab_id
        return split_pane(widest_pane_id(ids[0]), "down", cwd), tab_id

    doc = herdr(
        "tab", "create",
        "--workspace", workspace,
        "--cwd", str(cwd),
        "--label", WORKER_TAB_LABEL,
        "--no-focus",
        timeout=60.0,
    )
    return herdr_id(doc, "result", "root_pane", id_key="pane_id"), herdr_id(doc, "result", "tab", id_key="tab_id")


def label_worker_pane(pane_id, worker, harness):
    try:
        herdr("pane", "rename", pane_id, worker_label(worker, harness), timeout=5.0)
    except HerdrError:
        pass  # display labels do not affect worker execution


# ---------------------------------------------------------------------------
# launch arguments and brief
# ---------------------------------------------------------------------------


def launch_args(worker, directory):
    spec = HARNESSES[worker["harness"]]
    args = []
    if spec.provider_flag and worker["provider"]:
        args += [spec.provider_flag, worker["provider"]]
    args += [spec.model_flag, worker["model"]]
    if worker["effort"]:
        args += [arg.format(effort=worker["effort"]) for arg in spec.effort_args]
    if spec.add_task_dir:
        args += ["--add-dir", str(directory)]
    return args + list(worker["args"])


def native_launch_args(worker, directory, backend):
    args = launch_args(worker, directory)
    spec = HARNESSES[worker["harness"]]
    if spec.native_no_daemon:
        if any(arg == "--daemon" or arg.startswith(("--daemon=", "--no-daemon=")) for arg in args):
            fail("config_invalid", f"{backend} {spec.label} requires --no-daemon; conflicting daemon arguments were not changed")
        if "--no-daemon" not in args:
            args.append("--no-daemon")
    return args


def write_brief(directory, controller_brief, task_id, nonce):
    text = controller_brief.rstrip("\n") + "\n\n" + WORKER_RULES.format(
        result_path=directory / "result.json", task_id=task_id, nonce=nonce
    )
    (directory / "brief.md").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def resolve_cwd(raw):
    try:
        cwd = Path(raw or os.getcwd()).resolve(strict=True)
    except OSError:
        cwd = None
    if cwd is None or not cwd.is_dir():
        fail("cwd_not_found", f"--cwd is not a directory: {raw}")
    return cwd


def process_ancestors(stop_at=None):
    """Return pids up to the terminal child, when present, or init."""
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                                 text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    parents = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = int(fields[1])
    chain, pid = set(), os.getpid()
    while pid > 1 and pid in parents and pid not in chain:
        chain.add(pid)
        if pid == stop_at:
            break
        pid = parents[pid]
    return chain


def pane_process_info(pane_id, *, env=None):
    return herdr_path(herdr("pane", "process-info", "--pane", pane_id, timeout=30.0, env=env),
                      "result", "process_info")


def pane_owning_process(ancestors):
    """Return the pane whose shell is an ancestor of this process, if any."""
    for pane in herdr_path(herdr("pane", "list", timeout=30.0), "result", "panes"):
        try:
            if pane_process_info(pane["pane_id"]).get("shell_pid") in ancestors:
                return pane["pane_id"]
        except HerdrError:
            continue  # a pane closed during the scan cannot own this process
    return None


def expected_process_names(harnesses):
    return {name for harness in harnesses for name in HARNESSES[harness].process_names}


def controller_process_ancestor(ancestors):
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,comm="], capture_output=True,
                                 text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return any(len(fields := line.split()) == 2 and fields[0].isdigit()
               and int(fields[0]) in ancestors and Path(fields[1]).name in ALL_HARNESS_PROCESS_NAMES
               for line in listing.splitlines())


def visible_text(pane_id, *, env=None):
    return herdr("pane", "read", pane_id, "--source", "visible", timeout=30,
                 env=env, expect_json=False)


def caller_verification(pane, info, method, text):
    return dict(pane, controller_verification={
        "pane_id": pane["pane_id"], "workspace_id": pane["workspace_id"],
        "tab_id": pane["tab_id"], "cwd": str(Path.cwd().resolve()),
        "shell_pid": info.get("shell_pid"), "method": method,
        "controller_processes": [{"pid": p["pid"], "name": p["name"]}
                                 for p in info.get("foreground_processes") or []
                                 if p.get("name") in ALL_HARNESS_PROCESS_NAMES and isinstance(p.get("pid"), int)],
        "screen_sha256": hashlib.sha256(text.encode()).hexdigest(), "verified_at": iso_now(),
    })


def _same_cwd(raw_cwd, target_cwd):
    if not raw_cwd:
        return False
    try:
        return Path(raw_cwd).resolve() == target_cwd
    except OSError:
        return False


def _herdr_session_mismatch(pane, controllers):
    session = pane.get("agent_session") if isinstance(pane.get("agent_session"), dict) else {}
    for harness in controllers:
        own = os.environ[CONTROLLER_SESSION_ENV[harness]]
        spec = HARNESSES[harness]
        session_agents = (harness, *spec.process_names, *spec.legacy_session_aliases)
        if session.get("agent") in session_agents and session.get("value") and session["value"] != own:
            return harness, session["value"], own
    return None


def _pane_has_live_ids(pane):
    return isinstance(pane, dict) and all(
        isinstance(pane.get(key), str) and pane[key].strip()
        for key in ("pane_id", "tab_id", "workspace_id")
    )


def require_caller_context(claimed=None, caller_text=None):
    """Prove the conversation's live pane, independently of a daemon's process host.

    Agent controllers require unique screen evidence even when their daemon
    remains a descendant of its original pane's shell. When --caller-text is
    supplied without --caller-pane, live panes running an expected harness in
    this cwd are scanned and accepted iff exactly one matches. Ordinary shell
    automation can use its actual pane ancestry.
    """
    guidance = ("Confirm the controller's pane from its own process or session, never from UI focus, "
                "e.g. pass --caller-text '<16+ unique visible chars from your status line>', "
                "and see caller context in references/setup.md.")
    controllers = [h for h, var in CONTROLLER_SESSION_ENV.items() if os.environ.get(var)]
    expected = controllers or list(HARNESSES)
    expected_names = expected_process_names(expected)
    cwd = Path.cwd().resolve()

    # Auto-resolve controller pane from --caller-text when --caller-pane is omitted.
    if claimed is None and caller_text is not None:
        if len(caller_text.strip()) < 16:
            fail("caller_context_invalid",
                 "Agent-controller dispatch requires --caller-text with at least 16 characters unique to this "
                 "conversation's visible screen.")
        needle = " ".join(caller_text.split())
        matches = []
        checked = 0
        for candidate in herdr_path(herdr("pane", "list", timeout=30.0), "result", "panes"):
            candidate_id = candidate.get("pane_id") if isinstance(candidate, dict) else None
            if not isinstance(candidate_id, str) or not candidate_id.strip():
                continue
            try:
                candidate_info = pane_process_info(candidate_id)
            except HerdrError as exc:
                if herdr_error_code(exc) in MISSING_PANE_CODES:
                    continue
                raise
            foreground = candidate_info.get("foreground_processes") or []
            if not any(p.get("name") in expected_names and _same_cwd(p.get("cwd"), cwd) for p in foreground):
                continue
            try:
                candidate_pane = herdr_path(
                    herdr("pane", "current", "--pane", candidate_id, timeout=30.0), "result", "pane"
                )
            except HerdrError as exc:
                if herdr_error_code(exc) in MISSING_PANE_CODES:
                    continue
                raise
            if not _pane_has_live_ids(candidate_pane):
                continue
            if _herdr_session_mismatch(candidate_pane, controllers) is not None:
                continue
            try:
                text = visible_text(candidate_pane["pane_id"])
            except HerdrError as exc:
                if herdr_error_code(exc) in MISSING_PANE_CODES:
                    continue
                raise
            checked += 1
            if needle in " ".join(text.split()):
                matches.append((candidate_pane, candidate_info, text))
        if len(matches) != 1:
            fail("caller_context_invalid",
                 f"Conversation text must match exactly one live controller pane in this cwd; "
                 f"checked {checked} candidate pane(s), matching panes: {[m[0]['pane_id'] for m in matches]} "
                 f"(prefer unwrapped plain text such as the status line). {guidance}")
        pane, info, screen = matches[0]
        return caller_verification(pane, info, "conversation_text", screen)

    source = "--caller-pane" if claimed is not None else "HERDR_PANE_ID"
    pane_id = claimed if claimed is not None else os.environ.get("HERDR_PANE_ID")
    # Herdr can fall back to UI focus when the caller pane ID is blank.
    if not pane_id or not pane_id.strip():
        fail("caller_context_invalid", f"Controller pane ID is missing. {guidance}")
    try:
        pane = herdr_path(herdr("pane", "current", "--pane", pane_id, timeout=30.0), "result", "pane")
    except HerdrError as exc:
        if herdr_error_code(exc) not in MISSING_PANE_CODES:
            raise
        fail("caller_context_invalid", f"Controller pane {pane_id!r} is no longer available. {guidance}")
    if not _pane_has_live_ids(pane):
        fail("caller_context_invalid", f"Controller context is missing live Herdr IDs. {guidance}")

    info = pane_process_info(pane["pane_id"])
    ancestors = process_ancestors()
    needs_screen = bool(controllers) or controller_process_ancestor(ancestors) or caller_text is not None
    if info.get("shell_pid") in ancestors and not needs_screen:
        return caller_verification(pane, info, "process_ancestry", visible_text(pane["pane_id"]))
    owner = pane_owning_process(ancestors)
    if owner is not None and not needs_screen:
        fail("caller_context_invalid",
             f"{source} names pane {pane_id!r}, but agent-workers runs inside pane {owner!r}. "
             f"Rerun with HERDR_PANE_ID={owner} if that pane is this controller. {guidance}")
    if claimed is None:
        fail("caller_context_invalid",
             f"HERDR_PANE_ID={pane_id!r} cannot prove this conversation's pane; "
             "a shared daemon may inherit another pane's environment and ancestry. "
             f"Pass --caller-text <unique-text> (or --caller-pane <pane-id> --caller-text <unique-text>). {guidance}")

    names = {p.get("name") for p in info.get("foreground_processes") or [] if isinstance(p, dict)}
    if not names.intersection(expected_names):
        fail("caller_context_invalid",
             f"--caller-pane {pane_id!r} is not running {' or '.join(expected)} in its foreground "
             f"(found: {', '.join(sorted(n for n in names if n)) or 'nothing'}). {guidance}")
    mismatch = _herdr_session_mismatch(pane, controllers)
    if mismatch is not None:
        harness, reported_session, own = mismatch
        fail("caller_context_invalid",
             f"--caller-pane {pane_id!r} reports {harness} session {reported_session!r}, "
             f"not this controller's {own!r}. {guidance}")
    if not caller_text or len(caller_text.strip()) < 16:
        fail("caller_context_invalid",
             "Agent-controller dispatch requires --caller-text with at least 16 characters unique to this "
             "conversation's visible screen, alongside --caller-pane. Session IDs alone are insufficient.")
    foreground = info.get("foreground_processes") or []
    if not any(p.get("name") in expected_names and _same_cwd(p.get("cwd"), cwd) for p in foreground):
        fail("caller_context_invalid", "Controller foreground cwd does not match this conversation's cwd. " + guidance)
    needle = " ".join(caller_text.split())
    matches = []
    screen = None
    for candidate in herdr_path(herdr("pane", "list", timeout=30), "result", "panes"):
        candidate_id = candidate["pane_id"]
        candidate_info = pane_process_info(candidate_id)
        if not any(p.get("name") in expected_names for p in candidate_info.get("foreground_processes") or []):
            continue
        text = visible_text(candidate_id)
        if needle in " ".join(text.split()):
            matches.append(candidate_id)
            if candidate_id == pane["pane_id"]:
                screen = text
    if matches != [pane["pane_id"]]:
        fail("caller_context_invalid",
             f"Conversation text must match only the claimed controller pane; matching panes: {matches}. {guidance}")
    return caller_verification(pane, info, "conversation_text", screen)


def has_herdr_context():
    return os.environ.get("HERDR_ENV") == "1" or any(os.environ.get(key) for key in HERDR_CONTEXT_ENV)


def controller_family(args):
    """Select a controller candidate. Dispatch verifies the live location separately."""
    if getattr(args, "caller_block", None) is not None:
        return "rex"
    if getattr(args, "caller_pane", None) is not None:
        return "herdr"
    herdr_context = has_herdr_context()
    rex_context = any(os.environ.get(key) for key in REX_CONTEXT_ENV)
    if herdr_context and rex_context:
        fail("caller_context_conflict", "Both Rex and Herdr context are present. Confirm the controller and "
             "pass --caller-block or --caller-pane, with --caller-text for an agent controller.")
    if rex_context:
        return "rex"
    return "herdr" if herdr_context or getattr(args, "caller_text", None) is not None else "headless"


def core_caller_context(claimed=None, caller_text=None):
    """Require a viewer for Herdr callers, even when HERDR_ENV was dropped."""
    if claimed is None and caller_text is None and not has_herdr_context():
        return None
    caller = require_caller_context(claimed, caller_text)
    if not os.environ.get("HERDR_SOCKET_PATH", "").strip():
        fail("caller_context_invalid",
             "Herdr viewer requires HERDR_SOCKET_PATH before worker launch. "
             "Restore the controller's endpoint; do not bypass placement by clearing Herdr context.")
    return caller


def rex_foreground_harness(process, expected):
    foreground = process.get("foreground") or {}
    names = expected_process_names(expected)
    return any(Path(foreground.get(key) or "").name in names
               for key in ("name", "argv0", "invoked_path"))


def _rex_screen_matches(binding, block_id, needle):
    """Match caller text against visible screen, falling back to soft-unwrapped lines."""
    screen = rex.capture(binding, block_id, visible=True)
    if needle in " ".join(screen.split()):
        return True, screen
    unwrapped = rex.capture(binding, block_id, visible=True, unwrap=True)
    if needle in " ".join(unwrapped.split()):
        return True, unwrapped
    return False, screen


def require_rex_context(claimed, caller_text):
    """Prove the caller with its local process tree or conversation screen evidence."""
    guidance = ("Confirm the controller's full Rex block ID or pass "
                "--caller-text '<16+ unique visible chars from your status line>'. "
                "Agent-controller tools require --caller-text (optionally with --caller-block <id>).")
    controllers = [h for h, var in CONTROLLER_SESSION_ENV.items() if os.environ.get(var)]
    expected = controllers or HARNESSES
    cwd = Path.cwd().resolve()

    # Auto-resolve controller block from --caller-text when --caller-block is omitted.
    if claimed is None and caller_text is not None:
        if len(caller_text.strip()) < 16:
            fail("caller_context_invalid",
                 f"Rex caller proof requires --caller-text with at least 16 characters unique to this "
                 f"conversation's visible screen. {guidance}")
        base_binding = rex.new_binding()
        blocks = rex.blocks(base_binding, all_sessions=True)
        needle = " ".join(caller_text.split())
        matches = []
        checked = 0
        for candidate in blocks:
            if (not candidate.get("window_id") or candidate.get("host_id") != base_binding["host_id"]
                    or candidate.get("creator_name") != rex.TERMINAL):
                continue
            candidate_id = candidate["block_id"]
            candidate_binding = dict(base_binding, session=candidate["session_id"])
            try:
                candidate_process = rex.block_process(candidate_binding, candidate_id)
            except rex.RexError as exc:
                if exc.kind == "target_not_found":
                    continue
                raise
            candidate_cwd = (candidate_process.get("foreground") or {}).get("cwd")
            if not _same_cwd(candidate_cwd, cwd) or not rex_foreground_harness(candidate_process, expected):
                continue
            try:
                matched, screen = _rex_screen_matches(candidate_binding, candidate_id, needle)
            except rex.RexError as exc:
                if exc.kind == "target_not_found":
                    continue
                raise
            checked += 1
            if matched:
                matches.append((candidate, candidate_binding, candidate_process, screen))
        if len(matches) != 1:
            fail("caller_context_invalid",
                 f"Conversation text must match exactly one Rex controller block in this cwd; "
                 f"checked {checked} candidate block(s), matches: {[m[0]['block_id'] for m in matches]} "
                 f"(prefer unwrapped plain text such as the status line). {guidance}")
        caller, binding, process, screen = matches[0]
        block_id = caller["block_id"]
        child, foreground = process.get("child") or {}, process.get("foreground") or {}
        screen_hash = hashlib.sha256(screen.encode()).hexdigest()
        return {"binding": binding, "block_id": block_id, "window_id": caller["window_id"],
                "workspace_id": binding["session"], "controller_verification": {
                    "session_id": binding["session"], "window_id": caller["window_id"], "block_id": block_id,
                    "child_pid": child.get("pid"), "foreground_pid": foreground.get("pid"),
                    "cwd": str(cwd), "method": "conversation_text", "screen_sha256": screen_hash, "verified_at": iso_now(),
                }}

    block_id = claimed if claimed is not None else os.environ.get("REX_BLOCK", "")
    session_id = os.environ.get("REX_SESSION", "")
    if not rex.full_id(block_id, "block") or (claimed is None and not rex.full_id(session_id, "session")):
        fail("caller_context_invalid", f"Rex caller context is incomplete. {guidance}")

    binding = dict(rex.new_binding(), session=session_id)
    blocks = rex.blocks(binding, all_sessions=claimed is not None)
    match = [block for block in blocks if block["block_id"] == block_id]
    if len(match) != 1 or not match[0].get("window_id") or match[0].get("host_id") != binding["host_id"]:
        fail("caller_context_invalid", f"Rex controller block {block_id!r} is not placed on the local server. {guidance}")
    caller = match[0]
    binding["session"] = caller["session_id"]
    process = rex.block_process(binding, block_id)
    child, foreground = process.get("child") or {}, process.get("foreground") or {}
    ancestors = process_ancestors(stop_at=child.get("pid"))
    needs_screen = bool(controllers) or controller_process_ancestor(ancestors) or caller_text is not None
    screen_hash = None
    if child.get("pid") in ancestors and not needs_screen:
        method = "process_ancestry"
    else:
        if (claimed is None or not caller_text or len(caller_text.strip()) < 16
                or not rex_foreground_harness(process, expected)
                or not _same_cwd(foreground.get("cwd"), cwd)):
            fail("caller_context_invalid", f"Rex caller proof requires an explicit block, its foreground harness "
                 f"in the conversation cwd, and unique visible text. {guidance}")
        needle = " ".join(caller_text.split())
        matches = []
        for candidate in blocks:
            if (not candidate.get("window_id") or candidate.get("host_id") != binding["host_id"]
                    or candidate.get("creator_name") != caller.get("creator_name")):
                continue
            candidate_id = candidate["block_id"]
            candidate_binding = dict(binding, session=candidate["session_id"])
            candidate_process = process if candidate_id == block_id else rex.block_process(candidate_binding, candidate_id)
            candidate_cwd = (candidate_process.get("foreground") or {}).get("cwd")
            if (not _same_cwd(candidate_cwd, cwd)
                    or not rex_foreground_harness(candidate_process, expected)):
                continue
            matched, screen = _rex_screen_matches(candidate_binding, candidate_id, needle)
            if matched:
                matches.append(candidate_id)
                if candidate_id == block_id:
                    screen_hash = hashlib.sha256(screen.encode()).hexdigest()
        if matches != [block_id]:
            fail("caller_context_invalid", f"Conversation text must match only the claimed Rex block; matches: {matches}. {guidance}")
        method = "conversation_text"
    return {"binding": binding, "block_id": block_id, "window_id": caller["window_id"],
            "workspace_id": binding["session"], "controller_verification": {
                "session_id": binding["session"], "window_id": caller["window_id"], "block_id": block_id,
                "child_pid": child.get("pid"), "foreground_pid": foreground.get("pid"),
                "cwd": str(cwd), "method": method, "screen_sha256": screen_hash, "verified_at": iso_now(),
            }}


def dispatch_context(args):
    if controller_family(args) == "rex":
        return require_rex_context(args.caller_block, args.caller_text), None
    binary = core.executable()
    if binary is None:
        require_herdr_env()
        caller = require_caller_context(args.caller_pane, args.caller_text)
    else:
        caller = core_caller_context(args.caller_pane, args.caller_text)
    return caller, binary


def cmd_run(args):
    if args.max_seconds is not None and not args.wait:
        fail("invalid_arguments", "--max-seconds on run requires --wait")
    if args.max_seconds is not None and args.max_seconds < 0:
        fail("invalid_arguments", "--max-seconds must be a non-negative integer")
    caller, binary = dispatch_context(args)
    cfg_path, cfg_profile = resolve_config(args)
    config = load_config(cfg_path, profile=cfg_profile)
    if args.brief == "-":
        brief_text = sys.stdin.read()
        if not brief_text.strip():
            fail("brief_empty", "brief from stdin is empty")
    else:
        brief_source = Path(args.brief).expanduser()
        try:
            brief_source = brief_source.resolve(strict=True)
        except OSError:
            brief_source = None
        if brief_source is None or not brief_source.is_file():
            fail("brief_not_found", f"brief file not found: {args.brief}")
        brief_text = brief_source.read_text(encoding="utf-8", errors="replace")
    worker = config["workers"].get(args.worker)
    binding = caller.get("binding") if caller else None
    if binding is None and binary is None and worker is not None:
        require_legacy_integrations((worker["harness"],))
    if binary:
        binding = core.new_binding(binary)
    launched = start_task(config, args.worker, brief_text, resolve_cwd(args.cwd),
                          caller_pane=args.caller_pane, caller_text=args.caller_text, binding=binding, caller=caller)
    emit(launched)
    if args.wait:
        info = make_info(launched["task_id"])
        wait_until_change([info], config, args.max_seconds)
        emit(wait_line(info))


def start_task(config, worker_name, brief_text, cwd, *, skip_if_full=False,
               caller_pane=None, caller_text=None, binding=None, caller=None):
    # Hold task_store_lock() only during capacity check, reservation, and placement;
    # release it before waiting on harness readiness, viewer verification, and prompt ack.
    if binding is not None and binding["kind"] == "rex":
        return start_rex_task(config, worker_name, brief_text, cwd, skip_if_full, caller)
    if binding is not None:
        return start_core_task(config, worker_name, brief_text, cwd, skip_if_full,
                               caller_pane, caller_text, binding, caller=caller)
    return start_legacy_task(config, worker_name, brief_text, cwd, skip_if_full,
                             caller_pane, caller_text, caller=caller)


def core_agent(terminal):
    if terminal is None or terminal.get("state") != "live":
        return None
    return {"agent_status": core.status(terminal), "completion_seq": terminal.get("turn")}


def close_task_resources(task):
    if is_rex(task):
        return rex.close(task["backend"])
    if not is_core(task):
        return {"pane": close_pane(task["pane_id"])}
    outcome = core.close(task["backend"])
    viewer = task.get("viewer")
    if task.get("viewer_unresolved"):
        raise HerdrError("viewer placement outcome is unknown; inspect the recorded viewer endpoint before releasing this reservation")
    outcome["viewer"] = (close_pane(viewer["pane_id"], socket_path=viewer["socket_path"])
                         if viewer else "not_created")
    return outcome


def verify_viewer(task):
    task["viewer_verified"] = False
    task["viewer_verification_error"] = None
    task.pop("viewer_verification", None)
    viewer = task.get("viewer")
    if not viewer:
        task["viewer_verification_error"] = "viewer was not created" if task.get("controller_verification") else "headless controller"
        return
    if not task.get("controller_verification"):
        task["viewer_verification_error"] = "historical task has no controller verification; inspect it and use a fresh verified run after deciding recovery"
        task["viewer_warning"] = task["viewer_verification_error"]
        return
    env = dict(os.environ, HERDR_SOCKET_PATH=viewer["socket_path"])
    deadline = time.monotonic() + 5
    while True:
        try:
            controller = task["controller_verification"]
            caller = herdr_path(herdr("pane", "get", controller["pane_id"], env=env), "result", "pane")
            controller_info = pane_process_info(caller["pane_id"], env=env)
            if controller_info.get("shell_pid") != controller["shell_pid"]:
                raise HerdrError("controller process identity changed; confirm the controller again")
            processes = controller.get("controller_processes") or []
            live = controller_info.get("foreground_processes") or []
            if processes and not all(any(p.get("pid") == saved["pid"] and p.get("name") == saved["name"]
                                         for p in live) for saved in processes):
                raise HerdrError("controller harness process changed; confirm the controller again")
            pane = herdr_path(herdr("pane", "get", viewer["pane_id"], env=env), "result", "pane")
            tab = herdr_path(herdr("tab", "get", pane["tab_id"], env=env), "result", "tab")
            expected_label = viewer.get("tab_label", HISTORICAL_CORE_TAB_LABEL)
            if (pane["workspace_id"] != caller["workspace_id"]
                    or tab["workspace_id"] != caller["workspace_id"]
                    or pane["tab_id"] == caller["tab_id"] or pane["tab_id"] != viewer["tab_id"]
                    or tab.get("label") != expected_label):
                raise HerdrError(f"viewer is outside the live controller workspace or its separate {expected_label} tab")
            binding = task["backend"]
            info = pane_process_info(pane["pane_id"], env=env)
            argv = [binding["executable"], "attach", binding["terminal"]]
            attach = next((p for p in info.get("foreground_processes") or [] if p.get("argv") == argv), None)
            if attach is None:
                raise HerdrError("viewer foreground is not the pinned core terminal's attach")
            terminal = core.get(binding)
            if terminal is None or terminal["state"] != "live":
                raise HerdrError("core terminal is no longer live")
            native = core.call(binding, "terminal.read", terminal=binding["terminal"], lines=0)["text"]
            screen = visible_text(pane["pane_id"], env=env)
            rendered = " ".join(screen.split())
            lines = [" ".join(line.split()) for line in native.splitlines()]
            if not any(len(line) >= 8 and line in rendered for line in lines):
                raise HerdrError("viewer has not rendered recognizable output from the pinned terminal")
            task["viewer_verified"] = True
            task["viewer_verification_error"] = None
            task["viewer_verification"] = {
                "verified_at": iso_now(), "pane_id": pane["pane_id"], "tab_id": pane["tab_id"],
                "workspace_id": caller["workspace_id"], "attach_pid": attach["pid"],
                "terminal_id": binding["terminal"], "core_id": binding["core_id"],
                "screen_sha256": hashlib.sha256(screen.encode()).hexdigest(),
            }
            task.pop("viewer_warning", None)
            return
        except (HerdrError, core.CoreError) as exc:
            task["viewer_verification_error"] = str(exc)
            if time.monotonic() >= deadline:
                task["viewer_warning"] = "worker retained; viewer visibility unconfirmed: " + str(exc)
                return
            time.sleep(0.2)


def progress_fields(state):
    return {"startup_ready": state["startup_ready"], "submission": state["submission"],
            "execution_observed": state["saw_working"], "native_status": state["native_status"]}


def viewer_fields(task):
    return {"viewer": task.get("viewer"), "viewer_verified": bool(task.get("viewer_verified")),
            "viewer_verification_error": task.get("viewer_verification_error"),
            "warning": task.get("viewer_warning")}


def persist_viewer_verification(directory, task):
    """Merge viewer verification fields into task.json under the per-task lock."""
    with task_state_lock(directory):
        stored = load_task(directory, task["task_id"])
        for key in ("viewer_verified", "viewer_verification_error", "viewer_verification", "viewer_warning"):
            if key in task:
                stored[key] = task[key]
            else:
                stored.pop(key, None)
        write_json(directory / "task.json", stored)
        task.update(stored)


def abort_starting_state(directory, state, reason):
    """Avoid stranding a task in state='starting' if phase 2 is interrupted."""
    if state["state"] == "starting" and not state["closed"]:
        state["state"] = "start_failed"
        state["problem"] = reason
        save_state(directory, state)


def cmd_verify_viewer(args):
    directory = task_dir(args.task_id)
    task = load_task(directory, args.task_id)
    if not is_core(task):
        fail("invalid_arguments", "verify-viewer requires a core task")
    verify_viewer(task)
    persist_viewer_verification(directory, task)
    emit({"task_id": args.task_id, **viewer_fields(task)})


def prepare_send(directory, task, read_screen, blocked_error):
    """Check visible startup blockers before recording a send attempt."""
    harness = task.get("harness")
    spec = HARNESSES.get(harness) if isinstance(harness, str) else None
    if spec and spec.screen_blocker:
        screen = " ".join(read_screen().split()).lower()
        if spec.screen_blocker in screen:
            raise blocked_error(f"{harness} startup banner or modal overlay detected ({spec.screen_blocker!r})")
    return f"New task {task['task_id']}. Read {directory / 'brief.md'} in full and follow it exactly."


def submit_core_task(directory, task, state):
    binding = task["backend"]
    try:
        terminal = core.ready(binding, START_TIMEOUT_MS / 1000)
        baseline = terminal.get("turn")
        if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            raise core.CoreError("native turn baseline missing; no task was sent")
        pointer = prepare_send(
            directory, task,
            lambda: core.call(binding, "terminal.read", terminal=binding["terminal"], lines=0)["text"],
            lambda message: core.CoreError(f"{message}; no task was sent"),
        )
        state.update(startup_ready=True, native_status=core.status(terminal), baseline_seq=baseline,
                     state="not_started", problem=None, submission="unknown")
        save_state(directory, state)
        if state["closed"] or state["state"] == "done":
            return
        sent = core.call(binding, "terminal.send", terminal=binding["terminal"], text=pointer, **{"if": "idle"})
        state["submission"] = "sent"
        state["state"] = "running" if sent.get("started") is True else "not_started"
        state["saw_working"] = sent.get("started") is True
        state["problem"] = None if state["saw_working"] else "task submitted; execution acknowledgement not observed; inspect and use wait --recheck, never resend"
        save_state(directory, state)
        terminal = core.get(binding)
        state["native_status"] = core.status(terminal) if terminal else None
        if state["native_status"] == "working":
            state.update(state="running", saw_working=True, problem=None)
        elif state["native_status"] in ("blocked", "error"):
            state["state"] = state["native_status"]
            state["problem"] = "worker reported " + state["native_status"]
    except core.CoreError as exc:
        if state["submission"] == "not_sent":
            state["state"] = "start_failed"
            state["problem"] = str(exc) + f"; after inspection and resolving readiness, use agent-workers submit {task['task_id']}"
        elif state["submission"] == "unknown":
            state["state"] = "not_started"
            state["problem"] = f"send outcome unresolved: {exc}; inspect, then wait --recheck; do not resend"
        else:
            state["problem"] = f"task submitted; observation failed: {exc}; use wait --recheck; do not resend"
        try:
            terminal = core.get(binding)
            state["native_status"] = core.status(terminal) if terminal else None
        except core.CoreError:
            pass
    save_state(directory, state)


def cmd_submit(args):
    directory = task_dir(args.task_id)
    task = load_task(directory, args.task_id)
    if not (is_core(task) or is_rex(task)):
        fail("invalid_arguments", "submit recovery requires a core or Rex task; inspect and close the legacy task before a fresh run")
    if is_rex(task) and not task["backend"]["block"]:
        fail("submission_unsafe", "Rex block creation is unresolved; inspect and close the task before a fresh run")
    with task_state_lock(directory):
        state = load_state(directory)
        if state["closed"] or state["state"] in ("done", "starting") or state["submission"] != "not_sent":
            fail("submission_unsafe", "Only an unclosed, non-starting task recorded as not_sent can be submitted; sent, unknown, starting and historical outcomes must never be resent")
        state["state"] = "starting"
        state["problem"] = None
        write_json(directory / "state.json", state)
    try:
        if is_rex(task):
            submit_rex_task(directory, task, state)
            target = rex_location(task["backend"])
        else:
            submit_core_task(directory, task, state)
            target = {"terminal_id": task["backend"]["terminal"]}
    except BaseException:
        abort_starting_state(directory, state, "recovery submission interrupted; inspect the task before retrying")
        raise
    emit({"task_id": args.task_id, "state": state["state"], "message": state["problem"],
          **target,
          **progress_fields(state), **viewer_fields(task)})


def rex_location(binding):
    return {"session_id": binding["session"], "window_id": binding["window"], "block_id": binding["block"]}


def rex_status_time(value):
    if isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is not None:
                return timestamp
        except ValueError:
            pass
    return None


def rex_status_advanced(updated_at, baseline):
    current = rex_status_time(updated_at)
    earlier = rex_status_time(baseline)
    return current is not None and earlier is not None and current > earlier


def rex_ready(binding):
    deadline = time.monotonic() + START_TIMEOUT_MS / 1000
    while True:
        terminal = rex.get(binding)
        if not terminal or terminal["state"] != "live" or terminal["status"] in ("blocked", "error"):
            raise rex.RexError("Rex worker exited or reported a startup problem before native idle readiness")
        if terminal["status"] == "idle" and rex_status_time(terminal["updated_at"]) is not None:
            return terminal
        if time.monotonic() >= deadline:
            raise rex.RexError("native idle readiness missing in the Rex block; inspect for a startup dialog")
        time.sleep(0.25)


def submit_rex_task(directory, task, state):
    binding = task["backend"]
    try:
        baseline = rex_ready(binding)
        pointer = prepare_send(
            directory, task, lambda: rex.capture(binding, binding["block"], visible=True),
            lambda message: rex.RexError(message, "not_sent"),
        )
        state.update(startup_ready=True, native_status="idle", baseline_status_at=baseline["updated_at"],
                     baseline_status_owner=baseline["owner"],
                     state="not_started", problem=None, submission="unknown")
        save_state(directory, state)
        if state["closed"] or state["state"] == "done":
            return
        rex.send(binding, pointer, baseline)
        state.update(submission="sent", problem="task submitted; execution acknowledgement not observed; "
                     "inspect and use wait --recheck, never resend")
        save_state(directory, state)
        deadline = time.monotonic() + ACK_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            terminal = rex.get(binding)
            if not terminal or terminal["state"] != "live":
                state.update(state="exited", native_status=None,
                             problem="Rex worker exited after submission; inspect the block and result")
                break
            status = terminal["status"] if terminal["owner"] == baseline["owner"] else None
            state["native_status"] = status
            if rex_status_advanced(terminal["updated_at"], baseline["updated_at"]):
                if status in ("working", "done"):
                    state.update(state="running", saw_working=status == "working", problem=None)
                    if status == "done":
                        state["completion_status_at"] = terminal["updated_at"]
                    break
                if status in ("blocked", "error"):
                    state.update(state=status, problem=f"Rex worker reported {status}")
                    break
            time.sleep(0.25)
    except rex.RexError as exc:
        if exc.kind == "not_sent":
            state["submission"] = "not_sent"
        if state["submission"] == "not_sent":
            state.update(state="start_failed", problem=f"{exc}; no task was sent. After resolving readiness, "
                         f"use agent-workers submit {task['task_id']}")
        elif state["submission"] == "unknown":
            state["problem"] = f"Rex send outcome unresolved: {exc}; inspect, then wait --recheck; do not resend"
        else:
            state["problem"] = f"Rex task submitted; observation failed: {exc}; use wait --recheck; do not resend"
        try:
            terminal = rex.get(binding)
            if terminal and (state["baseline_status_owner"] is None
                             or terminal["owner"] == state["baseline_status_owner"]):
                state["native_status"] = terminal["status"]
        except rex.RexError:
            pass
    save_state(directory, state)


def _refresh_herdr_caller(caller):
    try:
        pane = herdr_path(herdr("pane", "current", "--pane", caller["pane_id"], timeout=30.0), "result", "pane")
    except HerdrError as exc:
        if herdr_error_code(exc) not in MISSING_PANE_CODES:
            raise
        fail("caller_context_invalid", f"Controller pane {caller['pane_id']!r} is no longer available.")
    if not _pane_has_live_ids(pane):
        fail("caller_context_invalid", "Controller context is missing live Herdr IDs.")
    return dict(caller, pane_id=pane["pane_id"], tab_id=pane["tab_id"], workspace_id=pane["workspace_id"])


def start_rex_task(config, worker_name, brief_text, cwd, skip_if_full, caller):
    worker = config["workers"].get(worker_name)
    if worker is None:
        fail("unknown_worker", f"no worker named {worker_name!r} in {config.get('config_path') or config_path()}")
    program = shutil.which(worker["harness"])
    if not program:
        fail("rex_error", f"configured harness {worker['harness']} is not installed")
    context = caller["binding"]
    with task_store_lock():
        if not any(block["block_id"] == caller["block_id"] and block.get("window_id") == caller["window_id"]
                   and block.get("host_id") == context["host_id"] for block in rex.blocks(context)):
            fail("caller_context_invalid", "The Rex controller moved or disappeared; confirm its current block before dispatch")
        active, invalid, windows = task_capacity(context["session"], context)
        if active >= config["max_active_workers"]:
            if skip_if_full:
                return None
            fail("worker_limit", f"Rex session {context['session']} has {active} reserved tasks; "
                 f"max_active_workers = {config['max_active_workers']}; invalid tasks: {invalid}")
        task_id = "t-" + secrets.token_hex(3)
        directory = task_dir(task_id)
        while directory.exists():
            task_id = "t-" + secrets.token_hex(3)
            directory = task_dir(task_id)
        nonce = secrets.token_hex(8)
        agent = "horch-" + task_id[2:]
        argv = native_launch_args(worker, directory, "Rex")
        label = f"{worker_label(worker_name, worker['harness'])} · {nonce}"
        binding = dict(context, window=None, block=None, label=label, harness=worker["harness"])
        task = {"task_id": task_id, "nonce": nonce, "worker": worker_name,
                "harness": worker["harness"], "model": worker["model"], "cwd": str(cwd),
                "config_path": config.get("config_path"), "profile": config.get("profile"),
                "task_dir": str(directory), "brief_path": str(directory / "brief.md"),
                "result_path": str(directory / "result.json"), "agent": agent,
                "pane_id": binding["label"], "argv": argv, "created_at": iso_now(), "backend": binding,
                "workspace_id": context["session"], "controller_verification": caller["controller_verification"]}
        directory.mkdir(parents=True)
        write_brief(directory, brief_text, task_id, nonce)
        state = default_state()
        state.update(state="starting", submission="not_sent")
        write_json(directory / "state.json", state)
        write_json(directory / "task.json", task)
        # The Rex server's PATH can lack the controller's shims (e.g. mise node for Pi).
        command = [sys.executable, str(Path(__file__).resolve()), "--exec-rex-worker",
                   worker_environment().get("PATH", os.defpath), os.path.abspath(program), *argv]
        try:
            try:
                placement = rex.launch(binding, caller["window_id"], windows, command, cwd, PANES_PER_TAB)
            except rex.RexError as exc:
                if exc.kind == "worker_absent":
                    raise
                placement = rex.reconcile(binding)
                if placement is None:
                    raise rex.RexError(f"Rex creation outcome unresolved: {exc}; reservation retained. "
                                       f"Inspect worker label {binding['label']} at the stored endpoint") from exc
                if (placement["window"] == caller["window_id"] or not any(
                        window["window_id"] == placement["window"] and window.get("label") == rex.WINDOW_LABEL
                        for window in rex.windows(binding))):
                    rex.close(dict(binding, **placement))
                    raise rex.RexError("Recovered Rex worker was outside a worker tab and was removed", "worker_absent")
            binding.update(placement)
            task["pane_id"] = binding["block"]
            write_json(directory / "task.json", task)
        except rex.RexError as exc:
            state.update(state="start_failed", problem=str(exc), closed=exc.kind == "worker_absent")
            save_state(directory, state)
    # Lock released: wait for harness readiness and submit prompt concurrently.
    if state["state"] == "starting" and not state["closed"]:
        try:
            submit_rex_task(directory, task, state)
        except BaseException:
            abort_starting_state(directory, state, "Rex startup interrupted before submission; inspect the task")
            raise
    return {"task_id": task_id, "worker": worker_name, "agent": agent, "pane_id": task["pane_id"],
            "backend": "rex", **rex_location(binding), "state": state["state"], "message": state["problem"],
            **progress_fields(state), "controller_verification": task["controller_verification"],
            "brief_path": task["brief_path"], "task_dir": task["task_dir"]}


def start_core_task(config, worker_name, brief_text, cwd, skip_if_full, caller_pane, caller_text, binding, caller=None):
    worker = config["workers"].get(worker_name)
    if worker is None:
        fail("unknown_worker", f"no worker named {worker_name!r} in {config.get('config_path') or config_path()}")
    if caller is None and (caller_pane is not None or caller_text is not None or has_herdr_context()):
        caller = core_caller_context(caller_pane, caller_text)
    with task_store_lock():
        if caller is not None:
            caller = _refresh_herdr_caller(caller)
        active, invalid, owned_tabs = task_capacity(caller["workspace_id"] if caller else None, binding)
        if active >= config["max_active_workers"]:
            if skip_if_full:
                return None
            fail("worker_limit", f"core session {binding['session']} has {active} reserved tasks; "
                 f"max_active_workers = {config['max_active_workers']}; invalid tasks: {invalid}")
        task_id = "t-" + secrets.token_hex(3)
        directory = task_dir(task_id)
        while directory.exists():
            task_id = "t-" + secrets.token_hex(3)
            directory = task_dir(task_id)
        nonce = secrets.token_hex(8)
        argv = native_launch_args(worker, directory, "core")
        binding = dict(binding, terminal="horch-" + task_id[2:], name="horch-" + task_id[2:], nonce=nonce)
        task = {"task_id": task_id, "nonce": nonce, "worker": worker_name,
                "harness": worker["harness"], "model": worker["model"], "cwd": str(cwd),
                "config_path": config.get("config_path"), "profile": config.get("profile"),
                "task_dir": str(directory), "brief_path": str(directory / "brief.md"),
                "result_path": str(directory / "result.json"), "agent": binding["name"],
                "pane_id": binding["terminal"], "argv": argv, "created_at": iso_now(),
                "backend": binding, "viewer": None}
        if caller:
            task["workspace_id"] = caller["workspace_id"]
            task["controller_verification"] = caller["controller_verification"]
        directory.mkdir(parents=True)
        write_brief(directory, brief_text, task_id, nonce)
        write_json(directory / "task.json", task)
        state = default_state()
        state.update(state="starting", submission="not_sent")
        save_state(directory, state)
        try:
            try:
                terminal = core.launch(binding, worker["harness"], argv, cwd)
            except core.CoreError as exc:
                terminal = core.get(binding)
                if terminal is None:
                    raise core.CoreError(f"creation outcome unresolved: {exc}; reservation retained. "
                                         f"Inspect {binding['name']} at the stored endpoint; do not relaunch") from exc
            binding["terminal"] = terminal["address"]
            task["pane_id"] = terminal["address"]
            write_json(directory / "task.json", task)
            if caller:
                try:
                    viewer_socket = os.environ.get("HERDR_SOCKET_PATH")
                    if not viewer_socket:
                        raise HerdrError("cannot pin viewer endpoint without HERDR_SOCKET_PATH; no GUI writes attempted")
                    task["viewer_socket"] = viewer_socket
                    task["viewer_unresolved"] = True
                    write_json(directory / "task.json", task)
                    pane_id, tab_id = place_pane(caller["workspace_id"], cwd, caller["tab_id"], owned_tabs)
                    task["viewer"] = {"pane_id": pane_id, "tab_id": tab_id, "socket_path": viewer_socket,
                                      "tab_label": WORKER_TAB_LABEL}
                    task["viewer_unresolved"] = False
                    write_json(directory / "task.json", task)
                    label_worker_pane(pane_id, worker_name, worker["harness"])
                    env = core.cli_env(binding)
                    assignments = [f"{k}={env[k]}" for k in (*binding["env"], "HC_SESSION", "HC_SOCKET")]
                    command = shlex.join(["env", "-u", "HC_TERMINAL_ID", *assignments,
                                          binding["executable"], "attach", binding["terminal"]])
                    herdr("pane", "run", pane_id, command, timeout=30, expect_json=False)
                except HerdrError as exc:
                    warning = f"core worker retained; required Workers viewer failed: {exc}; "
                    warning += "inspect for an empty viewer pane after ambiguous placement"
                    task["viewer_warning"] = warning
                    write_json(directory / "task.json", task)
        except core.CoreError as exc:
            state["state"] = "start_failed"
            state["problem"] = str(exc)
            save_state(directory, state)
    # Lock released: verify viewer and wait for harness readiness/submission concurrently.
    if state["state"] == "starting" and not state["closed"]:
        try:
            if caller:
                verify_viewer(task)
                persist_viewer_verification(directory, task)
            state = load_state(directory)
            if state["state"] == "starting" and not state["closed"]:
                submit_core_task(directory, task, state)
        except BaseException:
            abort_starting_state(directory, state, "core startup interrupted before submission; inspect the task")
            raise
    return {"task_id": task_id, "worker": worker_name, "agent": task["agent"],
            "pane_id": task["pane_id"], "terminal_id": binding["terminal"], "backend": "core",
            "state": state["state"], "message": state["problem"],
            **progress_fields(state), **viewer_fields(task),
            "controller_verification": task.get("controller_verification"),
            "brief_path": task["brief_path"], "task_dir": str(directory)}


def wait_for_legacy_session(agent, harness, deadline):
    # Herdr 0.9.3 can classify Pi's pre-session trust dialog as idle. The
    # integration reports a session once trust and the input handler are ready.
    spec = HARNESSES[harness]
    while time.monotonic() < deadline:
        entry = herdr_path(herdr("agent", "get", agent), "result", "agent")
        if entry.get("agent_status") == "blocked":
            raise HerdrError(f"{spec.label} is blocked during startup; no task prompt was sent")
        session = entry.get("agent_session") or {}
        if (session.get("agent") == harness and session.get("source") == spec.legacy_session_source
                and session.get("value") and entry.get("agent_status") in ("idle", "done")):
            return
        time.sleep(POLL_SECONDS)
    raise HerdrError(f"{spec.label} did not report a ready session; no task prompt was sent. "
                     f"Inspect its pane for a startup dialog and verify that the {spec.label} "
                     f"integration is installed with herdr integration install {harness}")


def start_legacy_task(config, worker_name, brief_text, cwd, skip_if_full, caller_pane, caller_text, caller=None):
    """Start one legacy Herdr worker on one task and return the run object; fail() on contract errors."""
    worker = config["workers"].get(worker_name)
    if worker is None:
        fail("unknown_worker", f"no worker named {worker_name!r} in {config.get('config_path') or config_path()}")
    if caller is None:
        caller = require_caller_context(caller_pane, caller_text)

    with task_store_lock():
        caller = _refresh_herdr_caller(caller)
        max_active = config["max_active_workers"]
        active, invalid, owned_tabs = task_capacity(caller["workspace_id"])
        if active >= max_active:
            if skip_if_full:
                return None
            guidance = (f"; invalid tasks: {', '.join(invalid)}; inspect them with agent-workers list"
                        if invalid else "")
            fail(
                "worker_limit",
                f"worker limit reached in workspace {caller['workspace_id']}: "
                f"{active} active tasks, max_active_workers = {max_active}{guidance}",
            )

        root = tasks_root()
        taken = {d.name for d in root.iterdir()} if root.is_dir() else set()
        while True:
            task_id = "t-" + secrets.token_hex(3)
            if task_id not in taken:
                break
        agent = "horch-" + task_id[2:]
        nonce = secrets.token_hex(8)

        directory = root / task_id
        directory.mkdir(parents=True)
        try:
            write_brief(directory, brief_text, task_id, nonce)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        try:
            pane_id, tab_id = place_pane(caller["workspace_id"], cwd, caller["tab_id"], owned_tabs)
        except BaseException as exc:
            shutil.rmtree(directory, ignore_errors=True)
            print(f"warning: pane placement failed: {exc}; an empty pane may exist "
                  "after an ambiguous placement failure", file=sys.stderr)
            raise

        task = {
            "task_id": task_id,
            "nonce": nonce,
            "worker": worker_name,
            "harness": worker["harness"],
            "model": worker["model"],
            "cwd": str(cwd),
            "config_path": config.get("config_path"),
            "profile": config.get("profile"),
            "task_dir": str(directory),
            "brief_path": str(directory / "brief.md"),
            "result_path": str(directory / "result.json"),
            "agent": agent,
            "pane_id": pane_id,
            "tab_id": tab_id,
            "workspace_id": caller["workspace_id"],
            "controller_verification": caller["controller_verification"],
            "argv": launch_args(worker, directory),
            "backend": {"kind": "legacy", "socket_path": os.environ.get("HERDR_SOCKET_PATH")},
            "created_at": iso_now(),
        }
        state = default_state()
        state.update(state="starting", submission="not_sent")
        try:
            write_json(directory / "task.json", task)
            save_state(directory, state)
        except BaseException:
            # If publication fails, close the unused pane. If close is uncertain,
            # retain/publish its reservation so a later launch cannot reuse the slot.
            try:
                close_pane(pane_id)
            except HerdrError as exc:
                state["state"] = "start_failed"
                state["problem"] = f"task publication failed; unused pane cleanup failed: {exc}"
                try:
                    write_json(directory / "task.json", task)
                    save_state(directory, state)
                except OSError as recovery_error:
                    print(f"warning: cannot preserve task {task_id} for pane {pane_id}: "
                          f"{recovery_error}", file=sys.stderr)
            else:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        label_worker_pane(pane_id, worker_name, worker["harness"])

    def run_object(state_name):
        return {
            "task_id": task_id,
            "worker": worker_name,
            "agent": agent,
            "pane_id": pane_id,
            "state": state_name,
            "message": state["problem"],
            **progress_fields(state),
            "controller_verification": task["controller_verification"],
            "brief_path": task["brief_path"],
            "task_dir": task["task_dir"],
        }

    # Lock released: start harness, wait for readiness, and submit prompt concurrently.
    state = load_state(directory)
    if state["closed"] or state["state"] == "done":
        return run_object(state["state"])

    try:
        start_problem = None
        startup_deadline = time.monotonic() + START_TIMEOUT_MS / 1000
        try:
            doc = herdr(
                "agent", "start", agent,
                "--kind", worker["harness"],
                "--pane", pane_id,
                "--timeout", str(START_TIMEOUT_MS),
                "--", *task["argv"],
                timeout=150.0,
            )
            started_type = (doc.get("result") or {}).get("type")
            if started_type != "agent_started":
                start_problem = f"herdr agent start reported {started_type!r}"
            else:
                harness = worker["harness"]
                if HARNESSES[harness].legacy_session_source:
                    wait_for_legacy_session(agent, harness, startup_deadline)
                pointer = prepare_send(directory, task, lambda: visible_text(pane_id),
                                       lambda message: HerdrError(f"{message}; no task prompt was sent"))
        except HerdrError as exc:
            start_problem = str(exc)
        if start_problem:
            state["state"] = "start_failed"
            state["problem"] = start_problem
            save_state(directory, state)
            if not state["closed"]:
                notify(f"agent-workers: {task_id} start_failed", f"worker {worker_name} failed to start in pane {pane_id}: {start_problem}")
            return run_object(state["state"])

        index = agent_index()
        entry = (index or {}).get(agent)
        baseline = entry.get("state_change_seq") if isinstance(entry, dict) else None
        if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            state["state"] = "start_failed"
            state["problem"] = "could not capture a usable agent baseline; prompt was not submitted"
            save_state(directory, state)
            if not state["closed"]:
                notify(f"agent-workers: {task_id} start_failed", state["problem"])
            return run_object(state["state"])
        state["baseline_seq"] = baseline
        state["startup_ready"] = True
        save_state(directory, state)
        if state["closed"] or state["state"] == "done":
            return run_object(state["state"])

        state["submission"] = "unknown"
        save_state(directory, state)
        if state["closed"] or state["state"] == "done":
            return run_object(state["state"])
        notice = None
        try:
            doc = herdr(
                "agent", "prompt", agent, pointer,
                "--wait", "--until", "working", "--until", "blocked",
                "--timeout", str(ACK_TIMEOUT_MS),
                timeout=45.0,
            )
            status = ((doc.get("result") or {}).get("agent") or {}).get("agent_status")
            state["submission"] = "sent"
            state["native_status"] = status
            if status == "blocked":
                state["state"] = "blocked"
                state["problem"] = "the worker is waiting at a dialog"
                notice = (f"agent-workers: {task_id} blocked",
                          f"worker {worker_name} is waiting at a dialog in pane {pane_id}")
            else:
                state["state"] = "running"
                state["saw_working"] = status == "working"
        except HerdrError as exc:
            code = None
            if isinstance(exc.payload, dict) and isinstance(exc.payload.get("error"), dict):
                code = exc.payload["error"].get("code")
            if code == "agent_blocked":
                state["submission"] = "not_sent"
                state["state"] = "blocked"
                state["problem"] = "the worker is waiting at a dialog"
                notice = (f"agent-workers: {task_id} blocked",
                          f"worker {worker_name} is waiting at a dialog in pane {pane_id}")
            else:
                state["state"] = "not_started"
                state["problem"] = f"prompt acknowledgement not observed: {exc}"
                notice = (
                    f"agent-workers: {task_id} not_started",
                    f"worker {worker_name} prompt acknowledgement not observed within {ACK_TIMEOUT_MS // 1000}s: {exc}",
                )
        save_state(directory, state)
        if notice and not state["closed"]:
            notify(*notice)
        return run_object(state["state"])
    except BaseException:
        abort_starting_state(directory, state, "legacy startup interrupted before submission; inspect the task")
        raise


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------


def turn_ended(agent, state):
    status = agent.get("agent_status")
    if status not in ("idle", "done"):
        return False
    if state["baseline_status_at"] is not None:
        return (rex_status_advanced(agent.get("status_at"), state["baseline_status_at"])
                and (status == "done" or state["saw_working"]))
    completion = agent.get("completion_seq")
    baseline = state.get("baseline_seq")
    if isinstance(completion, (int, float)) and isinstance(baseline, (int, float)):
        return completion > baseline
    # completion_seq stays null after some turns (observed on Codex); fall back
    # to "working was seen after the prompt".
    return bool(state.get("saw_working"))


def result_verdict(directory, task):
    path = directory / "result.json"
    if not path.is_file():
        return "missing"
    return validate_result(read_json(path), task)


def validate_result(parsed, task):
    if not isinstance(parsed, dict):
        return "invalid"
    keys = {"task_id", "nonce", "status", "summary", "files", "question"}
    if (set(parsed) != keys or parsed["task_id"] != task["task_id"]
            or parsed["nonce"] != task["nonce"]
            or parsed["status"] not in ("completed", "blocked", "failed")
            or not isinstance(parsed["summary"], str)
            or not isinstance(parsed["files"], list)
            or not all(isinstance(item, str) for item in parsed["files"])):
        return "invalid"
    question = parsed["question"]
    if parsed["status"] == "blocked":
        return "valid" if isinstance(question, str) and question.strip() else "invalid"
    return "valid" if question is None else "invalid"


def result_stable_for_fallback(directory, task, now_epoch=None):
    """True when a valid result.json (and any existing declared files) has been untouched long enough."""
    result_path = directory / "result.json"
    if not result_path.is_file():
        return False
    parsed = read_json(result_path)
    if validate_result(parsed, task) != "valid":
        return False
    try:
        latest_mtime = result_path.stat().st_mtime
    except OSError:
        return False
    for rel in parsed["files"]:
        try:
            target = directory / rel
            if target.exists():
                latest_mtime = max(latest_mtime, target.stat().st_mtime)
        except OSError:
            continue
    now = time.time() if now_epoch is None else now_epoch
    return latest_mtime <= now + 1.0 and (now - latest_mtime) >= RESULT_FALLBACK_STABLE_SECONDS


def ran_longer_than(task, minutes):
    try:
        started = datetime.fromisoformat(str(task.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - started).total_seconds() > minutes * 60


def confirm_result_fallback(info, agent):
    state, task = info["state"], info["task"]
    if agent is None or agent.get("agent_status") is not None or not state["saw_working"]:
        return False
    # A valid result can also resolve an uncertain submission during evaluation.
    if state["submission"] != "sent" and not (
            state["submission"] == "unknown"
            and (state["baseline_seq"] is not None or state["baseline_status_at"] is not None)):
        return False
    if not result_stable_for_fallback(info["dir"], task):
        return False

    try:
        if is_core(task):
            terminal = core.get(task["backend"])
            return core_fingerprint(terminal) == core_fingerprint(info["terminal_observation"])
        if is_rex(task):
            terminal = rex.get(task["backend"])
            return (terminal is not None and terminal["state"] == "live" and terminal["status"] is None
                    and terminal["owner"] == agent["status_owner"])
    except (core.CoreError, rex.RexError):
        return False
    current = (agent_index() or {}).get(task["agent"])
    return (current is not None and current.get("agent_status") is None
            and current.get("pane_id") == agent.get("pane_id"))


def evaluate_task(info, agent, config, fallback_confirmed):
    state, task = info["state"], info["task"]
    if is_rex(task):
        if rex_status_advanced(state["completion_status_at"], state["baseline_status_at"]):
            agent = {"agent_status": "done", "status_at": state["completion_status_at"]}
        elif agent and agent["status_owner"] != state["baseline_status_owner"]:
            agent = {"agent_status": None}
    state["native_status"] = agent.get("agent_status") if agent else None
    if state["submission"] == "not_sent":
        state["state"] = "start_failed"
        can_submit = is_core(task) or (is_rex(task) and task["backend"]["block"])
        state["problem"] = ("no task was sent; inspect readiness, then use agent-workers submit " + task["task_id"]
                            if can_submit else "no task was sent; inspect and close this task before a fresh run")
        return state["state"]
    if state["submission"] == "unknown":
        if (agent and (state["baseline_seq"] is not None or state["baseline_status_at"] is not None)
                and result_verdict(info["dir"], task) == "valid"):
            state["submission"] = "sent"
        else:
            state["state"] = "not_started"
            state["problem"] = "submission outcome is unknown; native activity cannot prove receipt of this task; inspect and never resend"
            if agent and agent.get("agent_status") == "working":
                state["saw_working"] = True
            return "not_started"
    if agent is None:
        state["state"] = "exited"
        state["problem"] = f"worker {task['worker']} ({task['agent']}) has finished or is gone from its backend"
        return "exited"
    status = agent.get("agent_status")
    if status == "working":
        state["saw_working"] = True
    if status == "error":
        state["state"] = "error"
        state["problem"] = f"worker {task['worker']} reported a native error"
        return "error"
    if status == "blocked":
        state["state"] = "blocked"
        state["problem"] = f"worker {task['worker']} is waiting at a dialog in pane {task['pane_id']}"
        return "blocked"
    if turn_ended(agent, state):
        verdict = result_verdict(info["dir"], task)
        if verdict == "valid":
            state["state"] = "done"
            state["problem"] = None
            state["settled_by"] = state.get("settled_by") or "native"
            return "done"
        if verdict == "missing":
            state["state"] = "result_missing"
            state["problem"] = f"turn ended without a valid result.json ({task['result_path']})"
            return "result_missing"
        state["state"] = "result_invalid"
        state["problem"] = f"result.json does not match the result schema or task_id/nonce ({task['result_path']})"
        return "result_invalid"
    if state["submission"] == "sent" and not state["saw_working"]:
        state["state"] = "not_started"
        state["problem"] = "task submitted; execution acknowledgement not observed; inspect and use wait --recheck, never resend"
        return "not_started"
    if (fallback_confirmed and state["submission"] == "sent" and state["saw_working"]
            and status is None and result_stable_for_fallback(info["dir"], task)):
        state["state"] = "done"
        state["problem"] = None
        state["settled_by"] = "result_file"
        return "done"
    if not state["long_notified"] and ran_longer_than(task, config["notify_after_minutes"]):
        state["long_notified"] = True
        state["state"] = "running"
        state["problem"] = None
        return "long_running"
    state["state"] = "running"
    state["problem"] = None
    return "running"


def poll_round(infos, previous, config):
    for info in infos:
        if info["state"]["state"] == "starting":
            info["state"] = load_state(info["dir"])
            if info["state"]["state"] != "starting":
                info["task"] = load_task(info["dir"], info["task_id"])
    observing = {info["task_id"]: info for info in infos
                 if not info["state"]["closed"] and info["state"]["state"] not in ("done", "starting")
                 and (info["state"]["state"] not in SETTLED_STATES or info.get("recheck"))}
    legacy = any(not (is_core(info["task"]) or is_rex(info["task"])) for info in observing.values())
    index = agent_index() if legacy else {}
    if index is None:
        return False, False, False
    observations = {}
    for info in observing.values():
        task = info["task"]
        if is_core(task):
            terminal = core.get(task["backend"])
            info["terminal_observation"] = terminal
            observations[info["task_id"]] = core_agent(terminal)
        elif is_rex(task) and not info["state"]["completion_status_at"]:
            binding = task["backend"]
            terminal = rex.get(binding) if binding["block"] else None
            if terminal and terminal["state"] == "live":
                observations[info["task_id"]] = {"agent_status": terminal["status"], "status_at": terminal["updated_at"],
                                                "status_owner": terminal["owner"]}
    changed = False
    problem_changed = False
    for info in infos:
        directory = info["dir"]
        notice = None
        cleanup = False
        task = info["task"]
        agent = (observations.get(info["task_id"]) if is_core(task) or is_rex(task)
                 else index.get(task["agent"]))
        # Confirm just before the transaction. Backend calls must stay outside the lock.
        fallback_confirmed = info["task_id"] in observing and confirm_result_fallback(info, agent)
        with task_state_lock(directory):
            state = load_state(directory)
            if info["state"]["state"] == "starting" and state["state"] != "starting":
                info["task"] = load_task(directory, info["task_id"])
            info["state"] = state
            old_state = state["state"]
            # A submitter can reserve the task after we sampled its backend.
            if info["task_id"] not in observing or state["closed"] or old_state in ("done", "starting") or (
                    old_state in SETTLED_STATES and not info.pop("recheck", False)):
                reported = old_state
            else:
                reported = evaluate_task(info, agent, config, fallback_confirmed)
                cleanup = reported == "done"
                if reported == "long_running":
                    notice = (f"worker {info['task']['worker']} has run longer than "
                              f"{config['notify_after_minutes']} minutes; still waiting")
                elif state["problem"] and old_state != state["state"]:
                    notice = state["problem"]
                mark_settled(state)
                write_json(directory / "state.json", state)
        if cleanup:
            cleanup_error = None
            try:
                close_task_resources(info["task"])
            except (HerdrError, core.CoreError, rex.RexError) as exc:
                cleanup_error = f"task cleanup failed: {exc}; retry with agent-workers close {info['task_id']}"
            with task_state_lock(directory):
                state = load_state(directory)
                if not state["closed"]:
                    state["closed"] = cleanup_error is None
                    if state["problem"] != cleanup_error:
                        notice = cleanup_error
                    state["problem"] = cleanup_error
                    write_json(directory / "state.json", state)
                info["state"] = state
        # Notices are claimed in the state transaction, sent outside the lock.
        # Suppress a notice if a concurrent close has already completed.
        if (notice and not is_rex(info["task"]) and not load_state(directory)["closed"]
                and (not is_core(info["task"]) or info["task"].get("viewer"))):
            notify(f"agent-workers: {info['task_id']}", notice)
        info["reported"] = reported
        if previous.get(info["task_id"]) != reported:
            previous[info["task_id"]] = reported
            changed = True
            if (reported in PROBLEM_STATES or reported == "long_running"
                    or (reported == "done" and not info["state"]["closed"])):
                problem_changed = True
    return changed, True, problem_changed


def wait_line(info):
    state = load_state(info["dir"])
    reported = state["state"] if state["closed"] or state["state"] in ("done", "starting") else info["reported"]
    verdict = result_verdict(info["dir"], info["task"])
    # A worker may write its result before its turn ends. Do not deliver it yet.
    parsed = read_json(info["dir"] / "result.json") if reported == "done" and verdict == "valid" else None
    return {
        "task_id": info["task_id"],
        "state": reported,
        "result_status": parsed.get("status") if parsed else None,
        "result_verdict": verdict,
        "settled_by": state.get("settled_by"),
        "closed": bool(state["closed"]),
        "message": state["problem"],
        **progress_fields(state),
        **viewer_fields(info["task"]),
        "summary": parsed.get("summary") if parsed else None,
        "result_path": str(info["dir"] / "result.json"),
        "files": parsed.get("files") if parsed and isinstance(parsed.get("files"), list) else [],
        "question": parsed.get("question") if parsed else None,
    }


def make_info(task_id):
    directory = task_dir(task_id)
    state = load_state(directory)
    task = load_task(directory, task_id)
    return {"task_id": task_id, "dir": directory, "task": task, "state": state, "reported": state["state"]}


def cmd_wait(args):
    cfg_path, cfg_profile = resolve_config(args)
    config = load_config(cfg_path, profile=cfg_profile)
    if args.recheck and not args.task_ids:
        fail("invalid_arguments", "wait --recheck requires explicit task IDs")
    if args.task_ids:
        seen = []
        for task_id in args.task_ids:
            if task_id not in seen:
                seen.append(task_id)
        infos = []
        for task_id in seen:
            if not (task_dir(task_id) / "task.json").is_file():
                fail("unknown_task", f"no such task: {task_id}")
            infos.append(make_info(task_id))
    else:
        family = controller_family(args)
        infos = []
        for task_id in all_task_ids():
            try:
                info = make_info(task_id)
            except (TaskInvalidError, TaskMissingError):
                continue
            if (not info["state"]["closed"] and info["state"]["state"] not in SETTLED_STATES
                    and (family == "headless" or is_rex(info["task"]) == (family == "rex"))):
                infos.append(info)
    if len({is_rex(info["task"]) for info in infos}) > 1:
        fail("invalid_arguments", "Wait for Rex and Herdr tasks separately by task ID")
    if not infos:
        return

    if args.recheck:
        for info in infos:
            if (not info["state"]["closed"] and info["state"]["state"] in SETTLED_STATES
                    and info["state"]["state"] != "done"):
                info["recheck"] = True
    wait_until_change(infos, config, args.max_seconds, wait_all=args.all)
    for info in infos:
        emit(wait_line(info))


def wait_until_change(infos, config, max_seconds, wait_all=False):
    """Poll until a waited task changes state (or all settle with wait_all) or max_seconds pass."""
    if all((info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES)
           and not info.get("recheck") for info in infos):
        return
    deadline = None if max_seconds is None else time.monotonic() + max(0.0, max_seconds)
    previous = {info["task_id"]: info["state"]["state"] for info in infos}
    failures = 0
    while True:
        changed, polled, problem_changed = poll_round(infos, previous, config)
        failures = 0 if polled else failures + 1
        if failures >= 3:
            fail("herdr_error", "could not poll herdr agent list")
        all_settled = polled and all(
            (info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES)
            and not info.get("recheck")
            for info in infos
        )
        if all_settled or (problem_changed if wait_all else changed):
            return
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return
        any_starting = any(info["state"]["state"] == "starting" and not info["state"]["closed"] for info in infos)
        pending_fallback = any(
            info["state"]["state"] == "running" and not info["state"]["closed"]
            and info["state"].get("native_status") is None and info["state"].get("saw_working")
            for info in infos
        )
        core_only = all(is_core(info["task"]) for info in infos) and not any_starting
        interval = 180.0 if (core_only and not pending_fallback) else POLL_SECONDS
        gap = interval if deadline is None else min(interval, deadline - now)
        if gap > 0:
            observations = [(info["task"]["backend"], info.get("terminal_observation"))
                            for info in infos if is_core(info["task"]) and not info["state"]["closed"]
                            and info["state"]["state"] not in SETTLED_STATES
                            and info["state"]["state"] != "starting"
                            and info.get("terminal_observation") is not None]
            if observations and not any_starting:
                core.wait_changes(observations, gap)
            else:
                time.sleep(gap)


# ---------------------------------------------------------------------------
# read-only worker statistics
# ---------------------------------------------------------------------------


def stats_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return parsed.astimezone(timezone.utc)


def duration_summary(samples, sources):
    ordered = sorted(samples)
    return {
        "sample_size": len(ordered),
        "median": statistics.median(ordered) if ordered else None,
        "p90": ordered[math.ceil(len(ordered) * 0.9) - 1] if ordered else None,
        "max": ordered[-1] if ordered else None,
        "sources": dict(sorted(sources.items())),
    }


def cmd_stats(args):
    # No Herdr calls, state locks, or writes: a per-record view, not a snapshot.
    now = datetime.now(timezone.utc)
    if args.workspace is not None and not args.workspace.strip():
        fail("invalid_arguments", "--workspace must not be blank")
    try:
        if args.days is not None and args.days <= 0:
            raise ValueError("nonpositive days")
        cutoff = now - timedelta(days=args.days) if args.days is not None else None
    except (ValueError, OverflowError):
        fail("invalid_arguments", "--days must be a positive integer within datetime range")
    cfg_path, cfg_profile = resolve_config(args)
    config = load_config(cfg_path, profile=cfg_profile)
    roles = config["roles"]
    if not isinstance(roles, dict):
        fail("config_invalid", "[roles] must be a table")
    missing_roles = {}
    for role, assigned in sorted(roles.items()):
        names = [assigned] if isinstance(assigned, str) else assigned
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            fail("config_invalid", "role assignments must be worker names or lists of names")
        missing = sorted(set(names) - config["workers"].keys())
        if missing:
            missing_roles[role] = missing
    workers = {}
    samples = {}
    invalid = []
    timings = []

    def worker_row(name):
        if name not in workers:
            spec = config["workers"].get(name)
            row = {
                "configured": spec is not None,
                **{key: spec.get(key) if spec else None for key in ("harness", "model", "effort", "provider")},
                "task_count": 0, "reminder_fired": 0, "states": {}, "result_statuses": {},
                "problem_count": 0, "problem_rate": None, "unclosed_running": 0, "last_use": None,
                "workspaces": {}, "unknown_workspace_count": 0,
                "duration_excluded_count": 0,
            }
            if not args.no_samples:
                row["duration_samples"] = []
            workers[name] = row
            samples[name] = ([], {})
        return workers[name]

    for name in config["workers"]:
        worker_row(name)
    for task_id in all_task_ids():
        directory = task_dir(task_id)
        # Missing files are normal during publication/removal; existing corrupt
        # files remain diagnostic. Raw metadata is used only to narrow scope.
        if not (directory / "task.json").exists():
            continue
        raw = read_json(directory / "task.json")
        if isinstance(raw, dict):
            workspace = raw.get("workspace_id")
            if (args.workspace is not None and isinstance(workspace, str)
                    and workspace != args.workspace):
                continue
            try:
                if cutoff is not None and stats_timestamp(raw.get("created_at")) < cutoff:
                    continue
            except (ValueError, OverflowError):
                pass
        try:
            task = load_task(directory, task_id)
            created = stats_timestamp(task["created_at"])
        except TaskMissingError:
            continue
        except (TaskInvalidError, ValueError, OverflowError):
            if directory.is_dir():
                invalid.append(task_id)
            continue
        if ((args.workspace is not None and task.get("workspace_id") != args.workspace)
                or (cutoff is not None and created < cutoff)):
            continue
        if not (directory / "state.json").exists():
            continue
        state = read_json(directory / "state.json")
        if (not isinstance(state, dict) or not isinstance(state.get("state"), str)
                or state["state"] not in SETTLED_STATES | {"running", "starting"}):
            if directory.is_dir():
                invalid.append(task_id)
            continue
        result = read_json(directory / "result.json")
        minutes, source = None, None
        valid_result = state["state"] == "done" and validate_result(result, task) == "valid"
        if valid_result:
            try:
                if state.get("first_done_at") is not None:
                    ended = stats_timestamp(state["first_done_at"])
                    source = "first_done_at"
                else:
                    ended = datetime.fromtimestamp((directory / "result.json").stat().st_mtime, timezone.utc)
                    source = "result_mtime"
                minutes = (ended - created).total_seconds() / 60
                if minutes < 0 or ended > now:
                    minutes = None
            except (OSError, ValueError, OverflowError):
                pass
        if not directory.is_dir():
            continue
        row = worker_row(task["worker"])
        row["task_count"] += 1
        row["reminder_fired"] += state.get("long_notified") is True
        name = ("closed_before_done" if state.get("closed") and state["state"] not in SETTLED_STATES
                else state["state"])
        row["states"][name] = row["states"].get(name, 0) + 1
        row["problem_count"] += name in SETTLED_STATES - {"done"}
        row["unclosed_running"] += name in ("running", "starting")
        last = row["last_use"]
        if last is None or created > stats_timestamp(last):
            row["last_use"] = created.isoformat().replace("+00:00", "Z")
        workspace = task.get("workspace_id")
        if workspace is None:
            row["unknown_workspace_count"] += 1
        else:
            row["workspaces"][workspace] = row["workspaces"].get(workspace, 0) + 1
        if name == "done":
            if valid_result:
                status = result["status"]
                row["result_statuses"][status] = row["result_statuses"].get(status, 0) + 1
            if minutes is None:
                row["duration_excluded_count"] += 1
        if minutes is not None:
            values, sources = samples[task["worker"]]
            values.append(minutes)
            sources[source] = sources.get(source, 0) + 1
            timings.append(minutes)
            if not args.no_samples:
                row["duration_samples"].append({"task_id": task_id, "minutes": minutes,
                                                "endpoint_source": source})
    for name, row in workers.items():
        settled_count = row["problem_count"] + row["states"].get("done", 0)
        row["problem_rate"] = row["problem_count"] / settled_count if settled_count else None
        row["duration_minutes"] = duration_summary(*samples[name])

    def above(threshold):
        count = sum(value > threshold for value in timings)
        return {"minutes": threshold, "count": count,
                "share": count / len(timings) if timings else None}

    emit({
        "config_path": str(cfg_path),
        "profile": cfg_profile,
        "scope": {"workspace_id": args.workspace, "days": args.days,
                  "created_since": cutoff.isoformat().replace("+00:00", "Z") if cutoff else None},
        "task_count": sum(row["task_count"] for row in workers.values()),
        "reminder_fired": sum(row["reminder_fired"] for row in workers.values()),
        "workers": dict(sorted(workers.items())),
        "configured_unused_workers": sorted(name for name, row in workers.items()
                                            if row["configured"] and not row["task_count"]),
        "roles_with_unconfigured_workers": missing_roles,
        "invalid_task_ids": invalid,
        "delivered_duration_estimate": {"timed_task_count": len(timings),
                                        "current": above(config["notify_after_minutes"]),
                                        "thresholds": [above(n) for n in (15, 30, 45, 60, 90)
                                                       if n != config["notify_after_minutes"]]},
    })


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------


def _worker_role_summary(name, workers):
    spec = workers.get(name)
    if spec is None:
        return {"worker": name, "configured": False}
    summary = {
        "worker": name,
        "configured": True,
        "harness": spec["harness"],
        "model": spec["model"],
        "effort": spec["effort"],
        "description": spec["description"],
    }
    if spec.get("provider"):
        summary["provider"] = spec["provider"]
    return summary


def _resolve_role_entry(role_name, assigned, workers):
    if isinstance(assigned, str):
        if not assigned.strip():
            return {"kind": "invalid", "valid": False, "workers": [], "unconfigured": [],
                    "error": f"role {role_name!r} has an empty worker name"}
        unconfigured = [assigned] if assigned not in workers else []
        error = f"unconfigured worker: {assigned}" if unconfigured else None
        return {
            "kind": "single",
            "valid": not unconfigured,
            "workers": [_worker_role_summary(assigned, workers)],
            "unconfigured": unconfigured,
            "error": error,
        }
    if isinstance(assigned, list):
        if not assigned:
            return {"kind": "invalid", "valid": False, "workers": [], "unconfigured": [],
                    "error": f"role {role_name!r} panel list is empty"}
        if not all(isinstance(item, str) and item.strip() for item in assigned):
            return {"kind": "invalid", "valid": False, "workers": [], "unconfigured": [],
                    "error": f"role {role_name!r} panel list must contain non-empty worker name strings"}
        unconfigured = list(dict.fromkeys(name for name in assigned if name not in workers))
        error = f"unconfigured workers: {', '.join(unconfigured)}" if unconfigured else None
        return {
            "kind": "panel",
            "valid": not unconfigured,
            "workers": [_worker_role_summary(name, workers) for name in assigned],
            "unconfigured": unconfigured,
            "error": error,
        }
    return {
        "kind": "invalid",
        "valid": False,
        "workers": [],
        "unconfigured": [],
        "error": f"role {role_name!r} must be a worker name or list of worker names",
    }


def cmd_roles(args):
    cfg_path, cfg_profile = resolve_config(args)
    config = load_config(cfg_path, profile=cfg_profile)
    roles_raw = config["roles"]
    if not isinstance(roles_raw, dict):
        fail("config_invalid", "[roles] must be a table")
    workers = config["workers"]
    resolved = {}
    issues = []
    for name, assigned in sorted(roles_raw.items()):
        entry = _resolve_role_entry(name, assigned, workers)
        resolved[name] = entry
        if entry["error"]:
            issues.append(f"{name}: {entry['error']}")

    if args.role_name is not None:
        query = args.role_name
        matched_key = query if query in resolved else None
        if matched_key is None:
            normalized = query.strip().lower()
            token_matches = [
                key for key in resolved
                if key.strip().lower() == normalized
                or normalized in {part.strip().lower() for part in key.split(",") if part.strip()}
            ]
            if len(token_matches) == 1:
                matched_key = token_matches[0]
            elif len(token_matches) > 1:
                fail("ambiguous_role",
                     f"role {query!r} matched multiple configured roles: {', '.join(token_matches)}")
            else:
                configured = ", ".join(sorted(resolved)) or "none"
                fail("unknown_role",
                     f"no role named {query!r} in {cfg_path}; configured roles: {configured}")
        emit({
            "config_path": str(cfg_path),
            "profile": cfg_profile,
            "role": matched_key,
            **resolved[matched_key],
            "max_active_workers": config["max_active_workers"],
        })
        return

    worker_summaries = {}
    for name, spec in sorted(workers.items()):
        summary = {
            "harness": spec["harness"],
            "model": spec["model"],
            "effort": spec["effort"],
            "description": spec["description"],
        }
        if spec.get("provider"):
            summary["provider"] = spec["provider"]
        worker_summaries[name] = summary
    emit({
        "config_path": str(cfg_path),
        "profile": cfg_profile,
        "max_active_workers": config["max_active_workers"],
        "roles": resolved,
        "workers": worker_summaries,
        "issues": issues,
    })


# ---------------------------------------------------------------------------
# list and close
# ---------------------------------------------------------------------------


def cmd_list(args):
    if args.limit is not None and args.limit <= 0:
        fail("invalid_arguments", "--limit must be a positive integer")
    rows = []
    for task_id in all_task_ids():
        directory = task_dir(task_id)
        state = load_state(directory)
        if args.active and state.get("closed"):
            continue
        try:
            task = load_task(directory, task_id)
        except TaskMissingError:
            continue
        except TaskInvalidError as exc:
            rows.append(("", task_id, {"task_id": task_id, "state": "task_invalid",
                                      "error": "task_invalid", "message": str(exc)}))
            continue
        if args.verbose:
            row = {
                "task_id": task_id,
                "worker": task.get("worker"),
                "agent": task.get("agent"),
                "pane_id": task.get("pane_id"),
                "config_path": task.get("config_path"),
                "profile": task.get("profile"),
                "backend": task.get("backend", {"kind": "legacy"}),
                "terminal_id": task["backend"]["terminal"] if is_core(task) else None,
                **(rex_location(task["backend"]) if is_rex(task) else {}),
                **viewer_fields(task),
                **progress_fields(state),
                "workspace_id": task.get("workspace_id"),
                "state": state["state"],
                "closed": bool(state.get("closed")),
                "created_at": task.get("created_at"),
            }
        else:
            row = {
                "task_id": task_id,
                "worker": task.get("worker"),
                "pane_id": task.get("pane_id"),
                "backend": task.get("backend", {"kind": "legacy"}).get("kind", "legacy"),
                "state": state["state"],
                "closed": bool(state.get("closed")),
                "created_at": task.get("created_at"),
            }
            if is_core(task):
                row["terminal_id"] = task["backend"]["terminal"]
                row["viewer_verified"] = bool(task.get("viewer_verified"))
                row["viewer_verification_error"] = task.get("viewer_verification_error")
            elif is_rex(task):
                row.update(rex_location(task["backend"]))
            if state.get("problem"):
                row["message"] = state["problem"]
        rows.append((str(task.get("created_at") or ""), task_id, row))
    rows.sort(key=lambda row: (row[0], row[1]))
    if args.limit is not None:
        rows = rows[-args.limit:]
    for _, _, row in rows:
        emit(row)


def cmd_close(args):
    directory = task_dir(args.task_id)
    try:
        task = load_task(directory, args.task_id)
    except TaskInvalidError as exc:
        fail("task_invalid", f"{exc}; terminal is unknown. Inspect the task's original backend for a "
             f"leftover worker, then remove task directory {directory} by hand")
    outcome = ({"block": "already_gone"} if is_rex(task) and load_state(directory)["closed"]
               else close_task_resources(task))
    with task_state_lock(directory):
        current = load_state(directory)
        current["closed"] = True
        current["problem"] = None
        write_json(directory / "state.json", current)
    emit({"task_id": args.task_id, "closed": True, **outcome})


# ---------------------------------------------------------------------------
# detect and check
# ---------------------------------------------------------------------------


CHECK_BRIEF = """\
# Agent Workers setup check

This task only checks that agent-workers can start you and read your result. Do not
read, create, or change any file except `result.json`. Write `result.json` now
with status `completed` and summary `check ok`.
"""


def tool_version(name, version_arg="--version"):
    path = shutil.which(name)
    if path is None:
        return None
    try:
        proc = subprocess.run([path, version_arg], capture_output=True, text=True, timeout=30)
        version = (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr).strip() else None
    except (OSError, subprocess.TimeoutExpired):
        version = None
    return {"path": path, "version": version}


def pi_providers():
    """Providers that `pi --list-models` shows, with how many models each lists.

    Sign-in status is left out: `pi auth check` does not know providers that come
    from extensions (measured: commandcode reports provider_not_found yet works).
    `agent-workers check` is the real test.
    """
    try:
        proc = subprocess.run(["pi", "--list-models"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    counts = {}
    for line in proc.stdout.splitlines()[1:]:  # first line is the column header
        fields = line.split()
        if len(fields) >= 2:
            counts[fields[0]] = counts.get(fields[0], 0) + 1
    return [{"provider": provider, "models": count} for provider, count in counts.items()]


def legacy_integration_status(harness):
    """Read Herdr's local plaintext protocol without exposing paths or diagnostics."""
    try:
        proc = subprocess.run(["herdr", "integration", "status"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return {"status": "unavailable", "version": None}
    if proc.returncode != 0:
        return {"status": "unavailable", "version": None}
    prefix = f"{harness}: "
    lines = [line.removeprefix(prefix) for line in proc.stdout.splitlines() if line.startswith(f"{harness}:")]
    if len(lines) == 1:
        match = re.fullmatch(
            r"(?:not installed|(?:current|needs repair) \((?:v[0-9]+|legacy)\)"
            r"|outdated \((?:v[0-9]+|legacy) < v[0-9]+\)) \(.+\)", lines[0])
        if match:
            state = lines[0].split(" (")[0].replace(" ", "_")
            version = re.match(r"[a-z ]+ \(v([0-9]+)\b", lines[0])
            return {"status": state,
                    "version": int(version[1]) if state != "not_installed" and version else None}
    return {"status": "unknown", "version": None}


def require_legacy_integrations(harnesses):
    for harness in dict.fromkeys(harnesses):
        spec = HARNESSES[harness]
        if spec.legacy_session_source and legacy_integration_status(harness)["status"] == "not_installed":
            fail(f"{harness}_integration_missing",
                 f"{spec.label} requires the Herdr integration; install it with herdr integration install {harness}")


def herdr_server_version():
    """Read the running server version independently of the installed CLI."""
    try:
        proc = subprocess.run(["herdr", "status", "server", "--json"],
                              capture_output=True, text=True, timeout=10)
        status = _read_json_text(proc.stdout) if proc.returncode == 0 else None
        version = status.get("version") if isinstance(status, dict) else None
        return version if isinstance(version, str) else None
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return None


def cmd_detect(args):
    family = controller_family(args)
    cfg_path, cfg_profile = resolve_config(args)
    rex_controller = family == "rex"
    binary = None if rex_controller else core.executable()
    legacy = not rex_controller and binary is None
    harnesses = {name: tool_version(name) for name in HARNESSES}
    emit({
        "controller": family,
        "backend": "rex" if rex_controller else "legacy" if legacy else "core",
        "core": {"path": binary, "status_source": "native OSC 7501"} if binary else None,
        "rex": tool_version("rex", "version") if rex_controller else None,
        "herdr_env": os.environ.get("HERDR_ENV") == "1",
        "herdr": tool_version("herdr") if legacy else None,
        "herdr_server_version": herdr_server_version() if legacy else None,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "harnesses": harnesses,
        "pi_providers": pi_providers() if harnesses["pi"] else [],
        "pi_integration": legacy_integration_status("pi") if legacy else {"status": "native", "version": None},
        "config": {
            "path": str(cfg_path),
            "exists": cfg_path.is_file(),
            "profile": cfg_profile,
            "profiles": list_profiles(),
        },
    })


def cmd_check(args):
    caller, binary = dispatch_context(args)
    binding = core.new_binding(binary) if binary else caller.get("binding") if caller else None
    cfg_path, cfg_profile = resolve_config(args)
    config = load_config(cfg_path, profile=cfg_profile)
    names = list(dict.fromkeys(args.workers or list(config["workers"])))
    unknown = [name for name in names if name not in config["workers"]]
    if unknown:
        fail("unknown_worker", f"no worker named {', '.join(unknown)} in {cfg_path}")
    if binding is None:
        require_legacy_integrations(config["workers"][name]["harness"] for name in names)
    cwd = resolve_cwd(args.cwd)
    deadline = time.monotonic() + args.max_seconds
    pending = list(names)
    started = {}
    settled_times = {}
    capacity_invalid = set()
    while pending or any(not info["state"]["closed"] and info["state"]["state"] not in SETTLED_STATES
                         for info, _ in started.values()):
        while pending and time.monotonic() < deadline:
            name = pending[0]
            began = time.monotonic()
            run = start_task(config, name, CHECK_BRIEF, cwd, skip_if_full=True,
                             caller_pane=args.caller_pane, caller_text=args.caller_text, binding=binding, caller=caller)
            if run is None:
                _, invalid, _ = task_capacity(caller["workspace_id"] if caller else None, binding)
                capacity_invalid.update(invalid)
                break  # poll our started tasks before retrying pending workers
            pending.pop(0)
            info = make_info(run["task_id"])
            started[name] = (info, began)
            if info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES:
                settled_times[name] = time.monotonic()
        waiting = [info for info, _ in started.values()
                   if not info["state"]["closed"] and info["state"]["state"] not in SETTLED_STATES]
        if time.monotonic() >= deadline or (not waiting and pending):
            break  # out of time, or problem panes hold every slot
        wait_until_change(waiting, config, deadline - time.monotonic())
        for name, (info, _) in started.items():
            if name not in settled_times and (info["state"]["closed"] or info["state"]["state"] in SETTLED_STATES):
                settled_times[name] = time.monotonic()
    for name in names:
        if name not in started:
            message = ("check wait limit reached before this worker could start" if time.monotonic() >= deadline
                       else "no free worker slot; review max_active_workers or close problem panes with agent-workers close")
            if capacity_invalid:
                message += (f"; invalid tasks held capacity: {', '.join(sorted(capacity_invalid))}; "
                            "inspect them with agent-workers list")
            emit({"worker": name, "task_id": None, "state": "not_checked", "ok": False,
                  "pane_id": None, "seconds": None, "message": message})
            continue
        info, began = started[name]
        info["state"] = load_state(info["dir"])
        result = read_json(info["dir"] / "result.json")
        status = result.get("status") if isinstance(result, dict) else None
        state = info["state"]["state"]
        message = info["state"]["problem"]
        if state == "done" and status != "completed":
            result_message = f"worker result status is {status!r}; expected completed"
            message = f"{message}; {result_message}" if message else result_message
        elif state not in SETTLED_STATES and message is None:
            message = "check wait limit reached; task is still unsettled"
        emit({
            "worker": name,
            "task_id": info["task_id"],
            "state": state,
            "ok": state == "done" and status == "completed" and info["state"]["closed"]
                  and result_verdict(info["dir"], info["task"]) == "valid"
                  and not info["task"].get("viewer_warning"),
            "pane_id": None if info["state"]["closed"] else info["task"]["pane_id"],
            **viewer_fields(info["task"]),
            **progress_fields(info["state"]),
            "seconds": round(settled_times.get(name, time.monotonic()) - began),
            "message": message,
        })


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def add_caller_arguments(parser):
    caller = parser.add_mutually_exclusive_group()
    caller.add_argument("--caller-pane", help="confirmed Herdr controller pane ID")
    caller.add_argument("--caller-block", help="confirmed full Rex controller block ID")
    parser.add_argument("--caller-text", help="unique visible conversation text for an agent controller")


def add_config_arguments(parser):
    cfg = parser.add_mutually_exclusive_group()
    cfg.add_argument("--profile", help="named profile (loads workers.<profile>.toml)")
    cfg.add_argument("--config", help="explicit path to a workers TOML file")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agent-workers",
        description="Start worker agents in Rex or Herdr, give each one task, and wait for the result.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p_run = sub.add_parser("run", help="start a worker and submit one task")
    p_run.add_argument("worker", help="worker name from workers.toml")
    p_run.add_argument("--brief", required=True, help="path of the brief file for the worker, or '-' to read from stdin")
    p_run.add_argument("--cwd", help="working directory for the worker (default: the current directory)")
    p_run.add_argument("--wait", action="store_true", help="flush the launch JSON line, then wait for this task to change state")
    p_run.add_argument("--max-seconds", type=int, default=None, help="with --wait, return after at most this many seconds")
    add_caller_arguments(p_run)
    add_config_arguments(p_run)
    p_run.set_defaults(func=cmd_run)

    p_wait = sub.add_parser("wait", help="wait until at least one waited task changes state (or all settle with --all)")
    p_wait.add_argument("task_ids", nargs="*", help="tasks to wait on (default: unsettled tasks in the controller's backend family)")
    p_wait.add_argument("--all", action="store_true", help="wait until all targeted tasks settle/close, returning early on any problem or long_running state")
    p_wait.add_argument("--recheck", action="store_true", help="re-poll named unclosed problem tasks")
    p_wait.add_argument("--max-seconds", type=int, default=None, help="return after at most this many seconds")
    add_config_arguments(p_wait)
    p_wait.set_defaults(func=cmd_wait)

    p_list = sub.add_parser("list", help="print tasks as JSON lines, oldest first")
    p_list.add_argument("--active", action="store_true", help="only unclosed tasks")
    p_list.add_argument("--limit", type=int, default=None, help="only the most recent N tasks")
    p_list.add_argument("--verbose", action="store_true", help="include full backend binding, viewer, and progress details")
    p_list.set_defaults(func=cmd_list)

    p_roles = sub.add_parser("roles", help="resolve configured roles and worker metadata from workers.toml")
    p_roles.add_argument("role_name", nargs="?", default=None, help="optional role name or comma-separated role token to resolve")
    add_config_arguments(p_roles)
    p_roles.set_defaults(func=cmd_roles)

    p_stats = sub.add_parser("stats", help="summarize stored worker performance without terminal commands or writes")
    p_stats.add_argument("--workspace", help="only tasks created in this Herdr workspace or Rex session")
    p_stats.add_argument("--days", type=int, help="only tasks created in the last n days")
    p_stats.add_argument("--no-samples", action="store_true", help="omit per-task duration_samples arrays")
    add_config_arguments(p_stats)
    p_stats.set_defaults(func=cmd_stats)

    p_close = sub.add_parser("close", help="close the task's backend terminal and owned viewer")
    p_close.add_argument("task_id", help="task to close")
    p_close.set_defaults(func=cmd_close)

    p_submit = sub.add_parser("submit", help="submit a core or Rex task once after startup recovery, only when definitely not sent")
    p_submit.add_argument("task_id", help="unclosed core or Rex task recorded as not_sent")
    p_submit.set_defaults(func=cmd_submit)

    p_viewer = sub.add_parser("verify-viewer", help="re-read and verify a core task's viewer before user interaction")
    p_viewer.add_argument("task_id", help="core task whose owned viewer to inspect")
    p_viewer.set_defaults(func=cmd_verify_viewer)

    p_detect = sub.add_parser("detect", help="print the controller route, installed harnesses, and Pi providers")
    add_caller_arguments(p_detect)
    add_config_arguments(p_detect)
    p_detect.set_defaults(func=cmd_detect)

    p_check = sub.add_parser("check", help="start each worker on a tiny task and report whether it works")
    p_check.add_argument("workers", nargs="*", help="workers to check (default: all in workers.toml)")
    p_check.add_argument("--cwd", help="working directory for the check workers (default: the current directory)")
    p_check.add_argument("--max-seconds", type=int, default=300, help="stop waiting after this many seconds (default: 300)")
    add_caller_arguments(p_check)
    add_config_arguments(p_check)
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        for task_id in getattr(args, "task_ids", []):
            validate_task_id(task_id)
        if hasattr(args, "task_id"):
            validate_task_id(args.task_id)
        args.func(args)
    except TaskMissingError as exc:
        fail("unknown_task", str(exc))
    except TaskInvalidError as exc:
        fail("task_invalid", str(exc))
    except HerdrError as exc:
        fail("herdr_error", str(exc), exc.payload)
    except core.CoreError as exc:
        fail("core_error", str(exc))
    except rex.RexError as exc:
        fail("rex_error", str(exc))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # never crash with a traceback at the controller
        fail("internal_error", f"{type(exc).__name__}: {exc}")


def cli():
    if sys.argv[1:2] == ["--exec-rex-worker"]:
        # The Rex server can inherit another controller's multiplexer and harness environment.
        keep = {key: value for key, value in os.environ.items()
                if not key.startswith(("HERDR", "HC_", "ANTIGRAVITY_", "AGENT_WORKERS_"))
                and key not in WORKER_UNSET_ENV}
        keep["PATH"] = sys.argv[2]
        os.execve(sys.argv[3], sys.argv[3:], keep)
    main()


if __name__ == "__main__":
    cli()
