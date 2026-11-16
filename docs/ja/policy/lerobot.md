# LeRobotの方策 <span class="status status--mock">模擬のみ</span>

`roboloom.policy.lerobot:load` は，LeRobotで学習したチェックポイントを読み込む，既製の方策です．roboloomが記録したデータセットは，そのまま `lerobot-train` で学習できます．

!!! warning "確かめた範囲"
    LeRobotの方策は，模擬のPiPER＋Pikaの構成だけで確かめています．模擬で記録したデータを `lerobot-train` でCPUで短く学習したACTで，記録から推論までを通しました．実機と，十分に学習した方策では，まだ確かめていません．

## チェックポイントを読み込む { #loading }

```yaml
factory: roboloom.policy.lerobot:load
kwargs:
  path: /path/to/project/outputs/train/act_piper/checkpoints/last/pretrained_model  # HubのIDも可
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
- ACTの時間方向の平均（`temporal_ensemble_coeff`）は，`mode: step` のときだけ働きます（[限界](index.md#limitations)）．

## LeRobotで学習する { #training }

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
- `action.valid` が0の行（入力が操作していない間など）の `action` には，フォロワが保持している目標が入ります．方策は，その間は止まっていることを学びます．LeRobotは `valid` の列で行を選びません（[欠損の扱い](../data/format.md#missing-data)）．
- 試しに経路だけを確かめるなら，`--policy.device=cpu --steps=200 --batch_size=8` で数分です．ネットワークにつながらないときは，`--policy.pretrained_backbone_weights=null` でbackboneの重みを取りに行きません（学習の質は落ちます）．
- GPUで学習する前に，`labstatus` でGPUの空きを確かめてください．
- 学習の前にデータセットを検査し，悪いエピソードを除く方法は [検査と学習](../data/check-and-train.md) にあります．
