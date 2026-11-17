# follower（followers）

`followers:` のnode YAMLのkeyです．followerは指令を受けて動く装置（腕，gripperなど）で，1台につきcontrollerがちょうど1つ必要です（[controller](controllers.md#followers)）．

## 共通のkey { #common }

どの機種も読むkeyです．関節の名前と単位は機種が決めます．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | 機種（`rakuda2_follower`，`piper_follower`，`pika_gripper_follower`）か `module:Class` |
| `control_hz` | 数値 | 必須 | Hz | busを読み書きする周期（[制御周期](#control-rate)）．`dataset_fps` 以上 |
| `limits` | リスト | 必須 | — | 関節ごとの範囲・速度・飛びの制限（[limits](control.md#limits)） |
| `health` | mapping | — | — | 温度・電流などの検査（[health](#health)） |
| `record_effort` | 真偽値 | `false` | — | `true` で力の量を `observation.effort` に記録する．力を測らない機種では拒否 |
| `torque` | 真偽値 | `true` | — | `false` でtorqueを入れず，状態だけを記録する（実機の最初の確認用） |
| `parts` | mapping | `{}` | — | 部分の名前から関節のリストへ（[parts](#parts)） |
| `unattended` | 文字列 | — | — | 機種が `unknown` と宣言したときだけ，実測した値（`holds` か `torque_off`）を書ける（[脱力したときと放置したときの性質](#torque-off-and-unattended)） |

### health { #health }

`every_ticks` 周期ごとに，機種のdriverが報告する異常を調べます．motor自身の過負荷停止より先に `FAULT` にします．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `every_ticks` | 整数 | `10` | 周期 | 検査の間隔 |
| `max_temperature_c` | 数値 | — | °C | これを超えると `FAULT` |
| `max_current_mA` | 関節ごとのリスト | — | mA | 電流の上限 |
| `over_current_s` | 数値 | `1.0` | s | `max_current_mA` を超え続けたら `FAULT` にするまでの時間．`max_current_mA` があるときだけ |

### parts { #parts }

部分は，`type: parts` のcontrollerが別々に動かせる関節のまとまりです（[parts controller](controllers.md#parts)）．機種が持つ部分に，YAMLの `parts: {名前: [関節]}` で足せます．部分のないfollowerは何も書かなくてよく，全体で動かします．

## rakuda2_follower { #rakuda2-follower }

Rakuda2の17関節（1本のDynamixel bus）です．単位は `dynamixel_count`，力の量は `currents_mA`（mA）です．部分は `body`（胴体と頭），`right_arm`，`right_gripper`，`left_arm`，`left_gripper` です．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `port` | 文字列 | 必須 | — | U2D2のport（`/dev/serial/by-id/...`） |
| `motor_ids` | 整数のリスト | 必須 | — | 関節の順のmotor ID．決まった並び `[27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30]` と一致すること |
| `registers` | mapping | 必須 | — | 起動時に照合するEEPROMの値（下の表）．値が違うと起動しない |
| `control` | リスト | — | — | 関節groupごとの制御則（[control](control.md)）．書かなければ位置の目標だけを送る |
| `bus_watchdog_ms` | 整数か `null` | — | ms | DynamixelのBus Watchdog．電流制御の制御則には実機で必須 |
| `kinematics` | mapping | `{}` | — | `right_arm`，`left_arm` から関節の対応表（`roboloom calibrate-joints` の出力）へ．姿勢を指令するcontroller（`pose_ik`）が使う |

`registers` の各項目は `{default: 値, <関節名>: 値}` です．`operating_mode` は，`control` がなければ必須です．`control` があると制御則から決まり，書いた値が矛盾すると拒否します．

| `registers` のkey | 単位 | 説明 |
| --- | --- | --- |
| `operating_mode` | — | Operating Mode |
| `drive_mode` | — | Drive Mode |
| `homing_offset` | — | Homing Offset |
| `current_limit` | mA | Current Limit |
| `return_delay` | µs | Return Delay Time |
| `shutdown` | — | Shutdown（異常時に止める条件） |

## piper_follower <span class="status status--dev">開発中</span> { #piper-follower }

PiPERの腕1本（6関節，`joint1`〜`joint6`）です．腕自身の位置制御（MOVE J）で動かします．単位は `rad`，力の量は `efforts_Nm`（N·m）です．`control` は書けません．`health` が必須です（teach button，衝突，driverの異常はそこでしか分からないため）．詳しくは [PiPER](../../robots/piper/index.md) を参照してください．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `can` | 文字列か `{serial}` | 必須 | — | CANのinterface（例：`can0`），またはUSB-CAN adapterのserial番号（`{serial: "0029..."}`．開くときに今のinterfaceを探す．`roboloom setup` が書く） |
| `speed_percent` | 整数 | 必須 | % | firmwareの関節速度（1〜100） |
| `stale_ms` | 数値 | `50` | ms | これより古い状態を受け取ると `FAULT` |

## pika_gripper_follower <span class="status status--dev">開発中</span> { #pika-gripper-follower }

Pika Gripper（1関節 `gripper`）です．gripper自身のdriverの位置制御で動かします．単位は `rad`，力の量は `currents_mA`（mA）です．`control` は書けません．`health` が必須です．詳しくは [Pika](../../robots/pika/index.md) を参照してください．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `port` | 文字列 | 必須 | — | serial port（`/dev/serial/by-path/...`） |
| `current_limit_A` | 数値 | 必須 | A | torqueを入れる前に送るmotorの電流の上限（0より大きく2以下） |
| `stale_ms` | 数値 | `100` | ms | これより古い状態を受け取ると `FAULT` |

## 脱力したときと放置したときの性質 { #torque-off-and-unattended }

followerと動作する入力機器（制御則で動くleader）の機種は，安全に関わる次の2つの性質を宣言します．`release` の確認文，終了の選択肢，画面の表示はこの宣言から決まります．

| 性質 | 値 | 意味 |
| --- | --- | --- |
| `torque_off`（torqueが切れたとき：`release`・電源断） | `falls` | 自重で落ちる．操作者が支える |
| | `lets_go` | 本体はその場に残るが，つかんでいる物を放す（gripper）．物を外しておく |
| | `stays` | 何も動かない |
| `unattended`（roboloomが指令を書かなくなったとき：保持して終了・processの異常終了・通信の切断） | `holds` | 最後の目標を保つ |
| | `torque_off` | 脱力する（busのwatchdog，閉じるときに脱力するdriver） |
| | `unknown` | 確かめていない．`torque_off` と同じに扱う |

| 機種 | `torque_off` | `unattended` |
| --- | --- | --- |
| Rakuda2 follower | `falls` | `holds`．電流制御の制御則（`gravity_comp`，`impedance`）のgroupがあると `torque_off`（閉じるときとwatchdogで脱力するため）．`current_position` と `spring` は電流制限つき位置制御で位置を保つので `holds` |
| Rakuda-mini（leader） | `falls` | `torque_off`（sessionの終了時に脱力） |
| 外部のbus（`InProcessSession.from_components`） | `falls` | `unknown`（分からないので最悪の場合） |
| PiPER follower <span class="status status--dev">開発中</span> | `falls` | `unknown`（確かめていない） |
| Pika Gripper follower <span class="status status--dev">開発中</span> | `lets_go`（と見なす） | `unknown`（確かめていない） |

- 「保持したまま終了」は，`unattended: holds` のfollowerがあるときだけ選べます．保持しないfollowerは，終了の確認で名前と，脱力する（または，するかもしれない）ことを示します．torqueのあるfollowerがあれば，保持できなくても「支えてから脱力して終了」を選べます．指令のないまま有効のfollowerは，終了後にroboloomから脱力させられないためです．
- `release` の確認では，`falls` の機器に「支える」，`lets_go` の機器に「物を外す」と表示します．`stays` の機器は名前を出しません．確認そのものは，どの機器でも必要です．
- followerが `RELEASED` のときと，`FAULT` か `ESTOP` で保持しない（`unattended` が `holds` でない）ときは，画面のfollowerの行にすることを表示します．`FAULT` と `ESTOP` では，followerへ書くのをやめるためです（torqueは切りません．腕を落とさないためです）．Dynamixelのbusは，読み取りが1回失敗しても，もう1回読み直してから `FAULT` にします（書き込みはやり直しません）．読み直した回数は画面のfollowerの行に `bus reads repeated: N` と出ます．増え続けるなら，cableとUSB adapterを確かめてください．busを読めなかった周期の状態は，最後に読めた時刻のまま流すので，recorderは `max_age_ms` を過ぎた行を欠測（`valid` が0）として記録します．
- `ESTOP` は性質に依らず，その場で保持してlatchします．
- 機種が `unknown` と宣言した `unattended` だけは，followerのYAMLに実測した値（`unattended: holds` か `torque_off`）を書けます．値は `roboloom check-hold`（[CLI](../cli.md)）が測り，確認の後に書きます．機種が宣言した値と違う値を書くと，設定の読み込みで拒否します．

## 制御周期 { #control-rate }

`follower.yaml` の `control_hz` と，leaderの `poll_hz` は，そのnodeがbusを読み書きする周期です．1周期の仕事（状態の読み出し，制御則の計算，目標値の書き込み）が周期に収まる必要があります．周期を上げると，leaderの電流制御とfollowerの追従が細かくなります．

nodeの周期（`control_hz`，`poll_hz`，sensorの `fps`，方策の `rate_hz`）は，整数のHzか，1周期が整数のミリ秒になる値にします（30，120，12.5 = 80 msなど）．doraのtimerがそれ以外を刻めないためで，29.97のような値は `validate` と起動のときに拒否します．

周期は次の手順で決めます．

1. `roboloom probe <port>` を各portで実行します．状態の読み出し時間と，目安の周期上限（読み出しと書き込みに周期の70%を使う値）を表示します．`probe` は書き込みません．
2. `control_hz` と `poll_hz` を設定し，`run` の画面で確かめます．followerとleaderの行の `work … ms (max …)` が1周期の仕事の時間です．最大値が周期の70%程度以下で，`tick` が周期どおりなら，その周期で動いています．
3. 超える場合は周期を下げます．

Dynamixelのbusは，全motorのfirmwareがv45以上なら，起動時にFast Sync Read（全motorの応答を1 packetで返す読み出し）へ切り替えます．使えないときは通常の読み出しのまま動き，起動時に理由を表示します．

Rakuda2での実測値です（2026-10-27，17 motor，1 Mbps，FTDI latency timer 1 ms）．

| 読み出し | 時間 |
| --- | --- |
| 状態（位置・速度・電流），通常のSync Read | 5.0 ms |
| 状態，Fast Sync Read | 4.0 ms |
| Bus Watchdog（1 register），Fast Sync Read | 2.0 ms |

また，Dynamixel SDKが送信のたびに行う出力の待ち（`flush`）を省いています．leaderの1周期では，これだけで約1.9 msかかっていました．packetの順序は変わりません．

時間を節約するため，次の読み出しは毎周期は行いません．

- leaderのBus Watchdog：目標値の書き込みが `bus_watchdog_ms` の半分以上途切れたときと，100 msごとに読みます．作動していたら，今までどおり電流制御の関節を脱力します．
- followerの `health`：`every_ticks` 周期ごとに，Bus Watchdog・hardware error・温度を1つずつ順に読みます．各値は `every_ticks` の3倍の周期ごとに更新されます．

templateは120 Hzです．Rakuda2の実機で確かめた結果です（2026-10-27，121秒）．

| | 1周期の仕事（平均，最大） | 周期の間隔 |
| --- | --- | --- |
| leader（重力補償） | 4.3 ms，6.8 ms | 中央値 8.0 ms，p99.9 10.1 ms |
| follower | 3.7 ms，6.1 ms | 7.7 ms |

この間に1回，約120 msの停止がありました．60 Hzでも同じ程度の停止が起きており，周期とは関係ありません．120 HzはFTDIのlatency timerが1 msで，Fast Sync Readが使えることを前提にしています．`probe` の目安がこれを下回る場合や，`work` の最大が周期の70%を超える場合は，`control_hz` と `poll_hz` を下げてください（例：60）．

## 例 { #example }

```yaml
# nodes/follower.yaml（一部．limits と health は全関節ぶん書く）
type: rakuda2_follower
port: SET_FOLLOWER_PORT
motor_ids: [27, 28, 29, 1, 3, 5, 7, 9, 11, 31, 2, 4, 6, 8, 10, 12, 30]
control_hz: 120
torque: true
record_effort: true
registers:
  operating_mode: {default: 3, r_arm_grip: 5, l_arm_grip: 5}
  current_limit: {r_arm_grip: 54, l_arm_grip: 54}
health:
  every_ticks: 10
  max_temperature_c: 70
limits:
- {name: torso_yaw, min: 0, max: 4095, max_speed: 3072, max_jump: 300}
# ...
```
