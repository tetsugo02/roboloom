# データセットの列

roboloom が LeRobotDataset 0.7.0 に書く列（特徴量）の一覧です．どの列があるかは，設定の followers・inputs・sensors・記録する estimators と，有効なオプションで決まります．`roboloom validate` で検証した設定の列は `roboloom.recording.features(cfg)` で確かめられます（[Recording](python-api/recording.md#features)）．行の割り当てと欠損の扱いは [データの形式](../data/format.md) にあります．

- `<follower>`，`<input>`，`<sensor>`，`<estimator>`，`<source>` は，設定でのノードの名前です（Rakuda2 のテンプレートでは `follower`，`leader`，`camera`，`digit_left` など）．
- `<source>` は記録するノードすべて（inputs，followers，sensors，`record: true` の estimators）を指します．
- 複数のノードにまたがる列（`observation.state` など）は，設定の順にノードの値をつなぎます．`names` が，どの要素がどのノードのものかを示します（`follower.r_arm_sh_pitch1`）．
- 形は1行あたりです．

## 観測 { #observation }

| 列 | dtype | shape | ある条件 | 意味 |
| --- | --- | --- | --- | --- |
| `observation.state` | float32 | (全フォロワの関節数,) | フォロワがある | 各フォロワの関節位置．各フォロワの単位．`names` は `<follower>.<joint>` |
| `observation.effort` | float32 | (`record_effort` のフォロワの関節数,) | フォロワの `record_effort: true` | 関節の電流・トルク．単位は機種の値（Rakuda2・Pika は mA，PiPER は N·m）．1つの列に単位の違う機種は混ぜられない |
| `observation.<input>` | float32 | (関節数,) | 関節の入力（leader など）がある | 入力機器の関節位置．`names` は関節名．オプション `policy` では leader を外すのでこの列はなく，`policy_teleop` では leader を戻すのでこの列がある |
| `observation.<input>` <span class="status status--dev">開発中</span> | float32 | (10,) | 姿勢の入力（Pika Sense）がある | `x`，`y`，`z`（m），`qx`，`qy`，`qz`，`qw`，`gripper`（rad．ない機器は0），`tracking`（1/0），`engaged`（1/0） |
| `observation.images.<sensor>` | `video` か `image` | (高さ, 幅, 3) | カメラ・触覚の画像センサー（RealSense，DIGIT など） | RGB 画像．dtype はセンサーの `storage`（既定 `video`．`image` は <span class="status status--mock">模擬のみ</span>）．`names` は `height`，`width`，`channels` |
| `observation.audio.<sensor>` <span class="status status--dev">開発中</span> | int16 | (`sample_rate` / `dataset_fps`,) | `type: pcm_mono` | 1行ぶんの PCM |
| `observation.audio.<sensor>` <span class="status status--dev">開発中</span> | float32 | (`n_mels`, 1 + `sample_rate`·`window_seconds` // `hop_length`) | `type: mel_mono` | 直近 `window_seconds` の対数メルパワー（低い周波数から） |
| `observation.effort_ext` <span class="status status--mock">模擬のみ</span> | float32 | (推定する関節数,) | estimator の `record: true` | 外力（推定の残差の符号を反転したもの）．単位は estimator の単位．`names` は `<follower>.<joint>` |
| `observation.effort_ext.valid` <span class="status status--mock">模擬のみ</span> | float32 | (estimator の数,) | estimator の `record: true` | その estimator の推定が有効なら1 |
| `observation.contact` <span class="status status--mock">模擬のみ</span> | float32 | (estimator の数,) | estimator の `record: true` | 接触を判定したら1 |
| `task` | 文字列（LeRobot が `task_index` に変える） | — | 常に | エピソードの task |

- 使える標本がない行は，そのノードの最後の有効な値をくり返します（最初の標本より前は0）．このとき `observation.meta.<source>.valid` が0です（[欠損の扱い](../data/format.md#missing-data)）．
- 方策が受け取る観測は，同じ名前と形です（`observation.meta` を除く．[観測](../policy/custom.md#observations)）．

## 行動 { #action }

フォロワのない構成（手に持って記録する機器）には，`action` で始まる列はありません．

| 列 | dtype | shape | ある条件 | 意味 |
| --- | --- | --- | --- | --- |
| `action` | float32 | (全フォロワの関節数,) | フォロワがある | 各フォロワが行の時間 [t_k, t_{k+1}) に最初に送った指令．`observation.state` と同じ並びと単位．指令を送らなかったフォロワは，保持していた目標（なければ位置）で埋める．方策の `hold` に挙げた関節も，保持した目標の値で入る |
| `action.valid` | float32 | (1,) | フォロワがある | すべてのフォロワがその行で指令を送ったら1 |
| `action.clamped` | float32 | (1,) | フォロワがある | どれかのフォロワの指令が制限で切り詰められたら1 |
| `action.intervention` | float32 | (1,) | 方策に `teleop:` がある（オプション `policy_teleop`） | その行を人が leader で動かしたら1（[テレオペと介入](../policy/intervention.md#teleop)） |

## メタデータ { #meta }

各ノードの時刻と有効さです．時刻は `time.monotonic_ns()` の時間です．

| 列 | dtype | shape | ある条件 | 意味 |
| --- | --- | --- | --- | --- |
| `observation.meta.<source>.valid` | float32 | (1,) | 記録するノードごと | 行の時刻 t_k に，取得から `max_age_ms` 以内の標本があれば1（同じ標本が続く行で使われることもある）．0の行は最後の有効な値のくり返し |
| `observation.meta.<source>.capture_age_ms` | float32 | (1,) | 記録するノードごと | 行の時刻 t_k から見た，標本の取得からの経過（ms）．標本がなければ0 |
| `observation.meta.<source>.ready_age_ms` | float32 | (1,) | 記録するノードごと | t_k から見た，標本が使えるようになってからの経過（ms）．標本がなければ0 |
| `observation.meta.<source>.seq` | int64 | (1,) | 記録するノードごと | 標本の通し番号．標本がなければ −1 |
| `observation.meta.<source>.capture_ns` | int64 | (1,) | 記録するノードごと | 標本を取得した時刻．標本がなければ0 |
| `observation.meta.<source>.ready_ns` | int64 | (1,) | 記録するノードごと | 標本が使えるようになった時刻．標本がなければ0 |
| `observation.meta.<source>.receive_ns` | int64 | (1,) | 記録するノードごと | recorder が受け取った時刻．標本がなければ0 |
| `action.meta.<follower>.valid` | float32 | (1,) | フォロワごと | そのフォロワが行の時間に指令を送ったら1 |
| `action.meta.<follower>.clamped` | float32 | (1,) | フォロワごと | その指令が制限で切り詰められたら1 |
| `action.meta.<follower>.seq` | int64 | (1,) | フォロワごと | 指令の通し番号．なければ −1 |
| `action.meta.<follower>.sent_ns` | int64 | (1,) | フォロワごと | 指令を送った時刻．なければ0 |

LeRobot が足す列もあります．

| 列 | dtype | shape | 意味 |
| --- | --- | --- | --- |
| `timestamp` | float32 | (1,) | エピソードの始めからの時刻（秒） |
| `frame_index` | int64 | (1,) | エピソードの中の行番号 |
| `episode_index` | int64 | (1,) | エピソード番号 |
| `index` | int64 | (1,) | データセット全体での行番号 |
| `task_index` | int64 | (1,) | task の番号 |

## 学習での扱い { #training }

- LeRobot は `*.valid` の列を特別に扱いません．`valid` が0の行も，ほかの行と同じく学習に使われます．除き方は [データの検査と学習](../data/check-and-train.md#training) と [valid](../data/format.md#valid) を参照してください．
- LeRobot は `observation.` で始まる列を観測の特徴量として，`action` で始まる列を行動の特徴量として方策の設定に載せます．ただし ACT などの方策のモデルが読む観測は，`observation.state`，`observation.environment_state` と画像です．`observation.meta.*`，`observation.<input>`，`observation.effort` は，データセットにあってもモデルの入力になりません．

## Rakuda2 の例 { #rakuda2-example }

Rakuda2 のテンプレート（`roboloom init rakuda2`）で，オプションごとに変わる列です．

| オプション | 増える列 | なくなる列 |
| --- | --- | --- |
| なし（teleop の収集） | `observation.state`，`observation.effort`，`observation.leader`，`observation.images.camera`，`action`，`action.valid`，`action.clamped`，`action.meta.follower.*`，`observation.meta.{leader,follower,camera}.*` | — |
| `digit` | `observation.images.digit_left`，`observation.images.digit_right`，それぞれの `observation.meta.*` | — |
| `policy` | — | `observation.leader`，`observation.meta.leader.*` |
| `policy_teleop` | `observation.leader`，`observation.meta.leader.*`，`action.intervention` | — |
| `pika` <span class="status status--dev">開発中</span> | `observation.right_sense`，`observation.left_sense`，それぞれの `observation.meta.*` | `observation.leader`，`observation.meta.leader.*` |
| `--sensors camera,audio` <span class="status status--dev">開発中</span> | `observation.audio.audio`，`observation.meta.audio.*` | — |
| `bilateral` <span class="status status--mock">模擬のみ</span> | `observation.effort_ext`，`observation.effort_ext.valid`，`observation.contact`，`observation.meta.effort.*` | — |
