# Pika Senseを手に持った収集

!!! warning "開発中"
    ロボットを使わず，Pika Senseを手に持って集める仕組み（UMIに倣ったもの）の，開発中の記録です．模擬のSenseと模擬のカメラだけで確かめています．実機では動かしていません．集めたデータでPiPERを動かす推論は，まだありません．

## しくみ

1. **記録**：フォロワのない構成で，Senseごとの絶対の姿勢，挟みの角度，追跡の有無，engagedと，Senseの魚眼カメラを記録します．データセットに `action` はありません．
2. **変換**：`roboloom convert-handheld` で，記録を学習用の新しいデータセットにします．行動と状態を，Sense自身から見た相対の姿勢で表します．トラッカーの座標系とロボットの台座を合わせなくて済むようにするためです．
3. **学習**：変換したデータセットを，そのまま `lerobot-train` で学習します．

記録には生の値を残すので，同じ記録を別の表し方で変換し直せます．

## 構成

`.roboloom/pika-handheld-mock/` は，模擬のSense 2台（`left_sense`，`right_sense`）と，その魚眼カメラ（`left_wrist`，`right_wrist`）の構成です．

`.roboloom/pika-handheld-mock/` はroboloomのリポジトリにあり，インストールしたパッケージには入っていません（`roboloom init` のテンプレートは `rakuda2` だけです）．このページのコマンドは，cloneしたリポジトリのルートで実行します．自分のプロジェクトでは，[リポジトリ](https://github.com/tetsugo02/roboloom) からこのディレクトリを自分の `.roboloom/` にコピーして使えます．記録と変換には `record` extraが要ります（[インストール](../quick-start/installation.md)）．値は模擬のためのものなので，実機に使い回さないでください．

```yaml
trackers:  # 両方のSenseで1つのlibsurviveのコンテキスト
  lighthouse: nodes/lighthouse.yaml
inputs:
  left_sense: nodes/left_sense.yaml
  right_sense: nodes/right_sense.yaml
followers: {}  # なし：動かすものがなく，データセットに action がない
sensors:
  left_wrist: nodes/left_wrist.yaml
  right_wrist: nodes/right_wrist.yaml
```

- フォロワのない構成には，controllerを置けません．
- 入力とセンサーは，自分の周期を持つ必要があります．Senseは `poll_hz`（例：100），カメラは `fps` です．フォロワがないので，周期を借りる先がありません．
- Senseとトラッカーのノード `lighthouse` の書き方は [Pika SenseとIKによる遠隔操作](pika-sense.md) と同じです．カメラは [Pikaの手首カメラ](pika-cameras.md) と同じ `v4l2_rgb` です．

## 記録

```bash
uv run roboloom record pika-handheld-mock --task "pick" --seconds 15 --episodes 5 --plain
uv run roboloom run pika-handheld-mock     # 操作画面で
```

`observation.<Sense>` は10要素です．

| 名前 | 単位 | 意味 |
| --- | --- | --- |
| `x`，`y`，`z` | m | トラッカーの世界座標での位置 |
| `qx`，`qy`，`qz`，`qw` | 四元数 | 向き |
| `gripper` | rad | 挟みの角度 |
| `tracking` | 0/1 | 今の姿勢を追跡できているか．0の行の姿勢は，最後に追跡できた姿勢です |
| `engaged` | 0/1 | Senseのボタンで切り替わる状態 |

## 変換

```bash
uv run roboloom convert-handheld pika-handheld-mock --action delta
uv run roboloom convert-handheld pika-handheld-mock --action relative-chunk --horizon 16
```

| オプション | 既定 | 意味 |
| --- | --- | --- |
| `--action` | `delta` | 行動の表し方（下の表） |
| `--horizon` | 16 | `relative-chunk` の手数H |
| `--hands` | 記録した姿勢すべて | 使うSenseの名前（例：`left_sense,right_sense`） |
| `--max-gap` | 3 | 追跡が切れた行を埋める上限（行）．これより長く切れたエピソードは除き，理由を出します |
| `--output` | `<記録のoutput>-<action>` | 書き出す先（すでにあれば断ります） |
| `--repo-id` | `<repo_id>-<action>` | 新しいデータセットの名前 |

P[t] を行tのSenseの姿勢とします．相対の姿勢は，位置（3）と回転の6D表現（回転行列の最初の2列，6）の9要素で表します．

| 表し方 | `action`（Senseごと） | 使いどころ |
| --- | --- | --- |
| `delta` | inv(P[t])·P[t+1] と，t+1の挟みの角度．10要素 | LeRobotのACTやDiffusionを，設定を変えずに使えます．まとめた行動は，観測した姿勢から差分を積み重ねて目標にします．誤差は手数とともにたまりやすくなります |
| `relative-chunk` | k=1..Hの inv(P[t])·P[t+k] と，t+kの挟みの角度．H×10要素を1行に | UMIの表し方そのもので，誤差がたまりません．LeRobotでは `chunk_size=1` で学習します．ACTは使えますが，Diffusionは使いにくいです |

`observation.state` は，Senseごとの inv(P[t])·P[t-1]（速さの手がかり）とtの挟みの角度（10要素）です．Senseが2台以上なら，1台目から見た他のSenseの姿勢（9要素）を加えます．2台なら29要素です．

- 追跡が切れた行は，`--max-gap` 行までなら埋めます．間は，位置を線形に，回転をslerpで補います．エピソードの端では，最も近い追跡できた姿勢を使います．サンプルが届かなかった行（`observation.meta.<hand>.valid` が0．値は直前のサンプルの繰り返しで，最初のサンプルより前と古い版の記録ではすべて0）も，追跡が切れた行として扱います．
- 画像，`observation.<Sense>` の生の値，`observation.meta.*` は，そのまま残ります．動画は作り直さずに写します．
- 変換の条件（表し方，H，Sense，fps，除いたエピソード）は，`meta/roboloom_handheld.json` に残ります．

## 学習

```bash
# roboloomのリポジトリをcloneした中で
uv sync --extra policy --extra train
# 自分のプロジェクトで（recordなど，使っているextrasはそのまま残る）
uv add git+https://github.com/tetsugo02/roboloom.git --extra policy --extra train

# delta
uv run lerobot-train --dataset.repo_id=local/pika-handheld-mock-delta \
  --dataset.root=.roboloom/pika-handheld-mock/datasets/pika-handheld-mock-delta \
  --policy.type=act --policy.push_to_hub=false --wandb.enable=false \
  --output_dir=outputs/train/act_handheld_delta
# relative-chunk
uv run lerobot-train --dataset.repo_id=local/pika-handheld-mock-relative-chunk \
  --dataset.root=.roboloom/pika-handheld-mock/datasets/pika-handheld-mock-relative-chunk \
  --policy.type=act --policy.chunk_size=1 --policy.n_action_steps=1 \
  --policy.push_to_hub=false --wandb.enable=false \
  --output_dir=outputs/train/act_handheld_chunk
```

GPUで学習する前に，`labstatus` でGPUの空きを確かめてください．CPUで経路だけを確かめる方法は，[方策で動かす](../controllers/policy.md) の「LeRobotで学習する」にあります．

## 限界

- 実機（Sense，libsurvive，ベースステーション，魚眼カメラ）では確かめていません．
- SenseとPika Gripperで，魚眼カメラと挟みの位置関係が同じかを，まだ測っていません．違う場合，学習した方策はGripperの画像に合いません．
- 学習した方策でPiPERを動かす推論（相対の姿勢を目標に変え，IKで関節にする）は，まだありません．
- PiPERで実行できない動き（可動域，特異姿勢）を除く検査はありません．
- 推論の遅れに合わせて行動を進める仕組み（UMIの遅れの補償）はありません．
- 模擬のSenseは，左右で同じ動きをします．
