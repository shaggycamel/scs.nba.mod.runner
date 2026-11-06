"""Environment-driven configuration for the mod runner."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    source_label: str = "scs.nba.mod.runner"
    db_section: str = "cockroach-write"
    ini_path: str | None = None
    host: str = "jetson"
    base_path: str = "/home/oli/shaggy_camel_sports/nba/mod"
    remote_path: str = "/home/oli/.local/bin:/usr/local/bin:/usr/bin:/bin"
    entrypoint: str = "uv run --frozen --group data python __main__.py"
    default_timeout: int = 3600
    alert: bool = True
    bookends: str = "source"
    remote_credentials: str | None = None
    ssh_binary: str = "ssh"
    ssh_options: tuple[str, ...] = (
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=30",
        "-o",
        "ServerAliveInterval=30",
    )


def load_config() -> Config:
    env = os.environ
    return Config(
        source_label=env.get("SCS_MOD_RUNNER_SOURCE", "scs.nba.mod.runner"),
        db_section=env.get("SCS_MOD_DB_SECTION", "cockroach-write"),
        ini_path=env.get("SCS_HUB_CREDENTIALS") or None,
        host=env.get("SCS_MOD_HOST", "jetson"),
        base_path=env.get(
            "SCS_MOD_BASE_PATH", "/home/oli/shaggy_camel_sports/nba/mod"
        ),
        remote_path=env.get(
            "SCS_MOD_REMOTE_PATH",
            "/home/oli/.local/bin:/usr/local/bin:/usr/bin:/bin",
        ),
        entrypoint=env.get(
            "SCS_MOD_ENTRYPOINT",
            "uv run --frozen --group data python __main__.py",
        ),
        default_timeout=int(env.get("SCS_MOD_TIMEOUT", "3600")),
        alert=env.get("SCS_MOD_ALERT", "1").lower() not in {"0", "false", "no"},
        bookends=env.get("SCS_MOD_BOOKENDS", "source"),
        remote_credentials=env.get("SCS_MOD_REMOTE_CREDENTIALS") or None,
        ssh_binary=env.get("SCS_MOD_SSH_BINARY", "ssh"),
    )
