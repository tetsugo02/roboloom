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
rate_hz: 10
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
uv sync --extra policy --extra train   # 学習に lerobot[training]（accelerate，wandb）が要ります
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

- 方策ノードは，`rate_hz` の周期で指令を1つ送ります．並んでいる行動がなくなると，`infer` を呼びます．
- `infer` の間は指令を送りません（同期）．推論が `command_deadline_ms` より長くかかると，フォロワはHOLDに入り，止まって待ちます．画面のcontrollerの行に，推論の時間（`infer_ms`，`infer_max_ms`）が出ます．
- `rate_hz` は，学習に使ったデータセットの `dataset_fps` に合わせます．
- 送る目標は，フォロワが保持している目標から `max_speed` の分までに切り詰め，`FollowerSafety` が可動域と期限を検査します．遠隔操作と同じです．

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
