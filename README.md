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
from roboloom.devices import MockBus

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

実験 YAML は9個のノード YAML を参照します。初期版は Rakuda leader 1台と follower 1台、joint controller 1個を選びます。leader と follower の Dynamixel バスはそれぞれのノードだけが開きます。`validate` は実機に接続しません。

```bash
uv run roboloom validate examples/mock/experiment.yaml
uv run roboloom run examples/mock/experiment.yaml
```

実行中は `start <task>`、`stop`、`save`、`discard`、`estop`、`quit` を入力します。別端末からは `uv run roboloom session examples/mock/experiment.yaml start handover` の形でも操作できます。hardware 構成を実行する場合だけ `run --hardware` が必要です。実機の EEPROM 設定は変更しません。機体固有の関節限界、最大変化量、ポート、機器 ID は実験 YAML に明示してください。模擬構成の値を実機用の安全値として流用しないでください。

全ての関節値は現行 robopy に合わせた **Dynamixel の生の位置カウント**です。`HOLD` は毎 tick で現在位置を目標として送ります。`FAULT` と `ESTOP` はラッチされ、自動復帰しません。実機での停止動作と収集品質は別途確認が必要です。

recorder は取得、利用可能、受信、送信の単調時計時刻を区別します。各フレーム時刻までに recorder が受信済みの観測を選び、`action[t]` はその後最初に送信成功した tick の指令を保存します。欠損はゼロ値と有効フラグで表します。保存後も同じ dataset へ次のエピソードを追記し、再起動時は既存 dataset のスキーマと FPS を確認して再開します。
