# Python API

Every roboloom operation is available as a Python function. The CLI (`roboloom ...`) is only a thin layer that calls those functions and prints the result. The API descriptions on these pages are generated from the docstrings.

Add roboloom to your own uv project following [Installation](../../get-started/installation.md), and use `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.1.0 --extra record` for recording. Save the code below in your own Python script and run it with `uv run python <script.py>`. Configuration and `.roboloom/` paths are relative to your project root.

## Public API { #modules }

| Module | Contents | Page |
| --- | --- | --- |
| `roboloom` | `Session`, `EpisodeInfo`, `EpisodeResult`, `EpisodeFailed`, `SessionError`, `InProcessSession`, `load_config`, `resolve_config`, `init_project`, `Sample`, the exceptions | [Session](session.md) |
| `roboloom.setup` | Measurement and setup steps (EEPROM, zeros, travel, gravity, poses, bench tests), `Operator` | [Setup](setup.md) |
| `roboloom.policy` | The policy contract (`Policy`, `PolicySpec`), `load_policy`, `hold`, the LeRobot, remote and replay loaders | [Policy](policy.md) |
| `roboloom.recording` | Checking a dataset (`check_dataset`), episode records (`episodes`), the features (`features`) | [Recording](recording.md) |

## CLI and Python { #cli-and-python }

| Task | CLI | Python |
| --- | --- | --- |
| Create a project | `roboloom init rakuda2` | `roboloom.init_project("rakuda2")` |
| Align the EEPROM | `roboloom commission [robot] <node>` | `setup.plan_commission(...)`, `setup.apply_commission(plan, operator)` |
| Measure the range of motion | `roboloom measure-travel <cal> --out ...` | `setup.measure_travel(cal, out, operator)` |
| Identify the gravity model | `roboloom identify-gravity <cal> --out ... --collect` | `setup.identify_gravity(cal, out, operator, collect=True)` |
| Check gravity compensation | `roboloom gravity-check [robot] leader right_arm --with gravity` | `setup.gravity_check(...)` |
| Tune gravity compensation | `roboloom tune-gravity [robot] leader right_arm --with gravity` | `setup.open_tuning(...)` → `TuningSession` |
| Record an episode | `roboloom record [robot] --task ... --seconds 30` | `Session.launch(...)` → `record(...)` |
| Run with a policy | `roboloom infer [robot] --policy pkg:make --seconds 30` | `Session.launch(cfg, options=["policy"], policy="pkg:make")` → `record(...)` |
| Record continuously from the operation screen | `roboloom run [robot]` | The `Session.launch(...)` status screen and `start()` / `stop()` / `save()` |
| Install the skill for coding agents | `roboloom skills install` | `roboloom.agent_skills.install(root=".", targets=("agents", "claude"), force=False)`, `agent_skills.check(...)` |

The arguments of each command are in [CLI](../cli.md).

## Example { #example }

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as s:
    s.wait_ready()  # wait until the leader is aligned with the follower
    result = s.record("pick up the cup", seconds=30)
    print(result.index, result.frames, result.warnings)
```

For more, see [Session](session.md); for running and evaluating a policy, see [Running a policy](../../policy/run.md) and [Evaluation verdicts](../../policy/evaluation.md#labels).
