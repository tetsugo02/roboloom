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
| `compress_images` | 真偽値 | `true` | — | `rr.Image.compress()` で color 画像を JPEG 圧縮してから記録する |
| `serve` | 真偽値 | `true` | — | `ip: null` のとき，web viewer 付きの local Rerun server を起動または再利用する |
| `ip` | 文字列か `null` | `null` | — | 外部 Rerun gRPC server の host 名または IP．`port` の指定が必要 |
| `port` | 整数（1〜65535）か `null` | `null` | — | 外部または local server の gRPC port．local server は null のとき `9876` を使う．`serve: false` で `port` を設定する場合は `ip` が必要 |
| `web_port` | 整数（1〜65535） | `9090` | — | local server の web viewer が使う HTTP port |
| `bind` | 文字列 | `"0.0.0.0"` | — | 新しく起動する local server の待ち受け address．node は `127.0.0.1` に接続するため，IPv4 loopback 接続を受け付ける address が必要 |
| `public_host` | 文字列か `null` | `null` | 共有 URL 内の両方の address に使う host 名または IP．null のときは robot 側 PC の host 名を使う．待ち受け address は `bind` で決まる |
| `server_memory_limit` | 文字列 | `"25%"` | — | 新しく起動する local server に `--server-memory-limit` で渡す live buffer の memory 上限 |
| `open_browser` | 真偽値 | `false` | — | robot 側 PC の browser で local server の web viewer を開く |
| `save` | path か `null` | `null` | — | `.rrd` file への path．相対 path は viewer node file の directory を基準に解決する |
| `memory_limit` | 文字列 | `"10%"` | — | native viewer window 用に `rr.spawn()` へ渡す memory 上限 |

## 出力先 { #targets }

| `ip` | `serve` | `save` | 動作 | status の `target` |
| --- | --- | --- | --- | --- |
| 指定あり | どちらでも可 | 任意 | `rerun+http://<ip>:<port>/proxy` に送り，`save` 指定時は `.rrd` file にも保存する | `"<ip>:<port>"` |
| `null` | `true` | 任意 | `127.0.0.1:<port>` の local server を起動または再利用し，`save` 指定時は `.rrd` file にも保存する | `"127.0.0.1:<port>"` |
| `null` | `false` | path | `.rrd` file へ直接書き出す（headless） | 解決後の `save` path |
| `null` | `false` | `null` | robot 側 PC で native Rerun window を起動する | `"spawn"` |

| local server の lifecycle | 動作 |
| --- | --- |
| 起動 | `127.0.0.1:<port>` で待ち受ける server を再利用する．`web_port` はその server の設定に揃える．新しく起動するときは異なる 2 つの空き port が必要 |
| log と停止 | 独立した server は実行 log の directory がある場合に `rerun-server.log` へ出力する．node が終了しても動き続ける．停止 command は [Live view（Rerun）](../../data/recording.md#live-view) に記載 |

## 描画される entity { #entities }

| entity path | Rerun の型 / timeline | 備考 |
| --- | --- | --- |
| `observation.images.<sensor>` | `Image`，`EncodedImage` または `DepthImage`（`roboloom` timeline） | 有効な画像 sensor ごとに時刻付きで記録する．各画像 entity を独立した spatial view に表示する |
| `observation.state` | `Scalars`（`roboloom` timeline） | 設定順につないだ follower 位置．履歴を保持する．結合特徴量をまだ組み立てられない tick では省かれる |
| `observation.<other>` | `Scalars`（`roboloom` timeline） | そのほかの有効な source と結合 vector（`observation.leader`，`observation.effort` など）．履歴を保持する |
| `action.<follower>` | `Scalars`（`roboloom` timeline） | follower ごとの指令位置（例：`action.follower`）．履歴を保持する．すべての follower が関節数の一致する有効な action を送ったときだけ描画する |
| `meta/<stream>/capture_age_ms` | `Scalars`（`roboloom` timeline） | sample を受け取った各 stream（`<source>` と `action_<follower>`）の取得からの経過時間 `(now - t_capture_ns) / 1e6`（ms）．履歴を保持する |
| `session/events` | `TextLog`（`roboloom` timeline） | session の lifecycle command（`start`，`stop`，`save`，`discard`）と任意の task 文字列 |

## status の項目 { #status }

| 項目 | 型 | 値・意味 |
| --- | --- | --- |
| `state` | 文字列 | 動作中は `"viewing"`．Rerun session の開始に失敗すると `"failed"`（dataflow を止めないよう event の消費は続ける） |
| `streams` | 整数 | 1 件以上の sample を受け取った入力 stream（`<source>` と `action_<follower>`）の数 |
| `drawn` | 整数 | 完了した `draw` の回数 |
| `errors` | 整数 | `draw` または session event 記録の失敗回数 |
| `target` | 文字列か `null` | 上の表に示す設定上の出力先 |
| `url` | 文字列か `null` | gRPC proxy address を encode した共有用の web viewer URL．両方の address に `public_host` または robot 側 PC の host 名を使う．local server を使う mode 以外や起動失敗時は null |
| `local_url` | 文字列か `null` | 両方の address が `localhost` の URL．local での表示や SSH port 転送に使う．`url` がある場合に利用できる |
| `error` | 文字列 | 最後の起動または記録 error（空のときは省く）．記録 error は後の `draw` が成功すると消去される |
| `browser_error` | 文字列 | 任意の browser 起動に失敗した場合の警告．空のときは省く |
