# 対応表

どの機体で，どのcontroller・sensor・方策が使えるかの一覧です．labelの意味と今の状態の元の表は [状態label](../reference/status-labels.md) にあります．ここと機体ページ，Controllers，Sensorsの表は，同じ表から写しています．

| label | 意味 |
| --- | --- |
| <span class="status status--verified">実機検証済み</span> | 実機で動かして確かめた |
| <span class="status status--mock">模擬のみ</span> | testと模擬（`--mock`）だけで確かめた |
| <span class="status status--dev">開発中</span> | 実装の途中か，実機で一度も動かしていない |
| <span class="status status--design">設計のみ</span> | 使える機能として扱わない |

## 機体 { #robots }

| 機体 | followerの `type` | 状態 | ページ |
| --- | --- | --- | --- |
| Rakuda2 | `rakuda2_follower` | <span class="status status--verified">実機検証済み</span> | [Rakuda2](../robots/rakuda2/index.md) |
| PiPER | `piper_follower` | <span class="status status--dev">開発中</span> | [PiPER](../robots/piper/index.md) |
| Pika Gripper | `pika_gripper_follower` | <span class="status status--dev">開発中</span> | [Pika](../robots/pika/index.md) |
| 自分のrobot | `module:Class` | <span class="status status--mock">模擬のみ</span> | [自分のrobotを足す](../tutorials/own-robot.md) |

## Controllerと入力 { #controllers }

| 機体 | Leader（`joint`） | 重力補償付きleader | 方策（`policy`） | 方策＋介入（`policy_teleop`） | Pika SenseとIK（`pose_ik`） | 力の逆送（`bilateral`） |
| --- | --- | --- | --- | --- | --- | --- |
| Rakuda2 | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--dev">開発中</span> | <span class="status status--mock">模擬のみ</span>（中断中） |
| PiPER＋Pika Gripper | — | — | <span class="status status--dev">開発中</span> | —（`pose_ik` は介入に未対応） | <span class="status status--dev">開発中</span> | — |
| 自分のrobot | 設定しだい | — | <span class="status status--mock">模擬のみ</span> | 設定しだい | 設定しだい | — |

- Rakuda2のleaderの関節固定（`law: position`）と腰yawの相殺（`couplings`）は <span class="status status--mock">模擬のみ</span> です（[Leader](../controllers/leader.md)）．
- 機体ごとの設定例は [Rakuda2のcontroller](../robots/rakuda2/controllers.md) と [PiPERのcontroller](../robots/piper/controllers.md) にあります．

## sensor { #sensors }

| 機体 | RealSense | DIGIT | 音声 | Pikaの手首camera | Web camera |
| --- | --- | --- | --- | --- | --- |
| Rakuda2 | <span class="status status--verified">実機検証済み</span> | <span class="status status--verified">実機検証済み</span> | <span class="status status--dev">開発中</span> | — | <span class="status status--dev">開発中</span> |
| PiPER＋Pika Gripper | <span class="status status--dev">開発中</span> | — | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> |
| Pika Senseを手に持つ（followerなし） | — | — | — | <span class="status status--dev">開発中</span> | — |

- 音声（`mel_mono`）とWeb camera（`opencv_rgb`）は，どの機体の設定にも足せる種類です．Web cameraはtemplateには入っていません．
- 機体ごとの組み合わせは [Rakuda2のsensor](../robots/rakuda2/sensors.md) にあります．

## 方策 { #policies }

| 機体 | 自作の方策 | LeRobotの方策 | 記録の再生（replay） | 別process（`serve-policy`） | 非同期の推論 |
| --- | --- | --- | --- | --- | --- |
| Rakuda2 | <span class="status status--verified">実機検証済み</span> | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> |
| PiPER＋Pika Gripper | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> | <span class="status status--dev">開発中</span> |
| 自分のrobot | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> | <span class="status status--mock">模擬のみ</span> |

- LeRobotの方策は，模擬のPiPER＋Pikaで記録から推論まで通しました（[LeRobotの方策](../policy/lerobot.md)）．Rakuda2の実機ではまだ使っていません．
- 方策の章は [方策と推論](../policy/index.md) にあります．
