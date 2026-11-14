# Python API: `Session`

```python
from roboloom import Session, EpisodeInfo, EpisodeResult, SessionError
```

`Session` launches the robot's dora dataflow (one process per follower, leader, sensor,
recorder, policy) and sends events. It never runs a control loop itself.

## Launch

```python
@classmethod
def launch(  # Session.launch
    cls,
    config,  # robot name ("rakuda2"), path, or a loaded RobotConfig
    *,
    options=None,  # whole set of options to enable; None = defaults
    mock=None,  # True mock devices, False hardware, None = YAML mode (default hardware)
    sensors=None,  # recorded sensors to start; None = defaults, [] = none
    observe=None,  # policy inputs; None = YAML
    video_codec=None,  # "av1" / "h264" for storage: video images; None = recorder YAML
    policy=None,  # "module:callable" replacing the policy controller's factory
    policy_kwargs=None,  # dict of kwargs for it
    log_dir=None,
    timeout=60.0,  # wait until every node reports status
    screen="auto",  # Rich status table when stdout is a TTY; False disables
    operator="auto",  # ask to support arms on exit when stdin is a TTY; None skips
) -> Session: ...
```

- `options` / `mock` apply only when `config` is a name or path. For a `RobotConfig`,
  choose them in `load_config(config, options=..., mock=...)`; `sensors`, `observe`
  and `video_codec` with a `RobotConfig` are an error (choose them in `load_config`).
- Use it as a context manager. Leaving the block discards an in-progress episode, asks
  the operator (if any) to support the arms, stops the dataflow. The leader goes limp;
  the follower keeps torque unless release was chosen. From a script decide explicitly:
  `s.close(release=True)` or `s.close(release=False)`.
- `screen` reads no keys: `print()` and `input()` work in your script.

## Record

```python
with Session.launch("rakuda2", options=["gravity"]) as s:
    s.wait_ready()  # leader aligned / policy loaded (timeout=30.0)
    r = s.record("pick up the cup", seconds=30)
    print(r.index, r.frames, r.warnings, r.ok)
```

`record(task, seconds, *, keep=None, on_tick=None, tick_s=0.2, ready_timeout=60.0, home=False) -> EpisodeResult`

- Waits until start is allowed (alignment), starts, records, stops, saves unless
  `keep(result)` returns `False`. Exception or Ctrl-C discards the episode.
- Raises `EpisodeFailed` (a `SessionError`) and discards the episode when a controller
  fails during it (the policy raised) or a follower latches FAULT/ESTOP. The policy is
  ready for the next `record` without a restart.
- When the launching process ends in any way (killed too), the dataflow discards the
  running episode, the followers hold and it ends; `close()` is not what keeps a robot
  from running on.
- `task`: a string or `Callable[[EpisodeInfo], str]`.
  `EpisodeInfo(index, number, dataset, previous)`: dataset episode index, number in this
  session, dataset name (e.g. `rakuda2-digit`), tasks saved in this session.
- `home=True` moves leader and follower to the controller's `home` pose first.
- `EpisodeResult(task, saved, frames, index, metrics, warnings)`, `.ok` = no warnings.

```python
import itertools

objects = itertools.cycle(["cup", "bottle", "sponge"])
s.record(lambda info: f"pick up the {next(objects)}", seconds=20, keep=lambda ep: ep.ok)
```

## Fine-grained control

| Call | Effect |
| --- | --- |
| `start(task)` | start following + recording; `SessionError` if not aligned |
| `stop() -> EpisodeResult` | stop; not saved yet (inspect metrics/warnings) |
| `save(timeout=300.0) -> EpisodeResult` / `discard()` | write the episode (readable from then on, whatever happens to the process) or drop it; a failed write raises `SessionError` and drops the episode |
| `home(timeout=None)` | slow move to the home pose; refused while recording |
| `estop()` | emergency stop (latched); goes out even after a node failed |
| `release(confirm=False)` | torque off; with `confirm=False` raises `HardwareError` carrying `release_note()` |
| `status() -> dict` | latest status per node `{name: {"role", "level", "fields", "t_ns"}}`, e.g. `s.status()["follower"]["fields"]["mode"]` |
| `reports() -> list[dict]` | unread reports (mode changes, ...) |
| `episodes` (property) | episodes in the dataset |
| `log_dir` | log directory of this run |
| `note(text, level="info")` | message on the status screen |

```python
s.start("wipe the table")
while not task_done():
    time.sleep(0.5)
stopped = s.stop()
s.save() if stopped.ok else s.discard()
```

Each node process gets `ROBOLOOM_OPTIONS` and `ROBOLOOM_MODE` in its environment.

## Policies

`Session.launch(cfg, options=["policy"], policy="pkg.mod:load", policy_kwargs={...})`;
then `record(...)` saves evaluation episodes to the `-eval` dataset. See
[policy.md](policy.md).

## Loading configuration

```python
from roboloom import load_config, resolve_config

cfg = load_config("rakuda2", options=["digit"], mock=True)  # validates; opens nothing
cfg.options, cfg.repo_id, cfg.mock
```

## Errors

`RoboloomError` ⊃ `ConfigError` (bad configuration), `SetupError` (measurement
preconditions/accuracy), `HardwareError` (device state mismatch), `SessionError` (dataflow
refused a command or stopped); `roboloom.errors.Cancelled` = an operator declined, nothing
written.

Other modules: setup steps in [setup.md](setup.md); one-process sessions in
[in-process.md](in-process.md).
