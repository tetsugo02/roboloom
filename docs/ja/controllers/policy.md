# 方策で動かす

`type: policy` のcontrollerは，学習した方策でフォロワを動かします．方策は，自分で書いたものでも，LeRobotのチェックポイントでも，同じ仕組みで読み込みます．

!!! warning "確かめた範囲"
    自作の方策の経路は，Rakuda2の構成と模擬で使っています．LeRobotの方策（`roboloom.policy.lerobot`）は，模擬のPiPER＋Pikaの構成だけで確かめています．模擬で記録したデータを `lerobot-train` でCPUで短く学習したACTで，記録から推論までを通しました．実機と，十分に学習した方策では，まだ確かめていません．

## 設定

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

- `factory` のモジュールは，インストール済みのパッケージを先に探し，見つからなければロボットのディレクトリ（`.roboloom/<robot>/`）を探します．
- `roboloom infer` は，`policy` という名前のオプションを自動で有効にします．`--policy` と `--policy-kwargs` で，YAMLを書き換えずに方策を差し替えられます．

```bash
uv run roboloom infer piper-mock --seconds 20 \
  --policy roboloom.policy.lerobot:load --policy-kwargs '{"path": "outputs/act/pretrained_model"}'
```

## 観測を選ぶ

Rakuda2のテンプレートは，DIGITなしで関節状態とRealSenseを方策に渡します．`nodes/policy.yaml` の `observe` を，学習時に使った入力に合わせます．フォロワの関節状態は常に渡されます．

| 方策に渡す観測 | `observe` | 有効にするオプション |
| --- | --- | --- |
| 関節状態＋RealSense（既定） | `[camera]` | `policy` |
| 関節状態＋RealSense＋左右DIGIT | `[camera, digit_left, digit_right]` | `digit`，`policy` |
| 関節状態のみ | `[]` | `policy` |

`digit` を有効にするだけでは，方策の入力は変わりません．`observe` に追加したセンサーは，`sensors` にも存在する必要があります．`observe` から外しても，`sensors` にあるセンサーは開いて記録します．カメラも使わない構成では，`config.yaml` の `sensors` から `camera` を外してください．

DIGITを入力とする学習済み方策を，DIGITなしでそのまま使えるわけではありません．DIGITなしの入力で学習した方策を使います．LeRobotの読み込みは，必要な入力が足りなければ開始前に拒否します．自作の方策では `bind(spec)` で同じ検査を書けます．

既存プロジェクトの設定は，パッケージ更新では上書きされません．以前のテンプレートから移行するときは，`config.yaml` の `options.policy` から `requires: [digit]` を削除し，`nodes/policy.yaml` を `observe: [camera]` に変更します．評価の保存先はDIGITなしなら `datasets/rakuda2-eval`，`digit` も有効なら `datasets/rakuda2-digit-eval` です．

## 自作の方策

`reset()` と `infer(observation)` を持つオブジェクトを返す関数を書きます（`roboloom.Policy`）．

```python
# .roboloom/<robot>/my_policy.py か，インストールしたパッケージ
import numpy as np


class MyPolicy:
    def __init__(self, checkpoint: str): ...

    def bind(self, spec):  # 任意．読み込みの直後に1回呼ばれる
        if "observation.images.left_wrist" not in spec.observation:
            raise ValueError("left_wrist を observe に加えてください")

    def reset(self): ...  # エピソードの始めに呼ばれる

    def infer(self, observation) -> np.ndarray:
        state = observation["observation.state"]  # float32 [n]
        image = observation["observation.images.left_wrist"]  # uint8 [h, w, 3]，RGB
        task = observation["task"]
        return self.model(state, image, task)  # [n] か [H, n]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

- **観測**：キーは記録したデータセットの特徴量と同じです（`observation.state`，`observation.images.<名前>`，`observation.<入力の名前>` など）．値はnumpyで，画像は `[h, w, 3]` のuint8（RGB）です．`task` も渡されます．
- **出力**：関節の目標値を，記録した `action` と同じ並び（フォロワを設定の順につないだもの）と単位で返します．1手 `[n]` か，まとめた行動 `[H, n]` です．
- ロボットごとの観測の名前と大きさ，行動の並び・要素数・単位は，各ロボットのページにあります（[Rakuda2](../robots/rakuda2.md)，開発中の [PiPER](../contribution/piper.md)）．
- **`bind(spec)`（任意）**：読み込みの直後，エピソードより前に1回呼ばれます．`spec`（`roboloom.policy.PolicySpec`）の中身は次のとおりです．
  - `observation`：観測の名前ごとの `dtype`，`shape`，`names`
  - `action`：行動の各要素の名前（`left.joint1`，…，`right_gripper.gripper`）
  - `rate_hz`，`dataset_fps`

  学習したときと違う構成なら例外を出してください．controllerは `failed` になり，理由を画面に出して，エピソードを始めません．`roboloom infer` と `Session.wait_ready` は，待たずに理由を示して終わります．`bind` を書かない方策も，これまでどおり動きます．

### 履歴，動かさない関節，新しい観測

最新のフレーム以外にモデルが要るものは，controllerに頼みます．モデルを作り替えるたびに書き直す必要はありません．正規化，画像の縮小，モデル独自の行動（差分，一部の関節だけ）を関節の目標へ直す処理は，方策の側に書きます．

```yaml
observation_history: 4                       # 既定は1：最新のフレームだけ
hold: [follower.torso_yaw, follower.head_yaw, follower.head_pitch]  # 既定は []
```

- **`observation_history: N`**：観測を行動1手ごと（`1/rate_hz` ごと）に1回採ります．まとめた行動のうち推論しない手でも採ります．`infer` には `observation["history"]` も渡ります．観測の各配列を `[N, ...]` に重ねたもので，古い順に並び，最後が今のフレームです．エピソードの始めは，最初のフレームで履歴を埋めます．`history["action"]`（float32 `[N, n]`）は，各フレームの前に実行した行動です（始めはフォロワが保持していた目標）．過去の行動を読むモデルに使います．`N = 1` なら観測は今までと同じです．
- **`hold`**：行動のうち方策が動かさない要素（`<フォロワ>.<関節>`）です．方策がそこに何を返しても（NaNでも），フォロワが保持している目標に置き換えます．一部の関節だけで学習したモデルも，`[n]` か `[H, n]` を返せば済みます．ほかの要素は有限でなければならず，そうでなければエピソードを止めます．
- **`options()`（任意）**：方策が自分でこれらを指定できます．YAMLより優先します．モデルを差し替えても設定を書き換えずに済みます．

    ```python
    def options(self) -> dict:
        return {"observation_history": 4, "hold": ["follower.torso_yaw"], "action_horizon": 8}
    ```

- `bind(spec)` には `spec.history`，`spec.hold`，`spec.units`（行動の各要素の単位）も渡ります．
- **新しい観測だけを使う**：観測する入力やセンサーの最新の値が，recorderの `max_age_ms.<ノード>` より古いと，方策を止めます（controllerの行に `stale_observation`）．指令を送らず，フォロワは保持します．値が新しくなると，方策を `reset()` して始め直します．

### 記録から自分のモデルまで

roboloomはモデルの形を決めません．方策には，記録と同じ観測，その履歴，実行した行動を渡し，関節の絶対目標を受け取ります．モデルごとに変わる処理は方策の側に書きます．

| 処理 | 書く場所 |
| --- | --- |
| モデルが動かす関節の選択 | 方策．ほかの関節には何を返してもよく（NaN），その関節を `hold` に挙げる |
| 正規化（学習データの統計） | 方策．統計はチェックポイントと一緒に保存する |
| 画像の縮小や切り出しなどの前処理 | 方策 |
| 行動の形（状態からの差分，一部の関節だけ） | 方策が `infer` の中で絶対目標に戻す |
| 観測の履歴，過去の行動 | roboloom（`observation_history`） |
| 記録より低い行動周期 | k行おきに学習し，`rate_hz` を `dataset_fps / k` にする |
| 制御周期への補間，速度の制限，安全の検査 | roboloom |

リポジトリの `examples/policies/chunk_mlp.py` は，これらを一通り行う小さなモデルです（関節状態だけを使い，CPUで数秒で学習できます）．記録したデータセットの `observation.state` と `action` の列を読んで学習し，統計・動かす関節・履歴の長さをチェックポイントに保存して，`options()` でroboloomに伝えます．

```bash
uv run python examples/policies/chunk_mlp.py train \
    --dataset .roboloom/rakuda2/datasets/rakuda2 --out outputs/chunk_mlp.pt \
    --history 4 --horizon 8 --stride 3 --exclude torso_yaw head_yaw head_pitch
PYTHONPATH=examples/policies uv run roboloom infer rakuda2 --seconds 20 \
    --policy chunk_mlp:load --policy-kwargs '{"checkpoint": "outputs/chunk_mlp.pt"}'
```

15 fpsの記録で `--stride 3` なら，方策の周期は5 Hzです．`nodes/policy.yaml` を `rate_hz: 5` にします．学習でデータセットを読むとき，表の列（`observation.state`，`action`，`action.valid`，`episode_index`，`index`）は `LeRobotDataset(...).hf_dataset` にあります．画像は `dataset[i]` で1行ずつ復号します．

### 記録を再生する

`roboloom.policy.replay:load` は，記録した1エピソードの `action` を，観測に関係なくフォロワへ送ります．学習した方策と同じ経路（controller，速度の制限，補間，安全の検査）を通るので，モデルなしでその経路を確かめられます．再生を記録すれば，その `observation.state` を元のエピソードと比べられます．

```bash
uv run roboloom infer rakuda2 --seconds 20 --home --task replay \
    --policy roboloom.policy.replay:load \
    --policy-kwargs '{"path": ".roboloom/rakuda2/datasets/rakuda2", "episode": 0}'
```

- `path` は，記録したデータセットか，行動を並べた `.npy` ファイル（`[T, n]`）です．`.npy` は，別の道具で記録したデータの関節の並びと単位を確かめるのに使えます．`stride: k` はk行おきに取ります（`rate_hz` は `dataset_fps / k`）．`horizon` はまとめて渡す手数です．
- データセットの行動の名前と周期を，読み込むときに構成と照らします．
- 始める前に，エピソードの最初の姿勢へロボットを動かしてください（`home`）．最初は `max_speed` を低くします．最後の行動のあと，フォロワはそこに留まります．

### 方策を別のプロセスで動かす { #running-the-policy-in-another-process }

roboloomを動かす環境に依存関係が入らないモデル（torchの版が違うなど）や，別のマシンで動かしたいモデルは，自分のプロセスから提供します．方策ノードは `roboloom.policy.remote:connect` でそこへつなぎます．`bind`，`reset`，`infer`，`options` はそのまま渡るので，方策の書き方は上と同じです．

```bash
# モデルのある側：そのモデルの環境．roboloomはextraなしで入れる
export ROBOLOOM_POLICY_AUTHKEY=some-shared-secret
uv run roboloom serve-policy my_lab.policies:load --kwargs '{"checkpoint": "..."}'
# roboloomのコマンドを使わない場合：python -m roboloom.policy.remote my_lab.policies:load
```

```yaml
# nodes/policy.yaml（roboloomを動かす環境にも同じ ROBOLOOM_POLICY_AUTHKEY が要る）
factory: roboloom.policy.remote:connect
kwargs: {address: "127.0.0.1:18765"}   # timeout_s: 30 は infer 1回の上限
```

- サーバーはモデルを1回だけ読み込み，方策ノードを1つずつ相手にします．エピソードやセッションをまたいで使えます．`roboloom infer` より先に起動してください．ノードは `connect_timeout_s`（30秒）まで待ちます．
- サーバー側に要るのは，numpyとextraなしのroboloomだけです（LeRobotも，roboloomが入れるtorchも要りません）．
- 方策が出した例外は，同じプロセスの方策と同じく，controllerの行に出ます．
- 共有する秘密の文字列で両側を認証します．通信は暗号化しません．アドレスはループバックか，信頼できるネットワークにしてください．メッセージはJSONのヘッダと配列の生のバイト列です（pickleは使いません）．
- ネットワーク越しでは，`infer` のたびに観測を送ります（480×640の画像1枚で約0.9 MB，`observation_history` の枚数分）．

## LeRobotの方策

`roboloom.policy.lerobot:load` は，LeRobotで学習したチェックポイントを読み込む，既製の方策です．

```yaml
factory: roboloom.policy.lerobot:load
kwargs:
  path: outputs/train/act_piper/checkpoints/last/pretrained_model  # HubのIDも可
  device: auto        # CUDAがあればcuda，なければcpu
  mode: step          # step か chunk
  rename: {}          # {チェックポイントの名前: roboloomの名前}
action_horizon: 1     # mode: step のとき
```

| キー | 意味 |
| --- | --- |
| `path` | チェックポイントのディレクトリ（`config.json`，`model.safetensors`，`policy_preprocessor.json` などを含む）か，Hugging Face HubのID |
| `device` | `auto`（既定），`cpu`，`cuda` など |
| `mode` | `step`（既定）：LeRobotの `select_action` で1手ずつ返します．まとめた行動の列と観測の履歴は方策自身が持つので，ACT・Diffusion・SmolVLAのどれでも，LeRobotのrolloutと同じに動きます．`action_horizon: 1` で使います．`chunk`：`predict_action_chunk` でまとめた行動 `[H, n]` を返し，`action_horizon` 手を実行してから次を求めます．観測の履歴を使わない方策（ACTなど）に限ります |
| `rename` | チェックポイントの特徴量の名前を，この構成の名前に対応させます．例：`{observation.images.wrist: observation.images.left_wrist}` |
| `revision` | Hubのリビジョン（任意） |

- 読み込みは，LeRobot 0.6.1のrolloutと同じ手順です．設定と重み，保存された前処理と後処理（正規化の統計を含む）をチェックポイントから読みます．
- 読み込むときに，チェックポイントの入力と出力を，この構成の観測とフォロワと照らします．足りない観測や大きさの違いがあれば，名前を挙げて断ります．
  - 入力として照らすのは，LeRobotの方策が読むもの（`observation.state`，`observation.images.*`，`observation.environment_state`）です．
  - LeRobotの学習は，データセットの `observation.*` をすべて入力として記録します（`observation.meta.*`，`observation.effort`，Pika Senseの `observation.left_sense` など）．LeRobotの方策はこれらを読まないので，推論の構成になくても構いません．
  - 出力として照らすのは `action` の次元です．
- 必要なもの：`uv add 'roboloom[policy]'`（このリポジトリでは `uv sync --extra policy`）．torchも一緒に入ります．ACTはこれで足ります．Diffusionは `lerobot[diffusion]`，SmolVLAは `lerobot[smolvla]`，pi0は `lerobot[pi]` が別に要ります．
- GPUで推論するときや学習するときは，始める前に `labstatus` でGPUの空きを確かめてください．

## LeRobotで学習する

roboloomが記録したデータセット（LeRobotDataset v3.0）は，そのまま `lerobot-train` で学習できます．

```bash
# 学習に lerobot[training]（accelerate，wandb）が要ります
uv add git+https://github.com/tetsugo02/roboloom.git --extra policy --extra train   # 自分のプロジェクトで
uv sync --extra policy --extra train                                                # roboloomのリポジトリをcloneした中で
uv run lerobot-train \
  --dataset.repo_id=local/piper-mock \
  --dataset.root=.roboloom/piper-mock/datasets/piper-mock \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --wandb.enable=false \
  --output_dir=outputs/train/act_piper_mock
```

- `--dataset.repo_id` は構成の `repo_id`，`--dataset.root` はロボットのディレクトリから見た `output` です．
- 学習したチェックポイントは `<output_dir>/checkpoints/last/pretrained_model` にできます．これを `path` に渡します．名前は記録したときのままなので，`rename` は要りません．
- `lerobot-train` は，データセットの `observation.*` をすべて入力に，`action*` をすべて出力に数えます（`observation.meta.*`，`observation.effort`，`action.valid`，`action.meta.*` など）．ACTが読むのは `observation.state`，画像，`action` だけで，ほかは学習にも推論にも使われません．
- `action.valid` が0の行（入力が操作していない間など）の `action` には，フォロワが保持している目標が入ります．方策は，その間は止まっていることを学びます．
- 試しに経路だけを確かめるなら，`--policy.device=cpu --steps=200 --batch_size=8` で数分です．ネットワークにつながらないときは，`--policy.pretrained_backbone_weights=null` でbackboneの重みを取りに行きません（学習の質は落ちます）．
- GPUで学習する前に，`labstatus` でGPUの空きを確かめてください．

## 周期と手数

- 方策ノードは，`rate_hz` の周期で行動を1手ずつ取り出します．並んでいる行動がなくなると，`infer` を呼びます．
- `rate_hz` は，学習に使ったデータセットの `dataset_fps` に合わせます．指令を速くするために `rate_hz` を上げると，行動の列を学習時より速く使い切ってしまいます．
- `infer` の間は指令を送りません（同期）．推論が `command_deadline_ms` より長くかかると，フォロワはHOLDに入り，止まって待ちます．画面のcontrollerの行に，推論の時間（`infer_ms`，`infer_max_ms`）が出ます．

### 行動の補間

方策ノードは `rate_hz × N`（N は `interpolation_multiplier`）の周期で指令を送ります．行動はN回の指令ごとに1手取り出し，その間は1つ前の行動から今の行動までの直線をN等分した目標を送ります．行動の時間の間隔は学習時のまま，フォロワには細かい目標が届きます．

N を書かなければ（または `auto`），`rate_hz × N` が整数のHzで，いちばん遅いフォロワの `control_hz` 以下になる最大のNを使います．フォロワが受け取れる限り細かく指令を送ります．

| `rate_hz` | フォロワの `control_hz` | 計算されるN | 指令の周期 |
| --- | --- | --- | --- |
| 15 | 120（Rakuda2） | 8 | 120 Hz |
| 5 | 120 | 24 | 120 Hz |
| 7.5 | 120 | 16 | 120 Hz |
| 30 | 30 | 1（補間しない） | 30 Hz |

数を書くと，その値を使います．`1` は補間せず，行動を1手ずつ送ります．

```yaml
rate_hz: 5                    # 5 Hz で学習した方策
interpolation_multiplier: 12  # 指令を 60 Hz に抑える（省略すると 24，120 Hz）
```

- LeRobotのrollout（`lerobot.utils.action_interpolator.ActionInterpolator` の `interpolation_multiplier`）と同じ方法です．違いは最初の1手だけです．LeRobotは最初の行動をそのまま送りますが，roboloomはフォロワが保持している目標から最初の行動まで補間します．
- フォロワが各行動に着くのは，その行動が出てから1手分（`1/rate_hz`，5 Hzなら200 ms）あとです．
- 数を書くときは，`rate_hz × N` を整数のHzで，どのフォロワの `control_hz` 以下にします．それ以外は読み込み時に拒否します．`rate_hz` が整数のHzにできない値（7.33 など）のときは，計算されるNは1です．
- 使っているNは，操作画面の方策の行に `interpolation` として出ます．
- 評価で記録するデータセットの `action` は，フォロワに実際に送った補間後の目標です．
- まとめた行動の境目では，`infer` の間だけ補間も止まります．次の行動は，止まる前に着いた行動から続けます．
- 送る目標は，フォロワが保持している目標から `max_speed` の分までに切り詰め，`FollowerSafety` が可動域と期限を検査します．遠隔操作と同じです．

## 初期姿勢から始める（home）

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

## テレオペと介入（teleop）

`teleop:` を書いた方策では，leaderでフォロワを動かせます．エピソードの前に開始姿勢を合わせ，`start` で方策に渡し，エピソードの途中で人が介入して，また方策に戻せます．

```yaml
# nodes/policy_teleop.yaml（Rakuda2 のオプション policy_teleop）
teleop: [controller.yaml]   # leaderで動かすときの controller（このファイルの隣）
```

| 操作（session の命令） | エピソードの外 | エピソード中 |
| --- | --- | --- |
| Teleop（`teleop`，キー `t`） | 記録せずに，leaderでフォロワを動かす | 方策を止めて，leaderに切り替える（介入） |
| Policy（`policy`，キー `p`） | 使えない（`start` で方策が始まる） | leaderから方策に戻す |
| Stop teleoperating（`stop_teleop`） | leaderでの操作を終え，その場で保持する | 使えない（`stop` を使う） |
| Start（`start`） | 方策と記録を始める．Teleop の後なら，そこから方策が引き継ぐ | ― |

- **関節ごとにつかまえる**：Teleop を押すと，フォロワの関節はすべて今の目標で止まります．leaderの関節が，その関節の値に `alignment_tolerance`（teleop の controller の値）以内まで近づくか，値をまたぐと，その関節から順にleaderに追従します．操作画面の方策の行に，まだつかまえていない関節と残りの差（`pickup`）が出ます．
- グリッパーは，トリガーをフォロワの開き具合まで握り込むまで動きません．介入した瞬間に，つかんでいる物を落とすことはありません．
- 方策に戻すとき（Policy）は，方策の履歴を消し（`policy.reset()`），フォロワが保持している目標から補間を始め直します．
- 記録では，人が動かした行を `action.intervention`（1）で区別します．`teleop:` のある構成だけにある特徴量です．leaderも入力として記録されるので，データセット名は別になります（Rakuda2 では `-eval-teleop`）．
- エピソードの外のTeleopは記録しません．エピソードの最初の1〜2行は，`start` の直前の人の指令が残ることがあり，`action.intervention` が1になります．
- Pythonでは `Session.teleop()`，`Session.policy()`，`Session.stop_teleop()` を使います．
- 対応する teleop の controller は `type: joint` だけです．`pose_ik`（PiPER＋Pika Sense など）は，読み込み時に「介入に未対応」として断ります．
- フォロワがESTOP・FAULTになったとき，信号が途絶えたときは，Teleop も止まります．もう一度 Teleop を押すと，その時点から関節ごとにつかまえ直します．

## 限界

- 推論しながら前の行動を実行し続ける非同期の推論と，LeRobotのRTCには対応していません．
- ACTの時間方向の平均（`temporal_ensemble_coeff`）は，`mode: step` のときだけ働きます．

## PiPER＋Pikaでの手順（模擬）

1. 模擬のSenseで記録します（[Pika SenseとIKによる遠隔操作](../contribution/pika-sense.md)）．

    ```bash
    uv run roboloom record piper-mock --task "pick" --seconds 15 --episodes 5 --home --plain
    ```

2. 記録したデータセットで，LeRobotの学習（`lerobot-train`）を行います（上の「LeRobotで学習する」）．学習の前に `labstatus` でGPUの空きを確かめます．
3. 学習したチェックポイントで動かします．

    ```bash
    uv run roboloom infer piper-mock --seconds 20 --task "pick" \
      --policy roboloom.policy.lerobot:load \
      --policy-kwargs '{"path": "outputs/train/act_piper_mock/checkpoints/last/pretrained_model"}'
    ```

    `--task` を付けると，実行した回を評価のデータとして保存します．

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
