# Pika Gripper follower

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> AgileX Pika Gripperをfollowerとして動かすdriverの開発中の記録です．模擬のbusと，偽のserialを使った試験だけで確かめています．実機では動かしていません．通信の仕様は，AgileXのpika_sdkとpika_rosのsourceから読み取ったものです．

## Pikaの機器 { #pika-devices }

| 機器 | 役割 | ページ | 状態 |
| --- | --- | --- | --- |
| Pika Gripper | follower（このページ）．PiPERの先に付ける | — | <span class="status status--dev">開発中</span> |
| Pika Sense | 手に持つ入力．Vive trackerの姿勢と挟みの角度 | [Pika SenseとIK](../../controllers/pose-ik.md) | <span class="status status--dev">開発中</span> |
| 手首camera | GripperとSenseの魚眼cameraとD405 | [Pikaの手首camera](../../sensors/pika-cameras.md) | <span class="status status--dev">開発中</span> |

PiPERと組にした構成は [PiPERのcontroller](../piper/controllers.md)，Senseを手に持って集める構成は [Pika Senseを手に持った収集](../../tutorials/pika-handheld.md) にあります．

## 必要なもの

- 追加のpackageは要りません．serialはpyserial（roboloomの依存）で直接扱います．AgileXのSDK（`agx-pypika`）は使いません．cameraやGUIのpackageまで要求するためです．
- Senseのtrackerと手首の魚眼cameraを含むPika一式は，[Installation](../../get-started/installation.md) の `pika` extraで追加します．Gripperのserial制御だけならpysurviveとそのGUI依存は使いません．
- gripperごとにUSB serial 1本と，24 Vの電源．PiPERのCANとは別の機器なので，PiPERとは別のfollowerとして設定します．
- portは，USBの差し込み口で決まる `/dev/serial/by-path/...` を使います．`/dev/ttyUSB0` のような番号は，抜き差しや起動の順で左右が入れ替わることがあります．by-pathはsudoなしで使えます（差し込み口を変えるとpathも変わります）．
- gripperのcamera（魚眼とD405）は，別のsensorとして設定します（[Pikaの手首camera](../../sensors/pika-cameras.md)）．

## 設定

```yaml
type: pika_gripper_follower
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0
control_hz: 100
current_limit_A: 1.0     # 必須．有効化の前に送るmotorの電流の上限（0より大きく2以下）
stale_ms: 100            # 任意．これより古いfeedbackはFAULT
torque: true
record_effort: true      # observation.effort にmotorの相電流（mA）を記録する
health:                  # 必須．過電流・過熱・driverの異常はここでしか分からない
  every_ticks: 10        # 任意．既定10
  max_temperature_c: 70
limits:                  # rad（motorの角度）．0〜1.67の内側に
  - {name: gripper, min: 0.0, max: 1.6, max_speed: 3.0, max_jump: 0.5}
```

| key | 意味 |
| --- | --- |
| `port` | serial port．`SET_` のままでは拒否します |
| `current_limit_A` | 必須．motorの電流の上限（A）．pika_sdkの説明の範囲（0〜2 A）を超える値は拒否します |
| `stale_ms` | 既定100．feedbackがこれより古いとbusの異常としてFAULTにします．frameに時刻がないので，受け取った時刻で判断します |
| `health` | 必須（`health: {}` だけでもよい）．制御の `every_ticks` 周期（既定10）ごとに状態を読みます |
| `limits` | rad．gripperの範囲（0〜1.67 rad）を超える値は拒否します |
| `unattended` | 任意．放置したときの実測値（下の「安全に関わる性質」） |

`record_effort` はPiPERの `record_effort` と同じ構成では使えません．`observation.effort` は1つのvectorなので，N·m（PiPER）とmA（gripper）を混ぜられず，設定の読み込みで拒否します．どちらか一方だけで記録します．

関節は `gripper` の1つです．値はmotorの角度（rad）で，0が閉じた状態です．開き幅（mm）は使いません．pika_sdkのlink機構の式で換算した値で，実機では確かめていないためです（1.67 radは式の上でおよそ97 mm）．`control:`（制御則のgroup）は使えません．位置制御はgripperのdriverが行います．

## 振る舞い

- 開くときは，`motor` と `motorstatus` のfeedbackが，開いた後に届くまで最大2 s待ちます．
- 指令はmotorの角度（rad）で送ります．範囲と速さはFollowerSafetyが見ます．
- 有効化では，まず電流の上限を送り，状態が有効と報告するまで（最大2 s）有効化を繰り返します．
- 次のどれかでFAULTにします．
  - feedbackが `stale_ms` より古い（電源やUSBが切れた）
  - 状態のbitの異常（電圧低下，motorの過熱，過電流，driverの過熱，sensorの異常，driverの異常）
  - 有効化した後に無効になった
- `release` はmotorを無効にします．持っている物を離します．
- dataflowの終了（portを閉じる）ではmotorを無効にしません．

## 安全に関わる性質

| 性質 | 値 |
| --- | --- |
| `torque_off` | `lets_go`（motorを無効にすると物を離す，と見なす．brakeがないため） |
| `unattended` | `unknown`（指令が来なくなったときに保持するかは，確かめていない） |

`unknown` のため，終了の確認に「保持したまま終了」は出ません．`release` の確認では「物を外す」と表示します．値の意味は [設定](../../reference/configuration/index.md) の「脱力したときと放置したときの性質」にあります．

## 模擬で画面を確かめる

`.roboloom/piper-mock/` は，模擬のPiPER 2台（`left`，`right`）とPika Gripper 2台（`left_gripper`，`right_gripper`）とcameraの構成です．hardwareなしで操作画面を確かめられます．腕とgripperは，模擬のPika Senseで遠隔操作します（[Pika SenseとIKによる遠隔操作](../../controllers/pose-ik.md)）．Launchのあと「Move home」で腕を始める姿勢へ移すと，模擬のSenseが開始して腕が動きます．`--with policy` を付けると，同じdirectoryの確認用の方策（`demo_policy.py`）が動かします．

`.roboloom/piper-mock/` はroboloomのrepositoryにあり，installしたpackageには入っていません（`roboloom init` のtemplateは `rakuda2` だけです）．下のcommandは，cloneしたrepositoryのrootで実行します．自分のprojectでは，[repository](https://github.com/tetsugo02/roboloom) からこのdirectoryを自分の `.roboloom/` にコピーして使えます．`ik` extraが要ります（[Pika SenseとIKによる遠隔操作](../../controllers/pose-ik.md)）．値は模擬のためのものなので，実機に使い回さないでください．

```bash
uv run roboloom run piper-mock
uv run roboloom run piper-mock --with policy
```

## 実機で最初にすること

1. gripperをUSBと電源につなぎ，portのpathを確かめます．

    ```bash
    ls -l /dev/serial/by-path/
    ```

2. 読むだけで状態を確かめます．有効化も移動もしません（版を尋ねる `GET_INFO` だけを送ります）．

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika
    ```

    版，角度・速さ・電流，状態のbit（有効，原点済み），電圧，温度，feedbackの周期，異常を表示します．

3. 放置したときに保持するかを測ります．手を離し，指の間に何も挟まない状態で実行します．手順はPiPERと同じです（[PiPER follower](../piper/index.md) の「実機で最初にすること」）．

    ```bash
    uv run roboloom check-hold left_gripper --tolerance 0.02
    ```

## 実機で確かめること

- 角度の0が閉じた状態か．違えば，pika_sdkの `set_zero()`（指令12）で零点を合わせる手順が要ります（roboloomにはまだありません）．
- feedbackの周期．`stale_ms` と `control_hz` の目安を決めます．
- 指令15が電流の上限か．pika_sdkでは `set_motor_torque`（電流），pika_rosでは起動時の電流の上限として送っています．
- 無効にしたとき，持っている物を離すか（`torque_off`）．
- 有効化したまま指令が来なくなったとき，最後の目標を保つか（`check-hold`）．
- 相電流（`currents_mA`）の符号と大きさ．物をつかんだときの値を見ます．
