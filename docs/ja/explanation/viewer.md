# viewer を独立した node にする理由

<span class="status status--mock">模擬のみ</span>

```mermaid
flowchart LR
  I["inputs"] --> C["controllers / policy<br/>(hook は control budget 内で実行)"]
  C --> F["followers"]
  F --> C
  X["sensors"] --> R["recorder<br/>有界 queue (queue_s)"]
  F --> R
  I --> R
  X -. "最新のみ (queue_size: 1, drop_oldest)" .-> V["viewer<br/>独自の timer (rate_hz)"]
  F -. "最新のみ" .-> V
  I -. "最新のみ" .-> V
  N["session"] -.-> C
  N -.-> R
  N -.-> V
  V -. "status" .-> N
  V --> RR["Rerun (spawn / gRPC / .rrd)"]
```

`viewer` は，方策の hook や recorder の中ではなく，独立した dora node process として動きます．`viewer` への入力（`inputs`，`followers`，`sensors`，`estimators`，`action_<follower>`）はすべて `queue_size: 1`・`queue_policy: drop_oldest` の最新値専用 queue であり，溜まった timer tick も 1 回の起床で 1 回の再描画へまとめられ，独自の `rate_hz` で動きます．上流の queue を押し戻さないため，Rerun の描画・JPEG 圧縮・gRPC 通信の遅延や，viewer の起動失敗が起きても，機器の読み取り・follower の制御・`recorder` の行の整列を遅らせません（失敗した viewer も入力の消費を続け，error を `status` に報告します）．これに対して local の [policy hook](hooks.md) は `policy` node 内の制御周期と短い budget（既定 `0.5 / rate_hz` ms）の中で同期実行される仕組みであり，teleop（`record`・`run`）のときには存在しません．

模擬での計測値（`rakuda2`，`digit` + `viewer`，20 秒）：follower の制御間隔 p99 は viewer ありで **9.82 ms**，なしで **9.72 ms** であり，欠損 sample はありませんでした．

設定 key と出力先は [Live viewer（viewer）](../reference/configuration/viewer.md)，使い方は [Live view（Rerun）](../data/recording.md#live-view) を参照してください．
