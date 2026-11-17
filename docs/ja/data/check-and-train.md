# 検査と学習

記録したdatasetを学習の前に検査し，使わないepisodeを除いて，LeRobotで学習する手順です．

## datasetを検査する { #check-dataset }

`roboloom check-dataset [robot]` は，datasetを読むだけで検査します（[CLI](../reference/cli.md#check-dataset)）．robotの名前（`--with`・`--without` で記録したときのoption）か，datasetのdirectoryを指定します．

```bash
uv run roboloom check-dataset --with policy
```

| 出力 | 中身 |
| --- | --- |
| 要約 | episode数，行数，fps，robot，記録したroboloomの版，fileの数．episodeごとの記録があれば成否の数（`labels: 7 success, 3 failure, ...`） |
| `problems` | 壊れているところ：読めないfile，`info.json` とepisodeのmetadataの数の食い違い，episode番号の飛び，動画の欠落と動画と行数の不一致，書きかけのepisode |
| `notes` | 学習の前に知っておくべきこと：`*.valid` の列ごとの，0の行の割合．`action` がすべて0の行の割合（指令のない行を保持した目標で埋める前に記録したもの） |

- `problems` があると，終了code 1で終わります．
- 保存の途中でprocessが止まり，書きかけのepisodeが残っているときは，`--recover` で取り除いてから検査します．同じdatasetに記録し直しても取り除かれます（[保存したepisodeの扱い](recording.md#saved-episodes)）．
- `valid` の意味は [有効flag](format.md#valid)，0の行の値は [欠損の扱い](format.md#missing-data) にあります．

## 悪いepisodeを除く { #excluding-episodes }

episodeごとの指標（[episodeごとの記録](recording.md#episode-records)）から，学習に使うepisodeを選べます．

```python
from roboloom.recording import episodes

records = episodes.read(".roboloom/rakuda2/datasets/rakuda2")
keep = [
    index
    for index, record in sorted(records.items())
    if record.get("metrics", {}).get("action_valid_rate", 0) >= 0.9
]
print(keep)
```

選んだ番号を `lerobot-train` の `--dataset.episodes` に渡すと，そのepisodeだけで学習します．

```bash
uv run lerobot-train \
  --dataset.repo_id=local/rakuda2 \
  --dataset.root=.roboloom/rakuda2/datasets/rakuda2 \
  --dataset.episodes='[0, 1, 3, 4]' \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --trackio.enable=false \
  --output_dir=outputs/train/act_rakuda2
```

- `--dataset.episodes` は行を選ぶだけです．正規化の統計は，dataset全体の `meta/stats.json` のまま使います．除いたepisodeに外れた値がある場合は，次の方法で除いたdatasetを作ります．
- LeRobotの `lerobot-edit-dataset --operation.type delete_episodes --operation.episode_indices "[2, 5]"` は，episodeを除いた新しいdatasetを作り，残したepisodeの統計を集め直します（`--root` と `--new_root`，`--new_repo_id` で場所を指定します）．episodeの番号は0から振り直されます．roboloomのfile（`meta/roboloom.json`，`meta/roboloom_episodes.jsonl`）は新しいdatasetに写りません．
- dataset全体の統計を計算し直すときは，`lerobot-edit-dataset --operation.type recompute_stats` を使います．
- どちらも `lerobot[dataset]` が要ります．`--extra train`（`lerobot[training]`）で入ります．roboloomではこれらの道具の動作を確かめていません．使い方はLeRobotの説明を参照してください．
- `lerobot-train` の `--dataset.*` には，`action.valid` などで行を選ぶ設定はありません．行を選ぶときは，`LeRobotDataset(...).hf_dataset` を読んで自分で除いてください（[欠損の扱い](format.md#missing-data)）．

## LeRobotで学習する { #training }

roboloomが記録したdataset（LeRobotDataset v3.0）は，そのまま `lerobot-train` で学習できます．必要なextra，command，学習したcheckpointの使い方は [LeRobotで学習する](../policy/lerobot.md#training) にあります．

- `--dataset.repo_id` は構成の `repo_id`，`--dataset.root` はrobotのdirectoryから見た `output` です．
- `lerobot-train` は `*.valid` の列を見ません．`action.valid` が0の行の `action` には，followerが保持している目標が入ります．
- GPUで学習する前に，`labstatus` でGPUの空きを確かめてください．
- 自作のmodelを学習する例は [記録から自分のmodelまで](../policy/custom.md#from-recording-to-model) にあります．
