# roboloom

Rakuda の leader 操作、RGB、左右 DIGIT、モノラル PCM を収集し、LeRobotDataset 0.6.1 に保存する Python パッケージです。Python 3.12、dora-rs と dora-rs-cli 1.0.1 を固定しています。`robopy` は実行時依存ではありません。

## Python interface

```bash
uv sync --extra record
uv run python main.py
```

```python
from roboloom import Experiment

with Experiment.from_yaml("examples/mock/experiment.yaml") as experiment:
    experiment.start_episode("handover")
    experiment.run(3.0)
    experiment.stop_episode()
    experiment.save_episode()       # LeRobotDataset に確定

    experiment.start_episode("retry")
    experiment.run(1.0)
    experiment.discard_episode()    # このエピソードだけ破棄

    experiment.start_inference()
    result = experiment.step(policy=lambda obs: obs["state"])
    experiment.stop_inference()
```

`Experiment.from_components(...)` では、任意の関節数と名前、ロボットバス、controller 関数、センサー読み取り関数を渡せます。controller または `step(policy=...)` は `obs` を受け取り、次の関節目標値を返します。センサー関数は `Sample(value, capture_ns)` または `None` を返します。ロボットバスは `read_positions`、`write_positions`、`enable_torque`、`close` を実装します。観測は `obs["state"]` と各センサー名で渡されます。`step()` の指令は必ず robot 側の期限・次元・有限値・関節範囲・変化量検査を通ります。

```python
from roboloom import Experiment
from roboloom.drivers.mock import MockBus

experiment = Experiment.from_components(
    robot_id="my_robot", robot=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    limits=[{"name": "j1", "min": 0, "max": 4095, "max_step": 100},
            {"name": "j2", "min": 0, "max": 4095, "max_step": 100}],
    controller=lambda obs: [2048, 2048],
    output="datasets/my_robot", repo_id="local/my_robot",
)
```

`from_yaml` は初期 Rakuda 構成を読み込みます。模擬構成の leader は自動的に開きます。追加センサーは `sensors={"camera": ..., "digit_left": ..., "digit_right": ..., "audio": ...}` で渡します。機器ごとに独立した取得周期が必要な本番収集には下記の dora dataflow を使います。

## dora dataflow

実験 YAML はノード YAML を役割ごと（`inputs`、`controllers`、`robots`、`sensors`）に名前付きで参照し、`recorder` と `session` を加えます。各ノードの `type` で実装を選びます。ノード名がそのまま dora のノード ID と LeRobot の feature 名になります。模擬構成は Rakuda leader 1台、joint controller 1個、follower 1台、センサー4個の9ノードです。leader と follower の Dynamixel バスはそれぞれのノードだけが開きます。`validate` は実機に接続しません。

```bash
uv run roboloom validate examples/mock/experiment.yaml
uv run roboloom run examples/mock/experiment.yaml
```

実行中は `start <task>`、`stop`、`save`、`discard`、`estop`、`quit` を入力します。別端末からは `uv run roboloom session examples/mock/experiment.yaml start handover` の形でも操作できます。hardware 構成を実行する場合だけ `run --hardware` が必要です。実機の EEPROM 設定は変更しません。機体固有の関節限界、最大変化量、ポート、機器 ID は実験 YAML に明示してください。模擬構成の値を実機用の安全値として流用しないでください。

全ての関節値は現行 robopy に合わせた **Dynamixel の生の位置カウント**です。`HOLD` は毎 tick で現在位置を目標として送ります。`FAULT` と `ESTOP` はラッチされ、自動復帰しません。実機での停止動作と収集品質は別途確認が必要です。

recorder は取得、利用可能、受信、送信の単調時計時刻を区別します。各フレーム時刻までに recorder が受信済みの観測を選び、`action[t]` はその後最初に送信成功した tick の指令を保存します。欠損はゼロ値と有効フラグで表します。保存後も同じ dataset へ次のエピソードを追記し、再起動時は既存 dataset のスキーマと FPS を確認して再開します。

## パッケージ構成

```text
src/roboloom/
  core/         Envelope（通信形式）、値の検査、型レジストリ、Source（入力・センサー共通の契約）
  drivers/      機器バス（Dynamixel、模擬バス）。inputs と robots が共有する
  inputs/       操作入力の契約（InputDevice、JointInput）
    rakuda2/    leader（rakuda2_leader）
  controllers/  入力から RobotCommand への変換。joint
  robots/       Robot の契約（base）、FollowerSafety（safety）
    rakuda2/    spec（関節・モーター ID。leader も参照）、follower（rakuda2_follower）
  sensors/
    vision/     ImageSensor（base）、realsense_rgb
    tactile/    TactileImageSensor（base）、digit
    audio/      PcmAudio（base）、pcm_mono（microphone）
  recording/    時刻整列、LeRobot スキーマ、指標
  runtime/      dora dataflow の生成とノードの実行
  config.py     実験 YAML の読み込みと、ノード間の整合性検査
  api.py        Python から使う Experiment
```

依存の向きは `core` ← `drivers` ← `robots`/`inputs`/`sensors` ← `controllers` ← `recording`/`config` ← `runtime`/`api`/`cli` です。各役割のパッケージは `__init__.py` に `type` 名から実装への対応表（`ROBOTS`、`INPUTS`、`CONTROLLERS`、`SENSORS`）を持ちます。実装のモジュールは選ばれたときにだけ import されます。

拡張するときは、次のように実装を1つのモジュールに書き、対応表に1行追加します。

- **ロボット**（Koch、SO-101、xArm）：`robots/<model>/` に機体情報（`spec.py`）と `robots.base.Robot` を継承した follower を置き、`ROBOTS` に登録します。leader アームがあれば `inputs/<model>/` に置いて `spec.py` を参照し、`INPUTS` に登録します。新しいバスが必要なら `drivers/` に追加します。
- **入力**（SpaceMouse、VR）：`inputs/<device>/` に置きます。関節空間の入力なら `inputs.base.JointInput` を継承します。姿勢・速度の入力は `PoseInput`／`TwistInput` のような基底クラスを `inputs/base.py` に追加し、固有の `kind` を持たせます。
- **controller**：`controllers.base.Controller` を継承します。コンストラクタで入力とロボットの組を検査するため、未対応の組は起動前にエラーになります。
- **センサー**：該当するモダリティ（`vision`、`tactile`、`audio`）の `base` にあるストリーム型を継承し、`open_device` を実装します。ペイロードと feature はストリーム型で決まります。深度や力覚のような新しい種類はそのモダリティの `base` にストリーム型を追加し、新しいモダリティはサブパッケージごと追加します。

設定の読み込みはデバイスを開きません。ロボットは現在1実験1台で、ロボットごとに controller を1個とします。
