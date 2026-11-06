"""Query util.update_schedule and turn model rows into scs_runner tasks."""

from __future__ import annotations

import logging
import os
import posixpath
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import polars as pl
from scs_runner import Target, Task

from config import Config

logger = logging.getLogger(__name__)


def repo_name(associated_function: str) -> str:
    """``scs.nba.mod.player_archetypes`` -> ``player_archetypes``."""
    return associated_function.rsplit(".", 1)[-1].strip()


def query_schedule(
    hub: Any,
    *,
    cadences: Sequence[str] = (),
    tasks: Sequence[str] = (),
    all_cadences: bool = False,
    include_paused: bool = False,
) -> list[dict[str, Any]]:
    """Select model rows from util.update_schedule."""
    clauses = ["job_family = 'model'"]
    params: dict[str, Any] = {}

    if tasks:
        task_clauses = []
        for index, value in enumerate(tasks):
            exact = f"task{index}"
            suffix = f"task_suffix{index}"
            repo = value.removesuffix(".job").rsplit(".", 1)[-1]
            task_clauses.append(f"associated_function = :{exact}")
            task_clauses.append(f"associated_function LIKE :{suffix}")
            params[exact] = value
            params[suffix] = f"%.{repo}"
        clauses.append("(" + " OR ".join(task_clauses) + ")")
    else:
        if not all_cadences:
            if not cadences:
                raise ValueError("query_schedule needs at least one cadence or all_cadences")
            placeholders = []
            for index, value in enumerate(cadences):
                key = f"cadence{index}"
                placeholders.append(f":{key}")
                params[key] = value
            clauses.append(f"cadence IN ({', '.join(placeholders)})")
        if not include_paused:
            clauses.append("pause IS NOT TRUE")

    sql = f"""
        SELECT associated_function, cadence, schema_sequence, pause
        FROM util.update_schedule
        WHERE {' AND '.join(clauses)}
        ORDER BY schema_sequence NULLS LAST, associated_function
    """
    options = {"execute_options": {"parameters": params}} if params else {}
    return hub.db.read(sql, **options).to_dicts()


def build_tasks(
    rows: Sequence[Mapping[str, Any]],
    config: Config,
) -> tuple[list[Task], dict[str, Target]]:
    """Build one Task and one SSH Target per scheduled model row."""
    tasks: list[Task] = []
    targets: dict[str, Target] = {}

    for row in rows:
        source = _opt_str(row.get("associated_function"))
        if source is None:
            raise ValueError(f"model schedule row has no associated_function: {row!r}")
        repo = repo_name(source)
        if not repo:
            raise ValueError(f"could not derive a repo name from {source!r}")

        if source in targets:
            raise ValueError(f"duplicate model row for {source!r}")

        target_env = {"PATH": config.remote_path}
        if config.remote_credentials:
            target_env["SCS_HUB_CREDENTIALS"] = config.remote_credentials

        targets[source] = Target(
            host=config.host,
            root=posixpath.join(config.base_path, repo),
            ssh_options=config.ssh_options,
            ssh_binary=config.ssh_binary,
            environment=target_env,
        )
        tasks.append(
            Task(
                source=source,
                task=f"{repo}.job",
                command=config.entrypoint,
                cadence=_opt_str(row.get("cadence")),
                sequence=_opt_int(row.get("schema_sequence")),
                pause=_bool(row.get("pause")),
                timeout_seconds=config.default_timeout,
            )
        )

    return tasks, targets


def make_log_writer(hub: Any):
    """A scs_runner write_log callback backed by scs_hub."""

    def write_log(row: dict[str, Any]) -> None:
        frame = pl.DataFrame(
            [row],
            schema_overrides={"row_count": pl.Int64},
        )
        hub.db.write(frame, "update_log", "util")

    return write_log


def format_plan(tasks: Sequence[Task], targets: Mapping[str, Target]) -> str:
    lines = []
    for task in tasks:
        target = targets.get(task.source)
        if target is None:
            location = "<no target>"
        elif target.is_remote:
            location = f"{target.host}:{target.root}"
        else:
            location = str(target.root)
        lines.append(
            f"{task.source}\t{task.cadence or 'all'}\t{task.sequence or ''}\t"
            f"{location}\t{task.command}"
        )
    return "\n".join(lines)


def parse_kickoff() -> datetime:
    raw = os.environ.get("UPDATE_LOG_KICKOFF")
    if raw:
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("could not parse UPDATE_LOG_KICKOFF=%r; using now", raw)
        else:
            return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)
