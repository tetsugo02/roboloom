# Python API

| Scope | 説明 |
| --- | --- |
| Python API | CLI が呼ぶ Python function．説明は docstring から生成 |
| Installation | [Installation](../../get-started/installation.md) |
| Paths | configuration と .roboloom の path は project root からの相対 path |

## Public API { #modules }

| module | 中身 | ページ |
| --- | --- | --- |
| `roboloom` | `Session`，`EpisodeInfo`・`EpisodeResult`・`EpisodeFailed`・`SessionError`，`InProcessSession`，`load_config`・`resolve_config`，`init_project`，`Sample`，例外 | [Session](session.md) |
| `roboloom.setup` | 計測と設定の手順（EEPROM，零点，可動域，重力，姿勢，卓上試験），`Operator` | [Setup](setup.md) |
| `roboloom.policy` | 方策の形（`Policy`，`PolicySpec`），`load_policy`，`hold`，LeRobot・別process・再生の読み込み | [policy](policy.md) |
| `roboloom.hooks` | `HOOKS_API`, `Hook`, `Requirements`, `HookSpec`, `StepContext`, `ChunkPosition`, events, `HookChain` <span class="status status--mock">Mock only</span> | [Hooks](policy.md#hooks) |
| `roboloom.recording` | datasetの検査（`check_dataset`），episodeごとの記録（`episodes`），特徴量（`features`） | [Recording](recording.md) |

## CLI and Python { #cli-and-python }

| やること | CLI | Python |
| --- | --- | --- |
| projectを作る | `roboloom init rakuda2` | `roboloom.init_project("rakuda2")` |
| EEPROM を合わせる | `roboloom commission [robot] <node>` | `setup.plan_commission(...)`，`setup.apply_commission(plan, operator)` |
| 可動域を測る | `roboloom measure-travel <cal> --out ...` | `setup.measure_travel(cal, out, operator)` |
| 重力modelを同定する | `roboloom identify-gravity <cal> --out ... --collect` | `setup.identify_gravity(cal, out, operator, collect=True)` |
| 重力補償を確かめる | `roboloom gravity-check [robot] leader right_arm --with gravity` | `setup.gravity_check(...)` |
| 重力補償を調整する | `roboloom tune-gravity [robot] leader right_arm --with gravity` | `setup.open_tuning(...)` → `TuningSession` |
| episodeを録る | `roboloom record [robot] --task ... --seconds 30` | `Session.launch(...)` → `record(...)` |
| 方策で動かす | `roboloom infer [robot] --policy pkg:make --seconds 30` | `Session.launch(cfg, options=["policy"], policy="pkg:make")` → `record(...)` |
| 操作画面で続けて録る | `roboloom run [robot]` | `Session.launch(...)` の状態画面と `start()`／`stop()`／`save()` |
| coding agent向けのskillを入れる | `roboloom skills install` | `roboloom.agent_skills.install(root=".", targets=("agents", "claude"), force=False)`，`agent_skills.check(...)` |

| Reference | Link |
| --- | --- |
| Command arguments | [CLI](../cli.md) |

## Example { #example }

| Workflow | Link |
| --- | --- |
| Python session usage | [Session](session.md) |
| Policy execution | [Running a policy](../../policy/run.md) |
| Evaluation | [Evaluation verdicts](../../policy/evaluation.md#labels) |
| Background saving (`wait_saves`, pending results) | [記録と再開](../../data/recording.md#background-saving) |
