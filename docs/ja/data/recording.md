# 記録と再開

エピソードを保存・破棄する流れと，保存したデータセットに残るものです．recorderの設定キーは [recorderの設定](../reference/configuration/recorder.md#recorder)，コマンドは [CLI](../reference/cli.md#record) にあります．

## 保存と破棄 { #save-and-discard }

- エピソードは `start` で始まり，`stop` で止まります．止めたエピソードは，`save` で保存するか `discard` で捨てます．`roboloom record` と `Session.record` は，止めたあと保存します（[残すエピソードを選ぶ](#choosing-episodes)）．
- `save()` が返ったエピソードは，そのあとプロセスが止まっても読めます（[保存したエピソードの扱い](#saved-episodes)）．
- エピソードの途中でcontrollerが失敗したとき（方策の例外など）と，フォロワがFAULT・ESTOPになったときは，そのエピソードを破棄します．
- Pythonの操作は [Session](../reference/python-api/session.md) にあります．

## 再開 { #resuming }

同じデータセットに次のエピソードを追記できます．再開時はFPSとfeatureの互換性を検査します．記録するfeatureを変えるオプションには `dataset` を付け，データセットを分けます（[起動オプション](../reference/configuration/index.md#launch-options)）．

## 保存したエピソードの扱い { #saved-episodes }

- 保存のたびに，そのエピソードのファイルを閉じます．`save` が成功を返したエピソードは，そのあとプロセスが強制終了されても読めます．
- そのため，データ・エピソードのメタデータ・動画は1エピソードにつき1ファイルです（LeRobotで `resume` を繰り返したときと同じ配置）．Hubに上げる前にファイルをまとめたい場合は，LeRobotの集約ツールを使います．
- 保存が失敗した場合（ディスクの空きがないなど）は，そのエピソードを破棄し，データセットを保存前の状態に戻します．それまでのエピソードは残り，次のエピソードを記録できます．
- 保存の途中でプロセスが止まった場合は，次にそのデータセットを開いたとき（`run`・`record`，または `check-dataset --recover`）に，書きかけのエピソードを取り除きます．
- 動画の長さがエピソードの行数と合わない場合（画像を書けなかったなど）は，保存の失敗として扱います．
- 対象はプロセスの異常終了です．電源断までは保証しません（LeRobotがファイルをディスクへ同期しないため）．

## データセットのメタデータ { #metadata }

`meta/roboloom.json` に，データセットを作ったroboloomの版，`action` と `observation.state` の各要素の単位，エピソードを保存した起動ごとのオプションと設定（`meta/roboloom_config/<名前>.json`．ノードの値をそのまま写したもの）を残します．ノードのファイルが指す別のファイル（重力モデル，調整値，校正）は写しません．

## エピソードごとの記録 { #episode-records }

保存のたびに，データセットの `meta/roboloom_episodes.jsonl` に1行（JSON）を追記します．

| キー | 内容 |
| --- | --- |
| `episode` | データセットの中のエピソードの番号 |
| `saved` | 保存した時刻 |
| `task`，`frames` | task と行数 |
| `metrics` | recorderの指標（欠損率，有効な行動の割合，制御周期の分布） |
| `controllers` | 保存したときの各controllerの状態．方策では `infer_ms`・`infer_max_ms`（推論時間），`dropped`（非同期の推論で遅れて捨てた手数），`error` など |
| `label`，`note` | 評価の成否（`success`・`failure`．付けなければ `null`）とメモ |

- 成否は保存のときに付けます：Pythonの `save(label=...)`・`record(..., label=...)`（[評価の成否を残す](../policy/evaluation.md#labels)），操作画面のコマンド欄や `--plain` の行入力で `save success`・`save failure`，別端末から `roboloom session save success`．
- あとから付ける・付け直すときは `roboloom label [robot] <エピソード番号> success|failure` を使います（[CLI](../reference/cli.md#label)）．`{"episode", "label", "labelled", "note"}` の行を追記し，読むときは同じエピソードの行をあとのものを優先して重ねます．行を書き換えることはありません．
- `roboloom check-dataset` が，成否の数を表示します．
- LeRobotはこのファイルを読みません．学習には影響しません．保存に失敗したエピソードと破棄したエピソードの行はありません．
- Pythonからは `roboloom.recording.episodes.read(...)` で読めます（[Python API：記録](../reference/python-api/recording.md)）．学習から除くエピソードを選ぶ例は [悪いエピソードを除く](check-and-train.md#excluding-episodes) にあります．

## 残すエピソードを選ぶ { #choosing-episodes }

- `record` は，停止したあと，保存する前に `keep(result)` を呼びます．
  - `False` を返すと，そのエピソードを破棄します．
- `result` に入っているもの：
  - `metrics`：recorder の指標．欠損率，有効な行動の割合，制御周期の分布．
  - `warnings`：品質の上限を超えた項目．`result.ok` は警告がないときに真です．
- 品質の上限は，`nodes/recorder.yaml` の `quality` で変えられます（[品質の上限](../reference/configuration/recorder.md#quality)）．
  - `max_missing_rate`（既定 0.05）
  - `min_action_valid_rate`（既定 0.9）
  - `max_interval_ms`（既定 100）
- `control_interval_ms` と `action_missing_rate`（指令のなかった行の割合）はフォロワごとで，警告にはフォロワの名前が出ます．

```python
ok = s.record("pick up the cup", 30, keep=lambda ep: ep.ok)
```
