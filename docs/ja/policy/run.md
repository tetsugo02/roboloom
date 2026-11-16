# 方策を動かす

方策ノードの設定と，`roboloom infer` で方策を動かす手順です．キーの一覧は [方策の設定](../reference/configuration/policy.md)，コマンドのオプションは [CLI](../reference/cli.md#infer) にあります．

## 設定 { #configuration }

```yaml
# nodes/policy.yaml
type: policy
followers: [left, right, left_gripper, right_gripper]  # 全フォロワを設定の順に
factory: demo_policy:wave           # "module:callable"．方策を返す
kwargs: {}                          # factory に渡す引数
observe: [camera, left_wrist, right_wrist]  # 方策が見る入力とセンサー．フォロワの状態は常に見える
rate_hz: 10                         # 行動1手の周期．学習したデータセットの dataset_fps
interpolation_multiplier: auto      # 指令は rate_hz × この値の周期．省略・auto はフォロワの control_hz から計算
action_horizon: 2                   # まとめた行動のうち，次を求めるまでに実行する手数
max_speed: {left: 1.0, right: 1.0, left_gripper: 3.0, right_gripper: 3.0}  # フォロワごと，単位/s
command_deadline_ms: 300
```

- `factory` のモジュールは，インストール済みのパッケージを先に探し，見つからなければロボットのディレクトリ（`.roboloom/<robot>/`）を探します．設定の隣に置いた方策のファイルは，`PYTHONPATH` なしで読み込めます．同じ名前のモジュールがインストール済みなら，そちらが使われます．
- 方策とチェックポイント，有効にするオプション，保存先，task，長さは，プロジェクトの [実験ファイル](../reference/configuration/index.md#experiments)（`configs/roboloom/<名前>.yaml`）にまとめます．`roboloom infer --experiment <名前>` だけで走り，`nodes/policy.yaml` は書き換えません．
- `roboloom infer` は，`policy` という名前のオプションを自動で有効にします．`--policy` と `--policy-kwargs` で，YAMLを書き換えずに方策を差し替えられます．
- テンプレートの既定の方策 `roboloom.policy:hold` は，腕をその場に留めます．実機で，推論の経路を初めて確かめるときに使います．
- 方策が見る観測の選び方は [観測を選ぶ](custom.md#observations) にあります．

```bash
uv run roboloom infer piper-mock --seconds 20 \
  --policy roboloom.policy.lerobot:load --policy-kwargs '{"path": "outputs/act/pretrained_model"}'
```

## 周期と手数 { #rate-and-steps }

- 方策ノードは，`rate_hz` の周期で行動を1手ずつ取り出します．並んでいる行動がなくなると，`infer` を呼びます．
- `rate_hz` は，学習に使ったデータセットの `dataset_fps` に合わせます．指令を速くするために `rate_hz` を上げると，行動の列を学習時より速く使い切ってしまいます．
- 既定では，`infer` の間は指令を送りません（同期．[非同期の推論](async.md#asynchronous-inference)を参照）．推論が `command_deadline_ms` より長くかかると，フォロワはHOLDに入り，止まって待ちます．画面のcontrollerの行に，推論の時間（`infer_ms`，`infer_max_ms`）が出ます．
- 1手ごとの間は補間した目標を送ります（[行動の補間](async.md#interpolation)）．

## 初期姿勢から始める（home） { #home }

方策でも，エピソードの前に保存した姿勢へフォロワを動かせます．`roboloom capture-pose <名前>` で姿勢を保存し，`nodes/policy.yaml` に `home:` を書きます．

```yaml
home:
  pose: ../poses/follower/ready.yaml  # roboloom capture-pose ready
  max_speed: 200                      # この max_speed 以下（フォロワの単位/s）
  tolerance: 30                       # 測った各関節がこの差以内なら到着
  timeout_s: 30                       # 任意
```

- フォロワが複数のときは，`home: {left: {...}, right: {...}}` のようにフォロワごとに書きます．書かなかったフォロワは動きません．
- `roboloom infer --home` は毎回のエピソードの前に動かします．ランチャーの `infer` でも「Move home before every episode」を選べます．操作画面の `home`，Pythonの `Session.home()`・`Session.record(..., home=True)` も同じです．
- 到着は，送った目標ではなく測った関節で確かめます．移動のあと，すべての関節が `tolerance` 以内に入れば `reached` です．2秒たっても入らなければ `short` として関節名と差を表示し，`home` は失敗，`start` は拒否します．
- 開始前の検査は `home` と同じく，録画中・追従中は `home` を拒否し，移動中は `start` を拒否します．
- `teleop:` のある構成では，`home` はleaderも一緒に動かします（[テレオペと介入](intervention.md#behavior)）．

## Pythonから動かす { #python }

方策は，dataflowの中の方策ノードが `"module:callable"` の参照から読み込んで動かします．Pythonからは，起動する構成と方策を `Session.launch` に渡します（[Session](../reference/python-api/session.md)）．方策の書き方は [自作の方策](custom.md) にあります．

```python
# my_lab/policies.py
class MyPolicy:
    def __init__(self, checkpoint: str): ...
    def reset(self): ...
    def infer(self, observation):
        return self.model(observation)  # [H, n]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

```python
with Session.launch(
    "rakuda2",
    options=["policy"],  # 既定は関節状態＋RealSense．DIGITを使うなら "digit" も選ぶ
    policy="my_lab.policies:load",
    policy_kwargs={"checkpoint": "outputs/act/last"},
) as s:
    s.wait_ready()  # 方策の読み込みが済むまで
    for k in range(10):
        s.record(f"pick up the cup (eval {k})", seconds=30)  # 評価データとして保存
```

- 観測するセンサー（`observe`），周期（`rate_hz`），まとめた行動のうち何手を実行してから次を求めるか（`action_horizon`）は，`nodes/policy.yaml` で決めます．
- `wait_ready` は，方策が読み込めなかったとき（`bind` の例外を含む）待たずに理由を示して終わります．

## センサー選択 <span class="status status--mock">模擬のみ</span> { #sensor-selection }

起動・記録するセンサーと，方策が観測するセンサーは，別々に選べます．`load_config(..., sensors=[...], observe=[...])` と `Session.launch(..., sensors=[...], observe=[...])` で指定します．`None` は設定の既定，`[]` は選択なしです．フォロワの状態は常に渡します．`RobotConfig` を渡すときは，`load_config` で選択を確定してください．`Session.launch` は，追加の選択の引数を拒否します．

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

- CLIでは `--sensors camera,audio --observe camera`，空の選択は `--sensors "" --observe ""` です．ランチャーには，起動するセンサーと方策の観測のチェック欄が別々にあり，前回の選択を保存します．
- 選ばなかったセンサーのYAMLは読み込みません．起動していないセンサーを観測に指定するとエラーです．
- 左右のDIGITを含め，オプションで追加されるセンサーも個別に選べます．選択は，オプションを適用したあとに決まります．
- 任意のセンサーは `{file: nodes/audio.yaml, default: false}` と宣言します．従来の文字列のパスは，既定で有効です．
- `observe` に含めないセンサーも，起動すれば記録します．

設定の書き方は [センサー選択](../reference/configuration/sensors.md#sensor-selection) にあります．[音声](../sensors/audio.md)も参照してください．

## PiPER＋Pikaでの手順（模擬） <span class="status status--dev">開発中</span> { #piper-pika }

1. 模擬のSenseで記録します（[Pika SenseとIKによる遠隔操作](../controllers/pose-ik.md)）．

    ```bash
    uv run roboloom record piper-mock --task "pick" --seconds 15 --episodes 5 --home --plain
    ```

2. 記録したデータセットで，LeRobotの学習（`lerobot-train`）を行います（[LeRobotで学習する](lerobot.md#training)）．学習の前に `labstatus` でGPUの空きを確かめます．
3. 学習したチェックポイントで動かします．

    ```bash
    uv run roboloom infer piper-mock --seconds 20 --task "pick" \
      --policy roboloom.policy.lerobot:load \
      --policy-kwargs '{"path": "outputs/train/act_piper_mock/checkpoints/last/pretrained_model"}'
    ```

    `--task` を付けると，実行した回を評価のデータとして保存します．
