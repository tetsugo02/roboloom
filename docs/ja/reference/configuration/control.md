# 制御則（control）

leader（`rakuda_mini`）とfollower（`rakuda2_follower`）のnode YAMLの `control:` は，関節groupごとに制御則を選びます．同じ制御則がleaderとfollowerで使えます．このページは制御則ごとのkeyと，followerの `limits`，controllerの `home` のkeyをまとめます．使い方は [Leaderの設定例](../../controllers/leader.md) と [重力補償](../../explanation/gravity-compensation.md) を参照してください．

## groupの共通のkey { #common }

`control:` はgroupのリストです．全関節をちょうど1回ずつ，どれかのgroupに入れます．group名は重複できません．groupは，その制御則が読むkeyだけを受け付けます（ほかのkeyは読み込み時に拒否します）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `group` | 文字列 | 必須 | — | group名．[`extends`](index.md#extends) で同じ名前のgroupに重ねる |
| `law` | 文字列 | 必須 | — | `free`，`position`，`current_position`，`spring`，`gravity_comp`，`impedance` のどれか |
| `joints` | 文字列のリスト | 必須 | — | このgroupの関節 |
| `feedback` | mapping | — | — | 力の逆送を受ける（[下記](#feedback)）．電流制御の制御則（`gravity_comp`，`impedance`）だけ <span class="status status--mock">模擬のみ</span> |

制御則の動作mode（Dynamixel の Operating Mode）は制御則から決まります．Rakuda2では，YAMLの `registers.operating_mode` と矛盾すると拒否します．

| `law` | 動作mode | 電流制御 |
| --- | --- | --- |
| `free` | なし（torqueを切る） | — |
| `position` | 位置制御 | — |
| `current_position` | 電流制限つき位置制御 | — |
| `spring` | 電流制限つき位置制御 | — |
| `gravity_comp` | 電流制御 | はい |
| `impedance` | 電流制御 | はい |

電流制御の制御則のgroupがあるnodeは，実機では `bus_watchdog_ms` が必要です．

## free { #free }

torqueを切ります．手で動かすleaderの関節に使います．共通のkeyのほかにkeyはありません．

## position { #position }

目標の位置へ動かします．目標がないときは最後の目標を保ちます．leaderでは，torqueを入れたときの姿勢を保持します（関節の固定）．共通のkeyのほかにkeyはありません．

## current_position { #current-position }

電流制限つき位置制御です．目標電流がtorqueの上限になります．`target` を書くとその位置へ戻るばねになります．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `goal_current_mA` | 数値か関節ごとのリスト | 必須 | mA | 目標電流（torqueの上限）．実機ではEEPROMの `registers.current_limit` 以下 |
| `target` | 数値か関節ごとのリスト | — | 関節の単位 | 固定の目標．書くと入力の目標を使わない |

## spring { #spring }

手で操作する関節の戻りばねです（leaderのgripperのtriggerなど）．`rest` に電流制限つき位置制御で保ち，押すと変位に応じた力で戻ります．力は `goal_current_mA` までなので，操作者はいつでも押し切れます．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `rest` | 数値か関節ごとのリスト | 必須 | 関節の単位 | 戻る位置 |
| `goal_current_mA` | 数値か関節ごとのリスト | 必須 | mA | 戻す力の上限．実機ではEEPROMの `registers.current_limit` 以下 |

## 電流制御の共通のkey { #current-laws }

`gravity_comp` と `impedance` が読むkeyです．出力は `ramp_s` かけて立ち上がり，関節ごとに `max_current_mA` で制限します．速すぎる関節と範囲外の関節は逸走とみなし，nodeを脱力させます．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `max_current_mA` | 数値か関節ごとのリスト | 必須 | mA | 出力電流の上限 |
| `max_velocity` | 数値 | 必須 | count/s | これより速い関節は逸走とみなす |
| `range` | `[min, max]` の関節ごとのリスト，またはfileのpath | 必須 | count | 可動域．pathは `roboloom measure-travel` が書くfile |
| `range_margin` | 数値 | `100` | count | `range` の外でも逸走とみなさない幅 |
| `barrier_mA_per_count` | 数値 | `0.5` | mA/count | `range` の外で押し戻す電流 |
| `gravity_model` | path | — | — | 重力model（`roboloom identify-gravity` の出力）．node fileのdirectoryが基準 |
| `gravity_gain` | 数値か関節ごとのリスト | 重力modelがあれば `1.0`，なければ `0.0` | — | 重力の項の係数 |
| `tuning` | path | — | — | `roboloom tune-gravity` が書く調整値（`gravity_gain`，`hold_mA`，`hold_kp`）．同じkeyを直接書くと拒否 |
| `kd` | 数値か関節ごとのリスト | `0.0` | mA/(count/s) | 減衰 |
| `ramp_s` | 数値 | `1.0` | s | torqueを入れてから出力が全量になるまでの時間 |
| `homing` | `{kp_mA_per_count, max_mA}` | — | mA/count，mA | `home` で関節を引くばね．controllerに [`home`](#home) があるとき，leaderの電流制御のgroupには必須 |

## gravity_comp { #gravity-comp }

手で動かしても落ちない関節です．電流 = `gain × g(q) − kd × 速度` ＋範囲の押し戻し．`hold_mA` が0より大きいと，`hold_kp` のばねで関節を錨の位置へ引きます．力は `hold_mA` までで，強く押すと錨が手について動きます（摩擦のように働きます）．

[電流制御の共通のkey](#current-laws) に加えて，次を読みます．`gravity_model` は必須です．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `hold_mA` | 数値か関節ごとのリスト | `0.0` | mA | 保持の力の上限．0で保持しない |
| `hold_kp` | 数値 | `1.0` | mA/count | 保持のばねの強さ |

## impedance <span class="status status--mock">模擬のみ</span> { #impedance }

目標の周りの関節impedanceです：`kp (q* − q) − kd × 速度 + gain × g(q)`．実機では検証していないので，実機で使うには `allow_unvalidated: true` が必要です．

[電流制御の共通のkey](#current-laws) に加えて，次を読みます．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `kp` | 数値か関節ごとのリスト | 必須 | mA/count | ばねの強さ |
| `allow_unvalidated` | 真偽値 | `false` | — | `true` で実機でも起動する |

## 力の逆送を受ける（feedback） <span class="status status--mock">模擬のみ</span> { #feedback }

leaderの電流制御のgroup（`gravity_comp`，`impedance`）に `feedback:` を書くと，その関節がcontrollerからの逆送を受け取ります．位置制御のgroupや `free` には書けません．経路とcontroller側の設定は [controllerの `feedback`](controllers.md#feedback) を参照してください．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `max_mA` | 数値か関節ごとのリスト | 必須 | mA | 逆送分だけの上限 |
| `ramp_s` | 数値 | `0.3` | s | gateの開閉にかける時間 |
| `kd` | 数値か関節ごとのリスト | `0.0` | mA/(count/s) | 逆送中に足す減衰 |

```yaml
- group: right_arm
  law: gravity_comp
  # ...
  feedback:
    max_mA: 20     # 逆送分だけの上限（関節ごとのリストも可）
    ramp_s: 0.3    # gateの開閉にかける時間（既定0.3）
    kd: 0.0        # 逆送中に足す減衰，mA/(count/s)（既定0）
```

leaderは，毎周期，次の値を制御則の出力に足してから `max_current_mA` で制限します．

```text
gate × (clip(受け取った電流, ±max_mA) − kd × 速度)
```

`gate` は0〜1の値で，controllerが適用を希望し，かつmessageの期限（`deadline_ms`）内なら1へ，そうでなければ0へ，`ramp_s` かけて近づきます．急に変わりません．estop・release・quit，脱力，逸走の検出では即座に0になります．逆送を受ける関節は，重力のgainが0でも逸走の検査（`max_velocity`，範囲外）の対象です．`tune-gravity` と `gravity-check` の間は逆送を使いません．実機では `max_mA` ≤ `max_current_mA` を確かめます．leaderのstatusの `feedback` に，`gate`，各関節の逆送電流（`mA`），受信数を出します．trace（`<leader名>_trace.npz`）の `feedback_mA` にも残ります．

逆送の電流は，重力補償と同じ `max_current_mA` とEEPROMのCurrent Limitの内側にあります．上限の近くでは削られます．Current Limitを上げると，hostが止まったときに腕に残る力も大きくなります（XC330はBus Watchdogが作動しても電流を止めません）．

## 可動域と速度の制限（limits） { #limits }

followerの `limits` は関節ごとの安全の検査です．全関節を順に，名前付きで書きます．controllerの指令はすべてこの検査を通ります．実験fileからは変えられません．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `name` | 文字列 | 必須 | — | 関節名．followerの関節の順に並べる |
| `min` | 数値 | 必須 | followerの単位 | 位置の下限（`min` < `max`）．範囲の外の目標は範囲に削る |
| `max` | 数値 | 必須 | followerの単位 | 位置の上限 |
| `max_speed` | 数値 | 必須 | followerの単位/s | これを超える目標は削る．controllerの `max_speed` より大きくする（[単位](index.md#units)） |
| `max_jump` | 数値 | 必須 | followerの単位 | 直前に送った目標からこれ以上離れた指令は拒否する |

## 初期姿勢（home） { #home }

controllerの `home:` は，`home` の指令（`infer --home`，`Session.home()`，画面の Move home）で動く保存した姿勢です．姿勢は `roboloom capture-pose <名前>` で `poses/<follower>/<name>.yaml` に保存します．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `pose` | path | 必須 | — | 保存した姿勢．node fileのdirectoryが基準（例：`../poses/follower/ready.yaml`） |
| `max_speed` | 数値 | 必須 | followerの単位/s | 動く速さ．controllerの `max_speed` 以下 |
| `tolerance` | 数値 | 必須 | followerの単位 | 到着とみなす差 |
| `timeout_s` | 数値 | `30` | s | 到着を待つ上限 |

書く場所はcontrollerによって違います．

| controller | 書き方 |
| --- | --- |
| `joint` | `home: {pose, max_speed, tolerance}`．leaderも対応する姿勢へ動く．leaderの電流制御のgroupには `homing` が必要 |
| `policy` | followerが1台なら `home: {pose, ...}`，複数なら `{follower: {pose, ...}}`（書かないfollowerは動かない） |
| `pose_ik` | `{follower: {pose, ...}}` |
| `parts` | 書けない（内側のcontrollerにも書けない） |

## 例 { #example }

```yaml
# leaderのnode YAMLの一部
control:
- group: right_arm
  law: gravity_comp
  joints: [r_arm_sh_pitch1, r_arm_sh_roll, r_arm_sh_pitch2, r_arm_el_yaw, r_arm_wr_roll, r_arm_wr_yaw]
  gravity_model: ../calibration/gravity_right.yaml
  tuning: ../calibration/gravity_tuning_right.yaml
  max_current_mA: [150, 150, 100, 100, 60, 60]
  max_velocity: 3000
  range: ../calibration/travel_right.yaml
  homing: {kp_mA_per_count: 0.5, max_mA: 40}
- group: trigger
  law: spring
  joints: [r_arm_grip, l_arm_grip]
  rest: 2500
  goal_current_mA: 30
bus_watchdog_ms: 500
```
