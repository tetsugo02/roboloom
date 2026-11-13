# Rakuda2をPika SenseとIKで動かす（開発中）

!!! warning "開発中・模擬のみ"
    Rakuda2テンプレートのオプション `pika` は，模擬のデバイスだけで確かめています．腕の関節の対応表（零点のカウントと向き），グリッパーの対応，ツールのオフセット，作業範囲は，どれも仮の値です．腕の逆運動学は，方向によって条件が悪くなります（[限界](#limitations)）．[実機の前に](#before-hardware) の確認を済ませるまで，実機では動かさないでください．

leaderの代わりに，腕ごとに1台のPika Senseで，逆運動学を通してRakuda2を動かします．Rakuda2やPikaに限らない2つの仕組みを，初めて使う構成です．[フォロワの部分](../reference/configuration.md#parts) と，フォロワ自身の関節の単位で扱う運動学です．

## 構成

| ノード | ファイル | 内容 |
| --- | --- | --- |
| tracker `lighthouse` | `nodes/lighthouse.yaml` | libsurvive．2台のSenseを1つのノードで扱う |
| 入力 `right_sense`，`left_sense` | `nodes/right_sense.yaml`，`nodes/left_sense.yaml` | 手の姿勢とつまみの角度（[Pika Sense](pika-sense.md)） |
| controller `controller` | `nodes/controller_pika.yaml` | `type: parts`．下の2つのcontrollerを持ち，17関節すべての指令を1本にまとめてフォロワへ送る |
| その内側 | `nodes/pika_right.yaml`，`nodes/pika_left.yaml` | `type: pose_ik`．`follower.right_arm` と `follower.right_gripper`（左も同じ）を動かす |
| フォロワ `follower` | `nodes/follower.yaml` | 変更なし．`kinematics:` が腕ごとの関節の対応表を指す |

```bash
uv run roboloom run --with pika --mock
```

- 胴体と頭（部分 `body`）はどのcontrollerも動かさず，フォロワが保持している位置に留まります．姿勢は，胴体と一緒に回る座標系で表します．
- 対応付けは，PiPERと同じく相対です．操作者が握った時点の腕の位置から，それ以降の手の動きの分だけツールを動かします．目標が `workspace` の外にあるか，IKが届かない間は，指令を送りません．
- フォロワの安全の検査，記録する `action`（17個のカウント），データセットの形は，leaderでの遠隔操作と同じです．記録する入力が違うので，データセット名に `-pika` が付きます．
- IKはURDFのradで計算します．腕のカウントとの換算は，IKの前後で，`calibration/follower_<side>.yaml` の対応表（関節ごとの `urdf`，`zero`，`direction`）を使って行います．rad = direction ×（カウント − zero）× 2π / 4096 です．
- グリッパーは，1関節の部分で，単位はカウントです．カウント = `gripper_map.scale` × つまみの角度（rad）+ `gripper_map.offset` です．

## 実機の前に { #before-hardware }

1. `calibration/follower_<side>.yaml` の腕の各関節の `zero` と `direction` を実機で確かめ（`roboloom calibrate-joints`），`confirmed: true` にします．`confirmed: false` のままでは，このオプションは実機で起動しません．模擬のデバイスでは起動します．
2. Senseのつまみを閉じたときと開いたときのグリッパーのカウントを測り，`nodes/pika_<side>.yaml` の `SET_<SIDE>_GRIPPER_CLOSED_COUNT` と `SET_<SIDE>_GRIPPER_COUNTS_PER_RAD` を埋めます．
3. この機体に合わせて `tool_offset` と `workspace` を決め，`max_speed` を低くして始めます．[Pika Sense](pika-sense.md) の「実機で最初にすること」に従ってください．

## 限界 { #limitations }

- **腕のIKの条件．** 同梱のURDF（`assembly_2.urdf`，CADからの書き出し）では，試した姿勢で，腕のヤコビアンの最小の特異値が0.001〜0.02 m/radでした．ツールの向きを保ったままでは，ほとんど動かせない並進の方向が，たいてい1つあります．その方向へ動かそうとすると，controllerは `unreachable` を出して保持します．これが腕の実際の形によるものか，URDFや関節の対応表の誤りによるものかは，確かめていません．向きより位置を優先して解く方法は実装していません．
- `type: parts` の内側のcontrollerには，まだ `home` がありません．握る前に，別の方法で腕を曲げた姿勢にしてください（腕を伸ばした姿勢は特異です）．
- このオプションは `policy` と併用できません．partsのcontrollerを，方策の `teleop:` に使うこともできません．

## ほかの入力とシミュレーター

上の部品は，使い回すためのものです．以下はどれも実装していません．

- **VRのコントローラー，UMIのようなグリッパー．** 姿勢を出すデバイスは，`PoseInput`（`roboloom.inputs.base`．位置，クォータニオン，任意でつまみの角度，`tracking`，`engaged`）のサブクラスにして，`roboloom.inputs.INPUTS` に登録します．`pose_ik` と `parts` はそのまま使えます．別の計算機で読むデバイスは，受け取った側の時計で時刻を付ける必要があります．
- **フォロワと同じ形のleader．** 関節名と単位が同じなら，`type: joint` に対応表は要りません（[Leader](../controllers/leader.md)）．違うアームでは `joints:` を書きます．
- **別のロボット．** フォロワのモデルは，関節，単位，安全の性質を宣言します．腕の鎖があれば，`kinematics()` で，自分の単位からradへの対応と一緒に返します（PiPERのようにradで話すロボットは恒等です）．`PARTS` は，複数のcontrollerで分けて動かしたいフォロワだけが宣言します．`control:` の制御則（`roboloom.control`）は，Dynamixelのようなバス（カウント，mA，Operating Mode）を前提にしています．PiPERのように自前の位置制御を持つロボットは使いません．
- **シミュレーター．** フォロワの `open_bus` は `JointBus`（`read_positions`，`write_positions`，`enable_torque`，`close`，任意で `read_state`）を返します．同じフォロワのモデルの裏に模擬のバスを置けば，controller，IK，安全の検査，記録は変わりません．実機と同じ単位（Rakuda2ならカウント．同じ対応表を通す）で話せば，データセットと方策を実機と共有できます．
