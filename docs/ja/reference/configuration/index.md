# 設定

roboloomの設定は，機体ごとの設定ファイル `config.yaml` と，そこから参照するノードYAMLでできています．このページはファイルの配置，最上位のキー，単位，継承，起動オプション，実験ファイルをまとめます．ノードの種類ごとのキーは次のページにあります．機能の状態ラベル（実機検証済み，模擬のみ，開発中，設計のみ）は [状態ラベル](../status-labels.md) を参照してください．

| ページ | 中身 |
| --- | --- |
| [フォロワ](followers.md) | `followers:` の共通のキー，機種ごとのキー，脱力したときの性質，制御周期 |
| [入力](inputs.md) | `inputs:`（leaderアーム，Pika Sense）と `trackers:` |
| [controller](controllers.md) | `controllers:` の `joint`，`parts`，`pose_ik`，`policy`，力の逆送と推定器 |
| [方策のcontroller](policy.md) | `type: policy` のキー |
| [センサー](sensors.md) | `sensors:` のキー，画像の保存形式，センサーの選択 |
| [recorder と session](recorder.md) | `recorder:`，品質の警告，動画のcodec，`session:` |
| [制御則](control.md) | `control:` の制御則ごとのキー，`limits`，`home` |

## ファイルの配置 { #layout }

`roboloom init rakuda2` が `.roboloom/rakuda2/` に設定・ノード・calibration YAMLを作ります．既存のディレクトリは上書きしません．新しい版のテンプレートに追いつかせるときは `roboloom init rakuda2 --update` を使います（プロジェクトにないファイルを足し，触っていないファイルを置き換え，編集したファイルにはテンプレートだけにあるキーとオプションを一覧にします．[CLI](../cli.md#init)）．

```text
.roboloom/
  .gitignore              # 生データ・ログ・datasetを除外する（生成）
  rakuda2/
    config.yaml           # 設定（機体ごとに1つ）
    mock.yaml             # SET_ の代用値（模擬のデバイスのときだけ使う）
    README.md             # 測定の手順
    nodes/                # ノードYAML（機能ごとに分ける）
    calibration/          # 校正，重力モデル，可動域，調整値
    poses/<follower>/     # 保存した姿勢（roboloom capture-pose）
    logs/                 # ログ（Gitの外）
    datasets/             # 既定の保存先（Gitの外）
configs/roboloom/<name>.yaml   # 実験ファイル（プロジェクトのルート）
```

設定は機体ごとに1つ（`config.yaml`）で，機能の組み合わせは [起動オプション](#launch-options) で選びます．機体名 `rakuda2` は `.roboloom/rakuda2/config.yaml` を指します．`.roboloom/` の下に機体が1台だけなら省略でき，ファイルパスでも指定できます．

## 設定YAML { #config-yaml }

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
  audio: {file: nodes/audio.yaml, default: false}
  camera: nodes/camera.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
options:
  # 次の節を参照
```

ノードYAMLのパスと `output` は設定ファイルのディレクトリが基準です．オプションを有効にしない場合，上の保存先は `.roboloom/rakuda2/datasets/rakuda2` です．ロボットの名前は設定のディレクトリ名（`.roboloom/rakuda2/` なら `rakuda2`）で，データセットの `robot_type` にも使います．

### 最上位のキー { #top-level-keys }

最上位に書けるキーは次の表だけです．それ以外のキーは読み込み時に拒否します．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `repo_id` | 文字列 | 必須 | — | データセットの `namespace/name`．有効なオプションの `dataset` が末尾に付く |
| `output` | パス | 必須 | — | データセットの保存先．オプションの `dataset` が末尾に付く |
| `dataset_fps` | 数値 | 必須 | Hz | データセットの行の周期．各フォロワの `control_hz` 以下 |
| `mode` | 文字列 | `hardware` | — | `hardware` か `mock`．CLIの `--mock` とPython APIの `mock=` が優先する |
| `trackers` | `{名前: パス}` | `{}` | — | 追跡システム（[入力](inputs.md#trackers)） |
| `inputs` | `{名前: パス}` | `{}` | — | 入力機器（[入力](inputs.md)） |
| `controllers` | `{名前: パス}` | `{}` | — | controller（[controller](controllers.md)） |
| `followers` | `{名前: パス}` | `{}` | — | フォロワ（[フォロワ](followers.md)） |
| `sensors` | `{名前: パス か {file, default}}` | `{}` | — | センサー．`{file, default: false}` は既定で起動しない（[センサーの選択](sensors.md#sensor-selection)） |
| `estimators` | `{名前: パス}` | `{}` | — | 推定器（[controller](controllers.md#estimators)） <span class="status status--mock">模擬のみ</span> |
| `recorder` | パス | 必須 | — | [recorder](recorder.md#recorder) のノードYAML |
| `session` | パス | 必須 | — | [session](recorder.md#session) のノードYAML |
| `options` | マッピング | `{}` | — | [起動オプション](#launch-options) |

`followers` には，指令を受けて動く装置（腕，グリッパなど）を並べます．1つの設定に複数のフォロワを置けます．各フォロワには，それを動かすcontrollerがちょうど1つ必要です（[フォロワとcontroller](controllers.md#followers)）．`followers: {}` としてフォロワを置かない構成は，入力とセンサーを記録するだけで，`action` を記録しません．このときcontrollerは置けず，入力とセンサーは自分の周期（`poll_hz`，`fps`）を持つ必要があります（[Pika Senseを手に持った収集](../../tutorials/pika-handheld.md)，開発中）．

### ノード名 { #node-names }

ノード名はdoraのIDとデータセットのfeature名に使われます．役割をまたいで重複できません．英数字，`-`，`_` だけを使います．`recorder`，`session`，`action`，`tick` と，`action_` で始まる名前，`_status` で終わる名前は，dataflowが使うので付けられません．

### typeと未知のキー { #type }

各ノードの `type` が実装を選びます．roboloomの型の名前（`rakuda2_follower` など）か，自分のクラスへの参照 `module:Class` を書きます（[自分のパッケージから足す](../../contribution/index.md#own-types)）．ノードが読まないキーは，読み込みのときに拒否します（綴りを誤ったキーが黙って無視され，既定値が使われるのを防ぎます．例：`followers.follower: unknown keys torqe (did you mean torque?)`）．`control` のグループも，その制御則が読むキーだけを受け付けます．

### 未設定の値（SET_）と模擬 { #placeholders }

`SET_...` は機体固有の未設定値で，参照する設定に残っていると実行が拒否されます．`--mock` を付けると，`SET_...` を埋める前でも検証と実行ができます（模擬デバイスのときだけ，プロジェクトの `mock.yaml` にある代用値を使います．ファイルの `SET_...` はそのままで，実機では今までどおり拒否します）．`validate` は設定とdataflowの整合性を調べ，デバイスは開きません．EEPROMの実機との一致，画像取得，停止挙動までは確認しません．

## 単位 { #units }

関節の位置の単位は，フォロワとleader（`inputs`）がそれぞれ宣言します．既定値はありません．Rakuda2は `dynamixel_count` です．controllerの `unit` は，書くならleaderとフォロワの単位と一致させます（`joint` controllerは，全関節に `scale` があれば入力の単位が違ってよい．[関節の対応](controllers.md#joint-map)）．指令にも単位が入り，フォロワは自分の単位と違う指令を受け取りません．

速度の上限 `max_speed` は次の場所にあり，どれもフォロワの単位/sです．

| 場所 | 役割 |
| --- | --- |
| フォロワの `limits` の `max_speed`（関節ごと） | フォロワの安全の検査．これを超える目標は削られる．最後の砦なので，controllerの値より大きくする（[limits](control.md#limits)） |
| `joint` controllerの `max_speed` | 遠隔操作の目標を1周期に動かせる幅 |
| `policy` controllerと `pose_ik` controllerの `max_speed` | 目標を1周期に動かせる幅．フォロワごとに `{フォロワ名: 値}` で書く（単位がフォロワごとに違うため） |
| controllerの `home.max_speed` | 保存した姿勢へ動くときの速さ．controllerの `max_speed` 以下（[home](control.md#home)） |

`home.tolerance`（到着とみなす差）も，フォロワの単位で必ず書きます．

## ノードファイルの継承（extends） { #extends }

機能の組み合わせごとにノードファイルを写すと，ポートや測定値を直すたびに全部を直すことになります．土台のファイルを1つ決め，ほかのファイルは `extends` で土台を指して，違うところだけを書きます．

```yaml
# nodes/leader_gravity.yaml
extends: leader.yaml                  # 土台．同じディレクトリのノードファイル
without: [registers.operating_mode]   # 土台から外すキー（点区切り）．任意
registers:
  current_limit: {r_arm_sh_pitch1: 150}   # 足す・上書きするものだけ
control:
- group: right_arm                    # 土台の同じ名前のグループに重ねる
  law: gravity_comp
  gravity_model: ../calibration/gravity_right.yaml
bus_watchdog_ms: 500
```

| 値の種類 | 重ね方 |
| --- | --- |
| マッピング | キーごとに重ねる（入れ子も同じ） |
| `group` か `name` で名前が付いたマッピングのリスト（`control`，`limits`） | 同じ名前の要素に重ねる．新しい名前の要素は末尾に足す |
| それ以外（数値，文字列，ふつうのリスト） | 置き換える |

- 土台は同じディレクトリのファイルに限ります．ファイルの中の相対パス（`../calibration/...`）の基準が変わらないようにするためです．
- 土台がさらに `extends` を持てます．循環は拒否します．
- 土台の要素を消す・並べ替えるときは，`without: [control]` でリストごと外して書き直します．`without` に書いたキーが土台になければ拒否します．
- 未知のキーの検査は，重ねたあとの内容に対して行います．
- 保存したデータセットの `meta/roboloom.json` には，重ねたあとの値と，土台のファイル名（`extends`）が残ります．
- `check-hold` が書く `unattended` は，そのキーが書いてあるファイルに書きます．どこにもなければ，そのノードのファイルに書きます．

Rakuda2のテンプレートでは，`leader_gravity.yaml` が `leader.yaml` を，`policy_teleop.yaml` が `policy.yaml` を土台にしています．

## 起動オプション { #launch-options }

`options:` は，起動時に選ぶ機能（重力補償，追加のセンサーなど）を名前で定義します．各オプションはノードファイルを置き換え・追加・削除します．`nodes/` の下のノードファイルは機能ごとに分かれたままで，オプションはどれを使うかを選ぶだけです．オプションの名前は英数字，`-`，`_` です．

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `help` | 文字列 | `""` | — | ランチャーに表示する説明 |
| `default` | 真偽値 | `false` | — | `true` なら，指定がないときに有効 |
| `requires` | 文字列のリスト | `[]` | — | 一緒に有効にするオプション |
| `conflicts` | 文字列のリスト | `[]` | — | 同時に使えないオプション |
| `set` | `{<role>.<node>: パス か null}` | `{}` | — | roleは `trackers`，`inputs`，`controllers`，`followers`，`sensors`，`estimators` のどれか．`null` はそのノードを削除する |
| `dataset` | 文字列 | `""` | — | 有効なときにデータセット名へ付ける短い名前（英数字，`.`，`-`，`_`） |

規則は次のとおりです．

- オプションを有効にすると，`requires` のオプションも有効になり，`conflicts` のオプションは無効になります．無効にすると，それを必要とするオプションも無効になります．
- 有効な2つのオプションが同じノードを違うファイルにするとエラーです．ただし，片方がもう片方を `requires` に持つ場合は，必要とする側（依存する側）が優先します．テンプレートでは，`bilateral` のleaderが `gravity` のleaderを，`policy_teleop` のleaderと方策が `policy` のものを置き換えます．
- 未知のオプション名はエラーです．
- 有効なオプションの `dataset` を，宣言順に `-` でつないで `repo_id` と `output` の末尾に付けます．形の違うエピソードが同じデータセットに混ざらないようにするためです．
- `dataset` を持たないオプションが記録するfeatureを変える場合，読み込みを拒否します．
- `roboloom infer` は，`policy` という名前のオプションがあれば有効にします．

テンプレート（`src/roboloom/robots/rakuda2/template/config.yaml`）のオプションです．`bilateral` は <span class="status status--mock">模擬のみ</span>，`pika` は <span class="status status--dev">開発中</span> です．

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
  pika:
    help: a Pika Sense per arm through inverse kinematics (in development, mock only)
    conflicts: [gravity, policy]
    set:
      trackers.lighthouse: nodes/lighthouse.yaml
      inputs.leader: null
      inputs.right_sense: nodes/right_sense.yaml
      inputs.left_sense: nodes/left_sense.yaml
      controllers.controller: nodes/controller_pika.yaml
    dataset: pika
  policy_teleop:
    help: with policy, the leader can drive before and during an episode (Teleop / Policy)
    requires: [policy]
    set:
      inputs.leader: nodes/leader.yaml
      controllers.policy: nodes/policy_teleop.yaml
    dataset: teleop
```

| 有効なオプション | `repo_id` |
| --- | --- |
| なし | `local/rakuda2` |
| `digit` | `local/rakuda2-digit` |
| `policy` | `local/rakuda2-eval` |
| `digit`，`policy` | `local/rakuda2-digit-eval` |
| `policy`，`policy_teleop` | `local/rakuda2-eval-teleop` |
| `gravity`，`bilateral` | `local/rakuda2-bilateral` |
| `pika` | `local/rakuda2-pika` |

`output` にも同じ名前が付きます（例：`datasets/rakuda2-digit`）．どのオプションが有効か，データセット名が何になるかは `roboloom validate --with digit` のように確かめられます．オプションの選び方は [CLI](../cli.md) を，Rakuda2で使える組み合わせと制約は [Rakuda2](../../robots/rakuda2/index.md) を参照してください．

## 実験ファイル { #experiments }

`.roboloom/<robot>/` には実機と制御の設定（ポート，測定値，制限，姿勢）を置きます．実験ごとに変わるもの（方策とチェックポイント，有効にするオプション，保存先，task，長さ）は，プロジェクトの `configs/roboloom/<名前>.yaml` に書きます．`roboloom infer --experiment <名前>` と `roboloom record --experiment <名前>` が，このファイルのとおりに走ります．

```yaml
# configs/roboloom/drawer.yaml
help: 引き出しを開ける方策の評価
robot: rakuda2                       # .roboloom/rakuda2 を使う．コマンドの robot が優先
options: [policy, digit]             # 有効にする起動オプション
dataset:                             # 保存先．省略すると robot の設定どおり
  root: data/roboloom/drawer
  repo_id: local/rakuda2-drawer
nodes:                               # ノードの設定への上書き
  controllers.policy:                # マッピング：そのノードの設定に重ねる
    factory: my_lab.policies:load
    kwargs: {checkpoint: outputs/drawer/last.ckpt}
    rate_hz: 10
    action_horizon: 8
  inputs.leader: nodes/leader_fixed_head.yaml   # 文字列：robot のディレクトリの別のノードファイルにする
task: open the drawer
steps: 200                           # または seconds: 40
episodes: 10
home: true
```

```bash
uv run roboloom infer --experiment drawer            # configs/roboloom/drawer.yaml
uv run roboloom infer --experiment path/to/file.yaml
```

| キー | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `help` | 文字列 | — | — | 説明 |
| `robot` | 文字列 | — | — | ロボットの名前（`.roboloom/<名前>/`）．コマンドに書いた robot が優先 |
| `options` | 文字列のリスト | — | — | 有効にする起動オプション．`--with`・`--without` で足し引きできる |
| `dataset` | `{root, repo_id}` | robotの設定どおり | — | `root`（保存先のディレクトリ）と `repo_id`．書いた場所がそのまま保存先になり，オプションの名前（`-digit-eval`）は付かない |
| `nodes` | `{<role>.<node>: マッピング か パス}` | `{}` | — | ノードごとの上書き．マッピングは，そのノードの設定に [`extends`](#extends) と同じ規則で重ねる．文字列は，robot のディレクトリから見た別のノードファイルに差し替える |
| `task` | 文字列 | — | — | `--task` の値 |
| `seconds` | 数値 | — | s | `--seconds` の値 |
| `episodes` | 整数 | — | — | `--episodes` の値 |
| `home` | 真偽値 | — | — | `--home` の値 |
| `steps` | 整数 | — | 手 | `infer --steps` の値．エピソードを，方策が実行した行動の数で終える．`seconds` とは同時に書けない |

- **名前とパス**：`--experiment drawer` は，コマンドを実行したディレクトリの `configs/roboloom/drawer.yaml` です．`/` を含むか `.yaml` で終わるものはパスとして読みます．
- **相対パス**：`dataset.root` はコマンドを実行したディレクトリ（プロジェクトのルート）から，`nodes` の文字列は robot のディレクトリから見ます．
- **`nodes` で指せるノード**：オプションを適用したあとに存在するノードだけです．`followers.*` は上書きできません（フォロワの範囲・速度・飛びの制限は，すべての指令を検査する最後の層です）．
- 書かなかった設定は，robot のノードファイルの値のままです（方策の `max_speed`，`command_deadline_ms` など）．
- コマンドラインに書いた値が優先します（`--experiment drawer --seconds 10`）．`seconds` も `steps` もどちらにもなければ拒否します．
- `steps` のエピソードは，方策が指定の手数を実行した時点で終わります．推論待ちで遅れる場合に備えて，上限時間（`steps / rate_hz × 1.5 + 5` 秒）でも終わり，そのときは何手で終わったかを表示します．
- 未知のキーは拒否します．
- `validate`，`check-dataset`，`label` も `--experiment` を受けます（その実験の構成と保存先を指します）．
- 保存したデータセットの `meta/roboloom.json` には，実験の名前と，重ねたあとの設定が残ります．
- `backend: server` の方策は，同じファイルからサーバーを起動できます（`roboloom serve-policy --experiment <ファイル>`）．

Pythonでは `Session.launch(experiment=...)` に，名前，パス，同じキーのマッピングのどれかを渡します．Hydraで実験を合成するプロジェクトは，合成した結果を渡します．roboloom自身はHydraに依存しません．

```python
from omegaconf import OmegaConf
from roboloom import Session

experiment = OmegaConf.to_container(cfg.roboloom, resolve=True)   # Hydraで合成したもの
with Session.launch(experiment=experiment) as session:
    session.wait_ready(60)
    session.record(experiment["task"], 155.0, steps=experiment["steps"])
```

## ログと設定の管理 { #logs }

ログは設定ファイルの隣の `logs/<データセット名>-<時刻>/` に置きます（例：`logs/rakuda2-digit-20261102-101500/`）．データセット名から，有効だったオプションが分かります．leaderの電流制御は `<leader名>_trace.npz` に，フォロワは毎周期の状態（位置・速度・電流・目標・モード）を `<フォロワ名>_trace.npz` に，ノードの終了時に書きます．YAMLの設定・重力モデル・可動域・調整値・保存した初期姿勢（`poses/<フォロワ名>/`）はGitで管理し，生データ `*.npz`・ログ・dataset・FIFO（`config.fifo`）は生成した `.roboloom/.gitignore` で除外します．

APIの詳細は [Python API](../python-api/index.md)，コマンドは [CLI](../cli.md) にあります．
