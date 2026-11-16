# Recording

`roboloom.recording` のうち，記録したデータセットを読む・検査する API です．列の一覧は [データセットの列](../dataset-features.md) に，手順は [データの検査と学習](../../data/check-and-train.md) にあります．このページは docstring から生成した説明（英語）を載せます．

## データセットの検査 { #check-dataset }

::: roboloom.recording.check.check_dataset
    options:
      heading_level: 3

::: roboloom.recording.check.DatasetReport
    options:
      heading_level: 3

## エピソードごとの記録 { #episodes }

::: roboloom.recording.episodes
    options:
      heading_level: 3
      members:
        - read
        - label
        - summary
        - total
        - saved
        - check_label

## 特徴量 { #features }

::: roboloom.recording.features
    options:
      heading_level: 3
