# PiPER＋Pika：初めての遠隔操作

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> 実機で通したことのない手順です．腕を支える人と，止める人（操作画面の前）の2人で行い，物を持たせずに確かめます．

- **目的**：腕を有効にして保持を確かめ，開始の姿勢へ動かし，ゆるい設定（`workspace` と `tool_offset` なし，遅い速度）でSenseから遠隔操作する．
- **前提**：[機体設定](setup.md) が済み，`roboloom validate piper-pika` が通る．腕の周り（届く範囲）を空けている．
- **所要**：30分．
- **結果**：両腕がSenseの動きに追従し，Gripperが挟みの開閉に追従する．

## 止め方を先に決める

- 操作画面の `Stop`（または `q` で終了するときの `hold`）は，腕をその場で保持させます．
- `release` はmotorを無効にします．**PiPERは無効にすると落ちます．** 支えている人に声をかけてから選びます．
- 通信を閉じても（processが終わっても），PiPERとGripperのmotorは無効になりません．

## 1. 保持を確かめる

腕ごとに，指令が止まったときに保持するかを測ります．支えられる状態で，周りを空けて実行します．

```bash
uv run roboloom check-hold piper-pika left --tolerance 0.02
uv run roboloom check-hold piper-pika right --tolerance 0.02
```

結果を `record` するとfollowerのYAMLに `unattended:` を書きます．最後に `release`（脱力，腕は落ちる）か，そのままにするかを選びます．詳しくは [PiPER](../../robots/piper/index.md) を参照してください．

## 2. 開始の姿勢を確かめる

`poses/left/ready.yaml` と `poses/right/ready.yaml` は，templateの値（joint2 = 1.2，joint3 = −0.9 など，この機体で測ったものではない）です．休止の姿勢から，この姿勢へ移る途中で台やもう一方の腕に当たらないかを，腕の配置と照らして確かめます．当たりそうなら値を変えます．

## 3. 起動して home へ動かす

```bash
uv run roboloom run piper-pika
```

1. Launch（Ctrl-S）で起動します．motorが有効になり，腕はその場で保持します．
2. 「Move home」で開始の姿勢へ動かします（`max_speed` 0.3 rad/s）．休止の姿勢（すべて約0）は特異姿勢で，IKが手に追従できません．
3. controllerの行が `ready` になれば，遠隔操作を始められます．

## 4. 遠隔操作する

1. Senseを，Gripperと同じ向き（挟みが前）に持ちます．
2. **Senseを素早く2回開閉すると開始**します．その瞬間のSenseと腕の道具の姿勢が基準になり，以後の手の動きがそのまま道具の動きになります（trackerとrobotの校正は要りません）．
3. はじめはゆっくり，数cmずつ動かします．腕の速度は `max_speed`（腕 0.5 rad/s）と `speed_percent` 20 で制限しています．
4. もう一度2回開閉すると停止します．腕はその場で保持します．

画面のcontrollerの状態：

| 状態 | 意味 | すること |
| --- | --- | --- |
| `following` | 追従している | — |
| `unreachable` | IKが届かない（関節の範囲の外など） | 手を戻す．戻れば追従を続ける |
| `input_jump` / `tracking_lost` | trackerが跳んだ・見失った | 基地局から見える場所で，開始し直す |
| `homing` | home へ移動中 | 終わるまで待つ |

初回は `workspace` がないので，画面に `workspace: none` と出ます．目標を止めるのは関節の範囲とIKだけです．台より下にも行こうとするので，台の近くでは特にゆっくり動かします．

## 次へ

[設定を絞る](tighten.md)：`tool_offset` と `workspace` を書き足し，速度を上げます．
