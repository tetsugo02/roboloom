# Configuration

## 設定の指定

`roboloom init rakuda2` が `.roboloom/rakuda2/` に設定・ノード・calibration YAMLを作ります．既存のディレクトリを上書きしません．設定は機体ごとに1つ（`config.yaml`）で，機能の組み合わせは起動オプションで選びます．機体名 `rakuda2` は `.roboloom/rakuda2/config.yaml` を指します．`.roboloom/` の下に機体が1台だけなら省略でき，ファイルパスでも指定できます．

## 設定YAML

```yaml
repo_id: local/rakuda2
output: datasets/rakuda2
dataset_fps: 15
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
followers:
  follower: nodes/follower.yaml
sensors:
  camera: nodes/camera.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
options:
  # 次の節を参照
```

`mode` は省略でき，既定は `hardware` です．`mode: mock` も書けます．CLIの `--mock` とPython APIの `mock=` はYAMLの `mode` より優先します．

ノードYAMLのパスと `output` は設定ファイルのディレクトリが基準です．オプションを有効にしない場合，上の保存先は `.roboloom/rakuda2/datasets/rakuda2` です．

最上位に書けるキーは `repo_id`，`output`，`dataset_fps`，`mode`，役割（`trackers`，`inputs`，`controllers`，`followers`，`sensors`，`estimators`），`recorder`，`session`，`options` だけです．それ以外のキーは読み込み時に拒否します．ロボットの名前は設定のディレクトリ名（`.roboloom/rakuda2/` なら `rakuda2`）で，データセットの `robot_type` にも使います．

`followers` には，指令を受けて動く装置（腕，グリッパなど）を並べます．1つの設定に複数のフォロワを置けます．各フォロワには，それを動かすcontrollerがちょうど1つ必要です．`followers: {}` としてフォロワを置かない構成は，入力とセンサーを記録するだけで，`action` を記録しません．このときcontrollerは置けず，入力とセンサーは自分の周期（`poll_hz`，`fps`）を持つ必要があります（[Pika Senseを手に持った収集](../contribution/pika-handheld.md)，開発中）．

ノード名はdoraのIDとデータセットのfeature名に使われます．英数字，`-`，`_` だけを使います．`recorder`，`session`，`action`，`tick` と，`action_` で始まる名前，`_status` で終わる名前は，dataflowが使うので付けられません．

各ノードの `type` が実装を選びます．`SET_...` は機体固有の未設定値で，参照する設定に残っていると実行が拒否されます．`validate` は設定とdataflowの整合性を調べ，デバイスは開きません．EEPROMの実機との一致，画像取得，停止挙動までは確認しません．

## フォロワとcontroller

各controllerは `followers:` に，動かすフォロワを並べます．1台のフォロワを動かすcontrollerはちょうど1つです．

| controller | 動かすフォロワ |
| --- | --- |
| `joint` | ちょうど1台（leaderの関節を1台のフォロワの関節へ対応させる） |
| `pose_ik` | 腕1台と，任意でグリッパ1台（手に持った機器の姿勢をIKで腕の関節へ．[開発中](../contribution/pika-sense.md)） |
| `parts` | ちょうど1台．内側のcontrollerがそれぞれ一部の関節を動かす（[フォロワの部分を別々に動かす](#parts)） |
| `policy` | 全フォロワを設定の順に．記録した `action` と `observation.state` が全フォロワをつないだ形なので，方策の出力も同じ形です．出力を並び順に分けて各フォロワへ送ります |

フォロワが複数あるcontrollerは，全フォロワの状態がそろうまで指令を送りません．どれかのフォロワが `FAULT` や `ESTOP` になるか，状態が `follower_timeout_ms` より古くなると，そのcontrollerは全フォロワへの指令を止めます．指令が途切れたフォロワは，保持している目標を保ちます．controllerは，位置を合わせ直すまで次の指令を送りません．`policy` controllerは，フォロワの状態が古くなると，その回のエピソードの方策の実行を止めます．画面のcontrollerの行に，止めた理由（`stopped_by`）と，状態を待っているフォロワ（`waiting_state`）が出ます．

`feedback`（力の逆送）は，フォロワが1台のcontrollerでだけ使えます．

### フォロワの部分を別々に動かす { #parts }

`type: parts` のcontrollerを使うと，Rakuda2（1本のバスに17関節）のように関節の多いフォロワを，複数の入力で，それぞれ別の関節について動かせます．腕ごとに手持ちのデバイスを使う，片腕だけleaderで動かす，といった構成です．フォロワが受け取る指令は，今までどおり1つのcontrollerからの1本です．安全の検査，記録する `action`，データセットは変わりません．確かめたのは模擬のデバイスだけです．

フォロワは自分の部分に名前を付けます．Rakuda2は `body`（胴体と頭），`right_arm`，`right_gripper`，`left_arm`，`left_gripper` を持ちます．どのフォロワのYAMLでも `parts: {名前: [関節]}` で足せます．部分のないフォロワは何も書かなくてよく，全体で動かします．

```yaml
# nodes/controller.yaml
type: parts
followers: [follower]
command_deadline_ms: 100
parts: [right_hand.yaml, left_hand.yaml]   # このファイルの隣のcontrollerのファイル
```

```yaml
# nodes/right_hand.yaml：controllerの種類は自由．followers は部分（<フォロワ>.<部分>）
type: joint
input: leader
followers: [follower.right_arm]
alignment_tolerance: 300
max_speed: 2048
command_deadline_ms: 100
input_timeout_ms: 150
```

- 内側のcontrollerは，自分の部分を1台のフォロワとして扱います（単位と周期は同じ，可動域はその関節のもの）．それぞれ自分の入力に追従します．同じ入力に複数の内側のcontrollerが追従しても構いません．
- 1つの関節を動かせる内側のcontrollerは1つまでです．どの部分も動かさない関節は，フォロワが保持している位置に留まります．
- フォロワへの指令は全関節の1本なので，ある入力の指令には，ほかの部分の目標も入ります．入れるのは，その部分の目標がまだ有効な間だけです（指令してから内側のcontrollerの `command_deadline_ms` 以内で，そのcontrollerがそのあと指令を止めていないこと）．入力が止まった部分，手を離した部分，IKが届かなかった部分には，フォロワが保持している目標を入れます．古い目標へ動き続けることはありません．
- フォロワが `FAULT` か `ESTOP` になると，すべての部分が揃え直してから指令を再開します．
- 内側のcontrollerには，まだ `home` と `feedback` を書けません．partsのcontrollerを方策の `teleop:` に使うこともできません．
- controllerの行は，どれかの部分が指令を送っていれば `following` です．`parts` に内側のcontrollerごとの状態が出ます．

## 単位

関節の位置の単位は，フォロワとleader（`inputs`）がそれぞれ宣言します．既定値はありません．Rakuda2は `dynamixel_count` です．controllerの `unit` はleaderとフォロワの単位と一致させます．指令にも単位が入り，フォロワは自分の単位と違う指令を受け取りません．

速度の上限 `max_speed` は3か所にあり，どれもフォロワの単位/sです．

| 場所 | 役割 |
| --- | --- |
| フォロワの `limits` の `max_speed`（関節ごと） | フォロワの安全の検査．これを超える目標は削られる．最後の砦なので，controllerの値より大きくする |
| `joint` controllerの `max_speed` | 遠隔操作の目標を1周期に動かせる幅 |
| `policy` controllerの `max_speed` | 方策の目標を1周期に動かせる幅．フォロワごとに `{フォロワ名: 値}` で書く（単位がフォロワごとに違うため） |
| controllerの `home.max_speed` | 保存した姿勢へ動くときの速さ．controllerの `max_speed` 以下 |

`home.tolerance`（到着とみなす差）も，フォロワの単位で必ず書きます．

## 脱力したときと放置したときの性質

フォロワと動作する入力機器（制御則で動くleader）の機種は，安全に関わる次の2つの性質を宣言します．`release` の確認文，終了の選択肢，画面の表示はこの宣言から決まります．

| 性質 | 値 | 意味 |
| --- | --- | --- |
| `torque_off`（トルクが切れたとき：`release`・電源断） | `falls` | 自重で落ちる．操作者が支える |
| | `lets_go` | 本体はその場に残るが，つかんでいる物を放す（グリッパ）．物を外しておく |
| | `stays` | 何も動かない |
| `unattended`（roboloomが指令を書かなくなったとき：保持して終了・プロセスの異常終了・通信の切断） | `holds` | 最後の目標を保つ |
| | `torque_off` | 脱力する（バスのwatchdog，閉じるときに脱力するドライバ） |
| | `unknown` | 確かめていない．`torque_off` と同じに扱う |

| 機種 | `torque_off` | `unattended` |
| --- | --- | --- |
| Rakuda2フォロワ | `falls` | `holds`．電流制御の制御則（`gravity_comp`，`impedance`，`spring`）のグループがあると `torque_off`（閉じるときとwatchdogで脱力するため）．`current_position` は位置を保つので `holds` |
| Rakuda-mini（leader） | `falls` | `torque_off`（セッションの終了時に脱力） |
| 外部のバス（`InProcessSession.from_components`） | `falls` | `unknown`（分からないので最悪の場合） |
| PiPERフォロワ（[開発中](../contribution/piper.md)） | `falls` | `unknown`（確かめていない） |
| Pika Gripperフォロワ（[開発中](../contribution/pika-gripper.md)） | `lets_go`（と見なす） | `unknown`（確かめていない） |

- 「保持したまま終了」は，`unattended: holds` のフォロワがあるときだけ選べます．保持しないフォロワは，終了の確認で名前と，脱力する（または，するかもしれない）ことを示します．トルクのあるフォロワがあれば，保持できなくても「支えてから脱力して終了」を選べます．指令のないまま有効のフォロワは，終了後にroboloomから脱力させられないためです．
- `release` の確認では，`falls` の機器に「支える」，`lets_go` の機器に「物を外す」と表示します．`stays` の機器は名前を出しません．確認そのものは，どの機器でも必要です．
- フォロワが `RELEASED` のときと，`FAULT` か `ESTOP` で保持しない（`unattended` が `holds` でない）ときは，画面のフォロワの行にすることを表示します．`FAULT` と `ESTOP` では，フォロワへ書くのをやめるためです．
- `ESTOP` は性質に依らず，その場で保持してラッチします．
- 機種が `unknown` と宣言した `unattended` だけは，フォロワのYAMLに実測した値（`unattended: holds` か `torque_off`）を書けます．値は `roboloom check-hold`（[CLI](cli.md)）が測り，確認の後に書きます．機種が宣言した値と違う値を書くと，設定の読み込みで拒否します．

## 起動オプション

`options:` は，起動時に選ぶ機能（重力補償，追加のセンサーなど）を名前で定義します．各オプションはノードファイルを置き換え・追加・削除します．`nodes/` の下のノードファイルは機能ごとに分かれたままで，オプションはどれを使うかを選ぶだけです．

| キー | 意味 |
| --- | --- |
| `help` | ランチャーに表示する説明 |
| `default` | `true` なら，指定がないときに有効（既定 `false`） |
| `requires` | 一緒に有効にするオプションのリスト |
| `conflicts` | 同時に使えないオプションのリスト |
| `set` | `<role>.<node>`（roleは `trackers`，`inputs`，`controllers`，`followers`，`sensors`，`estimators` のどれか）からノードファイルへの対応．`null` はそのノードを削除する |
| `dataset` | 有効なときにデータセット名へ付ける短い名前 |

規則は次のとおりです．

- オプションを有効にすると，`requires` のオプションも有効になり，`conflicts` のオプションは無効になります．無効にすると，それを必要とするオプションも無効になります．
- 有効な2つのオプションが同じノードを違うファイルにするとエラーです．ただし，片方がもう片方を `requires` に持つ場合は，必要とする側（依存する側）が優先します．テンプレートでは，`bilateral` のleaderが `gravity` のleaderを置き換えます．
- 未知のオプション名はエラーです．
- 有効なオプションの `dataset` を，宣言順に `-` でつないで `repo_id` と `output` の末尾に付けます．形の違うエピソードが同じデータセットに混ざらないようにするためです．
- `dataset` を持たないオプションが記録するfeatureを変える場合，読み込みを拒否します．

テンプレート（`src/roboloom/robots/rakuda2/template/config.yaml`）のオプションです．

```yaml
options:
  digit:
    help: record the left/right DIGIT tactile sensors
    set:
      sensors.digit_left: nodes/digit_left.yaml
      sensors.digit_right: nodes/digit_right.yaml
    dataset: digit
  gravity:
    help: gravity-compensated leader arms (after the measurement steps of README.md)
    set:
      inputs.leader: nodes/leader_gravity.yaml
  bilateral:
    help: force feedback from the follower to the leader (NOT verified on hardware)
    requires: [gravity]
    set:
      inputs.leader: nodes/leader_bilateral.yaml
      controllers.controller: nodes/controller_bilateral.yaml
      followers.follower: nodes/follower_bilateral.yaml
      estimators.effort: nodes/effort.yaml
    dataset: bilateral
  policy:
    help: a learned policy drives the follower (`roboloom infer` turns this on)
    conflicts: [gravity]
    set:
      inputs.leader: null
      controllers.controller: null
      controllers.policy: nodes/policy.yaml
    dataset: eval
```

| 有効なオプション | `repo_id` |
| --- | --- |
| なし | `local/rakuda2` |
| `digit` | `local/rakuda2-digit` |
| `policy` | `local/rakuda2-eval` |
| `digit`，`policy` | `local/rakuda2-digit-eval` |
| `gravity`，`bilateral` | `local/rakuda2-bilateral` |

`output` にも同じ名前が付きます（例：`datasets/rakuda2-digit`）．どのオプションが有効か，データセット名が何になるかは `roboloom validate --with digit` のように確かめられます．オプションの選び方は [CLI](cli.md) を，Rakuda2で使える組み合わせと制約は [Rakuda2](../robots/rakuda2.md) を参照してください．

## 関節固定と相殺

leaderノードの `control` は，`free`（脱力），`position`（leaderでは通電時の姿勢を保持），`spring`，`gravity_comp` などを関節グループごとに選びます．全関節をちょうど1回ずつ指定します．`joint` controllerの `couplings`（既定 `[]`）は，`{joint, source, scale, reference}`（任意で `lead_ms`） のリストで，他のfollower関節の `reference` からの実測変位を目標へ加えます．両者は独立した設定です．[Leaderの設定例](../controllers/leader.md)を参照してください．

## 力の逆送（実機未検証）

!!! warning "実機では未検証"
    followerが受けた外力をleaderへ返す経路です．模擬（mock）の試験だけを通しています．設計と今後の段階は [バイラテラル制御の設計](../contribution/bilateral.md) を参照してください．

設定に `estimators` を足し，controllerの `feedback` で推定器を参照します．テンプレートでは，オプション `bilateral` が `estimators.effort` を追加し，leader・controller・followerを逆送用のノードファイルに置き換えます．辺は書きません．各ノードの参照から次の経路を導きます．

```text
leader ──sample──► controller ──command──► follower ──state──► estimator
  ▲                    │  ▲                                  │
  └──── feedback ──────┘  └────────────── estimate ──────────┘
```

```yaml
estimators:
  effort: nodes/effort.yaml
```

推定器（`nodes/effort.yaml`）：

| キー | 意味 |
| --- | --- |
| `type` | `none`（常に推定なし．経路の確認用）または `model_residual` |
| `models` | `model_residual` の重力モデル（腕ごと）．出力関節を合わせると `joints` とちょうど一致すること |
| `follower` | 状態を読むフォロワのノード名 |
| `joints` | 推定するfollower関節 |
| `smoothing_alpha` | 指数移動平均の係数（0より大きく1以下，既定1＝平滑化なし） |
| `contact_on` / `contact_off` | 残差のL1ノルムによる接触の判定（ヒステリシス）．`contact_off` ≤ `contact_on`．既定はどちらも0で，常に接触とみなす |
| `record` | `true` で推定をデータセットに記録する（既定 `false`）．`recorder.max_age_ms` にこの推定器の名前が必要 |

推定器は，フォロワが申告する力の量（Rakuda2は `currents_mA`，単位mA）から，関節ごとの残差（実測 − 自由運動での予測）を出します．外力は残差と逆向きにかかります．

`model_residual` は `残差 = 実測電流 − g(q)` です．`g(q)` はfollowerで同定した重力モデルで，学習は要りません．摩擦・慣性・位置の追従誤差は残差に残るので，自由に動かしているときも0になりません．推定器ノードのstatusの `residual_l1`（接触の判定と比べる値）を，自由に動かしたときと押したときで見て，`contact_on` をその間に置きます．重力モデルは，leaderと同じ `identify-gravity` で，followerのcalibration（`calibration/follower_<side>.yaml`）から作ります．

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/follower_right.yaml \
    --out .roboloom/rakuda2/calibration/effort_gravity_right.yaml --collect
```

followerの腕は，XM540とXM430が混在するため関節ごとに別々に同定します（`shared_parameters: false`）．leaderより多くの姿勢が要ります．同定中はfollowerのノードを止めておきます．

controllerの `feedback`：

```yaml
feedback:
  estimator: effort
  deadline_ms: 100
  unit: mA/mA          # leaderの単位 / 推定器の単位
  gain:                # followerの関節名 → 係数（0以上）
    r_arm_el_yaw: 0.1
```

leaderへの電流は `−gain × sign × 残差` です（`sign` は `joints` の対応の符号）．controllerは，推定が有効で接触中，followerが `ACTIVE`，controllerが `following` のときだけ，適用の希望（gate）を立てます．期限は，推定の元になったfollowerの状態の時刻から `deadline_ms` です．推定が遅れて届き，その時点で期限を過ぎていれば送らず，controllerのstatusの `feedback_error` に理由を出します．leaderは，`feedback:` を書いた電流制御のグループ（`gravity_comp`，`impedance`）の関節だけで受け取ります．位置制御のグループや `free` には書けません．

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

`gate` は0〜1の値で，controllerが適用を希望し，かつメッセージの期限（`deadline_ms`）内なら1へ，そうでなければ0へ，`ramp_s` かけて近づきます．急に変わりません．estop・release・quit，脱力，逸走の検出では即座に0になります．逆送を受ける関節は，重力のゲインが0でも逸走の検査（`max_velocity`，範囲外）の対象です．`tune-gravity` と `gravity-check` の間は逆送を使いません．実機では `max_mA` ≤ `max_current_mA` を確かめます．leaderのstatusの `feedback` に，`gate`，各関節の逆送電流（`mA`），受信数を出します．トレース（`<leader名>_trace.npz`）の `feedback_mA` にも残ります．

逆送の電流は，重力補償と同じ `max_current_mA` とEEPROMのCurrent Limitの内側にあります．上限の近くでは削られます．Current Limitを上げると，ホストが止まったときに腕に残る力も大きくなります（XC330はBus Watchdogが作動しても電流を止めません）．

`record: true` の推定器は，`observation.effort_ext`（外力＝−残差，推定器の単位），`observation.effort_ext.valid`，`observation.contact` を記録します．推定がないフレームは0です．記録する推定器が複数あるときは，設定の順につなげます．`names` は `observation.effort_ext` が `<フォロワ名>.<関節名>`，ほかの2つが推定器の名前です．単位の違う推定器は1本のベクトルにできないので，読み込み時に拒否します．

読み込み時に，参照先の存在，推定器とcontrollerのフォロワの一致，単位，leader側の受け入れを確かめます．合わない設定は起動前に拒否されます．`couplings` の対象の関節にも，`joints` の対応どおりに返します．Python API（`InProcessSession`）は推定器を扱いません．

## 制御周期

`follower.yaml` の `control_hz` と，leaderの `poll_hz` は，そのノードがバスを読み書きする周期です．1周期の仕事（状態の読み出し，制御則の計算，目標値の書き込み）が周期に収まる必要があります．周期を上げると，leaderの電流制御とfollowerの追従が細かくなります．

周期は次の手順で決めます．

1. `roboloom probe <port>` を各ポートで実行します．状態の読み出し時間と，目安の周期上限（読み出しと書き込みに周期の70%を使う値）を表示します．`probe` は書き込みません．
2. `control_hz` と `poll_hz` を設定し，`run` の画面で確かめます．followerとleaderの行の `work … ms (max …)` が1周期の仕事の時間です．最大値が周期の70%程度以下で，`tick` が周期どおりなら，その周期で動いています．
3. 超える場合は周期を下げます．

Dynamixelのバスは，全モーターのファームウェアがv45以上なら，起動時にFast Sync Read（全モーターの応答を1パケットで返す読み出し）へ切り替えます．使えないときは通常の読み出しのまま動き，起動時に理由を表示します．

Rakuda2での実測値です（2026-10-27，17モーター，1 Mbps，FTDI latency timer 1 ms）．

| 読み出し | 時間 |
| --- | --- |
| 状態（位置・速度・電流），通常のSync Read | 5.0 ms |
| 状態，Fast Sync Read | 4.0 ms |
| Bus Watchdog（1レジスタ），Fast Sync Read | 2.0 ms |

また，Dynamixel SDKが送信のたびに行う出力の待ち（`flush`）を省いています．leaderの1周期では，これだけで約1.9 msかかっていました．パケットの順序は変わりません．

時間を節約するため，次の読み出しは毎周期は行いません．

- leaderのBus Watchdog：目標値の書き込みが `bus_watchdog_ms` の半分以上途切れたときと，100 msごとに読みます．作動していたら，今までどおり電流制御の関節を脱力します．
- followerの `health`：`every_ticks` 周期ごとに，Bus Watchdog・ハードウェアエラー・温度を1つずつ順に読みます．各値は `every_ticks` の3倍の周期ごとに更新されます．

テンプレートは120 Hzです．Rakuda2の実機で確かめた結果です（2026-10-27，121秒）．

| | 1周期の仕事（平均，最大） | 周期の間隔 |
| --- | --- | --- |
| leader（重力補償） | 4.3 ms，6.8 ms | 中央値 8.0 ms，p99.9 10.1 ms |
| follower | 3.7 ms，6.1 ms | 7.7 ms |

この間に1回，約120 msの停止がありました．60 Hzでも同じ程度の停止が起きており，周期とは関係ありません．120 HzはFTDIのlatency timerが1 msで，Fast Sync Readが使えることを前提にしています．`probe` の目安がこれを下回る場合や，`work` の最大が周期の70%を超える場合は，`control_hz` と `poll_hz` を下げてください（例：60）．

## 記録と再開 { #recording-and-resuming }

`record` extraでLeRobotDataset 0.6.1に保存します．取得・利用可能・受信・指令送信の単調時計時刻を区別して整列し，欠損は直前の有効な値と有効フラグで表します．`task` はフレームに記録されます．

フォロワが複数あるとき，`observation.state`，`observation.effort`，`action` は全フォロワを設定の順につなげた1本のベクトルです．`names` が各要素の持ち主を `<フォロワ名>.<関節名>` で示します（例：`follower.r_arm_sh_pitch1`）．ほかのfeatureはノードごとで，ノード名が付きます．

| feature | 中身 |
| --- | --- |
| `observation.state` | 各フォロワの関節の位置 |
| `observation.effort` | `record_effort: true` のフォロワの力の量．単位の違うフォロワは混ぜられません |
| `observation.<input名>` | 各inputの読み値．inputのノード名が付きます（例：`observation.leader`）．leaderアームのような関節のinputは，関節の位置をそのinputの単位で，関節名（接頭辞なし）を付けて記録します．姿勢のinputは `x`，`y`，`z`，`qx`，`qy`，`qz`，`qw`，`gripper`，`tracking`，`engaged` を記録します |
| `observation.images.<センサー名>` などセンサーのfeature | 各センサーが記録するもの．[Sensors](../sensors/index.md) の各ページを参照 |
| `observation.meta.<ノード名>.valid` / `capture_age_ms` / `ready_age_ms`（float32），`seq` / `capture_ns` / `ready_ns` / `receive_ns`（int64） | 記録するノード（input，フォロワ，センサー）ごとに1組．その行でそのノードのサンプルを使ったか，取得からと使えるようになってからの経過時間（ms），通し番号，取得・使用可能・受信の時刻（単調時計のns） |
| `action` | 各フォロワがその行の区間に送った最初の指令．`observation.state` と同じ並び |
| `action.valid` | 全フォロワが指令を送った行で1 |
| `action.clamped` | どれかのフォロワが制限した行で1 |
| `action.meta.<フォロワ名>.valid` / `clamped` / `seq` / `sent_ns` | フォロワごとの指令の有無，制限，指令の番号，送信時刻 |

`nodes/recorder.yaml` のそのノードの `max_age_ms` より古いサンプルは使いません．その行は `observation.meta.<ノード名>.valid` を0，`seq` を-1にし，featureにはそのノードの直前の有効なサンプルの値を入れます（まだ一度も届いていないときだけ0）．0で埋めると，統計の最小値と平均が0に引かれるためです．input，フォロワ，センサーのどれにも `max_age_ms` の項目が必要です（[Sensors](../sensors/index.md) の「Recorderの設定」）．

指令を送らなかったフォロワの部分は，そのフォロワが保持していた目標（状態の `target`．なければ位置）で埋めます．ゼロで埋めると，学習した方策が0への跳びを覚えるためです．LeRobotの学習は `action.valid` を見ないので，有効な行だけを使う場合は `action.valid` で選んでください．行は，全フォロワの指令がその区間を過ぎたとき，または `grace_ms`（既定500 ms）が過ぎたときに確定します．

同じデータセットに次のエピソードを追記できます．再開時はFPSとfeatureの互換性を検査します．記録するfeatureを変えるオプションには `dataset` を付け，データセットを分けます（「起動オプション」の節）．

### 保存したエピソードの扱い

- 保存のたびに，そのエピソードのファイルを閉じます．`save` が成功を返したエピソードは，そのあとプロセスが強制終了されても読めます．
- そのため，データ・エピソードのメタデータ・動画は1エピソードにつき1ファイルです（LeRobotで `resume` を繰り返したときと同じ配置）．Hubに上げる前にファイルをまとめたい場合は，LeRobotの集約ツールを使います．
- 保存が失敗した場合（ディスクの空きがないなど）は，そのエピソードを破棄し，データセットを保存前の状態に戻します．それまでのエピソードは残り，次のエピソードを記録できます．
- 保存の途中でプロセスが止まった場合は，次にそのデータセットを開いたとき（`run`・`record`，または `check-dataset --recover`）に，書きかけのエピソードを取り除きます．
- 動画の長さがエピソードの行数と合わない場合（画像を書けなかったなど）は，保存の失敗として扱います．
- 対象はプロセスの異常終了です．電源断までは保証しません（LeRobotがファイルをディスクへ同期しないため）．

`meta/roboloom.json` に，データセットを作ったroboloomの版，`action` と `observation.state` の各要素の単位，エピソードを保存した起動ごとのオプションと設定（`meta/roboloom_config/<名前>.json`．ノードの値をそのまま写したもの）を残します．ノードのファイルが指す別のファイル（重力モデル，調整値，校正）は写しません．

`roboloom check-dataset [robot]` は，データセットを読むだけで検査します（[CLI](cli.md)）．壊れているところ（読めないファイル，数の食い違い，動画と行数の不一致）と，学習の前に知っておくべきこと（`valid` が0の行の割合）を表示します．

`recorder.quality` の `max_missing_rate`，`min_action_valid_rate`，`max_interval_ms` で品質警告の閾値を指定できます．保存結果のmetricsとwarningsを確認します．`control_interval_ms` と `action_missing_rate`（指令のなかった行の割合）はフォロワごとで，警告にはフォロワの名前が出ます．

### Image storage

画像センサーのノード YAML に `storage: video | image` を指定します（RealSense、DIGIT、Pika 手首カメラを含む V4L2）。既定は `video` で、従来の非可逆 MP4 です。`image` は可逆 PNG フレームを Parquet に埋め込みます。DIGIT と背景の微小な画素差を使う場合に推奨します。同じデータセット内で混在できます。不正な値は `validate` を含む設定読み込み時に拒否します。

PNG は一般に容量と PNG 圧縮・書き込み負荷が増えます。実際の容量と速度は画像内容と機器に依存します。非圧縮 RGB の参考値は 320×240×3、dataset fps 30 でセンサーあたり 6.9 MB/s（640×480 は 27.6 MB/s）です。PNG の実測値ではありません。LeRobot 0.6.1 の `image` の PNG 圧縮レベルは 6 です。保存形式の変更は feature dtype の変更になるため、別のデータセット `output` を指定してください。以前のスキーマへの追記は拒否します。

ライブ観測は引き続き HWC uint8 RGB です。LeRobot の読み出しは両形式とも既定で CHW float32、範囲 [0, 1] になり、チェックポイントの入力型は `VISUAL` のままです。保存形式は mock・合成フレームのみで試験し、実機では未検証です。


### Video codec

`storage: video` の画像センサーの MP4 の codec は，`nodes/recorder.yaml` の `video_codec` で選びます．ロボットによらず同じです．`storage: image`（PNG），音声，関節などの保存は変わりません．

| `video_codec` | codec | LeRobot のエンコーダー（`vcodec`） |
| --- | --- | --- |
| 指定なし | 新しいデータセットは H.264．追記では保存済みの動画の設定 | `h264` |
| `av1`（別名 `libsvtav1`） | AV1 | `libsvtav1` |
| `h264` | H.264 | `h264`（FFmpeg の libx264） |

既定の H.264 は，再生できる環境が広いので選んでいます．LeRobot 自身の既定は AV1 です．容量を小さくしたいときは `video_codec: av1` にします．

```yaml
# nodes/recorder.yaml
video_codec: av1
```

起動ごとに変えるときは，`load_config`・`Session.launch` の `video_codec`，CLI の `--video-codec` を使います．`None`（CLI では省略）は YAML の指定のままです．

```python
from roboloom import Session, load_config

cfg = load_config("rakuda2", video_codec="h264")
with Session.launch("rakuda2", video_codec="h264") as session:
    ...
```

```bash
roboloom record --task "pick" --seconds 30 --video-codec h264
roboloom validate --video-codec h264   # 要約に video codec: h264
```

- 構成済みの `RobotConfig` を `Session.launch` に渡すときは，`load_config` で選びます．`Session.launch(cfg, video_codec=...)` は（`sensors`・`observe` と同じく）エラーにします．
- ランチャーの Devices の下の「Video codec (storage: video)」で `YAML / dataset`・`AV1`・`H.264` を選べます．選択は前回の選択として保存されます．
- dora のノードは，起動したプロセスと同じ選択で設定を読み直します．
- エンコードは LeRobot が行います．roboloom は `lerobot.configs.video.RGBEncoderConfig(vcodec=...)` を `LeRobotDataset.create`・`resume` に渡すだけです．CRF・GOP・preset は LeRobot の既定（CRF 30，GOP 2）のままで，設定項目はありません．
- 選んだ codec のエンコーダーがこの環境の FFmpeg（PyAV）にないときは，別の codec に切り替えず，起動時（`validate` を含む）に理由を示して止めます．何も記録しません．

**既存のデータセットへの追記**：LeRobot は新しいエピソードの動画を既存の MP4 につなげるので，1つのデータセットの動画は1つの codec にそろえます．`video_codec` を指定しなければ，保存済みの動画の codec と設定（CRF，GOP など）を引き継ぎます．指定した codec が保存済みの動画と違うときは，書き込む前に `video_codec: 'av1' (saved videos) -> 'h264' (requested)` のように差分を示して止めます．別の codec で録るときは，`repo_id` と `output` を変えて別のデータセットにします．roboloom は保存先を自動で分けたり，既存の動画を変換・上書きしたりしません．

| | AV1 | H.264（既定） |
| --- | --- | --- |
| 容量 | 一般に，同じ画質なら H.264 より小さい | 一般に AV1 より大きい |
| 速度 | LeRobot の既定（SVT-AV1 の速い preset）では，下の測定で H.264 と同程度．デコードは H.264 より重いことがある | 速い．多くの機器にハードウェアデコーダーがある |
| 再生互換性 | 新しい再生環境が必要．古い再生ソフト，一部のブラウザ・エディタの動画表示，ハードウェアデコーダーのない機器では再生できないことがある | ほとんどの再生ソフト・ブラウザで再生できる |

このマシンで，合成の 640×480・90 フレーム（30 fps）を記録したときの保存時間はどちらも約 0.9 秒，ファイルは AV1 が 238 KiB，H.264 が 209 KiB でした．1回の測定で，映像の中身と機器で変わります．同じ CRF の値でも codec が違えば画質は同じではありません．

VS Code の LeRobot Viewer で AV1 の動画（以前の既定）が黒く表示されるときは，H.264 の別のデータセットで録って比べてください．H.264 にすると表示されるかは確かめていません．codec の選択は，合成フレームの記録・LeRobot での読み込みと mock の dataflow で試験しました．実機のカメラでは確かめていません．

## ログと設定の管理

ログは設定ファイルの隣の `logs/<データセット名>-<時刻>/` に置きます（例：`logs/rakuda2-digit-20261102-101500/`）．データセット名から，有効だったオプションが分かります．leaderの電流制御は `<leader名>_trace.npz` に，フォロワは毎周期の状態（位置・速度・電流・目標・モード）を `<フォロワ名>_trace.npz` に，ノードの終了時に書きます．YAMLの設定・重力モデル・可動域・調整値・保存した初期姿勢（`poses/<フォロワ名>/`）はGitで管理し，生データ `*.npz`・ログ・dataset・FIFO（`config.fifo`）は生成した `.roboloom/.gitignore` で除外します．

APIの詳細は [Python API](python-api.md)，コマンドは [CLI](cli.md) にあります．

## Webカメラ（開発中）

`sensors.<名前>` の `type: opencv_rgb` には `device`，`width`，`height`，`fps` が必要です．`backend`，`format`，`storage` は任意です．実機では確かめていません．詳細とOSごとの制約は [Webカメラ](../contribution/webcam.md) を参照してください．

## センサー選択

`load_config(..., sensors=[...], observe=[...])` と
`Session.launch(..., sensors=[...], observe=[...])` で起動・記録と policy 観測を
独立に指定します。None は設定の既定、[] は選択なしです。フォロワ状態は常に渡します。
RobotConfig を渡す場合は load_config で選択を確定してください。

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

CLI は `--sensors camera,audio --observe camera`、
空の選択は `--sensors "" --observe ""` です。ランチャーにはセンサー起動と
policy 観測の独立したチェック欄があり、前回の選択を保存します。
未選択センサーの YAML は読み込みません。未起動センサーの観測指定はエラーです。
左右の DIGIT を含め、オプションで追加されるセンサーも個別選択できます。
任意センサーは `{file: nodes/audio.yaml, default: false}` と宣言し、
従来の文字列パスは既定で有効です。オプション適用後に選択を解決します。
observe に含めないセンサーも、起動すれば記録対象になります。
[音声](../sensors/audio.md)も参照してください。
