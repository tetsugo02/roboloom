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
| `policy` | 全フォロワを設定の順に．記録した `action` と `observation.state` が全フォロワをつないだ形なので，方策の出力も同じ形です．出力を並び順に分けて各フォロワへ送ります |

フォロワが複数あるcontrollerは，全フォロワの状態がそろうまで指令を送りません．どれかのフォロワが `FAULT` や `ESTOP` になるか，状態が `follower_timeout_ms` より古くなると，そのcontrollerは全フォロワへの指令を止めます．指令が途切れたフォロワは，保持している目標を保ちます．controllerは，位置を合わせ直すまで次の指令を送りません．`policy` controllerは，フォロワの状態が古くなると，その回のエピソードの方策の実行を止めます．画面のcontrollerの行に，止めた理由（`stopped_by`）と，状態を待っているフォロワ（`waiting_state`）が出ます．

`feedback`（力の逆送）は，フォロワが1台のcontrollerでだけ使えます．

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
    requires: [digit]  # nodes/policy.yaml observes the DIGIT sensors
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

## 記録と再開

`record` extraでLeRobotDataset 0.6.1に保存します．取得・利用可能・受信・指令送信の単調時計時刻を区別して整列し，欠損はゼロ値と有効フラグで表します．`task` はフレームに記録されます．

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

`nodes/recorder.yaml` のそのノードの `max_age_ms` より古いサンプルは使いません．そのfeatureは0で埋め，`observation.meta.<ノード名>.valid` を0，`seq` を-1にします．input，フォロワ，センサーのどれにも `max_age_ms` の項目が必要です（[Sensors](../sensors/index.md) の「Recorderの設定」）．

指令を送らなかったフォロワの部分は，そのフォロワが保持していた目標（状態の `target`．なければ位置）で埋めます．ゼロで埋めると，学習した方策が0への跳びを覚えるためです．LeRobotの学習は `action.valid` を見ないので，有効な行だけを使う場合は `action.valid` で選んでください．行は，全フォロワの指令がその区間を過ぎたとき，または `grace_ms`（既定500 ms）が過ぎたときに確定します．

同じデータセットに次のエピソードを追記できます．再開時はFPSとfeatureの互換性を検査します．記録するfeatureを変えるオプションには `dataset` を付け，データセットを分けます（「起動オプション」の節）．

`recorder.quality` の `max_missing_rate`，`min_action_valid_rate`，`max_interval_ms` で品質警告の閾値を指定できます．保存結果のmetricsとwarningsを確認します．`control_interval_ms` と `action_missing_rate`（指令のなかった行の割合）はフォロワごとで，警告にはフォロワの名前が出ます．

### Image storage

画像センサーのノード YAML に `storage: video | image` を指定します（RealSense、DIGIT、Pika 手首カメラを含む V4L2）。既定は `video` で、従来の非可逆 MP4 です。`image` は可逆 PNG フレームを Parquet に埋め込みます。DIGIT と背景の微小な画素差を使う場合に推奨します。同じデータセット内で混在できます。不正な値は `validate` を含む設定読み込み時に拒否します。

PNG は一般に容量と PNG 圧縮・書き込み負荷が増えます。実際の容量と速度は画像内容と機器に依存します。非圧縮 RGB の参考値は 320×240×3、dataset fps 30 でセンサーあたり 6.9 MB/s（640×480 は 27.6 MB/s）です。PNG の実測値ではありません。LeRobot 0.6.1 の `image` の PNG 圧縮レベルは 6 です。保存形式の変更は feature dtype の変更になるため、別のデータセット `output` を指定してください。以前のスキーマへの追記は拒否します。

ライブ観測は引き続き HWC uint8 RGB です。LeRobot の読み出しは両形式とも既定で CHW float32、範囲 [0, 1] になり、チェックポイントの入力型は `VISUAL` のままです。保存形式は mock・合成フレームのみで試験し、実機では未検証です。


## ログと設定の管理

ログは設定ファイルの隣の `logs/<データセット名>-<時刻>/` に置きます（例：`logs/rakuda2-digit-20261102-101500/`）．データセット名から，有効だったオプションが分かります．leaderの電流制御は `<leader名>_trace.npz` に，フォロワは毎周期の状態（位置・速度・電流・目標・モード）を `<フォロワ名>_trace.npz` に，ノードの終了時に書きます．YAMLの設定・重力モデル・可動域・調整値・保存した初期姿勢（`poses/<フォロワ名>/`）はGitで管理し，生データ `*.npz`・ログ・dataset・FIFO（`config.fifo`）は生成した `.roboloom/.gitignore` で除外します．

APIの詳細は [Python API](python-api.md)，コマンドは [CLI](cli.md) にあります．

## Webカメラ（開発中）

`sensors.<名前>` の `type: opencv_rgb` には `device`，`width`，`height`，`fps` が必要です．`backend`，`format`，`storage` は任意です．実機では確かめていません．詳細とOSごとの制約は [Webカメラ](../contribution/webcam.md) を参照してください．
