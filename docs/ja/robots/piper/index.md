# PiPER follower

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> AgileX PiPERをfollowerとして動かすdriverの開発中の記録です．模擬のbusと，piper_sdkを模した試験だけで確かめています．実機では動かしていません．PiPER 2台とPika 2組のtemplateは `roboloom init piper-pika` で作れます（[PiPER＋Pikaの道筋](../../tutorials/piper-pika/index.md)）．

使えるcontroller（Pika SenseとIK，方策）は [PiPERのcontroller](controllers.md)，模擬で一周する手順は [PiPER＋Pikaを模擬で](../../tutorials/piper-pika/mock.md) にあります．

## 必要なもの

- piper_sdk（`uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.1.0 --extra piper`）．安定版の0.6系のV2 interfaceを使います．使うのは関節の位置制御（MOVE J）・状態・有効化だけで，これらはV3のfirmwareでも同じ形です．
- 腕ごとに1つのCAN interface（1 Mbps）．有効にするにはsudoが要るので，管理者に頼みます．名前は `can0`，`can1` のままでかまいません．設定にはUSB-CAN adapterのserial番号を書き（`can: {serial: ...}`），開くときに今のinterfaceの名前を探します．

## 設定

```yaml
type: piper_follower
can: {serial: "0029002F5746570A20383839"}  # USB-CAN adapterのserial（roboloom setup が書く）．can0 のような名前も可
control_hz: 100
speed_percent: 30        # firmwareの関節速度の割合（1〜100）
stale_ms: 50             # 任意．これより古いfeedbackはFAULT
torque: true
record_effort: true      # observation.effort に関節torque（N·m）を記録する
health:                  # 必須．教示ボタン・衝突・driverの異常はここでしか分からない
  every_ticks: 10        # 任意．既定10
  max_temperature_c: 70
limits:                  # rad．各関節はPiPERの範囲の内側に
  - {name: joint1, min: -2.6, max: 2.6, max_speed: 1.0, max_jump: 0.3}
  # ... joint2〜joint6
```

| key | 意味 |
| --- | --- |
| `can` | CAN interfaceの名前．`SET_` のままでは拒否します |
| `speed_percent` | 必須．1〜100の整数．firmwareがMOVE Jで目標へ向かう速さの割合 |
| `stale_ms` | 既定50．feedbackがこれより古いとbusの異常としてFAULTにします（cableが抜けても，SDKは最後の値を返し続けるため） |
| `health` | 必須（`health: {}` だけでもよい）．制御の `every_ticks` 周期（既定10）ごとに状態を読みます |
| `limits` | rad．PiPERの関節の範囲（joint1 ±150°，joint2 0〜180°，joint3 −170〜0°，joint4 ±100°，joint5 ±70°，joint6 ±120°）を超える値は拒否します |
| `unattended` | 任意．放置したときの実測値（下の「安全に関わる性質」） |

`control:`（制御則のgroup）は使えません．PiPERは位置制御を自分のcontrollerで行います．単位は `rad` に決まっています．

## 振る舞い

- 開くときは，関節・motor・driver・状態のfeedbackが，開いた後に届くまで最大2 s待ちます．最初のframeが届く前のSDKの値はゼロなので，待たずに保持目標を決めると0 radへ跳びます．
- 指令のたびに，CAN制御・MOVE J・`speed_percent` を送ってから関節の目標を送ります．
- 有効化は，6関節すべてが有効と報告するまで（最大5 s）繰り返します．目標は有効化の前に今の姿勢で書きます．
- 次のどれかでFAULTにします．
  - 制御modeがCANでない（教示ボタンなど）
  - 腕の状態が正常でない（急停，衝突，関節の通信異常，過熱など）
  - 関節の通信異常
  - driverの異常（電圧低下，過熱，過電流，衝突保護，stall）
  - 有効化した後に無効になった関節
- `release` はmotorを無効にします．腕は落ちます．
- dataflowの終了（busを閉じる）ではmotorを無効にしません．

## 安全に関わる性質

| 性質 | 値 |
| --- | --- |
| `torque_off` | `falls`（motorを無効にすると落ちる） |
| `unattended` | `unknown`（指令が来なくなったときに保持するかは，確かめていない） |

`unknown` のため，終了の確認に「保持したまま終了」は出ません．終了の確認では，支えてから脱力して終了するか，脱力せずに終了する（腕は落ちるかもしれない）かを選びます．値の意味は [設定](../../reference/configuration/index.md) の「脱力したときと放置したときの性質」にあります．

## 観測と行動（`.roboloom/piper-mock/`） { #observation-and-action }

PiPER 2台とPika Gripper 2台の構成で，記録するdatasetと方策の入出力は同じ並びと単位です．並びは `followers:` に書いた順です．

| 名前 | 要素 | 単位 |
| --- | --- | --- |
| `observation.state`，`action` | 14（`left.joint1` … `left.joint6`，`right.joint1` … `right.joint6`，`left_gripper.gripper`，`right_gripper.gripper`） | rad（gripperはmotorの角度） |
| `observation.effort` | 12（腕の2台だけ） | N·m |
| `observation.images.camera`，`observation.images.left_wrist`，`observation.images.right_wrist` | 模擬では48×64×3（RGB） | — |
| `observation.left_sense`，`observation.right_sense` | 10（遠隔操作のときだけ．[Pika Sense](../../controllers/pose-ik.md)） | m，四元数，rad |

- gripperの電流（mA）は，腕のN·mと1つの `observation.effort` にまとめられないので，記録しません．
- 方策（option `policy`）は，`camera` と手首のcamera 2台を観測し，`infer` は14要素の目標をradで返します．1手 `[14]` か，まとめた行動 `[H, 14]` です．`max_speed` はfollowerごとのrad/sです．
- 推論の構成にはSenseがないので，方策は `observation.left_sense` などを使えません．方策の書き方とLeRobotの方策は [方策で動かす](../../policy/index.md) にあります．

## 模擬で画面を確かめる

`.roboloom/piper-mock/` は，模擬のPiPER 2台（`left`，`right`）とPika Gripper 2台（`left_gripper`，`right_gripper`）とcameraの構成です．hardwareなしで操作画面を確かめられます．腕とgripperは，模擬のPika Senseで遠隔操作します（[Pika SenseとIKによる遠隔操作](../../controllers/pose-ik.md)）．Launchのあと「Move home」で腕を始める姿勢へ移すと，模擬のSenseが開始して腕が動きます．`--with policy` を付けると，同じdirectoryの確認用の方策（`demo_policy.py`）が動かします．

`.roboloom/piper-mock/` はroboloomのrepositoryにあり，installしたpackageには入っていません（`roboloom init` のtemplateは `rakuda2` だけです）．下のcommandは，cloneしたrepositoryのrootで実行します．自分のprojectでは，[repository](https://github.com/tetsugo02/roboloom) からこのdirectoryを自分の `.roboloom/` にコピーして使えます．`ik` extraが要ります（[Pika SenseとIKによる遠隔操作](../../controllers/pose-ik.md)）．値は模擬のためのものなので，実機に使い回さないでください．

```bash
uv run roboloom run piper-mock
uv run roboloom run piper-mock --with policy
```

## 実機で最初にすること

手順は [PiPER＋Pika：機体設定](../../tutorials/piper-pika/setup.md) と [初めての遠隔操作](../../tutorials/piper-pika/first-teleop.md) にあります．ここでは腕に関わる部分だけを説明します．

1. 管理者にCAN interfaceを1 Mbpsで有効にしてもらいます．`roboloom setup` の `can` の段階が，状態と，実行するcommandを表示します．どのCANがどの腕かは，`arms` の段階で腕のjoint1を手で回して特定します．
2. 腕を電源につないだまま，読むだけで状態を確かめます．有効化も移動もしません．

    ```bash
    uv run roboloom probe can0
    ```

    firmware，関節角（rad と度），制御mode，有効化，温度，異常，feedbackの周期を表示します．

3. 放置したときに保持するかを測ります．腕を支えられる状態で，周りを空けてから実行します．今の姿勢で2 s保持してから，有効化したまま指令を書くのをやめ，最大 `--seconds` のあいだ関節角を読むだけにします（保持して終了したとき，ESTOP，FAULTと同じ状態です）．同じprocessでCANを閉じて開き直すことはpiper_sdkでは確実でないため，busは開いたままにします．PiPERのdriverは閉じるときにmotorを無効にしないので，閉じた後も同じ状態です．短い `--seconds` では，ゆっくり下がる腕を見逃します．変化が `--tolerance`（rad）を超えるか，motorが無効になれば `torque_off`，そうでなければ `holds` です．`record` と入力すると，followerのYAMLに `unattended:` を書きます．最後に，`release` で脱力するか，そのままにするかを選びます．

    ```bash
    uv run roboloom check-hold piper-pika left --tolerance 0.02
    ```

## 実機で確かめること

- 関節角の符号と零点が，SDKの説明と合うか．
- 有効化したまま指令が来なくなったとき，腕が保持するか（`check-hold`）．
- motorを無効にしている間に送った `JointCtrl` を，有効化したときにfirmwareが目標として使うか．使う場合は，有効化の直前に書く今の姿勢がその目標になります．
- 有効化が途中で止まった（一部の関節だけ有効になった）ときの振る舞い．今は5 sで諦めてerrorにし，有効になった関節はそのままです．
- 1つのmessageのうち1つのCAN frame（例えば関節3〜4）だけが途絶えた場合は検出できません（SDKはmessageごとに1つの受信時刻しか持たないため）．
- 1 MbpsのCANで，毎回の指令の前に制御modeを送る形で，何Hzまで回るか．`control_hz` の目安を決めます．
- 関節torque（`efforts_Nm`）の符号と大きさ．
