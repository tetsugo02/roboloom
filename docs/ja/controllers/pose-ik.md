# Pika SenseとIKによる遠隔操作

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> 手に持ったAgileX Pika Senseの姿勢を，IKでPiPERの関節角に変えて遠隔操作する仕組みの，開発中の記録です．模擬のSenseと偽の機器を使った試験だけで確かめています．実機では動かしていません．通信と座標の変換は，AgileXのpika_sdk，pika_ros，PikaAnyArmのsourceから読み取ったものです．

## 対応する機体 { #supported-robots }

| 機体 | 動かす部分 | 状態 | 設定例 |
| --- | --- | --- | --- |
| PiPER＋Pika Gripper | 腕1台とgripper 1台（Senseごと） | <span class="status status--dev">開発中</span> | [PiPERのcontroller](../robots/piper/controllers.md#pose-ik) |
| Rakuda2 | 腕ごとの関節とgripper（`type: parts`） | <span class="status status--dev">開発中</span> | [Rakuda2のcontroller](../robots/rakuda2/controllers.md#pika) |

## 構成

| 部分 | 役割 |
| --- | --- |
| Pika Sense（`pika_sense` 入力） | 手に持つ機器．Vive trackerで姿勢を，serialで挟みの角度と開始・停止のボタン（`Command`）を送ります |
| 基地局（Lighthouse） | trackerの姿勢を測るのに要ります．libsurviveで校正します |
| `pose_ik` controller | Senseの姿勢をPiPERの関節角に（IK），挟みの角度をPika Gripperの角度に変えます |
| PiPER follower，Pika Gripper follower | [PiPER follower](../robots/piper/index.md)，[Pika Gripper follower](../robots/pika/index.md) |

1つのSenseで，1台の腕と1台のgripperを動かします．両腕では，Sense・controllerを2組使います．cameraは [Pikaの手首camera](../sensors/pika-cameras.md) にあります．

## 必要なもの

- PiPER＋Pikaの実機ではrobotのextrasを両方選びます．`piper` にPiPER SDKとIK用のPinocchio，`pika` に `pysurvive` と手首camera用の依存が入ります．
    - 自分のprojectでは：`uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.1.0 --extra piper --extra pika`（記録には `--extra record` も追加）
    - roboloomのrepositoryをcloneした中では：`uv sync --extra piper --extra pika`
- trackerはlibsurvive（Pythonでは `pysurvive`）で読みます．`pika` extraが，libsurviveのforkがbuildしたwheel（Linux x86_64）を入れます．install時のbuildはありません．trackerのudev規則（`81-vive.rules`）は管理者に頼みます．詳しくは [Installation](../get-started/installation.md) にあります．pysurviveが入っていないと，Senseのnodeは理由を示して止まります．
- `pysurvive` が必要なのは実機のSenseのtrackerの姿勢だけです．PiPERの関節制御，Pikaのserial・camera，模擬では使いません．模擬の `pose_ik` と `roboloom validate` には独立した `ik` extraだけで足ります（checkoutでは `uv sync --extra ik`）．
- Senseのserialは，Pika Gripperと同じくpyserialで直接扱います．portは `/dev/serial/by-path/...` を使います．

## 設定

```yaml
# config.yaml（抜粋）：1つのtracking systemのnodeが両方のSenseに配る
trackers:
  lighthouse: nodes/lighthouse.yaml
inputs:
  left_sense: nodes/left_sense.yaml
  right_sense: nodes/right_sense.yaml
```

```yaml
# nodes/lighthouse.yaml
type: libsurvive
args: []                 # 任意：libsurviveに渡す引数（例 [--lighthouse-gen, "2"]）
# poll_hz: 200           # 任意：姿勢を公開する周期
```

```yaml
# nodes/left_sense.yaml
type: pika_sense
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.0-port0
tracker: {system: lighthouse, serial: LHR-0123ABCD}  # trackerのserial番号
stale_ms: 100            # 任意，既定100．これより古い姿勢やserialは，失ったと見なす
# poll_hz: 100           # 任意．followerのない構成では必須
```

```yaml
# nodes/left_ik.yaml
type: pose_ik
input: left_sense
followers: [left, left_gripper]
arm: left                # IKで動かす腕（運動学のmodelを持つfollower）
gripper: left_gripper    # 任意．挟みの角度で動かす1関節のfollower
tool_offset: {xyz: [0.0, 0.0, 0.19], rpy: [0.0, -1.5708, 0.0]}  # 任意．flange（link6）から見た道具の座標
workspace: {min: [0.05, -0.45, 0.05], max: [0.6, 0.45, 0.6]}    # 任意．m．腕の基準座標（base_link）
max_input_jump: {position_m: 0.05, rotation_rad: 0.5}             # 必須
ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005, rotation_tolerance_rad: 0.05}  # 任意．この値が既定
gripper_map: {scale: 1.0, offset: 0.0}                            # 任意．この値が既定
max_speed: {left: 1.0, left_gripper: 3.0}                         # 必須．followerごとに1つ
home: {left: {pose: ../poses/left/ready.yaml, max_speed: 0.5, tolerance: 0.02}}  # 任意
command_deadline_ms: 100 # 必須
input_timeout_ms: 150    # 必須
```

`pika_sense`：

| key | 意味 |
| --- | --- |
| `port` | 必須．Senseのserial port．`SET_` のままでは拒否します |
| `tracker.system` | 必須．このSenseのtrackerを読む，`trackers:` の下のtracking systemのnode |
| `tracker.serial` | 必須．trackerのserial番号（`LHR-...`．「実機で最初にすること」で調べます）．`WM0` のような名前はlibsurviveが見つけた順で付き，入れ替わりうるので使いません．`SET_` のままでは拒否します．以前のkey `tracker.name` と `tracker.args` は，これらを案内して拒否します |
| `stale_ms` | 既定100．これより古い姿勢やserialのfeedbackは，失ったと見なします |
| `poll_hz` | 任意．入力を読む周期．書かなければ，controllerが動かすfollowerの `control_hz` のうち最も速いもので読みます．followerのない構成では必須です（[Pika Senseを手に持った収集](../tutorials/pika-handheld.md)） |

`libsurvive`（`trackers:` の下のnode）：1つのlibsurviveのcontextがUSBの受信機を一度だけ開いて全部のSenseに配ります．両方のtrackerの姿勢は，校正済みの同じworld座標で来ます．libsurviveは受信機を占有するので，別のprocessで開いた2つ目のcontextにはtrackerが見えません．1つのthreadがserial番号ごとに姿勢を持ちます．libsurviveが全部0の回転（追跡を失った）を返したら，次の正しい姿勢まで，そのtrackerを喪失として扱います（`tracking` が0になり，Senseの係合が解けます）．このnodeは記録しません．statusには，見えているserial，追跡を失った回数，libsurviveが止まったときのerrorが出ます．

| key | 意味 |
| --- | --- |
| `args` | 任意．libsurviveに渡す文字列のリスト |
| `poll_hz` | 任意．姿勢を公開する周期．書かなければ，それを読むSenseのうち最も速いものに合わせます |

`pose_ik`：

| key | 意味 |
| --- | --- |
| `arm`，`gripper` | `arm` は必須で，運動学のmodelを持つfollower（PiPER）．`gripper` は任意で，1関節のfollower．2つで，controllerの `followers` をちょうど指します |
| `tool_offset` | 任意．flangeから道具の先端への変換（`xyz` はm，`rpy` はrad）．省略するとflangeが道具になります．上の値はAgileXが自社のgripperに使う値です．Pika Gripperを付けたときの値は，計測して書きます（[設定を絞る](../tutorials/piper-pika/tighten.md)） |
| `workspace` | 任意．`min` と `max`（m．どの軸も `min` が `max` より小さい）．目標の位置がこの箱の外なら指令を送りません．省略すると，関節の範囲とIKだけが目標を制限し，`validate` が `note:` を，画面が `workspace: none` を出します（初回の遠隔操作向け） |
| `max_input_jump` | 必須．`position_m` と `rotation_rad`．Senseの姿勢が1回でこれより大きく跳んだら，遠隔操作を止めます |
| `ik` | 任意．反復の回数（既定30），減衰（既定0.001），届いたと見なす位置（既定0.005 m）と回転（既定0.05 rad）の許容．知らないkeyは拒否します．届かなければ指令を送りません |
| `gripper_map` | 任意．gripperの角度 = `scale`·挟みの角度 + `offset`（既定は1.0と0.0）．gripperの範囲に収めます |
| `max_speed` | 必須．followerごとに1つ．速さの上限（単位/s）．指令を送らなかった間の時間は持ち越さず，1回の指令で動くのは `input_timeout_ms` の分までです |
| `home` | 任意．「Move home」で移る保存した姿勢．followerごとに書けます．各項目に `pose`，`max_speed`（そのfollowerの `max_speed` 以下），`tolerance` が要ります．`timeout_s` は既定30です |
| `command_deadline_ms` | 必須．指令が有効な時間．これより古い指令はfollowerが拒否し，保持します |
| `input_timeout_ms` | 必須．入力の届く間隔がこれを超えて空くと，遠隔操作を止めます（下の「開始と停止」） |

記録には，Senseごとに `observation.<名前>`（`x, y, z, qx, qy, qz, qw, gripper, tracking, engaged`，trackerの世界座標）が加わります．`action` は，これまでどおりfollowerの関節の指令です．

## 写し方

AgileXの遠隔操作と同じ，相対の写し方です．

- Senseで開始した瞬間の，Senseの姿勢 T_s0 と，腕の道具の姿勢 T_a0（腕が保持している目標からの順運動学）を覚えます．
- その後は `T_a0 · inv(T_s0) · T_s` を道具の目標にします．手の動きを，Sense自身の座標で道具の座標に写します．
- trackerの世界座標と腕の基準座標の校正は要りません．

## 開始と停止

- Senseの `Command` が変わるたびに，開始と停止が切り替わります（AgileXではdouble-click）．
- 次のときは遠隔操作を止め，Senseで停止して開始し直すまで動かしません．
  - 姿勢を失った・古くなった（基地局が見えない），serialが途絶えた
  - 姿勢が `max_input_jump` を超えて跳んだ
  - followerが `FAULT` か `ESTOP` になった，入力が古くなった（届く間隔が `input_timeout_ms` を超えて空いたときも含む）
  - followerが「Move home」で移動している
- 目標が `workspace` の外のときと，IKが届かないときは，指令を送らず，腕は保持します．開始したままなので，目標が戻れば続きます．
- 電源を入れたときのPiPERの姿勢（全関節0，折りたたんだ姿勢）は特異点で，IKがほとんど解けません．開始の前に「Move home」で `home` の姿勢へ移ります．

## 模擬で確かめる

`.roboloom/piper-mock/` は，模擬のSense 2台で，模擬のPiPER 2台とPika Gripper 2台を動かす構成です．模擬のSenseは，開いてから2 s後に開始し，その後は10 s開始・2 s停止を繰り返します．

`.roboloom/piper-mock/` はroboloomのrepositoryにあり，installしたpackageには入っていません（実機用のtemplateは `roboloom init piper-pika`．[PiPER＋Pikaの道筋](../tutorials/piper-pika/index.md)）．下のcommandは，cloneしたrepositoryのrootで実行します．自分のprojectでは，[repository](https://github.com/tetsugo02/roboloom) からこのdirectoryを自分の `.roboloom/` にコピーすれば，同じように動かせます．模擬の構成（`mode: mock`）なので，port，CAN interface，trackerの名前，`limits`，`tool_offset`，`workspace` の値を実機に使い回さないでください．

```bash
uv run roboloom run piper-mock                     # Launchのあと，Move home
uv run roboloom run piper-mock --with policy       # Senseの代わりに確認用の方策
```

記録したdataで学習した方策を動かす手順は [方策で動かす](../policy/index.md) にあります．robotを使わずSenseを手に持って集める方法は [Pika Senseを手に持った収集](../tutorials/pika-handheld.md) にあります．

## 実機で最初にすること

1. 上記の `pika` extraを導入し，trackerのudev規則は管理者に頼みます．
2. 基地局を置き，libsurviveで校正します．Pythonのpackageには `survive-cli` が含まれないので，Pythonから `--force-calibrate` を渡して開きます．trackerを基地局から見える所に置いて動かさず，姿勢が出始めたらCtrl-Cで止めます．各行に，`tracker.serial` に書くtrackerのserial番号（`LHR-...`）と，今の名前が出ます．この手順は実機では未検証です．

    ```bash
    uv run python - <<'EOF'
    import time
    import pysurvive

    ctx = pysurvive.SimpleContext(["calibrate", "--force-calibrate"])
    try:
        while ctx.Running():
            updated = ctx.NextUpdated()
            if updated:
                serial = pysurvive.simple_serial_number(updated.ptr) or b""
                print(serial.decode(), updated.Name().decode(), updated.Pose()[0].Pos[:])
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    EOF
    ```

3. Senseのserialを，読むだけで確かめます．版を尋ねる `GET_INFO` だけを送ります．

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika_sense
    ```

    版，挟みの角度，`Command`，feedbackの周期を表示します．

4. 初回は `tool_offset` と `workspace` なしで，遅い速度で試します（[初めての遠隔操作](../tutorials/piper-pika/first-teleop.md)）．動いたら `tool_offset` を計測し，`workspace` を机と周りに合わせて書き足します．

## 実機で確かめること

- trackerのserial番号，姿勢の周期と遅れ．
- 1つの `lighthouse` のnodeに両方のtrackerが見え，それぞれのSenseが自分のtrackerに従うか．
- 受信機を抜いたときやSenseの電源を切ったときに戻るか．forkには，上流で未mergeの修正（抜いたときのcrash：[#383](https://github.com/collabora/libsurvive/pull/383)，issue #372．timeoutやSTALLのUSB転送：[#378](https://github.com/collabora/libsurvive/pull/378)）を入れています．試験は偽のlibusbに対してだけです．
- `Command` の変わり方（double-clickで0と1が入れ替わるか）．
- 挟みの角度の向きと範囲，Pika Gripperの角度との対応（`gripper_map`）．
- SDKのtrackerからSenseの中心への変換（`inputs/pika_sense/spec.py`）が，手元の機器で正しいか．
- `tool_offset`（Pika Gripperの取り付け）．
- PiPERのfirmwareの版．URDFはS-V1.6-3以降のDHに合わせています．
