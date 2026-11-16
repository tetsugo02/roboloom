# データの形式

`record` extraでLeRobotDataset 0.7.0に保存します．取得・利用可能・受信・指令送信の単調時計時刻を区別して整列し，欠損は直前の有効な値と有効フラグで表します．`task` はフレームに記録されます．列名・dtype・shapeの一覧は [データセットの特徴量](../reference/dataset-features.md) にあります．

## 記録するもの { #features }

フォロワが複数あるとき，`observation.state`，`observation.effort`，`action` は全フォロワを設定の順につなげた1本のベクトルです．`names` が各要素の持ち主を `<フォロワ名>.<関節名>` で示します（例：`follower.r_arm_sh_pitch1`）．ほかのfeatureはノードごとで，ノード名が付きます．

| feature | 中身 |
| --- | --- |
| `observation.state` | 各フォロワの関節の位置 |
| `observation.effort` | `record_effort: true` のフォロワの力の量．単位の違うフォロワは混ぜられません |
| `observation.<input名>` | 各inputの読み値．inputのノード名が付きます（例：`observation.leader`）．leaderアームのような関節のinputは，関節の位置をそのinputの単位で，関節名（接頭辞なし）を付けて記録します．姿勢のinputは `x`，`y`，`z`，`qx`，`qy`，`qz`，`qw`，`gripper`，`tracking`，`engaged` を記録します |
| `observation.images.<センサー名>` などセンサーのfeature | 各センサーが記録するもの．[Sensors](../sensors/index.md) の各ページを参照 |
| `observation.meta.<ノード名>.valid` / `capture_age_ms` / `ready_age_ms`（float32），`seq` / `capture_ns` / `ready_ns` / `receive_ns`（int64） | 記録するノード（input，フォロワ，センサー）ごとに1組．その行でそのノードのサンプルを使ったか，取得からと使えるようになってからの経過時間（ms），通し番号，取得・使用可能・受信の時刻（単調時計のns） |
| `action` | 各フォロワがその行の区間に送った最初の指令．`observation.state` と同じ並び |
| `action.valid` | 全フォロワが指令を送った行で1 |
| `action.clamped` | どれかのフォロワが制限した行で1 |
| `action.meta.<フォロワ名>.valid` / `clamped` / `seq` / `sent_ns` | フォロワごとの指令の有無，制限，指令の番号，送信時刻 |

詳しくは [観測](../reference/dataset-features.md#observation)，[行動](../reference/dataset-features.md#action)，[メタ情報](../reference/dataset-features.md#meta) の各表にあります．`action` の各要素の単位は，データセットの `meta/roboloom.json` に残ります（[データセットのメタデータ](recording.md#metadata)）．

## 構成で変わる特徴量 { #by-configuration }

どの特徴量があるかは，その記録で動いていたノードで決まります．

- `observation.<input名>` は，その input が構成にあるときだけあります．Rakuda2 のテンプレートのオプション `policy` は leader を外すので（`inputs.leader: null`），評価のデータセットに `observation.leader` はありません．`policy_teleop` は leader を戻すので，`observation.leader` があります．
- `action.intervention` は，`teleop:` のある方策の controller があるときだけあります（[テレオペと介入](../policy/intervention.md#recording)）．
- 方策の `hold` に挙げた関節も `action` にあり，その要素にはフォロワが保持している目標が入ります（[履歴，動かさない関節，新しい観測](../policy/custom.md#hold)）．
- 方策の `observe` は，方策に渡す観測を選ぶだけです．起動したセンサーはすべて記録します（[センサー選択](../policy/run.md#sensor-selection)）．
- フォロワのない構成（手に持った装置，センサーだけ）には `action*` の特徴量はありません．
- 記録する特徴量を変えるオプションには `dataset` を付け，データセットを分けます（[起動オプション](../reference/configuration/index.md#launch-options)）．

## 行の割り当て { #row-assignment }

recorderは，エピソードを `dataset_fps` の周期の行に区切り，各ノードの出力を因果的に（その時刻までに届いたものだけで）割り当てます．

```mermaid
sequenceDiagram
  participant X as センサー
  participant F as フォロワ
  participant R as recorder
  Note over R: 行 k は t_k から t_k+1 まで
  X->>R: 観測（t_k までに届いた最新）
  F->>R: 状態（t_k までに届いた最新）
  F->>R: 指令（t_k から t_k+1 の最初の1つ）
  Note over R: 全フォロワの指令が t_k+1 を過ぎたら確定
  R->>R: 行 k を書く
```

- 行 k は `[t_k, t_{k+1})`，`t_k = t0 + k / dataset_fps` です．
- 観測は，recorderが `t_k` までに受け取ったものから選びます．`max_age_ms` より古いものは使わず，直前の有効な値を繰り返して `observation.meta.<ノード>.valid` を0にします．
- `action[k]` は，フォロワごとに `[t_k, t_{k+1})` で最初に送った指令です．送らなかったフォロワは保持している目標で埋め，`action.meta.<フォロワ>.valid` を0にします．
- 行は，全フォロワの指令の流れが `t_{k+1}` を過ぎたとき（黙っているフォロワがあれば `t_{k+1}` から `grace_ms` 後）に確定します．
- `start` の直前に届いた最新のサンプルを残しておくので，行0は空になりません．
- フォロワのない構成（手に持つ機器，センサーだけ）では `action*` がなく，`t_{k+1}` を過ぎた行から確定します．

## 有効フラグ { #valid }

| 列 | 1の意味 | 0の意味 |
| --- | --- | --- |
| `observation.meta.<ノード名>.valid` | その行で，そのノードの新しいサンプルを使った | `max_age_ms` 以内のサンプルがなかった．値は直前の有効なサンプルのもの（[欠損の扱い](#missing-data)）．`seq` は-1 |
| `action.valid` | 全フォロワがその行の区間に指令を送った | どれかのフォロワが指令を送らなかった |
| `action.meta.<フォロワ名>.valid` | そのフォロワが指令を送った | そのフォロワは指令を送らず，その部分は保持していた目標で埋めた |
| `action.clamped`，`action.meta.<フォロワ名>.clamped` | どれかのフォロワ（またはそのフォロワ）の安全の検査が，指令を可動域か速度の上限に収めた | 制限しなかった |
| `action.intervention` | 人がleaderで動かした行（`teleop:` のある構成だけ） | 方策が動かした行 |

## 欠損の扱い { #missing-data }

- **古い観測**：`nodes/recorder.yaml` のそのノードの `max_age_ms` より古いサンプルは使いません．その行は `observation.meta.<ノード名>.valid` を0，`seq` を-1にし，featureにはそのノードの直前の有効なサンプルの値を入れます（まだ一度も届いていないときだけ0）．0で埋めると，統計の最小値と平均が0に引かれるためです．input，フォロワ，センサーのどれにも `max_age_ms` の項目が必要です（[recorderの設定](../reference/configuration/recorder.md#recorder)）．
- **指令のない行**：指令を送らなかったフォロワの部分は，そのフォロワが保持していた目標（状態の `target`．なければ位置）で埋めます．ゼロで埋めると，学習した方策が0への跳びを覚えるためです．その行の `action.meta.<フォロワ名>.valid` と `action.valid` は0です．
- **行の確定**：行は，全フォロワの指令がその区間を過ぎたとき，または `grace_ms`（既定500 ms）が過ぎたときに確定します．
- **LeRobotの学習は `valid` を見ません**：`lerobot-train` は `*.valid` の列で行を選ばず，ほかの列と同じく入力・出力に数えるだけです．LeRobotが学習から外すのは，エピソードの終わりを越えた分（`action_is_pad`）だけです．有効な行だけを使う場合は，`action.valid` や `observation.meta.<ノード名>.valid` で自分で選んでください．どれだけの行が0かは `roboloom check-dataset` が表示します（[検査と学習](check-and-train.md)）．
