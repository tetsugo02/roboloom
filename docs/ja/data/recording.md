# 記録と再開

episodeを保存・破棄する流れと，保存したdatasetに残るものです．recorderの設定keyは [recorderの設定](../reference/configuration/recorder.md#recorder)，commandは [CLI](../reference/cli.md#record) にあります．

## 保存と破棄 { #save-and-discard }

- episodeは `start` で始まり，`stop` で止まります．止めたepisodeは，`save` で保存するか `discard` で捨てます．`roboloom record` と `Session.record` は，止めたあと保存します（[残すepisodeを選ぶ](#choosing-episodes)）．
- `save()` が返ったepisodeは，そのあとprocessが止まっても読めます（[保存したepisodeの扱い](#saved-episodes)）．
- episodeの途中でcontrollerが失敗したとき（方策の例外など）と，followerがFAULT・ESTOPになったときは，そのepisodeを破棄します．
- Pythonの操作は [Session](../reference/python-api/session.md) にあります．

## 再開 { #resuming }

同じdatasetに次のepisodeを追記できます．再開時はFPSとfeatureの互換性を検査します．記録するfeatureを変えるoptionには `dataset` を付け，datasetを分けます（[起動option](../reference/configuration/index.md#launch-options)）．

## 保存したepisodeの扱い { #saved-episodes }

- 保存のたびに，そのepisodeのfileを閉じます．`save` が成功を返したepisodeは，そのあとprocessが強制終了されても読めます．
- そのため，data・episodeのmetadata・動画は1 episodeにつき1 fileです（LeRobotで `resume` を繰り返したときと同じ配置）．Hubに上げる前にfileをまとめたい場合は，LeRobotの集約toolを使います．
- 保存が失敗した場合（diskの空きがないなど）は，そのepisodeを破棄し，datasetを保存前の状態に戻します．それまでのepisodeは残り，次のepisodeを記録できます．
- 保存の途中でprocessが止まった場合は，次にそのdatasetを開いたとき（`run`・`record`，または `check-dataset --recover`）に，書きかけのepisodeを取り除きます．
- 動画の長さがepisodeの行数と合わない場合（画像を書けなかったなど）は，保存の失敗として扱います．
- 対象はprocessの異常終了です．電源断までは保証しません（LeRobotがfileをdiskへ同期しないため）．

## datasetのmetadata { #metadata }

`meta/roboloom.json` に，datasetを作ったroboloomの版，`action` と `observation.state` の各要素の単位，episodeを保存した起動ごとのoptionと設定（`meta/roboloom_config/<名前>.json`．nodeの値をそのまま写したもの）を残します．nodeのfileが指す別のfile（重力model，調整値，校正）は写しません．

## episodeごとの記録 { #episode-records }

保存のたびに，datasetの `meta/roboloom_episodes.jsonl` に1行（JSON）を追記します．

| key | 内容 |
| --- | --- |
| `episode` | datasetの中のepisodeの番号 |
| `saved` | 保存した時刻 |
| `task`，`frames` | task と行数 |
| `metrics` | recorderの指標（欠損率，有効な行動の割合，制御周期の分布） |
| `controllers` | 保存したときの各controllerの状態．方策では `infer_ms`・`infer_max_ms`（推論時間），`dropped`（非同期の推論で遅れて捨てた手数），`error` など |
| `label`，`note` | 評価の成否（`success`・`failure`．付けなければ `null`）とメモ |

- 成否は保存のときに付けます：Pythonの `save(label=...)`・`record(..., label=...)`（[評価の成否を残す](../policy/evaluation.md#labels)），操作画面のcommand欄や `--plain` の行入力で `save success`・`save failure`，別端末から `roboloom session save success`．
- あとから付ける・付け直すときは `roboloom label [robot] <episode> success|failure` を使います（[CLI](../reference/cli.md#label)）．`{"episode", "label", "labelled", "note"}` の行を追記し，読むときは同じepisodeの行をあとのものを優先して重ねます．行を書き換えることはありません．
- `roboloom check-dataset` が，成否の数を表示します．
- LeRobotはこのfileを読みません．学習には影響しません．保存に失敗したepisodeと破棄したepisodeの行はありません．
- Pythonからは `roboloom.recording.episodes.read(...)` で読めます（[Python API：記録](../reference/python-api/recording.md)）．学習から除くepisodeを選ぶ例は [悪いepisodeを除く](check-and-train.md#excluding-episodes) にあります．

## 残すepisodeを選ぶ { #choosing-episodes }

- `record` は，停止したあと，保存する前に `keep(result)` を呼びます．
  - `False` を返すと，そのepisodeを破棄します．
- `result` に入っているもの：
  - `metrics`：recorder の指標．欠損率，有効な行動の割合，制御周期の分布．
  - `warnings`：品質の上限を超えた項目．`result.ok` は警告がないときに真です．
- 品質の上限は，`nodes/recorder.yaml` の `quality` で変えられます（[品質の上限](../reference/configuration/recorder.md#quality)）．
  - `max_missing_rate`（既定 0.05）
  - `min_action_valid_rate`（既定 0.9）
  - `max_interval_ms`（既定 100）
- `control_interval_ms` と `action_missing_rate`（指令のなかった行の割合）はfollowerごとで，警告にはfollowerの名前が出ます．

```python
ok = s.record("pick up the cup", 30, keep=lambda ep: ep.ok)
```
