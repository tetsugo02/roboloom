# Controllers

controllerは，入力（leader，手に持つ機器，方策）の値をフォロワの目標に変えるノードです．設定は3つに分かれます．

| 設定 | 役割 | 例 |
| --- | --- | --- |
| `inputs` | 操作する機器を読む | Rakuda-mini（`rakuda_mini`），Pika Sense（`pika_sense`） |
| `controllers` | 入力をフォロワの目標に変える．開始の条件（姿勢合わせ），速度の制限，入力の期限を持つ | `joint`，`pose_ik`，`policy`，`parts` |
| `control` | 機器のモーターに当てる制御則（leaderのばね，重力補償など）．フォロワやleaderのノード自身が動かす | `spring`，`gravity_comp`，`position` |

```mermaid
flowchart LR
  I["入力<br/>inputs"] --> C["controller<br/>controllers"]
  P["方策"] --> C
  C -- "目標" --> F["フォロワ<br/>followers"]
  F -- "状態" --> C
  L["制御則<br/>control"] -.-> I
  L -.-> F
```

## 種類 { #types }

| Controller | `type` | 入力 | 状態 |
| --- | --- | --- | --- |
| [Leader](leader.md) | `joint` | 同じ関節を持つleader | <span class="status status--verified">実機検証済み</span> |
| [方策](policy.md) | `policy` | 学習した方策（介入には `joint` のleaderも） | <span class="status status--verified">実機検証済み</span> |
| [Pika SenseとIK](pose-ik.md) | `pose_ik`（腕ごとに分けるときは `parts`） | 手に持つ機器の姿勢 | <span class="status status--dev">開発中</span> |

## 機体ごとの対応 { #by-robot }

| 機体 | Leader | 方策 | 方策＋介入 | Pika SenseとIK |
| --- | --- | --- | --- | --- |
| [Rakuda2](../robots/rakuda2/controllers.md) | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--dev">開発中</span> |
| [PiPER＋Pika Gripper](../robots/piper/controllers.md) | — | <span class="status status--dev">開発中</span> | — | <span class="status status--dev">開発中</span> |

センサーと方策の種類まで含めた表は [対応表](../get-started/support-matrix.md) にあります．controllerのキーの一覧は [Controllersの設定](../reference/configuration/controllers.md) にあります．
