# PiPERフォロワ（開発中・実機未検証）

!!! warning "開発中"
    AgileX PiPERをフォロワとして動かすドライバの開発中の記録です．模擬のバスと，piper_sdkを模した試験だけで確かめています．実機では動かしていません．機体のテンプレート（`roboloom init`）とQuick startはまだありません．

## 必要なもの

- piper_sdk（`uv add git+https://github.com/tetsugo02/roboloom.git --extra piper`）．安定版の0.6系のV2インターフェースを使います．使うのは関節の位置制御（MOVE J）・状態・有効化だけで，これらはV3のファームウェアでも同じ形です．
- 腕ごとに1つのCANインターフェース（1 Mbps）．名前は `can_left`，`can_right` のように腕で決めます．インターフェースの作成と，USBポートによる名前付けにはsudoが要るので，管理者に頼みます．

## 設定

```yaml
type: piper_follower
can: can_left            # この腕のCANインターフェース
control_hz: 100
speed_percent: 30        # ファームウェアの関節速度の割合（1〜100）
stale_ms: 50             # 任意．これより古いフィードバックはFAULT
torque: true
record_effort: true      # observation.effort に関節トルク（N·m）を記録する
health:
  every_ticks: 10        # 必須．教示ボタン・衝突・ドライバの異常はここでしか分からない
  max_temperature_c: 70
limits:                  # rad．各関節はPiPERの範囲の内側に
  - {name: joint1, min: -2.6, max: 2.6, max_speed: 1.0, max_jump: 0.3}
  # ... joint2〜joint6
```

| キー | 意味 |
| --- | --- |
| `can` | CANインターフェースの名前．`SET_` のままでは拒否します |
| `speed_percent` | 必須．1〜100の整数．ファームウェアがMOVE Jで目標へ向かう速さの割合 |
| `stale_ms` | 既定50．フィードバックがこれより古いとバスの異常としてFAULTにします（ケーブルが抜けても，SDKは最後の値を返し続けるため） |
| `health` | 必須．`every_ticks` ごとに状態を読みます |
| `limits` | rad．PiPERの関節の範囲（joint1 ±150°，joint2 0〜180°，joint3 −170〜0°，joint4 ±100°，joint5 ±70°，joint6 ±120°）を超える値は拒否します |
| `unattended` | 任意．放置したときの実測値（下の「安全に関わる性質」） |

`control:`（制御則のグループ）は使えません．PiPERは位置制御を自分のコントローラで行います．単位は `rad` に決まっています．

## 振る舞い

- 開くときは，関節・モーター・ドライバ・状態のフィードバックが，開いた後に届くまで最大2 s待ちます．最初のフレームが届く前のSDKの値はゼロなので，待たずに保持目標を決めると0 radへ跳びます．
- 指令のたびに，CAN制御・MOVE J・`speed_percent` を送ってから関節の目標を送ります．
- 有効化は，6関節すべてが有効と報告するまで（最大5 s）繰り返します．目標は有効化の前に今の姿勢で書きます．
- 次のどれかでFAULTにします．
  - 制御モードがCANでない（教示ボタンなど）
  - 腕の状態が正常でない（急停，衝突，関節の通信異常，過熱など）
  - 関節の通信異常
  - ドライバの異常（電圧低下，過熱，過電流，衝突保護，ストール）
  - 有効化した後に無効になった関節
- `release` はモーターを無効にします．腕は落ちます．
- dataflowの終了（バスを閉じる）ではモーターを無効にしません．

## 安全に関わる性質

| 性質 | 値 |
| --- | --- |
| `torque_off` | `falls`（モーターを無効にすると落ちる） |
| `unattended` | `unknown`（指令が来なくなったときに保持するかは，確かめていない） |

`unknown` のため，終了の確認に「保持したまま終了」は出ません．終了の確認では，支えてから脱力して終了するか，脱力せずに終了する（腕は落ちるかもしれない）かを選びます．値の意味は [設定](../reference/configuration.md) の「脱力したときと放置したときの性質」にあります．

## 模擬で画面を確かめる

`.roboloom/piper-mock/` は，模擬のPiPER 2台（`left`，`right`）とPika Gripper 2台（`left_gripper`，`right_gripper`）とカメラの構成です．ハードウェアなしで操作画面を確かめられます．腕とグリッパは，模擬のPika Senseで遠隔操作します（[Pika SenseとIKによる遠隔操作](pika-sense.md)）．Launchのあと「Move home」で腕を始める姿勢へ移すと，模擬のSenseが開始して腕が動きます．`--with demo_policy` を付けると，同じディレクトリの確認用の方策（`demo_policy.py`）が動かします．

```bash
uv run roboloom run piper-mock
uv run roboloom run piper-mock --with demo_policy
```

## 実機で最初にすること

1. 管理者にCANインターフェース（1 Mbps，腕ごとの名前）を作ってもらいます．
2. 腕を電源につないだまま，読むだけで状態を確かめます．有効化も移動もしません．

    ```bash
    uv run roboloom probe can_left
    ```

    ファームウェア，関節角（rad と度），制御モード，有効化，温度，異常，フィードバックの周期を表示します．

3. 放置したときに保持するかを測ります．腕を支えられる状態で，周りを空けてから実行します．今の姿勢で2 s保持してから，有効化したまま指令を書くのをやめ，最大 `--seconds` のあいだ関節角を読むだけにします（保持して終了したとき，ESTOP，FAULTと同じ状態です）．同じプロセスでCANを閉じて開き直すことはpiper_sdkでは確実でないため，バスは開いたままにします．PiPERのドライバは閉じるときにモーターを無効にしないので，閉じた後も同じ状態です．短い `--seconds` では，ゆっくり下がる腕を見逃します．変化が `--tolerance`（rad）を超えるか，モーターが無効になれば `torque_off`，そうでなければ `holds` です．`record` と入力すると，フォロワのYAMLに `unattended:` を書きます．最後に，`release` で脱力するか，そのままにするかを選びます．

    ```bash
    uv run roboloom check-hold left --tolerance 0.02
    ```

## 実機で確かめること

- 関節角の符号と零点が，SDKの説明と合うか．
- 有効化したまま指令が来なくなったとき，腕が保持するか（`check-hold`）．
- モーターを無効にしている間に送った `JointCtrl` を，有効化したときにファームウェアが目標として使うか．使う場合は，有効化の直前に書く今の姿勢がその目標になります．
- 有効化が途中で止まった（一部の関節だけ有効になった）ときの振る舞い．今は5 sで諦めてエラーにし，有効になった関節はそのままです．
- 1つのメッセージのうち1つのCANフレーム（例えば関節3〜4）だけが途絶えた場合は検出できません（SDKはメッセージごとに1つの受信時刻しか持たないため）．
- 1 MbpsのCANで，毎回の指令の前に制御モードを送る形で，何Hzまで回るか．`control_hz` の目安を決めます．
- 関節トルク（`efforts_Nm`）の符号と大きさ．
