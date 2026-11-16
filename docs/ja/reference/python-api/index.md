# Python API

roboloom の操作は，どれも Python の関数として使えます．CLI（`roboloom ...`）は，その関数を呼んで結果を表示するだけの薄い層です．各ページの API の説明は docstring から生成していて，英語です．

[インストール](../../get-started/installation.md) に従って自分のuvプロジェクトへroboloomを追加し，記録には `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` を使います．以下のコードは自分のPythonスクリプトに保存して `uv run python <script.py>` で実行します．設定や `.roboloom/` のパスは自分のプロジェクトルートを基準にします．

## 公開している API { #modules }

| モジュール | 中身 | ページ |
| --- | --- | --- |
| `roboloom` | `Session`，`EpisodeInfo`・`EpisodeResult`・`EpisodeFailed`・`SessionError`，`InProcessSession`，`load_config`・`resolve_config`，`init_project`，`Sample`，例外 | [Session](session.md) |
| `roboloom.setup` | 計測と設定の手順（EEPROM，零点，可動域，重力，姿勢，卓上試験），`Operator` | [Setup](setup.md) |
| `roboloom.policy` | 方策の形（`Policy`，`PolicySpec`），`load_policy`，`hold`，LeRobot・別プロセス・再生の読み込み | [Policy](policy.md) |
| `roboloom.recording` | データセットの検査（`check_dataset`），エピソードごとの記録（`episodes`），特徴量（`features`） | [Recording](recording.md) |

## CLIとの対応 { #cli-and-python }

| やること | CLI | Python |
| --- | --- | --- |
| プロジェクトを作る | `roboloom init rakuda2` | `roboloom.init_project("rakuda2")` |
| EEPROM を合わせる | `roboloom commission [robot] <node>` | `setup.plan_commission(...)`，`setup.apply_commission(plan, operator)` |
| 可動域を測る | `roboloom measure-travel <cal> --out ...` | `setup.measure_travel(cal, out, operator)` |
| 重力モデルを同定する | `roboloom identify-gravity <cal> --out ... --collect` | `setup.identify_gravity(cal, out, operator, collect=True)` |
| 重力補償を確かめる | `roboloom gravity-check [robot] leader right_arm --with gravity` | `setup.gravity_check(...)` |
| 重力補償を調整する | `roboloom tune-gravity [robot] leader right_arm --with gravity` | `setup.open_tuning(...)` → `TuningSession` |
| エピソードを録る | `roboloom record [robot] --task ... --seconds 30` | `Session.launch(...)` → `record(...)` |
| 方策で動かす | `roboloom infer [robot] --policy pkg:make --seconds 30` | `Session.launch(cfg, options=["policy"], policy="pkg:make")` → `record(...)` |
| 操作画面で続けて録る | `roboloom run [robot]` | `Session.launch(...)` の状態画面と `start()`／`stop()`／`save()` |
| コーディングエージェント向けのスキルを入れる | `roboloom skills install` | `roboloom.agent_skills.install(root=".", targets=("agents", "claude"), force=False)`，`agent_skills.check(...)` |

各コマンドの引数は [CLI](../cli.md) にあります．

## 例 { #example }

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as s:
    s.wait_ready()  # leader が follower に揃うまで待つ
    result = s.record("pick up the cup", seconds=30)
    print(result.index, result.frames, result.warnings)
```

使い方の続きは [Session](session.md) を，方策で動かす・評価する手順は [方策で動かす](../../policy/run.md) と [評価の成否](../../policy/evaluation.md#labels) を参照してください．
