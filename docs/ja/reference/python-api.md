# Python API と CLI

roboloom の操作は，どれも Python の関数として使えます．CLI（`roboloom ...`）は，その関数を呼んで結果を表示するだけの薄い層です．

| やること | CLI | Python |
| --- | --- | --- |
| プロジェクトを作る | `roboloom init rakuda2` | `roboloom.init_project("rakuda2")` |
| EEPROM を合わせる | `roboloom commission <exp> <node> --hardware` | `setup.plan_commission(...)`，`setup.apply_commission(plan, operator)` |
| 可動域を測る | `roboloom measure-travel <cal> --out ...` | `setup.measure_travel(cal, out, operator)` |
| 重力モデルを同定する | `roboloom identify-gravity <cal> --out ... --collect --hardware` | `setup.identify_gravity(cal, out, operator, collect=True, hardware=True)` |
| 重力補償を確かめる | `roboloom gravity-check <exp> leader right_arm --hardware` | `setup.gravity_check(...)` |
| 重力補償を調整する | `roboloom tune-gravity <exp> leader right_arm --hardware` | `setup.open_tuning(...)` → `TuningSession` |
| エピソードを録る | `roboloom record <exp> --task ... --seconds 30 --hardware` | `Session.launch(...)` → `record(...)` |
| 方策で動かす | `roboloom infer <exp> --policy pkg:make --seconds 30 --hardware` | `Session.launch(exp, policy="pkg:make")` → `record(...)` |
| 操作画面で続けて録る | `roboloom run <exp> --hardware` | `Session.launch(...)` の状態画面と `start()`／`stop()`／`save()` |

実験は，ファイルのパスでも，`.roboloom/` の下の名前（`rakuda2`，`rakuda2/experiment_gravity`）でも指定できます．

## 1．収集と推論：`Session`

### 構成

調べたロボット学習の系（franka_ros2，DROID，deoxys，diffusion_policy，OpenPI など）は，どれも次の 3 つを分けていました．

- モーターを動かす速いループ
- 遠隔操作と記録
- 方策

roboloom も同じ構成をとります．

- **dora の dataflow**：次のものが，それぞれ別のプロセスで動きます．
  - robot ノードと leader ノード（制御のループ）
  - センサー
  - recorder
  - 方策ノード
- **`Session`**：dataflow を起動し，出来事を送ります．出来事とは，開始，停止，保存，task 名などです．制御のループは回しません．
  - そのため，利用者のスクリプトが重い処理をしたり，止まったりしても，制御の周期は乱れません．

### エピソードを録る

```python
from roboloom import Session

with Session.launch("rakuda2/experiment_gravity", hardware=True) as s:
    s.wait_ready()  # leader が follower に揃うまで待つ
    result = s.record("pick up the cup", seconds=30)
    print(result.index, result.frames, result.warnings)
```

- `launch` は，すべてのノードが状態を報告し始めるまで待ちます．
- 実機を開く実験では，`hardware=True` が必要です．
- `with` を抜けると，次のことをします．
  - 途中のエピソードがあれば破棄する．
  - モーターを制御する leader があり，`operator` が設定されていれば，腕を支えて Enter を押すように求める．
  - dataflow を止める．
  - leader は脱力し，follower はトルクと最後の目標を保持する．
- ログは，実験ファイルの隣の `logs/<実験名>-<時刻>/` に残ります．
  - `dora.log`
  - leader のトレース
  - 場所は `s.log_dir` で分かります．

### 状態画面と終了時の確認

- `Session.launch(..., screen="auto")` が既定です．標準出力が端末なら，CLI と同じノードの状態表とメッセージ欄を，別スレッドで 10 Hz で更新します．
  - `screen=False` で表示を切れます．パイプなど標準出力が端末でない場合，既定では表示しません．
  - スクリプトの `print()` は画面の上に出ます．画面はキーを読まないので，`input()` や API 呼び出しで操作できます．CLI の `record` のようなキー操作は追加しません．
  - 保存結果と品質の警告もメッセージ欄に出ます．
- `operator="auto"` が既定です．標準入力が端末なら，終了前に leader の腕を支える確認を出します．腕を支えてから Enter を押してください．
  - `operator=None`，または標準入力が端末でない場合は，この確認を出しません．`screen=False` だけでは確認は無効になりません．
  - follower は終了後も保持を続けます．電源を切る前に，腕を支えるか安全な姿勢に下ろしてください．

### task 名の自動命名

`task` には，文字列のほか，`EpisodeInfo` を受け取って文字列を返す関数を渡せます．

| `EpisodeInfo` の項目 | 中身 |
| --- | --- |
| `index` | データセットでのエピソード番号（保存済みのエピソード数） |
| `number` | この Session で録った数 |
| `experiment` | 実験ファイルの名前 |
| `previous` | この Session で保存した task の一覧 |

```python
import itertools

objects = itertools.cycle(["cup", "bottle", "sponge"])

with Session.launch("rakuda2", hardware=True) as s:
    s.wait_ready()
    for _ in range(9):
        s.record(lambda info: f"pick up the {next(objects)}", seconds=20)
```

```python
# 番号つき，操作者に毎回たずねる，など
s.record(lambda info: f"trial {info.index:03d}", seconds=20)
s.record(lambda info: input(f"task for episode {info.index}: "), seconds=20)
```

- 決まった task の文字列は，LeRobotDataset の各フレームの `task` に保存されます．
- 学習のときは，そのまま言語指示として使えます．

### 残すエピソードを選ぶ

- `record` は，停止したあと，保存する前に `keep(result)` を呼びます．
  - `False` を返すと，そのエピソードを破棄します．
- `result` に入っているもの：
  - `metrics`：recorder の指標．欠損率，有効な行動の割合，制御周期の分布．
  - `warnings`：品質の上限を超えた項目．
- 品質の上限は，実験の `recorder.quality` で変えられます．
  - `max_missing_rate`（既定 0.05）
  - `min_action_valid_rate`（既定 0.9）
  - `max_interval_ms`（既定 100）

```python
ok = s.record("pick up the cup", 30, keep=lambda ep: ep.ok)
```

### 細かく操作する

- `start(task)`，`stop()`，`save()`，`discard()`，`estop()`，`release(confirm=True)` を，1 つずつ呼べます．
  - 例：外部の合図で開始と終了を決めるとき．
- 状態を見る：
  - `status()`：各ノードの最新の状態．
  - `reports()`：未読の報告．robot のモードの変化など．
- コマンドが拒否されたとき（leader が揃っていないなど）は，`SessionError` になります．

```python
s.start("wipe the table")
while not task_done():  # 利用者の判定
    print(s.status()["robot"]["fields"]["mode"])
    time.sleep(0.5)
stopped = s.stop()  # まだ保存していない．metrics と warnings を見られる
s.save() if stopped.ok else s.discard()
```

### 方策で動かす

**方策の形**
- `reset()` と `infer(observation)` を持つオブジェクトです（`roboloom.Policy`）．
- 観測のキーは，データセットの特徴量と同じです．
  - `observation.state`
  - `observation.images.camera`
  - `observation.images.digit_left`
  - その他
- `task` も渡されます．
- `infer` が返すもの：関節の目標値（カウント）．1 手 `[17]` か，まとめた行動 `[H, 17]`．

**ノードの動き**
- 方策は，dataflow の中の方策ノードが，`"module:callable"` の参照から読み込んで動かします．
- 次の項目は `nodes/policy.yaml` で決めます．
  - 観測するセンサー（`observe`）
  - 周期（`rate_hz`）
  - まとめた行動のうち，何手を実行してから次を求めるか（`action_horizon`）
- 安全の確認は，遠隔操作と同じです．
  - 送る目標値は，速度の上限で切り詰めます．
  - `FollowerSafety` が，可動域と期限を検査します．

```python
# my_lab/policies.py
class MyPolicy:
    def __init__(self, checkpoint: str): ...
    def reset(self): ...
    def infer(self, observation):
        return self.model(observation)  # [H, 17]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

```python
with Session.launch(
    "rakuda2/experiment_policy",
    hardware=True,
    policy="my_lab.policies:load",
    policy_kwargs={"checkpoint": "outputs/act/last"},
) as s:
    s.wait_ready()  # 方策の読み込みが済むまで
    for k in range(10):
        s.record(f"pick up the cup (eval {k})", seconds=30)  # 評価データとして保存
```

**注意**
- `infer` の間は，command を送りません．
  - 推論が `command_deadline_ms` より長くかかると，robot は HOLD に入ります．止まって待つ動きになります．
  - 推論中も前のまとめた行動を実行し続ける非同期型は，今後の課題です．
- テンプレートの既定の方策 `roboloom.policy:hold` は，腕をその場に留めます．
  - 実機で，推論の経路を初めて確かめるときに使います．

## 2．セットアップと計測：`roboloom.setup`

- 計測の本体は，結果を dataclass で返し，失敗を例外で知らせます．
  - `ConfigError`：設定の誤り．
  - `SetupError`：計測の前提を満たさない，精度が足りない．
  - `HardwareError`：トルクが入っているなど，機器の状態が合わない．
  - `Cancelled`：確認が拒否された．何も書いていない．
- 人の操作が要る場面は，`Operator` に問い合わせます．
  - 腕を支える，姿勢を置く，Enter を押す，など．
  - CLI は `TerminalOperator` を渡します．
  - スクリプトや試験では `ScriptedOperator` に答えを並べて渡せます．
- モーターを動かす処理と，EEPROM を書く処理には，`hardware=True` が要ります．

```python
from roboloom import setup
from roboloom.operator import TerminalOperator

op = TerminalOperator()
plan = setup.plan_commission("rakuda2/experiment_gravity", "leader", hardware=True)
for line in plan.lines():
    print(line)
setup.apply_commission(plan, op)  # 確認してから書く

fit = setup.identify_gravity(
    ".roboloom/rakuda2/calibration/leader_right.yaml",
    ".roboloom/rakuda2/calibration/gravity_right.yaml",
    op,
    collect=True,
    hardware=True,
)
for joint in fit.joints:
    print(joint.joint, f"{joint.explained:.0%}")
```

```python
# 重力補償の調整を，画面なしで（例：値を順に試す自動化）
tuning = setup.open_tuning(
    "rakuda2/experiment_gravity", "leader", "right_arm", hardware=True
)
try:
    tuning.start()
    tuning.key("]")  # 選んだ関節の gain +0.1
    for _ in range(120):
        tuning.step()
        time.sleep(tuning.period_s)
    print([(r.joint, r.gain, r.sent_mA) for r in tuning.rows()])
finally:
    tuning.close()
```

## 3．1 つのプロセスで動かす：`Experiment`

- `Experiment` は，ロボットのバス，センサー，controller の呼び出しを，すべて呼び出し側のスレッドで行います．
- 使いどころ：
  - 試験
  - 模擬
  - センサーの少ない簡単な機体
- 方策を `step(policy=...)` に直接渡せます．
  - ただし，方策やセンサーが遅いと，制御の周期も遅れます．
- 実機の Rakuda-2 は，`Session` で動かします．
  - モーターを制御する leader（トリガーのばね，重力補償）を使う実験では，`from_yaml` を拒否します．
  - 方策の controller を使う実験でも，`from_yaml` を拒否します．

模擬構成では，次のように呼び出します．`record` extraが必要です．

```python
from roboloom import Experiment

with Experiment.from_yaml("examples/mock/experiment.yaml") as experiment:
    experiment.start_episode("handover")
    experiment.run(3.0)
    experiment.stop_episode()
    experiment.save_episode()
```

実機の収集手順は [Rakuda2 Quick start](../quick-start/rakuda2.md) を参照してください．
