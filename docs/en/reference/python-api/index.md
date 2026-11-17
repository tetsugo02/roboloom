# Python API

| Scope | Description |
| --- | --- |
| Python API | Functions used by the CLI; descriptions generated from docstrings |
| Installation | [Installation](../../get-started/installation.md) |
| Paths | Configuration and .roboloom paths are relative to the project root |

## Public API { #modules }

| Module | Contents | Page |
| --- | --- | --- |
| `roboloom` | `Session`, `EpisodeInfo`, `EpisodeResult`, `EpisodeFailed`, `SessionError`, `InProcessSession`, `load_config`, `resolve_config`, `init_project`, `Sample`, the exceptions | [Session](session.md) |
| `roboloom.setup` | Measurement and setup steps (EEPROM, zeros, travel, gravity, poses, bench tests), `Operator` | [Setup](setup.md) |
| `roboloom.policy` | The policy contract (`Policy`, `PolicySpec`), `load_policy`, `hold`, the LeRobot, remote and replay loaders | [Policy](policy.md) |
| `roboloom.hooks` | `HOOKS_API`, `Hook`, `Requirements`, `HookSpec`, `StepContext`, `ChunkPosition`, events, `HookChain` <span class="status status--mock">Mock only</span> | [Hooks](policy.md#hooks) |
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

| Reference | Link |
| --- | --- |
| Command arguments | [CLI](../cli.md) |

## Example { #example }

| Workflow | Link |
| --- | --- |
| Python session usage | [Session](session.md) |
| Policy execution | [Running a policy](../../policy/run.md) |
| Evaluation | [Evaluation verdicts](../../policy/evaluation.md#labels) |
