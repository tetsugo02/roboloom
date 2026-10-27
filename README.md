# roboloom

公開ドキュメント: [日本語](https://tetsugo02.github.io/roboloom/ja/) / [English](https://tetsugo02.github.io/roboloom/en/)．docs関連の変更が `main` にpushされると，GitHub Actionsが両言語をビルドしてGitHub Pagesへ公開します．初回設定とtriggerの対象は [Contribution](docs/ja/contribution.md#github-pagesへの公開) を参照してください．

**[Quick start](docs/ja/quick-start/installation.md)**（[English](docs/en/quick-start/installation.md)）から，インストールと [Rakuda2の設定・重力補償・データ収集](docs/ja/quick-start/rakuda2.md) を進められます．[対応機器](docs/ja/robots/rakuda2.md) も参照してください．roboloom本体の開発やdocsのビルド・プレビューは [Contribution](docs/ja/contribution.md) にまとめています．

Rakuda の leader 操作，RGB，左右 DIGIT，モノラル PCM を収集し，LeRobotDataset 0.6.1 に保存する Python パッケージです．Python 3.12，dora-rs と dora-rs-cli 1.0.1 を固定しています．

leaderの関節固定は `control` の `law: position`，首カメラの腰yaw相殺はjoint controllerの `couplings` で設定できます（既定は無効，組み合わせは模擬検証まで）．設定例と制約は [Leader](docs/ja/controllers/leader.md)（[English](docs/en/controllers/leader.md)）にあります．

## Installation

自分のuvプロジェクトに，GitHubからroboloomを追加します．新規プロジェクトの場合：

```bash
uv init --python '>=3.12,<3.13' my-robot
cd my-robot
uv add git+https://github.com/tetsugo02/roboloom.git
uv run roboloom --help
```

既存プロジェクトでは `project.requires-python` を `">=3.12,<3.13"` に設定してから `uv add` を実行します．記録・実機収集にはextrasを追加します．

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --extra hardware
uv run roboloom init rakuda2
```

`init` はインストール済みパッケージから，自分のプロジェクト内に `.roboloom/rakuda2/` を作ります．生成した設定を編集し，CLIもPythonスクリプトも自分のプロジェクトルートから実行します．`pyproject.toml` と `uv.lock` をGitで管理し，別の環境では `uv sync --locked` で再現します．更新・commit固定の手順は [Installation](docs/ja/quick-start/installation.md) を参照してください．

## Python interface

roboloom の操作は，どれも Python の関数として使えます．CLI はそれを呼ぶだけの薄い層です．対応表と例は [docs/ja/reference/python-api.md](docs/ja/reference/python-api.md) にあります．

- **`Session`**（実機の収集と推論）
  - 実験の dora dataflow を起動します．
  - 開始・停止・保存・task 名を送ります．task 名は関数で自動命名できます．
  - 方策は，dataflow の中の方策ノードで動きます．
- **`roboloom.setup`**（セットアップと計測）
  - commission，可動域，重力の同定・確認・調整を行います．
  - 結果をデータで返します．操作者とのやりとりは `Operator` に任せます．
- **`Experiment`**（1 プロセス）：試験と簡単な機体のためのもので，下で説明します．

```python
from roboloom import Session

with Session.launch("rakuda2/experiment_gravity", hardware=True) as s:
    s.wait_ready()
    for _ in range(3):
        s.record(lambda info: f"pick up the cup #{info.index}", seconds=20)
```

`Experiment` は，バス，センサー，controller を呼び出し側のスレッドで動かします．以下はデバイスもリポジトリ内のサンプルファイルも使わない模擬例です．記録用extraを追加し，Python例を自分の `main.py` に保存して実行します．

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record
uv run python main.py
```

```python
from roboloom import Experiment
from roboloom.drivers.mock import MockBus

with Experiment.from_components(
    robot_id="my-mock",
    robot=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
    output="datasets/my-mock",
    repo_id="local/my-mock",
) as experiment:
    experiment.start_episode("handover")
    experiment.run(3.0)
    experiment.stop_episode()
    experiment.save_episode()  # LeRobotDataset に確定

    experiment.start_episode("retry")
    experiment.run(1.0)
    experiment.discard_episode()  # このエピソードだけ破棄

    experiment.start_inference()
    result = experiment.step(policy=lambda obs: obs["state"])
    experiment.stop_inference()
```

`Experiment.from_components(...)` では，任意の関節数と名前，ロボットバス，controller 関数，センサー読み取り関数を渡せます．controller または `step(policy=...)` は `obs` を受け取り，次の関節目標値を返します．センサー関数は `Sample(value, capture_ns)` または `None` を返します．ロボットバスは `read_positions`，`write_positions`，`enable_torque`，`close` を実装します．観測は `obs["state"]` と各センサー名で渡されます．`step()` の指令は必ず robot 側の期限・次元・有限値・関節範囲・変化量検査を通ります．

この模擬例の関節範囲や速度を実機の安全値として使わないでください．

`from_yaml` について：
- 実験ファイルのパスでも，`.roboloom/` の下の名前でも指定できます．
- 模擬構成では，leader を自動で開きます．
- 追加のセンサーは，`sensors={"camera": ..., "digit_left": ..., "digit_right": ..., "audio": ...}` で渡します．
- 次の実験は拒否します．これらは `Session` で動かします．
  - モーターを制御する leader（Rakuda-2 のトリガーのばね，重力補償）を使う実験．
  - 方策の controller を使う実験．
- 機器ごとに独立した取得周期が必要な本番の収集には，`Session`（下の dora dataflow）を使います．

## dora dataflow

実験 YAML はノード YAML を役割ごと（`inputs`，`controllers`，`robots`，`sensors`）に名前付きで参照し，`recorder` と `session` を加えます．各ノードの `type` で実装を選びます．ノード名がそのまま dora のノード ID と LeRobot の feature 名になります．leader と follower の Dynamixel バスはそれぞれのノードだけが開きます．`validate` は実機に接続しません．

以下は `init` で生成した設定を使う実機の例です．先に [Rakuda2 Quick start](docs/ja/quick-start/rakuda2.md) に従って `SET_...` を埋め，EEPROM・安全範囲・停止動作を確認します．初回はfollowerの `torque: false` で経路を確認し，leaderを含めて腕を支えられる状態で行います．

```bash
uv run roboloom validate rakuda2/experiment_camera
uv run roboloom run rakuda2/experiment_camera --hardware
```

`run` を端末で実行すると，画面の上部に全ノードの状態が固定表示されます．

- robot：`HOLD`，`ACTIVE`，`FAULT` などと，その理由，tick の周期．
- controller：`following`（追従中），`aligning`（姿勢合わせ待ち．最も離れた関節と差を表示），`input_stale`（leader の入力が途絶えている）．
- 入力・センサー：実測のレートと，最後のサンプルからの経過時間．
- recorder：記録中のタスク，行数，欠損．
- 2 秒以上状態が届かないノードは赤で表示します．

その下にメッセージ（保存結果，エラー，状態の変化）と入力行があります．dora 自身の出力は，実験ファイルの隣の `logs/<実験名>-<時刻>/dora.log` に送り，エラーらしい行だけをメッセージ欄に写します．Ctrl-C は `quit` と同じです．パイプなど端末でないとき，または `--plain` を付けたときは，従来の行入力で動きます．

表示する項目は，各ノードが `status` 出力に載せる `fields` で決まります（`core/status.py`）．新しいロボットやセンサーは，`fields` を足すだけで `key=value` として表示されます．専用の表示にしたいときは，`ui/render.py` の `RENDERERS` に role ごとの関数を 1 つ登録します．

実行中に入力できるコマンド：

- `start <task>`，`stop`，`save`，`discard`，`estop`，`quit`
- `release`：follower のトルクを切る．HOLD 中だけ受け付け，CLI が「腕を支えて yes」と確認する．

別端末からは `uv run roboloom session rakuda2/experiment_camera start handover` の形でも操作できます．

決まった長さのエピソードを録って終わるとき（`--episodes` で回数を指定，既定 1）：

```bash
uv run roboloom record rakuda2/experiment_camera --task handover --seconds 10 --hardware
```

- 動作：
  - controller が準備できたら，Enter で開始します．
  - `q` はエピソードを破棄して終わります．
  - `e` は非常停止です．
- 保存したとき：
  - 欠損率，有効な行動の割合，制御周期の最大値が `recorder.quality` の上限を超えていれば，警告を出します．

方策で動かす（`type: policy` の controller を持つ実験．テンプレートの `experiment_policy.yaml`）：

```bash
uv run roboloom infer rakuda2/experiment_policy --policy my_lab.policies:load --seconds 30 --hardware
```

`--task` を付けると，その走行を保存します（評価データ）．

hardware 構成を実行するときだけ `run --hardware` が必要です．

EEPROM について：

- 実行中は EEPROM を書きません．起動時にモデル番号と EEPROM（Operating Mode，Current Limit，位置リミットなど）を読み，ノード YAML の `registers` と違えば起動を拒否します．
- EEPROM を書くのは，明示的に実行する `roboloom commission` だけです．

機体固有の関節限界，速度上限，ポート，機器 ID は実験 YAML に明示してください．模擬構成の値を実機用の安全値として流用しないでください．

全ての関節値は **Dynamixel の生の位置カウント**です．電流は mA で扱い，モーターごとの単位変換はドライバが行います．

follower の安全判定：

- 指令は，速度上限 `max_speed`（カウント/s）に切り詰めて送ります（soft clamp）．切り詰めた行は `action.clamped` に記録します．
- 範囲外，NaN，期限切れ，`max_jump` を超える飛びは拒否して `HOLD` にします（hard reject）．
- `HOLD` は，最後に送った目標を固定して送り続けます．実測位置を目標にし直すと，重力で少しずつ下がっていくためです．
- 健全性の検査（Hardware Error，温度，電流の継続超過，Bus Watchdog の発動）に引っかかると `FAULT` にします．
- `FAULT`，`ESTOP`，`RELEASED` はラッチされ，自動では復帰しません．

実機での停止動作と収集品質は，別途確認が必要です．

## 制御則（`control`）

ノード YAML の `control` で，関節をグループに分け，グループごとに制御則を選びます．leader と follower は同じ仕組みを使います．

| 制御則 | モード | 用途 |
| --- | --- | --- |
| `free` | トルクオフ | 手で動かす関節 |
| `position` | 位置 | follower の既定 |
| `current_position` | 電流制限つき位置 | グリッパー．目標を固定すれば leader のトリガーのばねになる |
| `gravity_comp` | 電流 | leader の重力補償（`gravity_gain·g(q) − kd·q̇`，範囲の押し戻し，電流の clip） |
| `impedance` | 電流 | `kp(q*−q) − kd·q̇ + g(q)`．実機では未検証で，`allow_unvalidated: true` がなければ拒否する |

トルクを入れるときは，次の順で行います．

1. 動作モードを照合する（ここでは書かない）．
2. 電流モードの関節の Goal Current を 0 にして読み戻す．
3. 位置の目標を現在値で初期化する．
4. トルクを入れる．電流モードの制御則は `ramp_s` をかけて立ち上がる．

制御中にバスの読み書きに失敗したり，関節が速度・範囲を外れて暴走を検知したりすると，電流を 0 にしてトルクを切ります．

実機で電流モードの制御則を使う条件：

- `bus_watchdog_ms` を設定していること．
- EEPROM の Current Limit（`registers.current_limit`）が `max_current_mA` 以下であること．

重力モデル（`dynamics/`）は，URDF の関節軸だけを使い，保持電流の実測から同定します．CAD の質量は使いません．

## 実機のプロジェクト（`roboloom init`）

実機の設定は，ロボットごとのテンプレートから作ります．

```bash
uv run roboloom init rakuda2      # .roboloom/rakuda2/ と .roboloom/.gitignore を作る
uv run roboloom validate rakuda2  # 埋めていない SET_ の値を，場所つきで一覧にする
```

- 機体ごとに測る値は，テンプレートでは `SET_…` になっています．ポート，センサーのシリアル番号などです．
- `SET_` が残っているあいだ，`run` や `validate` などは場所を示して止まります．
- 埋める手順は，`.roboloom/rakuda2/README.md` にあります．probe，commission，identify-gravity，measure-travel，tune-gravity の順です．
- 実験は，`.roboloom` からの名前で指定できます（例：`roboloom run rakuda2/experiment_gravity --hardware`）．ファイルのパスでも指定できます．
- YAML（設定，重力モデル，可動域，調整値）は git に入れます．測定の生データ（`*.npz`），ログ，データセットは `.gitignore` で除きます．ログは，実験ファイルの隣の `logs/` に置かれます．
- 自分のプロジェクトの `.roboloom/rakuda2/` に，使用する機体の設定を管理します．

実機を動かす手順は，腕を支えられる状態で行ってください．
- テンプレートの `nodes/robot.yaml` は `torque: true` です．初回の収集前に `torque: false` へ変更し，followerを動かさずデータの経路を確かめます（leaderの制御は独立して通電します）．
- 終了するときは `stop` → 腕を支えて `quit` → Enter（followerも脱力）の順にします．followerを保持したまま終えるときは，確認に `hold` と入力します．

leader の重力補償の調整（gain と hold の意味，`tune-gravity` の使い方）は，[docs/ja/reference/gravity-tuning.md](docs/ja/reference/gravity-tuning.md) を参照してください．

recorder は取得，利用可能，受信，送信の単調時計時刻を区別します．各フレーム時刻までに recorder が受信済みの観測を選び，`action[t]` はその後最初に送信成功した tick の指令を保存します．欠損はゼロ値と有効フラグで表します．保存後も同じ dataset へ次のエピソードを追記し，再起動時は既存 dataset のスキーマと FPS を確認して再開します．

## パッケージ構成

```text
src/roboloom/
  core/         Envelope（通信形式），値の検査，型レジストリ，Source（入力・センサー共通の契約）
  drivers/      機器バス（Dynamixel，模擬バス）．inputs と robots が共有する
  inputs/       操作入力の契約（InputDevice，JointInput）
    rakuda_mini/ Rakuda-mini（rakuda_mini．Rakuda2 を操作するアーム．実験では leader の役割で使う）
  controllers/  入力から RobotCommand への変換．joint，policy（方策ノード）
  control/      制御則（laws）と JointDevice（device）．leader と follower が共有する
  dynamics/     重力モデルの契約，URDF 運動学，同定（regressor，identify）
  robots/       Robot の契約（base），FollowerSafety（safety）
    rakuda2/    spec（関節・モーター ID・モデル．Rakuda-mini も参照），follower（rakuda2_follower），model（URDF），template（init が写す設定一式）
  sensors/
    vision/     ImageSensor（base），realsense_rgb
    tactile/    TactileImageSensor（base），digit
    audio/      PcmAudio（base），pcm_mono（microphone）
  recording/    時刻整列，LeRobot スキーマ，指標
  runtime/      dora dataflow の生成，ノードの実行，Session（dataflow の起動と指揮）
  ui/           操作画面（rich Live），状態の描画，session との受け渡し
  config.py     実験 YAML の読み込みと，ノード間の整合性検査
  probe.py      Dynamixel バスの読み取り専用の調査
  setup/        セットアップと計測の本体（commission，calibrate-joints，measure-travel，identify-gravity，gravity-check，tune-gravity）．結果をデータで返し，操作者とのやりとりは Operator に任せる
  operator.py   Operator（CLI は TerminalOperator，スクリプトと試験は ScriptedOperator）
  errors.py     利用者が対処できるエラー（ConfigError，SetupError，HardwareError，Cancelled）
  project.py    roboloom init（robots/<robot>/template から .roboloom/<robot>/ を作る）
  api.py        1 プロセスの Experiment（試験・簡単な機体）
  policy.py     方策の契約（reset，infer）と読み込み．hold（その場に留まる）
```

依存の向きは `core` ← `drivers` ← `dynamics` ← `control` ← `robots`/`inputs`/`sensors` ← `controllers` ← `recording`/`config` ← `runtime`/`api`/`cli` です．各役割のパッケージは `__init__.py` に `type` 名から実装への対応表（`ROBOTS`，`INPUTS`，`CONTROLLERS`，`SENSORS`）を持ちます．実装のモジュールは選ばれたときにだけ import されます．

拡張するときは，次のように実装を1つのモジュールに書き，対応表に1行追加します．

- **ロボット**（Koch，SO-101，xArm）：`robots/<model>/` に機体情報（`spec.py`）と `robots.base.Robot` を継承した follower を置き，`ROBOTS` に登録します．機体固有の機能は，汎用部分に書かずに機体の側で申告します．バスは `drivers.base` の契約（必要なら `read_state`，`read_health`，`write_goal_currents`，`set_torque`）を実装し，起動時に照合する EEPROM を `expected_eeprom`，`current_limits_mA` で示します．電流モードや watchdog を持たない機体では，その制御則が設定の読み込み時に拒否されます．leader アームがあれば `inputs/<model>/` に置いて `spec.py` を参照し，`INPUTS` に登録します．新しいバスが必要なら `drivers/` に追加します．
- **入力**（SpaceMouse，VR）：`inputs/<device>/` に置きます．関節空間の入力なら `inputs.base.JointInput` を継承します．姿勢・速度の入力は `PoseInput`／`TwistInput` のような基底クラスを `inputs/base.py` に追加し，固有の `kind` を持たせます．
- **controller**：`controllers.base.Controller` を継承します．コンストラクタで入力とロボットの組を検査するため，未対応の組は起動前にエラーになります．
- **センサー**：該当するモダリティ（`vision`，`tactile`，`audio`）の `base` にあるストリーム型を継承し，`open_device` を実装します．ペイロードと feature はストリーム型で決まります．深度や力覚のような新しい種類はそのモダリティの `base` にストリーム型を追加し，新しいモダリティはサブパッケージごと追加します．

設定の読み込みはデバイスを開きません．ロボットは現在1実験1台で，ロボットごとに controller を1個とします．
