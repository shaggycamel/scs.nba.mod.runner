# scs.nba.mod.runner

Runs the model repositories under `nba/mod` from `util.update_schedule`.

The NUC is the scheduler. It reads `job_family = 'model'` rows through
`scs_hub`, executes each repo's root `__main__.py` on the Jetson over SSH, and
writes `util.update_log` rows through `scs_runner`.

## Schedule row

A model row uses `associated_function` as the repo identifier:

```text
job_family          model
schema              mod
table_name          player_archetypes
associated_function scs.nba.mod.player_archetypes
cadence             weekly
schema_sequence     NULL
function_sequence   NULL
pause               FALSE
```

The repo directory is the last segment of `associated_function`
(`player_archetypes`). The runner executes:

```bash
cd <base_path>/<repo>
uv run --frozen --group data python __main__.py
```

The repo writes `SCS_RESULT_FILE` with `{"row_count": n}`. The runner writes
`process start`, one task row, and `process end` to `util.update_log`.

## Run

```bash
./cron.sh weekly
./cron.sh --list
./cron.sh --dry-run
./cron.sh --task player_archetypes
```

Crontab on the NUC:

```cron
0 14 * * 1 /home/oli/shaggy_camel_sports/nba/mod/_runner/cron.sh weekly \
  >> /home/oli/shaggy_camel_sports/nba/mod/_runner/cron.log 2>&1
```

Monday 14:00 UTC is after the database daily update at 13:00.

Deploy:

```bash
cd /home/oli/shaggy_camel_sports/nba/mod/_runner
uv sync --frozen --no-dev
./cron.sh --list
./cron.sh weekly --dry-run
```

## Configuration

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCS_MOD_DB_SECTION` | `cockroach-write` | credentials section |
| `SCS_HUB_CREDENTIALS` | `~/.config/scs_hub_credentials.ini` | credentials file |
| `SCS_MOD_HOST` | `jetson` | SSH host/alias |
| `SCS_MOD_BASE_PATH` | `/home/oli/shaggy_camel_sports/nba/mod` | model repo root on the Jetson |
| `SCS_MOD_REMOTE_PATH` | `/home/oli/.local/bin:/usr/local/bin:/usr/bin:/bin` | remote `PATH` |
| `SCS_MOD_ENTRYPOINT` | `uv run --frozen --group data python __main__.py` | repo command |
| `SCS_MOD_TIMEOUT` | `3600` | per-task timeout |
| `SCS_MOD_ALERT` | `1` | send failure email |
| `SCS_MOD_BOOKENDS` | `source` | `source`, `run` or `none` |
| `SCS_MOD_REMOTE_CREDENTIALS` | unset | optional `SCS_HUB_CREDENTIALS` path on the Jetson |
| `SCS_MOD_SSH_BINARY` | `ssh` | SSH binary (tests can substitute a fake) |

SSH options are `BatchMode=yes`, `ConnectTimeout=30` and
`ServerAliveInterval=30`. Put the host, user and key in the NUC's
`~/.ssh/config`:

```sshconfig
Host jetson
    HostName jetson.tail195465.ts.net
    User oli
    IdentityFile ~/.ssh/nuc_archetypes_key
```

## Development

```bash
uv sync --group dev
uv run pytest
```

`scs-runner` is installed from its git repository. `uv.lock` pins the resolved
commit for reproducible deploys.
