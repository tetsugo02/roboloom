# Live viewer（viewer）

<span class="status status--mock">模擬のみ</span>

| Detail | 説明 |
| --- | --- |
| 対象 | 観測・行動・取得からの経過時間・session の event を Rerun へ流す任意の `viewer` service node（[状態label](../status-labels.md)） |
| 使い方と背景 | [Live view（Rerun）](../../data/recording.md#live-view)，[viewer を独立した node にする理由](../../explanation/viewer.md) |
| 必要な extra | `viz`（`lerobot[viz]==0.7.0`：`rerun-sdk`，`foxglove-sdk`．[Installation](../../get-started/installation.md)）．無効のときは Rerun を確認も import もしない |

## 有効化と node file { #enabling }

| 項目 | 値 | 備考 |
| --- | --- | --- |
| node file の場所 | `.roboloom/<robot>/nodes/viewer.yaml` | `rakuda2` と `piper-pika` の template に含まれる |
| 起動 option | `options.viewer.set: {viewer: nodes/viewer.yaml}` | `rakuda2` と `piper-pika` の template に含まれる．`--with viewer` または `options=["viewer"]` で有効にする．`dataset` の接尾辞を持たず，`repo_id` と `output` は変わらない（[起動option](index.md#launch-options)） |
| 最上位の key | `viewer: nodes/viewer.yaml` | `config.yaml` に書くと既定で有効になる．`set: {viewer: null}` の option で無効にできる |
| 継承と模擬の代用値 | `extends`，`without`，`mock.yaml` | ほかの node file と同様に使える．`SET_...` の代用値は `mode: mock` のときだけ `mock.yaml` から補われる（[extends](index.md#extends)，[未設定の値と模擬](index.md#placeholders)） |
| 予約された node 名 | `viewer` | `trackers`，`inputs`，`controllers`，`followers`，`sensors`，`estimators` の node 名には使えない |

## node の key { #keys }

| key | 型 | 既定値 | 単位 | 備考 |
| --- | --- | --- | --- | --- |
| `rate_hz` | 数値 | `10` | Hz | 再描画の周期．正の有限値で，整数 Hz か 1 tick あたり整数 ms になる値（例：`10` や `12.5`＝80 ms．[制御周期](followers.md#control-rate)） |
| `compress_images` | 真偽値 | `true` | — | Rerun へ渡す前に RGB 画像を JPEG 圧縮する（`rr.Image.compress()`）．`false` は非圧縮のまま流す |
| `ip` | 文字列か `null` | `null` | — | Rerun gRPC server（`rerun+http://<ip>:<port>/proxy`）の host 名または IP．`port` と組で指定し，片方だけは不可 |
| `port` | 整数（1〜65535）か `null` | `null` | — | Rerun gRPC server の port．`ip` と組で指定し，片方だけは不可 |
| `save` | path か `null` | `null` | — | `.rrd` file への path．相対 path は viewer node file の directory を基準に解決する |
| `memory_limit` | 文字列 | `"10%"` | — | この機体で Rerun window を起動するときに `LEROBOT_RERUN_MEMORY_LIMIT` として渡す memory 上限（古い data を捨てる基準） |

## 出力先 { #targets }

| `ip` と `port` | `save` | 動作 | status の `target` |
| --- | --- | --- | --- |
| `null` | `null` | この機体で Rerun window を起動する（`memory_limit` を適用） | `"spawn"` |
| 指定あり | `null` | local window を開かず `rerun+http://<ip>:<port>/proxy` へ gRPC で送る | `"<ip>:<port>"` |
| `null` | path | window を開かず `.rrd` file へ書き出す（headless） | 解決後の `save` path |
| 指定あり | path | `<ip>:<port>` へ gRPC で送り，同時に `.rrd` file へ保存する | `"<ip>:<port>"` |

## 描画される entity { #entities }

| entity path | Rerun の型 / timeline | 備考 |
| --- | --- | --- |
| `observation.images.<sensor>` | `Image`（static） | LeRobot の helper が `static=True` で記録するため，view には最新の画像だけが残る |
| `observation.state` | `Scalars`（`roboloom` timeline） | 設定順につないだ follower 位置．履歴を保持する．結合特徴量をまだ組み立てられない tick では省かれる |
| `observation.<other>` | `Scalars`（`roboloom` timeline） | そのほかの有効な source と結合 vector（`observation.leader`，`observation.effort` など）．履歴を保持する |
| `action.<follower>` | `Scalars`（`roboloom` timeline） | follower ごとの指令位置（例：`action.follower`）．履歴を保持する．すべての follower が関節数の一致する有効な action を送ったときだけ描画する |
| `meta/<stream>/capture_age_ms` | `Scalars`（`roboloom` timeline） | sample を受け取った各 stream（`<source>` と `action_<follower>`）の取得からの経過時間 `(now - t_capture_ns) / 1e6`（ms）．履歴を保持する |
| `session/events` | `TextLog` | session の lifecycle command（`start`，`stop`，`save`，`discard`）と任意の task 文字列 |

## status の項目 { #status }

| 項目 | 型 | 値・意味 |
| --- | --- | --- |
| `state` | 文字列 | 動作中は `"viewing"`．Rerun session の開始に失敗すると `"failed"`（dataflow を止めないよう event の消費は続ける） |
| `streams` | 整数 | 1 件以上の sample を受け取った入力 stream（`<source>` と `action_<follower>`）の数 |
| `drawn` | 整数 | 完了した `draw` の回数 |
| `errors` | 整数 | `draw` または session event 記録の失敗回数 |
| `target` | 文字列か `null` | `"spawn"`，`"<ip>:<port>"`，または解決後の `save` path |
| `error` | 文字列 | 最後の error message（空のときは省く）．後の `draw` が成功すると消去される |
