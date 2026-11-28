# Leader

!!! note "状態：実機検証済み"
    <span class="status status--verified">実機検証済み</span> Rakuda2のleader（通常と重力補償付き）による収集は実機で確かめています．関節の固定（`law: position`），関節間の相殺（`couplings`）とその組み合わせは <span class="status status--mock">模擬のみ</span> です．力の逆送は <span class="status status--mock">模擬のみ</span>（中断中）です．

Rakuda2の遠隔操作では，`inputs` の `leader` node（機器は `type: rakuda_mini`，Rakuda-mini）が関節位置を読み，`controllers` の `joint` nodeがfollowerの目標へ変換します．leaderはfollowerと同じ関節名と単位を持つので，followerの各関節は同じ名前のleaderの関節に追従します．ほかに書くことはありません．

```yaml
type: joint
input: leader
followers: [follower]
alignment_tolerance: 300
max_speed: 2048
command_deadline_ms: 100
input_timeout_ms: 150
```

`leader` は設定の中での役割の名前で，`type` は使う機器の名前です．別のarmをleaderに使う場合は，`type` だけを変えます．

これらは配布templateの値です．機体の可動域・通信周期・停止挙動を確かめた上で設定してください．

| 項目 | 意味 |
| --- | --- |
| `alignment_tolerance` | 追従を始める前と，毎回のepisode開始（`start`）の前に許すleaderとfollowerの関節差（counts）．超えていると `start` を拒否します．`joints` の項目ごとにも書けます（物を持つと強く握ったleaderまで閉じられないgripperに `alignment_tolerance: 1000` など） <span class="status status--mock">模擬のみ</span> |
| `joints` | 任意．書かなければ，followerの各関節は同じ名前の入力の関節に追従する（入力がfollowerの関節をすべて持つこと）．書くときは，followerの関節ごとに `{leader, follower, sign, offset}` を，followerの順に並べる．名前が違う，向きが逆（`sign: -1`），ずれがある（目標＝leader × sign ＋ offset）場合に使う．減速比や単位がfollowerと違うleader（countで読むGELLO型のleaderと，radの腕など）は，各関節に `scale`（正の数）を足す：目標＝sign × scale × leader ＋ offset．全関節に `scale` を書けば，入力とfollowerの単位は違ってよい（`offset`，`max_speed`，`alignment_tolerance` はfollowerの単位）．力の逆送（`feedback`）とは併用できない |
| `unit` | 任意．入力とfollowerの単位は同じでなければならない（Rakuda2は `dynamixel_count`）．書いた場合は両方と一致させる |
| `max_speed` | 目標値の変化速度の上限（followerの単位/s．Rakuda2はcounts/s） |
| `followers` | 動かすfollower．`joint` controllerはちょうど1台です |
| `command_deadline_ms` | followerへ送る指令の有効期限 |
| `input_timeout_ms` | leader入力が古いと判定するまでの時間 |
| `follower_timeout_ms` | followerの状態が古いと判定するまでの時間（既定150）．古くなると追従をやめ，位置を合わせ直すまで指令を送りません |

画面で `aligning` が出たら，表示された関節差を見ながらleaderをfollowerに揃えます．`following` になってから `start <task>` します．入力が古いと `input_stale` となり，新しい入力なしに追従を続けません．

leaderのtriggerは `law: spring`，重力補償は `law: gravity_comp` で設定します．これらはleader node自身が実行するmotor制御則です．実機では `Session` / CLIのdataflowで動かします．`InProcessSession.from_yaml()` は制御則を実行するleaderを受け付けません．

具体的なsetupは [Rakuda2 Quick start](../tutorials/rakuda2/setup.md) にあります．

## 対応する機体 { #supported-robots }

| 機体 | 入力 | 状態 | 設定例 |
| --- | --- | --- | --- |
| Rakuda2 | Rakuda-mini（`rakuda_mini`） | <span class="status status--verified">実機検証済み</span> | [Rakuda2のcontroller](../robots/rakuda2/controllers.md#leader) |

## leaderの関節を固定する

使用する `nodes/leader.yaml` または `nodes/leader_gravity.yaml` を土台にしたfile（[`extends`](../reference/configuration/index.md#extends)）を作るか，そのfile自体の `control` で，固定する関節を `law: position` のgroupへ移します．例えば，templateの `body` groupを次の2 groupに置き換えると，腰は手で動かせ，首のyawとpitchは固定されます．腕とtriggerのgroupは残してください．既存の設定で胴体・頭部が `hand` に含まれる場合は，この3関節を `hand` から取り除きます．全関節がちょうど1 groupに含まれる必要があります．

```yaml
control:
  - group: body
    law: free
    joints: [torso_yaw]
  - group: fixed_head
    law: position
    joints: [head_yaw, head_pitch]
  # 腕とtriggerの既存groupを続けます．
```

`position` は通電直前の実測位置を目標として書いてから，選択した関節だけtorqueをオンにします．古いGoal Positionへ移動させる処理ではありません．leaderは外部目標を受けないため，その位置を保持します．固定はSessionの起動時から有効で，`stop` で収集を止めても続き，`estop`・`release`・`quit` で脱力します．起動前に，固定するleader関節をfollowerの姿勢へ揃えてください．

motorの位置制御と対応bus APIが必要です．Operating Modeは `position`（Rakuda2では3）を読み返して検査し，不一致では通電しません．変更が必要な場合はdataflowを止め，機体を支持した上で既存の `roboloom commission leader` を使います（起動optionでleaderを選ぶ場合は `--with` も指定します）．`nodes/follower.yaml` の `torque: false` はleaderの固定を無効にしません．

## 関節間の相殺を設定する

`nodes/controller.yaml` の `couplings` は，関節対応・符号・offsetで変換した目標へ，followerの別関節の**実測変位**を加えます．既定は `[]`（無効）です．Rakuda2の腰yawと首yawで，同じcount変化が同じ向きの回転を表す場合は次の設定になります．

```yaml
couplings:
  - joint: head_yaw
    source: torso_yaw
    scale: -1.0
    reference: 2048
    lead_ms: 70
```

```text
首の目標 = leaderから変換した首の目標
         - (followerの現在の腰位置 + 腰の速度 × lead_ms - reference)
```

`reference` は，leaderから変換した首の目標をそのまま使う腰の位置（counts）です．腰が正面を向く位置を設定します．例えば腰が `reference` から+100 counts回転すると，首の目標に-100 countsを加えます．上の関節固定と併用すると，leaderの首を固定したまま腰の回転を相殺できます．leaderの首を自由にすると，操作者による首の操作に相殺分が加わります．

- `joint` と `source` はfollowerの関節名です．同じ関節の指定，未知の関節，重複した `joint`，有限値でない `scale` は設定読み込み時に拒否します．
- 基準は設定した固定値です．位置合わせの時点の姿勢は使いません．位置合わせは許容差（`alignment_tolerance`）内のずれを認めるため，その時点の姿勢を基準にすると，ずれの分だけ首が常に偏ります．再位置合わせやleader nodeの再起動でも基準は変わりません．
- 位置合わせでは相殺後の首の目標とfollowerの首を比べます．followerのcameraが正面から大きく外れた状態で起動すると，`head_yaw` が許容差を超えて `aligning` のままになります．起動前にfollowerのcamera向きとleaderの首を揃えてください．
- 腰の目標値ではなく実測値を使うため，腰が指令に追いついていない段階で首だけを先回りさせません．相殺後にも既存の速度制限とfollower側の範囲・期限・変化量検査がかかります．
- `joint`・`source`・`scale`・`reference` はすべて必須です．
- `lead_ms`（任意，既定0，0〜500）は，腰の実測速度の方向へ目標を先読みする時間です．首のmotorは位置制御で目標に遅れて追従するため，腰が動いている間はcameraが遅れてずれます．Rakuda2では，腰を最大69°/sで回したときのずれ（最大4.6°）が，腰の速度×約70 msでほぼ説明できました（相関0.99，2026-10-27の記録）．このため例では70としています．大きすぎると首が行き過ぎます．robotが速度を出さない場合，先読みは加えません．
- これは指定した関節間の線形な相殺です．全姿勢のcamera安定化，IMU feedback，台座の回転補償ではありません．軸が平行で，符号と単位比が正しいことが前提です．他の機体では `scale` に軸の符号と単位比を設定します．速度制限や可動域端，追従遅れではcameraの向きに誤差が残ります．
- `type: joint` の遠隔操作に適用します．方策controllerの出力には適用しません．関節名をcodeに固定していないので，他のrobotのjoint controllerにも使えます．

関節固定と相殺の組み合わせは模擬bus・controllerで検証しています．実機での方向・可動域・追従精度は未検証です．既存の `.roboloom/` は自動更新しないため，設定例を使用中のYAMLへ反映してください．

## 初期姿勢へ動かす（home）

保存した初期姿勢へ，leaderとfollowerを `home` の操作でゆっくり動かせます．episodeを毎回同じ姿勢から始めるためのものです．着いてから1秒後，leaderは通常の制御（重力補償とbreakaway hold）に戻るので，そのまま手で持って操作を始められます．すべてのcontrollerが操作者の入力に従う構成では，[episodeの外でのteleop](index.md#teleop)（`t`，<span class="status status--mock">Mock only</span>）で，そこから記録せずに腕を動かせます．

**1. 姿勢を保存します．** followerを使いたい姿勢にしてから，dataflowを止めた状態で実行します．名前ごとに `poses/<follower>/<name>.yaml` が作られ，いくつでも保存できます．同じ名前は `--force` なしでは上書きしません．fileには保存したfollowerの名前が入り，別のfollowerでは読み込めません（左腕の姿勢を右腕で使う事故を防ぐため）．followerが複数ある設定では，`capture-pose left ready` のようにfollowerを指定します．

```bash
uv run roboloom capture-pose ready
```

followerを姿勢にするには，遠隔操作（teleop `t`，記録なし）で動かしてから `quit` で `hold`（followerを保持したまま終了）とするか，`release` 後に手で動かします．`capture-pose` はfollowerの位置を読むだけで，動かしません．busを開くときの通常の起動時の検査は行います．

**2. controllerのYAMLで使う姿勢を選びます．**

```yaml
home:
  pose: ../poses/follower/ready.yaml   # 保存した姿勢のどれか
  max_speed: 200              # counts/s（約18°/s）．遅く動かすための上限
  tolerance: 30               # 各関節がこの差以内なら到着（必須．followerの単位）
  timeout_s: 30
```

重力補償leaderの電流制御のgroupには，姿勢へ引くばねの設定が必要です．なければ設定の読み込み時に拒否します．

```yaml
- group: right_arm
  law: gravity_comp
  # ...
  homing:
    kp_mA_per_count: 0.5      # 目標との差1 countあたりの電流
    max_mA: 40                # ばねの電流の上限．重力補償との合計は max_current_mA で制限
```

**3. 動かします．** 操作画面で `home` と入力します（`roboloom session home`，Pythonでは `Session.home()` も同じ）．controllerの行に `home pose: ready.yaml` と，使う姿勢の名前が表示されます．移動中はrobotとleaderの行に進み具合が出て，到着すると `reached` になります．

- 全関節が同じ時間で到着するよう，滑らかな速度の曲線で動かします．最も遠い関節でも速さは `max_speed` を超えません．
- followerは，通常の指令と同じ範囲と速度の検査を通して動きます．`stop`・`estop` で移動を止められます．
- leaderの動かし方は関節の制御則で変わります．
  - 電流制御（`gravity_comp`）：重力補償に，`homing` のばね（上限つき）を足して引きます．
  - 位置制御（固定した首など）：目標を姿勢に沿って動かします．移動後は固定の目標がその姿勢になります．
  - `free`：motorが位置制御のmodeのときだけ，移動中にtorqueを入れて動かし，到着後に脱力へ戻します．それ以外は動かさず，画面に表示します．
  - triggerのばね：動かしません．
- 電流制御の関節は，静止摩擦のためにばねが姿勢の手前で止まることがあります．許容差（`tolerance`）より離れた関節は，到着後に `short`（黄）として差（counts）を表示します．開始できるかは，通常の位置合わせの検査（`alignment_tolerance`）で決まります．差が大きい場合は `kp_mA_per_count` か `max_mA` を上げます．
- followerは，移動が終わったあと，測った関節がすべて `tolerance` 以内に入ると `reached` になります．入るまでは `settling` です．2秒たっても入らない関節があれば `short`（赤）として関節名と差を表示し，`Session.home()`（`record --home` を含む）は失敗し，`start` も拒否します．重さで垂れる関節は，支えるか `tolerance` を見直してから，もう一度 `home` を実行します．
- leaderの目標は，controllerの関節対応（符号・offset）と `couplings` を逆にたどって計算します．到着後のleaderとfollowerの差はほぼ0です．
- 録画中や追従中（`start` 後）は `home` を拒否し，移動中は `start` を拒否します．
- 移動中は腕から手を離してください．`estop`・`release`・`quit` では今までどおりleaderが脱力します．

模擬のbusとdataflowで動作を確かめています．実機での動きは未検証です．

## 力の逆送を受ける（実機未検証）

電流制御のgroup（`gravity_comp`，`impedance`）に `feedback:` を書くと，そのgroupの関節は，controllerが返すfollowerの外力を電流として受け取ります．実機では確かめていません．

```yaml
- group: right_arm
  law: gravity_comp
  # ... 既存の gravity_model, tuning, range など
  feedback:
    max_mA: 20
    ramp_s: 0.3
    kd: 0.0
```

どの関節に返すかは，controllerの `feedback.gain` で選びます．逆送は重力補償などの出力に足してから `max_current_mA` で制限し，gateは `ramp_s` かけて開閉します．estop・release・quitでは即座に0になります．keyの意味と安全の仕組みは [設定](../reference/configuration/index.md) の「力の逆送」，Rakuda2での組み合わせは [Rakuda2](../robots/rakuda2/index.md) の「bilateral」を参照してください．
