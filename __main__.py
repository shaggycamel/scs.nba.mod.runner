"""Run the scs.nba.mod model repos listed in util.update_schedule.

The NUC runs this module from cron.sh. It reads model rows through scs_hub,
executes each repo's root __main__.py on the Jetson over SSH, and writes the
status rows through scs_runner.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace

from scs_runner import Failure, failure_alert, run_sources, send_failure_email

from config import load_config
from runner import (
    build_tasks,
    format_plan,
    make_log_writer,
    parse_kickoff,
    query_schedule,
)

logger = logging.getLogger("scs.nba.mod.runner")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scs-mod-run",
        description="Run the model repos scheduled in util.update_schedule.",
    )
    parser.add_argument(
        "cadences",
        nargs="*",
        help="Cadence filter(s), space- or comma-separated; bare run means all.",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="REPO",
        help="Run a specific model repo (repeatable); ignores cadence and pause.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ignore the cadence filter and run every unpaused model row.",
    )
    parser.add_argument(
        "--db-section",
        help="Credentials section (default: cockroach-write)",
    )
    parser.add_argument("--credentials", metavar="PATH", help="Credentials INI path")
    parser.add_argument("--host", help="SSH host/alias for the Jetson")
    parser.add_argument("--base-path", help="Base path containing the model repos")
    parser.add_argument("--list", action="store_true", help="List selected tasks")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved plan without running anything",
    )
    parser.add_argument("--no-alert", action="store_true", help="Do not send failure email")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    return parser


def parse_cadences(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in value.replace(",", " ").split():
            if part not in seen:
                seen.add(part)
                out.append(part)
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()
    if args.db_section:
        config = replace(config, db_section=args.db_section)
    if args.credentials:
        config = replace(config, ini_path=args.credentials)
    if args.host:
        config = replace(config, host=args.host)
    if args.base_path:
        config = replace(config, base_path=args.base_path)
    if args.no_alert:
        config = replace(config, alert=False)

    cadences = parse_cadences(args.cadences)
    if args.task and not cadences:
        cadence_label = "manual"
    elif args.all or not cadences:
        cadence_label = "all"
    else:
        cadence_label = ",".join(cadences)

    try:
        from scs_hub import SportsHub

        hub = SportsHub(db_con=config.db_section, ini_path=config.ini_path)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("could not connect to [%s]", config.db_section)
        _alert(config, [Failure("util.update_schedule", error)])
        return 1

    try:
        rows = query_schedule(
            hub,
            cadences=cadences,
            tasks=args.task,
            all_cadences=args.all or not cadences,
            include_paused=bool(args.task),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("could not read util.update_schedule")
        _alert(config, [Failure("util.update_schedule", error)])
        return 1

    if not rows:
        logger.warning(
            "no model tasks selected for cadence=%s host=%s", cadence_label, config.host
        )
        return 0

    try:
        tasks, targets = build_tasks(rows, config)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("invalid model schedule")
        _alert(config, [Failure("util.update_schedule", error)])
        return 1

    if args.list or args.dry_run:
        print(format_plan(tasks, targets))
        return 0

    alert = (
        failure_alert(config.source_label, ini_path=config.ini_path)
        if config.alert
        else None
    )
    try:
        result = run_sources(
            tasks,
            source=config.source_label,
            cadence=cadence_label,
            write_log=make_log_writer(hub),
            targets=targets,
            job_kickoff=parse_kickoff(),
            alert=alert,
            bookends=config.bookends,
            include_paused=bool(args.task),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("model run failed before execution completed")
        _alert(config, [Failure("scs.nba.mod.runner", error)])
        return 1

    if result.success:
        logger.info("all %d model task(s) successfully completed", len(result.results))
    else:
        logger.error(
            "failed tasks: %s",
            [
                f"{failure.source}:{failure.task}"
                if failure.source
                else failure.task
                for failure in result.failures
            ],
        )
    return result.exit_code


def _alert(config, failures: list[Failure]) -> None:
    if not config.alert:
        return
    try:
        send_failure_email(
            failures,
            source=config.source_label,
            ini_path=config.ini_path,
        )
    except Exception:
        logger.exception("could not send failure email")


if __name__ == "__main__":
    raise SystemExit(main())
