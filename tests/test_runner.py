import os
import sys

from scs_runner import run_sources

from config import Config
from runner import build_tasks, format_plan, query_schedule, repo_name


class FakeFrame:
    def __init__(self, rows):
        self._rows = rows

    def to_dicts(self):
        return self._rows


class FakeDB:
    def __init__(self):
        self.sql = None
        self.kwargs = None

    def read(self, sql, **kwargs):
        self.sql = sql
        self.kwargs = kwargs
        return FakeFrame([])


class FakeHub:
    def __init__(self):
        self.db = FakeDB()


def test_repo_name_uses_last_dotted_segment():
    assert repo_name("scs.nba.mod.player_archetypes") == "player_archetypes"


def test_query_schedule_filters_model_family_cadence_and_pause():
    hub = FakeHub()
    query_schedule(hub, cadences=["weekly", "intraday"])

    assert "job_family = 'model'" in hub.db.sql
    assert "cadence IN (:cadence0, :cadence1)" in hub.db.sql
    assert "pause IS NOT TRUE" in hub.db.sql
    assert hub.db.kwargs["execute_options"]["parameters"] == {
        "cadence0": "weekly",
        "cadence1": "intraday",
    }


def test_query_schedule_manual_task_ignores_cadence_and_pause():
    hub = FakeHub()
    query_schedule(
        hub,
        cadences=["weekly"],
        tasks=["player_archetypes"],
        include_paused=True,
    )

    assert "cadence IN" not in hub.db.sql
    assert "pause IS NOT TRUE" not in hub.db.sql
    assert "associated_function = :task0" in hub.db.sql
    assert "associated_function LIKE :task_suffix0" in hub.db.sql
    params = hub.db.kwargs["execute_options"]["parameters"]
    assert params["task0"] == "player_archetypes"
    assert params["task_suffix0"] == "%.player_archetypes"


def test_build_tasks_derives_source_task_and_remote_target():
    config = Config(
        base_path="/srv/nba/mod",
        host="jetson",
        remote_path="/usr/local/bin:/usr/bin",
        entrypoint="uv run --frozen python __main__.py",
        default_timeout=123,
    )
    rows = [
        {
            "associated_function": "scs.nba.mod.player_archetypes",
            "cadence": "weekly",
            "schema_sequence": None,
            "pause": False,
        }
    ]

    tasks, targets = build_tasks(rows, config)

    assert len(tasks) == 1
    assert tasks[0].source == "scs.nba.mod.player_archetypes"
    assert tasks[0].task == "player_archetypes.job"
    assert tasks[0].command == "uv run --frozen python __main__.py"
    assert tasks[0].timeout_seconds == 123
    target = targets["scs.nba.mod.player_archetypes"]
    assert target.host == "jetson"
    assert target.root == "/srv/nba/mod/player_archetypes"
    assert target.environment == {"PATH": "/usr/local/bin:/usr/bin"}


def test_build_tasks_rejects_duplicate_sources():
    config = Config()
    rows = [
        {
            "associated_function": "scs.nba.mod.player_archetypes",
            "cadence": "weekly",
            "schema_sequence": None,
            "pause": False,
        },
        {
            "associated_function": "scs.nba.mod.player_archetypes",
            "cadence": "weekly",
            "schema_sequence": None,
            "pause": False,
        },
    ]

    try:
        build_tasks(rows, config)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate sources should fail")


def test_build_tasks_and_ssh_round_trip(tmp_path):
    repo = tmp_path / "player_archetypes"
    repo.mkdir()
    (repo / "__main__.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path(os.environ['SCS_RESULT_FILE']).write_text("
        "json.dumps({'row_count': 11}))\n",
        encoding="utf-8",
    )
    fake_ssh = tmp_path / "fake-ssh"
    fake_ssh.write_text(
        "#!/bin/sh\nfor last; do :; done\nexec sh -c \"$last\"\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)

    config = Config(
        base_path=str(tmp_path),
        host="fake-host",
        remote_path=os.environ["PATH"],
        entrypoint=f"{sys.executable} __main__.py",
        ssh_binary=str(fake_ssh),
        default_timeout=60,
    )
    tasks, targets = build_tasks(
        [
            {
                "associated_function": "scs.nba.mod.player_archetypes",
                "cadence": "weekly",
                "schema_sequence": None,
                "pause": False,
            }
        ],
        config,
    )

    rows = []
    result = run_sources(
        tasks,
        source="scs.nba.mod.runner",
        cadence="weekly",
        write_log=rows.append,
        targets=targets,
    )

    assert result.success
    assert result.results[0].row_count == 11
    assert [row["task"] for row in rows] == [
        "process start",
        "player_archetypes.job",
        "process end",
    ]
    assert rows[1]["source"] == "scs.nba.mod.player_archetypes"
    assert rows[1]["row_count"] == 11


def test_format_plan_includes_remote_location():
    config = Config(base_path="/srv/nba/mod", host="jetson")
    tasks, targets = build_tasks(
        [
            {
                "associated_function": "scs.nba.mod.player_archetypes",
                "cadence": "weekly",
                "schema_sequence": None,
                "pause": False,
            }
        ],
        config,
    )

    plan = format_plan(tasks, targets)

    assert "scs.nba.mod.player_archetypes" in plan
    assert "jetson:/srv/nba/mod/player_archetypes" in plan
    assert "player_archetypes.job" not in plan
    assert "uv run" in plan
