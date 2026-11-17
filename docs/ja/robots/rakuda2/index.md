# Rakuda2

<span class="status status--verified">実機検証済み</span>

Rakuda2は，胴体・頭部3関節，左右それぞれ腕6関節とgripper 1関節の **17関節** を持つ構成です．関節値はDynamixelの生の位置count，電流はmAで扱います．

followerは `type: rakuda2_follower`，操作入力（`leader` の役割）はRakuda-mini arm（`type: rakuda_mini`）です．leaderとfollowerは別のDynamixel busを使い，それぞれのnodeが専有します．設定は `roboloom init rakuda2` で作成します．

## 対応controller { #controllers }

| Controller | option | 状態 |
| --- | --- | --- |
| Leader（`joint`） | なし | <span class="status status--verified">実機検証済み</span> |
| 重力補償付きleader | `gravity` | <span class="status status--verified">実機検証済み</span> |
| 方策 | `policy` | <span class="status status--verified">実機検証済み</span> |
| 方策＋介入 | `policy`，`policy_teleop` | <span class="status status--verified">実機検証済み</span> |
| Pika SenseとIK | `pika` | <span class="status status--dev">開発中</span> |

設定例は [Rakuda2のcontroller](controllers.md) にあります．

## 対応sensor { #sensors }

| sensor | node名 | 有効にする方法 | 状態 |
| --- | --- | --- | --- |
| [RealSense](../../sensors/realsense.md) | `camera` | 既定で有効 | <span class="status status--verified">実機検証済み</span> |
| [DIGIT](../../sensors/digit.md) | `digit_left`，`digit_right` | option `digit` | <span class="status status--verified">実機検証済み</span> |
| [音声](../../sensors/audio.md) | `audio` | `--sensors` で選ぶ | <span class="status status--dev">開発中</span> |

組み合わせと選び方は [Rakuda2のsensor](sensors.md) にあります．

## 観測と行動 { #observation-and-action }

記録するdatasetと方策の入出力は，同じ並びと単位です．

| 名前 | 要素 | 単位 |
| --- | --- | --- |
| `observation.state`，`action` | 17（`follower.torso_yaw`，`follower.head_yaw`，`follower.head_pitch`，右腕 `follower.r_arm_sh_pitch1` … `follower.r_arm_grip`，左腕 `follower.l_arm_sh_pitch1` … `follower.l_arm_grip`） | Dynamixelの位置count |
| `observation.effort` | 17（同じ並び．templateの `record_effort: true`） | mA（電流） |
| `observation.leader` | 17（leaderの関節位置．同じ並び．名前は接頭辞なしの `torso_yaw` … `l_arm_grip`．leaderを使わないoption `policy` では記録しない．`policy_teleop` では記録する） | Dynamixelの位置count |
| `observation.images.camera` | 480×640×3（RGB） | [storage](../../reference/configuration/sensors.md#image-storage) |
| `observation.images.digit_left`，`observation.images.digit_right` | 320×240×3（RGB．option `digit`） | [storage](../../reference/configuration/sensors.md#image-storage) |
| `observation.meta.<node>.valid`，`capture_age_ms`，`ready_age_ms` | 各1（float32）．記録するnodeごと：`leader`，`follower`，`camera`，`digit` のときは `digit_left`，`digit_right` も | `valid` は0/1，経過時間はms |
| `observation.meta.<node>.seq`，`capture_ns`，`ready_ns`，`receive_ns` | 各1（int64）．同じnode | 通し番号，単調時計のns |
| `action.valid`，`action.clamped` | 各1（float32） | 0/1 |
| `action.meta.follower.valid`，`clamped`，`seq`，`sent_ns` | 各1（`valid`，`clamped` はfloat32，`seq`，`sent_ns` はint64） | 0/1，指令の番号，単調時計のns |
| `action.intervention` | 1（float32．option `policy_teleop` のときだけ） | 人がleaderで動かした行は1 |
| `observation.audio.audio` | sensor `audio` を選んだときだけ．大きさは[音声](../../sensors/audio.md)を参照 | mel spectrogram |

- `observation.leader`，`observation.meta.<node>.*`，`action.valid`，`action.clamped`，`action.meta.follower.*` の意味，欠測の記録のしかた，指令のなかった行の `action` の中身は，[dataの形式](../../data/format.md) で説明しています．どのrobotでも同じです．
- 方策（option `policy`）は，既定で関節状態と `camera` を観測します．`nodes/policy.yaml` の `observe` でsensorを選べます（`[]` なら関節状態のみ）．`infer` は17関節の目標をcountで返します．1手 `[17]` か，まとめた行動 `[H, 17]` です．
- `max_speed` はcount/sです（templateは `{follower: 1024}`）．
- `storage: video` の画像は既定で H.264 です．`nodes/recorder.yaml` の `video_codec: av1` か `--video-codec av1` で AV1 にできます（[Video codec](../../reference/configuration/recorder.md#video-codec)）．
- templateの既定の方策 `roboloom.policy:hold` は，腕をその場に留めます．方策の書き方は [方策で動かす](../../policy/index.md) にあります．

## 起動optionと組み合わせ { #options }

設定は `.roboloom/rakuda2/config.yaml` の1つです．optionを何も有効にしない構成は，通常leader・`joint` controller・RealSenseです．templateは次の起動optionを持ちます（既定はすべて無効）．選び方は [CLI](../../reference/cli.md)，規則は [設定](../../reference/configuration/index.md) の「起動option」を参照してください．

| option | 内容 | 必要 / 競合 | dataset名 |
| --- | --- | --- | --- |
| `digit` | 左右DIGITを記録する | | `-digit` を付ける |
| `gravity` | leaderの左右腕を重力補償する（`nodes/leader_gravity.yaml`） | | 変えない |
| `bilateral` | 力の逆送（実機未検証）．leader・controller・robotを置き換え，推定器 `effort` を足す | `gravity` が必要 | `-bilateral` を付ける |
| `policy` | 学習した方策がfollowerを動かす．leaderとcontrollerを外し，`controllers.policy` を足す．`roboloom infer` が自動で有効にする | `gravity` と競合 | `-eval` を付ける |
| `policy_teleop` | `policy` に加えて，episodeの前と途中にleaderで動かせる（[teleopと介入](../../policy/intervention.md)）．leaderを戻し，`nodes/policy_teleop.yaml` を使う | `policy` が必要 | `-teleop` を付ける |
| `pika` | leaderの代わりに，腕ごとのPika SenseとIKで動かす（[開発中・模擬のみ](pika-sense-ik.md)） | `gravity`，`policy` と競合 | `-pika` を付ける |

| 有効なoption | Leader | Sensors | `repo_id` |
| --- | --- | --- | --- |
| なし | 通常 | RealSense | `local/rakuda2` |
| `digit` | 通常 | RealSense + 左右DIGIT | `local/rakuda2-digit` |
| `gravity` | 重力補償付き | RealSense | `local/rakuda2` |
| `gravity`，`digit` | 重力補償付き | RealSense + 左右DIGIT | `local/rakuda2-digit` |
| `gravity`，`bilateral` | 重力補償付き＋力の逆送（実機未検証） | RealSense | `local/rakuda2-bilateral` |
| `policy` | なし（方策） | RealSense | `local/rakuda2-eval` |
| `digit`，`policy` | なし（方策） | RealSense + 左右DIGIT | `local/rakuda2-digit-eval` |
| `policy`，`policy_teleop` | 通常（episodeの前と介入のとき） | RealSense | `local/rakuda2-eval-teleop` |

制約：

- `gravity` は，[Rakuda2：重力補償](../../tutorials/rakuda2-gravity.md) の測定（`calibrate-joints`，`measure-travel`，`identify-gravity`，`tune-gravity`）を済ませてから使います．測定値が `SET_...` のままだと読み込みを拒否します．
- `gravity` の有無でleaderのOperating Modeが変わります．端末から実機で起動するとき，CLIはEEPROMの差分を表示し，確認してから書きます．
- `policy` はDIGITなしで使えます．DIGITを方策に渡すときは，`digit` を有効にし，`nodes/policy.yaml` の `observe` を `[camera, digit_left, digit_right]` に変更します．`digit` の有効化だけでは方策の入力は変わりません．学習時の入力と一致させてください．DIGITが必要なLeRobot checkpointをDIGITなしで読み込むと，開始前に拒否します．
- 関節状態のみの方策は `observe: []` にします．sensorを開かない場合は，`config.yaml` の `sensors` から該当nodeも外します．
- `policy_teleop` の `nodes/policy_teleop.yaml` は，`nodes/policy.yaml` に `teleop: [controller.yaml]` を足したものです．方策の設定を変えるときは，両方を同じにしてください．
- `policy` はleaderを使わないため `gravity` とは同時に使えません．`gravity` を必要とする `bilateral` とも併用できません．
- `gravity` はdataset名を変えません．記録するfeatureが通常leaderと同じためです．通常leaderと重力補償付きleaderのepisodeは同じdatasetに入ります．
- 画像featureが変わるため，`digit` の有無でdatasetが分かれます．RealSenseだけの既存datasetへDIGITのepisodeは追記しません．

## bilateral（実機未検証）

option `bilateral` は，followerが受けた外力をleaderへ返す組み合わせです．実機では確かめていません．模擬の試験だけを通しています．

| node | 設定 | 内容 |
| --- | --- | --- |
| robot | `nodes/follower_bilateral.yaml` | 腕を電流制限つき位置制御（Operating Mode 5，`current_position`）にする．`goal_current_mA` が接触時の力の上限．`SET_FOLLOWER_ARM_GOAL_CURRENT_mA` を決め，`roboloom commission` でModeとCurrent Limitを書く |
| leader | `nodes/leader_bilateral.yaml` | 重力補償付きleaderの腕groupに `feedback:` を足したもの |
| controller | `nodes/controller_bilateral.yaml` | `feedback:` で推定器と返す関節（初期値は右肘1関節，小さいgain）を指定 |
| estimator | `nodes/effort.yaml` | followerの外力の推定器（`model_residual`）．followerで同定した重力model `calibration/effort_gravity_<side>.yaml` を使う．接触の閾値は実測前の仮の値 |

制約：

- `goal_current_mA` は，EEPROMの `current_limit` 以下でなければ起動を拒否します．
- Mode 5へ書き換えた後のmotorでは，通常の `nodes/follower.yaml`（Mode 3）は起動時の検査で拒否されます．戻すときは `commission follower` で書き戻します．端末から実機で起動する場合は，CLIが起動前に差分を表示し，確認してから書き戻します．
- `bilateral` を有効にしたcommand（`roboloom commission follower --with bilateral` など）は，設定全体を読み込みます．そのため，followerの重力model（`calibration/effort_gravity_<side>.yaml`）が無いと止まります．重力の同定はModeを書き換える前（Mode 3のまま）にできるので，先に同定してから `commission` します．
- 設定keyは [設定](../../reference/configuration/index.md) の「力の逆送」にあります．

## 起動前の確認

port，motor ID，model，EEPROM，関節範囲，速度・電流上限を実機で確認します．templateの `torque` は `true` なので，初回にfollowerを動かさず経路を確かめる場合は **起動前に `nodes/follower.yaml` を `torque: false` に変更** してください．leader側の制御は独立しており，triggerや重力補償は通電します．

制御周期はtemplateで120 Hzです．前提条件と下げ方は [制御周期](../../reference/configuration/followers.md#control-rate) を参照してください．

setupから収集までの手順は [Rakuda2：機体設定と読み取り確認](../../tutorials/rakuda2-setup.md)，制御値の意味は [Gravity tuning](../../explanation/gravity-compensation.md) を参照してください．
