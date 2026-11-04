# Pika Gripperフォロワ（開発中・実機未検証）

!!! warning "開発中"
    AgileX Pika Gripperをフォロワとして動かすドライバの開発中の記録です．模擬のバスと，偽のシリアルを使った試験だけで確かめています．実機では動かしていません．通信の仕様は，AgileXのpika_sdkとpika_rosのソースから読み取ったものです．

## 必要なもの

- 追加のパッケージは要りません．シリアルはpyserial（roboloomの依存）で直接扱います．AgileXのSDK（`agx-pypika`）は使いません．カメラやGUIのパッケージまで要求するためです．
- グリッパごとにUSBシリアル1本と，24 Vの電源．PiPERのCANとは別の機器なので，PiPERとは別のフォロワとして設定します．
- ポートは，USBの差し込み口で決まる `/dev/serial/by-path/...` を使います．`/dev/ttyUSB0` のような番号は，抜き差しや起動の順で左右が入れ替わることがあります．by-pathはsudoなしで使えます（差し込み口を変えるとパスも変わります）．
- グリッパのカメラ（魚眼とD405）は，別のセンサとして設定します（[Pikaの手首カメラ](pika-cameras.md)）．

## 設定

```yaml
type: pika_gripper_follower
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0
control_hz: 100
current_limit_A: 1.0     # 必須．有効化の前に送るモーターの電流の上限（0より大きく2以下）
stale_ms: 100            # 任意．これより古いフィードバックはFAULT
torque: true
record_effort: true      # observation.effort にモーターの相電流（mA）を記録する
health:
  every_ticks: 10        # 必須．過電流・過熱・ドライバの異常はここでしか分からない
  max_temperature_c: 70
limits:                  # rad（モーターの角度）．0〜1.67の内側に
  - {name: gripper, min: 0.0, max: 1.6, max_speed: 3.0, max_jump: 0.5}
```

| キー | 意味 |
| --- | --- |
| `port` | シリアルポート．`SET_` のままでは拒否します |
| `current_limit_A` | 必須．モーターの電流の上限（A）．pika_sdkの説明の範囲（0〜2 A）を超える値は拒否します |
| `stale_ms` | 既定100．フィードバックがこれより古いとバスの異常としてFAULTにします．フレームに時刻がないので，受け取った時刻で判断します |
| `health` | 必須．`every_ticks` ごとに状態を読みます |
| `limits` | rad．グリッパの範囲（0〜1.67 rad）を超える値は拒否します |
| `unattended` | 任意．放置したときの実測値（下の「安全に関わる性質」） |

`record_effort` はPiPERの `record_effort` と同じ構成では使えません．`observation.effort` は1つのベクトルなので，N·m（PiPER）とmA（グリッパ）を混ぜられず，設定の読み込みで拒否します．どちらか一方だけで記録します．

関節は `gripper` の1つです．値はモーターの角度（rad）で，0が閉じた状態です．開き幅（mm）は使いません．pika_sdkのリンク機構の式で換算した値で，実機では確かめていないためです（1.67 radは式の上でおよそ97 mm）．`control:`（制御則のグループ）は使えません．位置制御はグリッパのドライバが行います．

## 振る舞い

- 開くときは，`motor` と `motorstatus` のフィードバックが，開いた後に届くまで最大2 s待ちます．
- 指令はモーターの角度（rad）で送ります．範囲と速さはFollowerSafetyが見ます．
- 有効化では，まず電流の上限を送り，状態が有効と報告するまで（最大2 s）有効化を繰り返します．
- 次のどれかでFAULTにします．
  - フィードバックが `stale_ms` より古い（電源やUSBが切れた）
  - 状態のビットの異常（電圧低下，モーターの過熱，過電流，ドライバの過熱，センサの異常，ドライバの異常）
  - 有効化した後に無効になった
- `release` はモーターを無効にします．持っている物を離します．
- dataflowの終了（ポートを閉じる）ではモーターを無効にしません．

## 安全に関わる性質

| 性質 | 値 |
| --- | --- |
| `torque_off` | `lets_go`（モーターを無効にすると物を離す，と見なす．ブレーキがないため） |
| `unattended` | `unknown`（指令が来なくなったときに保持するかは，確かめていない） |

`unknown` のため，終了の確認に「保持したまま終了」は出ません．`release` の確認では「物を外す」と表示します．値の意味は [設定](../reference/configuration.md) の「脱力したときと放置したときの性質」にあります．

## 模擬で画面を確かめる

`.roboloom/piper-mock/` は，模擬のPiPER 2台（`left`，`right`）とPika Gripper 2台（`left_gripper`，`right_gripper`）とカメラの構成です．ハードウェアなしで操作画面を確かめられます．腕とグリッパは，模擬のPika Senseで遠隔操作します（[Pika SenseとIKによる遠隔操作](pika-sense.md)）．Launchのあと「Move home」で腕を始める姿勢へ移すと，模擬のSenseが開始して腕が動きます．`--with policy` を付けると，同じディレクトリの確認用の方策（`demo_policy.py`）が動かします．

```bash
uv run roboloom run piper-mock
uv run roboloom run piper-mock --with policy
```

## 実機で最初にすること

1. グリッパをUSBと電源につなぎ，ポートのパスを確かめます．

    ```bash
    ls -l /dev/serial/by-path/
    ```

2. 読むだけで状態を確かめます．有効化も移動もしません（版を尋ねる `GET_INFO` だけを送ります）．

    ```bash
    uv run roboloom probe /dev/serial/by-path/... --device pika
    ```

    版，角度・速さ・電流，状態のビット（有効，原点済み），電圧，温度，フィードバックの周期，異常を表示します．

3. 放置したときに保持するかを測ります．手を離し，指の間に何も挟まない状態で実行します．手順はPiPERと同じです（[PiPERフォロワ](piper.md) の「実機で最初にすること」）．

    ```bash
    uv run roboloom check-hold left_gripper --tolerance 0.02
    ```

## 実機で確かめること

- 角度の0が閉じた状態か．違えば，pika_sdkの `set_zero()`（指令12）で零点を合わせる手順が要ります（roboloomにはまだありません）．
- フィードバックの周期．`stale_ms` と `control_hz` の目安を決めます．
- 指令15が電流の上限か．pika_sdkでは `set_motor_torque`（電流），pika_rosでは起動時の電流の上限として送っています．
- 無効にしたとき，持っている物を離すか（`torque_off`）．
- 有効化したまま指令が来なくなったとき，最後の目標を保つか（`check-hold`）．
- 相電流（`currents_mA`）の符号と大きさ．物をつかんだときの値を見ます．
