# 装置なしで一周する

<span class="status status--mock">模擬のみ</span>

- **目的**：模擬のdeviceで，起動，記録，保存，検査を一周する．
- **前提**：roboloomのrepositoryをcloneし，Python 3.12以上（3.12〜3.14で試験済み）とuvがある．`examples/` はcloneした中だけにあり，installしたpackageには入っていない．
- **所要**：15分．
- **結果**：`datasets/rakuda-mock` に2 episodeのLeRobotDatasetができ，`check-dataset` が `problems: none` を返す．

`examples/mock/config.yaml` は，模擬のRakuda（leader，follower）とcamera，左右のDIGIT，音声の構成です．実機の値を使わないので，何も測らずに動きます．

## 1. 環境を作る

```bash
git clone https://github.com/tetsugo02/roboloom.git
cd roboloom
uv sync --extra rakuda2 --extra record
```

## 2. 設定を検証する

```bash
uv run roboloom validate examples/mock/config.yaml
```

`Valid: ... (9 nodes; options: none; dataset: local/rakuda-mock; ...)` と出れば，設定とdataflowの組み立てが通っています．`validate` はdeviceを開きません．

## 3. 操作画面で動かす

```bash
uv run roboloom run examples/mock/config.yaml
```

1. launcherで操作 `run` を選び，Launch（Ctrl-S）を押します．
2. 画面で全nodeの状態とsensorの取得周期を見ます．controllerが `following` になるのを待ちます．
3. 入力欄（Ctrl-L）に `start mock demo` と入れ，数秒後に `stop`，`save` と入れます．
4. `quit` で終了します．

各操作の意味は [runの操作](../reference/cli.md#run-operations)，画面のkeyは [操作画面](../reference/operator-screen.md) にあります．

## 4. 長さを決めて記録する

```bash
uv run roboloom record examples/mock/config.yaml --task "mock demo" --seconds 5 --episodes 2 --plain
```

`--plain` はkey入力なしで記録します．[background保存](../data/recording.md#background-saving) <span class="status status--mock">模擬のみ</span> では，episodeごとに保存待ちを報告し，最後に処理を待って2件の保存結果をdataset内の番号付きで表示します．保存先は `datasets/rakuda-mock` です（`output` は設定からの相対path）．

## 5. 記録を検査する

```bash
uv run roboloom check-dataset examples/mock/config.yaml
```

| 出力 | 見るところ |
| --- | --- |
| `episodes`，`frames`，`fps` | episode数と行数．`fps` は設定の `dataset_fps`（10） |
| `problems` | `none` なら壊れたfileはない |
| `notes` | `*.valid` が0の行の割合．模擬でも最初の行などで少し出る |

検査の項目は [検査と学習](../data/check-and-train.md#check-dataset) にあります．

## 次へ

- 方策を書いて模擬で動かす：[自作の方策を動かす](custom-policy.md)
- 自分のrobotを足す：[自分のrobotを足す](own-robot.md)
- 実機のRakuda2で始める：[Rakuda2：機体設定と読み取り確認](rakuda2/setup.md)
