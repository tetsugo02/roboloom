# Leader

Rakuda2のleaderは `inputs` の `rakuda2_leader` ノードが関節位置を読み，`controllers` の `joint` ノードがfollowerの目標へ変換します．leaderの関節とfollowerの関節の対応・符号・オフセットは `nodes/controller.yaml` の `joints` で指定します．

```yaml
type: joint
input: leader
robot: robot
unit: dynamixel_count
alignment_tolerance: 150
max_speed_counts_per_s: 2048
command_deadline_ms: 100
input_timeout_ms: 150
# 実際の設定には17関節のjoints対応表も必要です．
```

これらは配布テンプレートの値です．機体の可動域・通信周期・停止挙動を確かめた上で設定してください．

| 項目 | 意味 |
| --- | --- |
| `alignment_tolerance` | 開始前に許すleaderとfollowerの関節差（counts） |
| `max_speed_counts_per_s` | 目標値の変化速度の上限 |
| `command_deadline_ms` | robotへ送る指令の有効期限 |
| `input_timeout_ms` | leader入力が古いと判定するまでの時間 |

画面で `aligning` が出たら，表示された関節差を見ながらleaderをfollowerに揃えます．`following` になってから `start <task>` します．入力が古いと `input_stale` となり，新しい入力なしに追従を続けません．

leaderのトリガーは `law: spring`，重力補償は `law: gravity_comp` で設定します．これらはleaderノード自身が実行するモーター制御則です．実機では `Session` / CLIのdataflowで動かします．`Experiment.from_yaml()` は制御則を実行するleaderを受け付けません．

具体的なセットアップは [Rakuda2 Quick start](../quick-start/rakuda2.md) にあります．
