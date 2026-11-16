# 方策

!!! note "状態：実機検証済み"
    <span class="status status--verified">実機検証済み</span> Rakuda2の実機で，方策の推論と介入（`policy`，`policy_teleop`）を確かめています．非同期の推論，記録の再生，別プロセスの方策は <span class="status status--mock">模擬のみ</span> です．

`type: policy` のcontrollerは，学習した方策の行動をフォロワの目標にします．方策は `reset()` と `infer(observation)` を持つオブジェクトで，記録と同じ観測を受け取り，関節の絶対目標を返します．controllerは周期，補間，速度の制限，安全の検査を受け持ちます．

```yaml
# nodes/policy.yaml（抜粋）
type: policy
followers: [follower]
factory: roboloom.policy:hold  # "module:callable"
observe: [camera]
rate_hz: 15
action_horizon: 8
```

```bash
uv run roboloom infer --seconds 20 --policy my_lab.policies:load
```

`teleop:` を書くと，エピソードの前と途中にleaderで動かせます（[テレオペと介入](../policy/intervention.md)）．

## 対応する機体 { #supported-robots }

| 機体 | オプション | 状態 | 設定例 |
| --- | --- | --- | --- |
| Rakuda2 | `policy`，`policy_teleop` | <span class="status status--verified">実機検証済み</span> | [Rakuda2のcontroller](../robots/rakuda2/controllers.md#policy) |
| PiPER＋Pika Gripper | `policy` | <span class="status status--dev">開発中</span> | [PiPERのcontroller](../robots/piper/controllers.md#policy) |
| 自分のロボット | 設定しだい | <span class="status status--mock">模擬のみ</span> | [自分のロボットを足す](../tutorials/own-robot.md) |

## 詳しい説明 { #details }

方策の書き方，LeRobotの方策，周期と補間，評価は [方策と推論](../policy/index.md) の章にあります．キーの一覧は [方策の設定](../reference/configuration/policy.md) にあります．
