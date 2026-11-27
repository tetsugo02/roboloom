# controller（controllers）

`controllers:` のnode YAMLのkeyです．controllerは入力（または方策）をfollowerの指令に変えます．controllerごとの使い方は [Controllers](../../controllers/index.md) を参照してください．

## 共通のkey { #common }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | `joint`，`parts`，`pose_ik`，`policy` か `module:Class` |
| `followers` | 文字列のリスト | 必須 | — | 動かすfollowerのnode名（[followerとcontroller](#followers)） |
| `command_deadline_ms` | 数値 | 必須 | ms | 指令の有効期限．過ぎるとfollowerは保持する |
| `follower_timeout_ms` | 数値 | `150` | ms | followerの状態がこれより古くなると，全followerへの指令を止める |

### followerとcontroller { #followers }

各controllerは `followers:` に，動かすfollowerを並べます．1台のfollowerを動かすcontrollerはちょうど1つです．

| controller | 動かすfollower |
| --- | --- |
| `joint` | ちょうど1台（leaderの関節を1台のfollowerの関節へ対応させる） |
| `pose_ik` | 腕1台と，任意でgripper 1台（手に持った機器の姿勢をIKで腕の関節へ） |
| `parts` | ちょうど1台．内側のcontrollerがそれぞれ一部の関節を動かす |
| `policy` | 全followerを設定の順に．記録した `action` と `observation.state` が全followerをつないだ形なので，方策の出力も同じ形です．出力を並び順に分けて各followerへ送ります |

followerが複数あるcontrollerは，全followerの状態がそろうまで指令を送りません．どれかのfollowerが `FAULT` や `ESTOP` になるか，状態が `follower_timeout_ms` より古くなると，そのcontrollerは全followerへの指令を止めます．指令が途切れたfollowerは，保持している目標を保ちます．controllerは，位置を合わせ直すまで次の指令を送りません．`policy` controllerは，followerの状態が古くなると，その回のepisodeの方策の実行を止めます．画面のcontrollerの行に，止めた理由（`stopped_by`）と，状態を待っているfollower（`waiting_state`）が出ます．

## joint { #joint }

leaderの関節を1台のfollowerの関節へ対応させます．入力は関節の入力（`rakuda_mini` など）です．始めに位置を合わせ（leaderとfollowerの差が `alignment_tolerance` 以内になるまで待つ），そのあと速さを制限して追従します．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `input` | 文字列 | 必須 | — | 入力のnode名 |
| `alignment_tolerance` | 数値 | 必須 | followerの単位 | 追従を始める前と，episodeを始めるたびに許すleaderとfollowerの差．`joints` の関節ごとにも書ける |
| `max_speed` | 数値 | 必須 | followerの単位/s | 遠隔操作の目標を1周期に動かせる幅（[単位](index.md#units)） |
| `input_timeout_ms` | 数値 | 必須 | ms | 入力がこれより古くなると指令を止める |
| `unit` | 文字列 | — | — | 書くなら入力とfollowerの単位．全関節に `scale` があれば入力の単位は違ってよい |
| `joints` | リスト | 同じ名前の関節どうし | — | 関節の対応（[下記](#joint-map)） |
| `couplings` | リスト | `[]` | — | 他の関節の変位を目標に足す（[下記](#couplings)） |
| `home` | mapping | — | — | 保存した姿勢（[home](control.md#home)） |
| `feedback` | mapping | — | — | 力の逆送（[下記](#feedback)） <span class="status status--mock">模擬のみ</span> |

### 関節の対応（joints） { #joint-map }

入力がfollowerと同じ関節名と単位を持つ（Rakuda-miniとRakuda2）なら，書かなくてよく，各follower関節は同じ名前の入力関節に従います．名前，向き，ずれが違うときは，followerの関節の順に1関節1項目で書きます．`follower = sign × scale × leader + offset` です．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `leader` | 文字列 | 必須 | — | 入力の関節名 |
| `follower` | 文字列 | 必須 | — | followerの関節名（followerの順） |
| `sign` | `1` か `-1` | 必須 | — | 向き |
| `offset` | 数値 | 必須 | followerの単位 | ずれ |
| `scale` | 正の数 | `1.0` | followerの単位/入力の単位 | 歯車比や単位の違い．`feedback` とは併用できない |
| `alignment_tolerance` | 正の数 | controllerの値 | followerの単位 | この関節だけの，最初の位置合わせと毎回の開始前の許容差．物を持つgripperに使う：gripperは物に当たって止まり，強く握ったleaderまで閉じられないため，controllerの値では `start` を拒否される．policyのteleopへの引き継ぎではcontrollerの値を使う <span class="status status--mock">模擬のみ</span> |

### 関節の相殺（couplings） { #couplings }

`couplings` は，他のfollower関節の `reference` からの実測変位を，対応させたあとの目標に足します（速度の制限の前）．胴体を回したときに頭のcameraの向きを保つ，といった使い方です．leaderの `control`（関節の固定など）とは独立した設定です．[Leaderの設定例](../../controllers/leader.md) を参照してください．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `joint` | 文字列 | 必須 | — | 目標に足すfollower関節．重複できない |
| `source` | 文字列 | 必須 | — | 変位を測るfollower関節（`joint` と別） |
| `scale` | 数値 | 必須 | — | 変位に掛ける係数 |
| `reference` | 数値 | 必須 | followerの単位 | 何も足さない `source` の位置 |
| `lead_ms` | 数値 | `0` | ms | `source` の速度×この時間だけ先を見る（`joint` の位置制御の遅れの補い）．0〜500 |

```yaml
# nodes/controller.yaml
type: joint
input: leader
followers: [follower]
alignment_tolerance: 300
max_speed: 2048
command_deadline_ms: 100
input_timeout_ms: 150
couplings:
- {joint: head_yaw, source: torso_yaw, scale: -1.0, reference: 2048, lead_ms: 70}
```

## parts <span class="status status--mock">模擬のみ</span> { #parts }

`type: parts` のcontrollerを使うと，Rakuda2（1本のbusに17関節）のように関節の多いfollowerを，複数の入力で，それぞれ別の関節について動かせます．腕ごとに手持ちのdeviceを使う，片腕だけleaderで動かす，といった構成です．followerが受け取る指令は，今までどおり1つのcontrollerからの1本です．安全の検査，記録する `action`，datasetは変わりません．確かめたのは模擬のdeviceだけです．

followerは自分の部分に名前を付けます（[followerの `parts`](followers.md#parts)）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `parts` | pathのリスト | 必須 | — | 内側のcontrollerのfile．このfileのdirectoryが基準．名前はfile名（拡張子なし） |
| `input_timeout_ms` | 数値 | `150` | ms | 入力がこれより古くなると指令を止める |

```yaml
# nodes/controller.yaml
type: parts
followers: [follower]
command_deadline_ms: 100
parts: [right_hand.yaml, left_hand.yaml]   # このfileの隣のcontrollerのfile
```

```yaml
# nodes/right_hand.yaml：controllerの種類は自由．followers は部分（<follower>.<部分>）
type: joint
input: leader
followers: [follower.right_arm]
alignment_tolerance: 300
max_speed: 2048
command_deadline_ms: 100
input_timeout_ms: 150
```

- 内側のcontrollerは，自分の部分を1台のfollowerとして扱います（単位と周期は同じ，可動域はその関節のもの）．それぞれ自分の入力に追従します．同じ入力に複数の内側のcontrollerが追従しても構いません．
- 1つの関節を動かせる内側のcontrollerは1つまでです．どの部分も動かさない関節は，followerが保持している位置に留まります．
- followerへの指令は全関節の1本なので，ある入力の指令には，ほかの部分の目標も入ります．入れるのは，その部分の目標がまだ有効な間だけです（指令してから内側のcontrollerの `command_deadline_ms` 以内で，そのcontrollerがそのあと指令を止めていないこと）．入力が止まった部分，手を離した部分，IKが届かなかった部分には，followerが保持している目標を入れます．古い目標へ動き続けることはありません．
- followerが `FAULT` か `ESTOP` になると，すべての部分が揃え直してから指令を再開します．
- 内側のcontrollerには，まだ `home` と `feedback` を書けません．partsのcontrollerを方策の `teleop:` に使うこともできません．
- controllerの行は，どれかの部分が指令を送っていれば `following` です．`parts` に内側のcontrollerごとの状態が出ます．

## pose_ik <span class="status status--dev">開発中</span> { #pose-ik }

手に持った機器の姿勢を，IKで腕の関節に変えます．入力は姿勢の入力（`pika_sense`）です．操作者がclutchを入れた時点の入力の姿勢と腕の先端の姿勢を基準に，そこからの手の動きを先端の動きにします（相対の対応）．使い方は [Pika SenseとIK](../../controllers/pose-ik.md) を参照してください．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `input` | 文字列 | 必須 | — | 姿勢の入力のnode名 |
| `arm` | 文字列 | 必須 | — | IKを解く腕のfollower（または部分）．運動学のmodelが必要 |
| `gripper` | 文字列 | — | — | 顎の開きで動かす1関節のfollower（または部分） |
| `tool_offset` | `{xyz, rpy}` | flange | m，rad | flangeから見た工具の座標系 |
| `workspace` | `{min, max}` | なし | m | 腕の土台の座標系での目標の範囲．外れると指令しない．省略すると関節の範囲とIKだけで制限する |
| `max_input_jump` | `{position_m, rotation_rad}` | 必須 | m，rad | 1 sampleでこれより跳んだ入力は，見失ったとみなして操作を止める |
| `ik` | mapping | 下の表 | — | IKの設定 |
| `gripper_map` | `{scale, offset}` | `{scale: 1.0, offset: 0.0}` | — | gripper = `scale` × 顎の角度 + `offset` |
| `max_speed` | `{follower: value}` | 必須 | followerの単位/s | followerごとの速さの上限 |
| `input_timeout_ms` | 数値 | 必須 | ms | 入力がこれより古くなると操作を止める |
| `home` | `{follower: home}` | — | — | 保存した姿勢（[home](control.md#home)） |

| `ik` のkey | 既定値 | 単位 |
| --- | --- | --- |
| `iterations` | `30` | 回 |
| `damping` | `0.001` | — |
| `position_tolerance_m` | `0.005` | m |
| `rotation_tolerance_rad` | `0.05` | rad |

## policy { #policy }

学習した方策がcontrollerになります．全followerを設定の順に動かし（[followerとcontroller](#followers)），入力は持ちません．keyは [方策のcontroller](policy.md) にまとめています．

## 力の逆送（feedback） <span class="status status--mock">模擬のみ</span> { #feedback }

!!! warning "実機では未検証"
    followerが受けた外力をleaderへ返す経路です．模擬（mock）の試験だけを通しています．設計と今後の段階は [bilateral制御の設計](../../contribution/bilateral.md) を参照してください．

設定に `estimators` を足し（[推定器](#estimators)），controllerの `feedback` で推定器を参照します．templateでは，option `bilateral` が `estimators.effort` を追加し，leader・controller・followerを逆送用のnode fileに置き換えます．辺は書きません．各nodeの参照から次の経路を導きます．

```text
leader ──sample──► controller ──command──► follower ──state──► estimator
  ▲                    │  ▲                                  │
  └──── feedback ──────┘  └────────────── estimate ──────────┘
```

`feedback` は，followerが1台の `joint` controllerでだけ使えます．`scale` のある関節の対応とは併用できません．leader側の設定は [control の `feedback`](control.md#feedback) です．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `estimator` | 文字列 | 必須 | — | 推定器のnode名 |
| `deadline_ms` | 数値 | 必須 | ms | 推定の元になったfollowerの状態の時刻からの期限 |
| `unit` | 文字列 | 必須 | — | `<leaderの単位>/<推定器の単位>`（例：`mA/mA`） |
| `gain` | `{follower joint: gain}` | 必須 | — | 逆送する関節と係数（0以上） |

```yaml
feedback:
  estimator: effort
  deadline_ms: 100
  unit: mA/mA          # leaderの単位 / 推定器の単位
  gain:                # followerの関節名 → 係数（0以上）
    r_arm_el_yaw: 0.1
```

leaderへの電流は `−gain × sign × 残差` です（`sign` は `joints` の対応の符号）．controllerは，推定が有効で接触中，followerが `ACTIVE`，controllerが `following` のときだけ，適用の希望（gate）を立てます．期限は，推定の元になったfollowerの状態の時刻から `deadline_ms` です．推定が遅れて届き，その時点で期限を過ぎていれば送らず，controllerのstatusの `feedback_error` に理由を出します．leaderは，`feedback:` を書いた電流制御のgroup（`gravity_comp`，`impedance`）の関節だけで受け取ります．

読み込み時に，参照先の存在，推定器とcontrollerのfollowerの一致，単位，leader側の受け入れを確かめます．合わない設定は起動前に拒否されます．`couplings` の対象の関節にも，`joints` の対応どおりに返します．Python API（`InProcessSession`）は推定器を扱いません．

## 推定器（estimators） <span class="status status--mock">模擬のみ</span> { #estimators }

`estimators:` は最上位の役割の1つです．推定器は，followerが申告する力の量（Rakuda2は `currents_mA`，単位mA）から，関節ごとの残差（実測 − 自由運動での予測）を出します．外力は残差と逆向きにかかります．

```yaml
estimators:
  effort: nodes/effort.yaml
```

推定器（`nodes/effort.yaml`）：

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | `none`（常に推定なし．経路の確認用）または `model_residual` |
| `follower` | 文字列 | 必須 | — | 状態を読むfollowerのnode名 |
| `joints` | 文字列のリスト | 必須 | — | 推定するfollower関節 |
| `models` | pathのリスト | 必須（`model_residual`） | — | `model_residual` の重力model（腕ごと）．出力関節を合わせると `joints` とちょうど一致すること |
| `smoothing_alpha` | 数値 | `1.0` | — | 指数移動平均の係数（0より大きく1以下．1＝平滑化なし） |
| `contact_on` | 数値 | `0` | 推定器の単位 | 残差のL1 normがこれ以上で接触とみなす |
| `contact_off` | 数値 | `0` | 推定器の単位 | 接触中は，これを下回ると接触でなくなる（hysteresis）．`contact_off` ≤ `contact_on`．どちらも0なら常に接触 |
| `record` | 真偽値 | `false` | — | `true` で推定をdatasetに記録する．`recorder.max_age_ms` にこの推定器の名前が必要 |

`model_residual` は `残差 = 実測電流 − g(q)` です．`g(q)` はfollowerで同定した重力modelで，学習は要りません．摩擦・慣性・位置の追従誤差は残差に残るので，自由に動かしているときも0になりません．推定器nodeのstatusの `residual_l1`（接触の判定と比べる値）を，自由に動かしたときと押したときで見て，`contact_on` をその間に置きます．重力modelは，leaderと同じ `identify-gravity` で，followerのcalibration（`calibration/follower_<side>.yaml`）から作ります．

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/follower_right.yaml
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/follower_right.yaml \
    --out .roboloom/rakuda2/calibration/effort_gravity_right.yaml --collect
```

followerの腕は，XM540とXM430が混在するため関節ごとに別々に同定します（`shared_parameters: false`）．leaderより多くの姿勢が要ります．同定中はfollowerのnodeを止めておきます．

`record: true` の推定器は，`observation.effort_ext`（外力＝−残差，推定器の単位），`observation.effort_ext.valid`，`observation.contact` を記録します．推定がないframeは0です．記録する推定器が複数あるときは，設定の順につなげます．`names` は `observation.effort_ext` が `<follower>.<joint>`，ほかの2つが推定器の名前です．単位の違う推定器は1本のvectorにできないので，読み込み時に拒否します．
