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

## leaderの関節を固定する

使用する `nodes/leader.yaml` または `nodes/leader_gravity.yaml` の `control` で，固定する関節を `law: position` のグループへ移します．例えば，テンプレートの `body` グループを次の2グループに置き換えると，腰は手で動かせ，首のyawとpitchは固定されます．腕とトリガーのグループは残してください．既存の設定で胴体・頭部が `hand` に含まれる場合は，この3関節を `hand` から取り除きます．全関節がちょうど1グループに含まれる必要があります．

```yaml
control:
  - group: body
    law: free
    joints: [torso_yaw]
  - group: fixed_head
    law: position
    joints: [head_yaw, head_pitch]
  # 腕とトリガーの既存グループを続けます．
```

`position` は通電直前の実測位置を目標として書いてから，選択した関節だけトルクをオンにします．古いGoal Positionへ移動させる処理ではありません．leaderは外部目標を受けないため，その位置を保持します．固定はSessionの起動時から有効で，`stop` で収集を止めても続き，`estop`・`release`・`quit` で脱力します．起動前に，固定するleader関節をfollowerの姿勢へ揃えてください．

モーターの位置制御と対応バスAPIが必要です．Operating Modeは `position`（Rakuda2では3）を読み返して検査し，不一致では通電しません．変更が必要な場合はdataflowを止め，機体を支持した上で既存の `roboloom commission <exp> leader --hardware` を使います．`robot.yaml` の `torque: false` はleaderの固定を無効にしません．

## 関節間の相殺を設定する

`nodes/controller.yaml` の `couplings` は，関節対応・符号・オフセットで変換した目標へ，followerの別関節の**実測変位**を加えます．既定は `[]`（無効）です．Rakuda2の腰yawと首yawで，同じカウント変化が同じ向きの回転を表す場合は次の設定になります．

```yaml
couplings:
  - joint: head_yaw
    source: torso_yaw
    scale: -1.0
    reference: 2048
```

```text
首の目標 = leaderから変換した首の目標
         - (followerの現在の腰位置 - reference)
```

`reference` は，leaderから変換した首の目標をそのまま使う腰の位置（counts）です．腰が正面を向く位置を設定します．例えば腰が `reference` から+100 counts回転すると，首の目標に-100 countsを加えます．上の関節固定と併用すると，leaderの首を固定したまま腰の回転を相殺できます．leaderの首を自由にすると，操作者による首の操作に相殺分が加わります．

- `joint` と `source` はfollowerの関節名です．同じ関節の指定，未知の関節，重複した `joint`，有限値でない `scale` は設定読み込み時に拒否します．
- 基準は設定した固定値です．位置合わせの時点の姿勢は使いません．位置合わせは許容差（`alignment_tolerance`）内のずれを認めるため，その時点の姿勢を基準にすると，ずれの分だけ首が常に偏ります．再位置合わせやleaderノードの再起動でも基準は変わりません．
- 位置合わせでは相殺後の首の目標とfollowerの首を比べます．followerのカメラが正面から大きく外れた状態で起動すると，`head_yaw` が許容差を超えて `aligning` のままになります．起動前にfollowerのカメラ向きとleaderの首を揃えてください．
- 腰の目標値ではなく実測値を使うため，腰が指令に追いついていない段階で首だけを先回りさせません．相殺後にも既存の速度制限とrobot側の範囲・期限・変化量検査がかかります．
- `joint`・`source`・`scale`・`reference` はすべて必須です．
- これは指定した関節間の線形な相殺です．全姿勢のカメラ安定化，IMUフィードバック，台座の回転補償ではありません．軸が平行で，符号と単位比が正しいことが前提です．他の機体では `scale` に軸の符号と単位比を設定します．速度制限や可動域端，追従遅れではカメラの向きに誤差が残ります．
- `type: joint` の遠隔操作に適用します．方策controllerの出力には適用しません．関節名をコードに固定していないので，他のロボットのjoint controllerにも使えます．

関節固定と相殺の組み合わせは模擬バス・controllerで検証しています．実機での方向・可動域・追従精度は未検証です．既存の `.roboloom/` は自動更新しないため，設定例を使用中のYAMLへ反映してください．
