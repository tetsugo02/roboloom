# Pika SenseとIKによる遠隔操作（開発中・実機未検証）

!!! warning "開発中"
    手に持ったAgileX Pika Senseの姿勢を，IKでPiPERの関節角に変えて遠隔操作する仕組みの，開発中の記録です．模擬のSenseと偽の機器を使った試験だけで確かめています．実機では動かしていません．通信と座標の変換は，AgileXのpika_sdk，pika_ros，PikaAnyArmのソースから読み取ったものです．

## 構成

| 部分 | 役割 |
| --- | --- |
| Pika Sense（`pika_sense` 入力） | 手に持つ機器．Viveトラッカーで姿勢を，シリアルで挟みの角度と開始・停止のボタン（`Command`）を送ります |
| 基地局（Lighthouse） | トラッカーの姿勢を測るのに要ります．libsurviveで校正します |
| `pose_ik` controller | Senseの姿勢をPiPERの関節角に（IK），挟みの角度をPika Gripperの角度に変えます |
| PiPERフォロワ，Pika Gripperフォロワ | [PiPERフォロワ](piper.md)，[Pika Gripperフォロワ](pika-gripper.md) |

1つのSenseで，1台の腕と1台のグリッパを動かします．両腕では，Sense・controllerを2組使います．カメラは [Pikaの手首カメラ](pika-cameras.md) にあります．

## 必要なもの

- IKはpinocchioで解きます．`uv add 'roboloom[ik]'`（このリポジトリでは `uv sync --extra ik`）で入ります．
- トラッカーはlibsurvive（Pythonでは `pysurvive`）で読みます．libsurviveの導入とudev規則（`81-vive.rules`）にはsudoが要るので，管理者に頼みます．pysurviveが入っていないと，Senseのノードは理由を示して止まります．
- Senseのシリアルは，Pika Gripperと同じくpyserialで直接扱います．ポートは `/dev/serial/by-path/...` を使います．

## 設定

```yaml
# nodes/left_sense.yaml
type: pika_sense
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0
tracker: {name: WM0}     # libsurviveでのトラッカーの名前
stale_ms: 100            # 任意．これより古い姿勢やシリアルは，失ったと見なす
```

```yaml
# nodes/left_ik.yaml
type: pose_ik
input: left_sense
followers: [left, left_gripper]
arm: left                # IKで動かす腕（運動学のモデルを持つフォロワ）
gripper: left_gripper    # 任意．挟みの角度で動かす1関節のフォロワ
tool_offset: {xyz: [0.0, 0.0, 0.19], rpy: [0.0, -1.5708, 0.0]}  # フランジ（link6）から見た道具の座標
workspace: {min: [0.05, -0.45, 0.05], max: [0.6, 0.45, 0.6]}    # m．腕の基準座標（base_link）
max_input_jump: {position_m: 0.05, rotation_rad: 0.5}
ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005, rotation_tolerance_rad: 0.05}
gripper_map: {scale: 1.0, offset: 0.0}
max_speed: {left: 1.0, left_gripper: 3.0}
home: {left: {pose: ../poses/left/ready.yaml, max_speed: 0.5, tolerance: 0.02}}
command_deadline_ms: 100
input_timeout_ms: 150
```

| キー | 意味 |
| --- | --- |
| `tracker.name` | libsurviveが付けるトラッカーの名前（例 `WM0`）．`args` でlibsurviveに渡す引数を足せます |
| `tool_offset` | フランジから道具の先端への変換．上の値はAgileXが自社のグリッパに使う値です．Pika Gripperを付けたときの値は，計測して書きます |
| `workspace` | 目標の位置がこの箱の外なら指令を送りません |
| `max_input_jump` | Senseの姿勢が1回でこれより大きく跳んだら，遠隔操作を止めます |
| `ik` | 反復の回数，減衰，届いたと見なす位置と回転の許容．届かなければ指令を送りません |
| `gripper_map` | グリッパの角度 = `scale`·挟みの角度 + `offset`．グリッパの範囲に収めます |
| `max_speed` | フォロワごとの速さの上限（単位/s）．指令を送らなかった間の時間は持ち越さず，1回の指令で動くのは `input_timeout_ms` の分までです |
| `home` | 「Move home」で移る保存した姿勢．フォロワごとに書けます |

記録には，Senseごとに `observation.<名前>`（`x, y, z, qx, qy, qz, qw, gripper, engaged`，トラッカーの世界座標）が加わります．`action` は，これまでどおりフォロワの関節の指令です．

## 写し方

AgileXの遠隔操作と同じ，相対の写し方です．

- Senseで開始した瞬間の，Senseの姿勢 T_s0 と，腕の道具の姿勢 T_a0（腕が保持している目標からの順運動学）を覚えます．
- その後は `T_a0 · inv(T_s0) · T_s` を道具の目標にします．手の動きを，Sense自身の座標で道具の座標に写します．
- トラッカーの世界座標と腕の基準座標の校正は要りません．

## 開始と停止

- Senseの `Command` が変わるたびに，開始と停止が切り替わります（AgileXではダブルクリック）．
- 次のときは遠隔操作を止め，Senseで停止して開始し直すまで動かしません．
  - 姿勢を失った・古くなった（基地局が見えない），シリアルが途絶えた
  - 姿勢が `max_input_jump` を超えて跳んだ
  - フォロワが `FAULT` か `ESTOP` になった，入力が古くなった（届く間隔が `input_timeout_ms` を超えて空いたときも含む）
  - フォロワが「Move home」で移動している
- 目標が `workspace` の外のときと，IKが届かないときは，指令を送らず，腕は保持します．開始したままなので，目標が戻れば続きます．
- 電源を入れたときのPiPERの姿勢（全関節0，折りたたんだ姿勢）は特異点で，IKがほとんど解けません．開始の前に「Move home」で `home` の姿勢へ移ります．

## 模擬で確かめる

`.roboloom/piper-mock/` は，模擬のSense 2台で，模擬のPiPER 2台とPika Gripper 2台を動かす構成です．模擬のSenseは，開いてから2 s後に開始し，その後は10 s開始・2 s停止を繰り返します．

```bash
uv run roboloom run piper-mock                     # Launchのあと，Move home
uv run roboloom run piper-mock --with demo_policy  # Senseの代わりに確認用の方策
```

## 実機で最初にすること

1. 管理者に，libsurvive（pysurviveを含む）とudev規則の導入を頼みます．
2. 基地局を置き，libsurviveで校正します（`survive-cli --force-calibrate`）．トラッカーの名前（`WM0` など）を確かめます．
3. Senseのシリアルを，読むだけで確かめます．版を尋ねる `GET_INFO` だけを送ります．

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika_sense
    ```

    版，挟みの角度，`Command`，フィードバックの周期を表示します．

4. `tool_offset` を計測し，`workspace` を机と周りに合わせて狭くしてから，腕1台で試します．

## 実機で確かめること

- トラッカーの名前とシリアル，姿勢の周期と遅れ．
- 2台のSenseを，別々のプロセスからlibsurviveで読めるか．読めない場合は，1つの入力ノードで2台を読む形に変えます．
- `Command` の変わり方（ダブルクリックで0と1が入れ替わるか）．
- 挟みの角度の向きと範囲，Pika Gripperの角度との対応（`gripper_map`）．
- SDKのトラッカーからSenseの中心への変換（`inputs/pika_sense/spec.py`）が，手元の機器で正しいか．
- `tool_offset`（Pika Gripperの取り付け）．
- PiPERのファームウェアの版．URDFはS-V1.6-3以降のDHに合わせています．
