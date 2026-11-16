# 評価と再生

方策を走らせた回の成否を残す方法と，記録した行動を方策の経路で再生する方法です．

## 評価の成否を残す { #labels }

`roboloom infer --task <text>`（Pythonでは `record`）で保存した回は，評価のデータセットに入ります．それぞれの回が成功したかどうかは，エピソードごとの記録（データセットの `meta/roboloom_episodes.jsonl`）に残せます．

```bash
uv run roboloom infer --seconds 30 --episodes 10 --task "pick up the cup"
uv run roboloom label --with policy 3 failure --note "つかみ損ねた"   # あとから，エピソード3に
uv run roboloom check-dataset --with policy                            # labels: 7 success, 3 failure, ...
```

- 保存のときに付けることもできます：操作画面の入力欄で `save success`・`save failure`，別端末から `roboloom session save success`，Pythonでは `record(..., label=...)`・`save(label=...)`（下の「Pythonから」）．
- あとから付ける・付け直すときは `roboloom label [robot] <エピソード番号> success|failure` を使います（[CLI](../reference/cli.md#label)）．`roboloom check-dataset` が成否の数を表示します（[CLI](../reference/cli.md#check-dataset)）．
- 記録には，その回の方策の状態（推論時間 `infer_max_ms`，非同期の推論で遅れて捨てた手数 `dropped`，エラー）と，recorderの指標も入ります．項目は [エピソードごとの記録](../data/recording.md#episode-records) にあります．
- 途中で方策が失敗した回は保存されないので，記録にも入りません．
- このファイルをLeRobotは読みません．学習には影響しません．

### Pythonから { #labels-python }

- `record(..., label="success")` と `save(label="failure", note="...")` で，保存するエピソードに成否（`success` か `failure`）とメモを付けられます．
  - `record` の `label` には，停止したエピソード（`result`）を受け取って成否を返す関数も渡せます．`None` を返すと成否を付けません．
  - `success`・`failure` 以外の文字列は，保存の前に `ValueError` になります．
- 保存のたびに，データセットの `meta/roboloom_episodes.jsonl` に1行を書きます．成否を付けなくても書きます．
- あとから付ける・付け直すときは，`roboloom.recording.episodes.label(...)` も使えます（[Python API：記録](../reference/python-api/recording.md)）．

```python
from roboloom.recording import episodes

for k in range(10):
    s.record(
        "pick up the cup",
        seconds=30,
        label=lambda ep: "success" if cup_lifted() else "failure",  # 利用者の判定
    )
records = episodes.read(s.cfg.output)  # {エピソード番号: 記録}
print(episodes.summary(s.cfg.output, s.episodes))
# labels: 7 success, 3 failure, 0 not labelled (70% of the labelled)
```

## 記録を再生する <span class="status status--mock">模擬のみ</span> { #replaying-a-recording }

`roboloom.policy.replay:load` は，記録した1エピソードの `action` を，観測に関係なくフォロワへ送ります．学習した方策と同じ経路（controller，速度の制限，補間，安全の検査）を通るので，モデルなしでその経路を確かめられます．再生を記録すれば，その `observation.state` を元のエピソードと比べられます．

```bash
uv run roboloom infer rakuda2 --seconds 20 --home --task replay \
    --policy roboloom.policy.replay:load \
    --policy-kwargs '{"path": ".roboloom/rakuda2/datasets/rakuda2", "episode": 0}'
```

- `path` は，記録したデータセットか，行動を並べた `.npy` ファイル（`[T, n]`）です．`.npy` は，別の道具で記録したデータの関節の並びと単位を確かめるのに使えます．`stride: k` はk行おきに取ります（`rate_hz` は `dataset_fps / k`）．`horizon` はまとめて渡す手数です．
- データセットの行動の名前と周期を，読み込むときに構成と照らします．
- `inference: async` とは組み合わせられません（読み込むときに断ります）．再生は観測に関係なく行を順に返すので，並んでいる行動を入れ替えると，記録した行が飛びます．
- 始める前に，エピソードの最初の姿勢へロボットを動かしてください（[home](run.md#home)）．最初は `max_speed` を低くします．最後の行動のあと，フォロワはそこに留まります．
