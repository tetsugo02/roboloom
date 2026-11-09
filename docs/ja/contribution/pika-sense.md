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

- PiPER＋Pikaの実機ではロボットのextrasを両方選びます．`piper` にPiPER SDKとIK用のPinocchio，`pika` に `pysurvive` と手首カメラ用の依存が入ります．
    - 自分のプロジェクトでは：`uv add git+https://github.com/tetsugo02/roboloom.git --extra piper --extra pika`（記録には `--extra record` も追加）
    - roboloomのリポジトリをcloneした中では：`uv sync --extra piper --extra pika`
- トラッカーはlibsurvive（Pythonでは `pysurvive`）で読みます．`pika` extraが，libsurviveのforkがビルドしたwheel（Linux x86_64）を入れます．インストール時のビルドはありません．トラッカーのudev規則（`81-vive.rules`）は管理者に頼みます．詳しくは [インストール](../quick-start/installation.md) にあります．pysurviveが入っていないと，Senseのノードは理由を示して止まります．
- `pysurvive` が必要なのは実機のSenseのトラッカーの姿勢だけです．PiPERの関節制御，Pikaのシリアル・カメラ，模擬では使いません．模擬の `pose_ik` と `roboloom validate` には独立した `ik` extraだけで足ります（checkoutでは `uv sync --extra ik`）．
- Senseのシリアルは，Pika Gripperと同じくpyserialで直接扱います．ポートは `/dev/serial/by-path/...` を使います．

## 設定

```yaml
# nodes/left_sense.yaml
type: pika_sense
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0
tracker: {name: WM0}     # libsurviveでのトラッカーの名前
stale_ms: 100            # 任意，既定100．これより古い姿勢やシリアルは，失ったと見なす
# poll_hz: 100           # 任意．フォロワのない構成では必須
```

```yaml
# nodes/left_ik.yaml
type: pose_ik
input: left_sense
followers: [left, left_gripper]
arm: left                # IKで動かす腕（運動学のモデルを持つフォロワ）
gripper: left_gripper    # 任意．挟みの角度で動かす1関節のフォロワ
tool_offset: {xyz: [0.0, 0.0, 0.19], rpy: [0.0, -1.5708, 0.0]}  # 必須．フランジ（link6）から見た道具の座標
workspace: {min: [0.05, -0.45, 0.05], max: [0.6, 0.45, 0.6]}    # 必須．m．腕の基準座標（base_link）
max_input_jump: {position_m: 0.05, rotation_rad: 0.5}             # 必須
ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005, rotation_tolerance_rad: 0.05}  # 任意．この値が既定
gripper_map: {scale: 1.0, offset: 0.0}                            # 任意．この値が既定
max_speed: {left: 1.0, left_gripper: 3.0}                         # 必須．フォロワごとに1つ
home: {left: {pose: ../poses/left/ready.yaml, max_speed: 0.5, tolerance: 0.02}}  # 任意
command_deadline_ms: 100 # 必須
input_timeout_ms: 150    # 必須
```

`pika_sense`：

| キー | 意味 |
| --- | --- |
| `port` | 必須．Senseのシリアルポート．`SET_` のままでは拒否します |
| `tracker.name` | 必須．libsurviveが付けるトラッカーの名前（例 `WM0`）．`SET_` のままでは拒否します．`args`（任意，文字列のリスト）でlibsurviveに渡す引数を足せます |
| `stale_ms` | 既定100．これより古い姿勢やシリアルのフィードバックは，失ったと見なします |
| `poll_hz` | 任意．入力を読む周期．書かなければ，controllerが動かすフォロワの `control_hz` のうち最も速いもので読みます．フォロワのない構成では必須です（[Pika Senseを手に持った収集](pika-handheld.md)） |

`pose_ik`：

| キー | 意味 |
| --- | --- |
| `arm`，`gripper` | `arm` は必須で，運動学のモデルを持つフォロワ（PiPER）．`gripper` は任意で，1関節のフォロワ．2つで，controllerの `followers` をちょうど指します |
| `tool_offset` | 必須．フランジから道具の先端への変換（`xyz` はm，`rpy` はrad）．上の値はAgileXが自社のグリッパに使う値です．Pika Gripperを付けたときの値は，計測して書きます |
| `workspace` | 必須．`min` と `max`（m．どの軸も `min` が `max` より小さい）．目標の位置がこの箱の外なら指令を送りません |
| `max_input_jump` | 必須．`position_m` と `rotation_rad`．Senseの姿勢が1回でこれより大きく跳んだら，遠隔操作を止めます |
| `ik` | 任意．反復の回数（既定30），減衰（既定0.001），届いたと見なす位置（既定0.005 m）と回転（既定0.05 rad）の許容．知らないキーは拒否します．届かなければ指令を送りません |
| `gripper_map` | 任意．グリッパの角度 = `scale`·挟みの角度 + `offset`（既定は1.0と0.0）．グリッパの範囲に収めます |
| `max_speed` | 必須．フォロワごとに1つ．速さの上限（単位/s）．指令を送らなかった間の時間は持ち越さず，1回の指令で動くのは `input_timeout_ms` の分までです |
| `home` | 任意．「Move home」で移る保存した姿勢．フォロワごとに書けます．各項目に `pose`，`max_speed`（そのフォロワの `max_speed` 以下），`tolerance` が要ります．`timeout_s` は既定30です |
| `command_deadline_ms` | 必須．指令が有効な時間．これより古い指令はフォロワが拒否し，保持します |
| `input_timeout_ms` | 必須．入力の届く間隔がこれを超えて空くと，遠隔操作を止めます（下の「開始と停止」） |

記録には，Senseごとに `observation.<名前>`（`x, y, z, qx, qy, qz, qw, gripper, tracking, engaged`，トラッカーの世界座標）が加わります．`action` は，これまでどおりフォロワの関節の指令です．

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

`.roboloom/piper-mock/` はroboloomのリポジトリにあり，インストールしたパッケージには入っていません（`roboloom init` のテンプレートは `rakuda2` だけです）．下のコマンドは，cloneしたリポジトリのルートで実行します．自分のプロジェクトでは，[リポジトリ](https://github.com/tetsugo02/roboloom) からこのディレクトリを自分の `.roboloom/` にコピーすれば，同じように動かせます．模擬の構成（`mode: mock`）なので，ポート，CANインターフェース，トラッカーの名前，`limits`，`tool_offset`，`workspace` の値を実機に使い回さないでください．

```bash
uv run roboloom run piper-mock                     # Launchのあと，Move home
uv run roboloom run piper-mock --with policy       # Senseの代わりに確認用の方策
```

記録したデータで学習した方策を動かす手順は [方策で動かす](../controllers/policy.md) にあります．ロボットを使わずSenseを手に持って集める方法は [Pika Senseを手に持った収集](pika-handheld.md) にあります．

## 実機で最初にすること

1. 上記の `pika` extraを導入し，トラッカーのudev規則は管理者に頼みます．
2. 基地局を置き，libsurviveで校正します．Pythonのパッケージには `survive-cli` が含まれないので，Pythonから `--force-calibrate` を渡して開きます．トラッカーを基地局から見える所に置いて動かさず，姿勢が出始めたらCtrl-Cで止めます．出てくる名前（`WM0` など）がトラッカーの名前です．この手順は実機では未検証です．

    ```bash
    uv run python - <<'EOF'
    import time
    import pysurvive

    ctx = pysurvive.SimpleContext(["calibrate", "--force-calibrate"])
    try:
        while ctx.Running():
            updated = ctx.NextUpdated()
            if updated:
                print(updated.Name().decode(), updated.Pose()[0].Pos[:])
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    EOF
    ```

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
