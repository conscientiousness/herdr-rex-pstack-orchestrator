import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Harness:
    label: str
    process_names: tuple[str, ...]
    effort_args: tuple[str, ...] = ("--effort", "{effort}")
    model_flag: str = "--model"
    provider_flag: str | None = None
    add_task_dir: bool = True
    controller_session_env: str | None = None
    worker_unset_env: tuple[str, ...] = ()
    legacy_session_aliases: tuple[str, ...] = ()
    legacy_session_source: str | None = None
    screen_blocker: str | None = None
    native_no_daemon: bool = False
    rex_paste_delay: float = 0


HARNESSES = {
    "pi": Harness("Pi", ("pi",), effort_args=("--thinking", "{effort}"),
                  provider_flag="--provider", add_task_dir=False,
                  worker_unset_env=("PI_SESSION_ID",), legacy_session_source="herdr:pi"),
    "codex": Harness("Codex", ("codex",), effort_args=("-c", 'model_reasoning_effort="{effort}"'),
                     model_flag="-m", controller_session_env="CODEX_THREAD_ID",
                     native_no_daemon=True, rex_paste_delay=0.3),
    "claude": Harness("Claude Code", ("claude", "claude-code"),
                      controller_session_env="CLAUDE_CODE_SESSION_ID", worker_unset_env=("CLAUDECODE",)),
    "agy": Harness("Antigravity", ("agy", "antigravity"),
                   controller_session_env="ANTIGRAVITY_CONVERSATION_ID",
                   legacy_session_aliases=("antigravity-cli",), screen_blocker="esc to dismiss"),
}

CONTROLLER_SESSION_ENV = {key: spec.controller_session_env for key, spec in HARNESSES.items()
                          if spec.controller_session_env}
ALL_HARNESS_PROCESS_NAMES = {name for spec in HARNESSES.values() for name in spec.process_names}
WORKER_UNSET_ENV = set(CONTROLLER_SESSION_ENV.values()) | {
    key for spec in HARNESSES.values() for key in spec.worker_unset_env
}


def worker_environment(*, include_xdg=False):
    keys = ("PATH",)
    if include_xdg:
        keys += ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")
    return {key: os.environ[key] for key in keys if key in os.environ}
