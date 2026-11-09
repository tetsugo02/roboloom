# Rakuda2

Rakuda2は，胴体・頭部3関節，左右それぞれ腕6関節とグリッパー1関節の **17関節** を持つ構成です．関節値はDynamixelの生の位置カウント，電流はmAで扱います．

followerは `type: rakuda2_follower`，操作入力（`leader` の役割）はRakuda-miniアーム（`type: rakuda_mini`）です．leaderとfollowerは別のDynamixelバスを使い，それぞれのノードが専有します．設定は `roboloom init rakuda2` で作成します．

## 対応controller

現在の操作ガイドは [Leader](../controllers/leader.md) を対象にします．`inputs.leader` で関節位置を読み，`type: joint` のcontrollerがfollowerへ変換します．

- 通常のleader：腕・胴体・頭部は脱力，トリガーはばねとして制御します．
- 重力補償付きleader：左右腕を `gravity_comp` で制御し，同定した重力モデル・可動域・調整値を使います．
- 必要なleader関節は `position` で起動時の姿勢に固定できます．首カメラの腰yaw相殺は `joint` controllerの `couplings` で指定します．通常・重力補償付きleaderのどちらでも設定でき，既定は無効です．[設定例と制約](../controllers/leader.md)を参照してください．組み合わせの検証は模擬環境までです．
- 開始前にleaderとfollowerを揃えます．`aligning` の間は開始が拒否され，関節差が警告表示されます．揃えてから再試行できます．

## 対応センサー

| センサー | ノード名 | 設定 | 記録する値 |
| --- | --- | --- | --- |
| [RealSense](../sensors/realsense.md) | `camera` | `nodes/camera.yaml` | RGB画像（深度は取得しません） |
| [DIGIT](../sensors/digit.md) | `digit_left`, `digit_right` | `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | 左右の触覚RGB画像 |

センサーのシリアル番号は実機に合わせて設定します．センサー名はデータセットのfeature名にも使われます．

## 観測と行動

記録するデータセットと方策の入出力は，同じ並びと単位です．

| 名前 | 要素 | 単位 |
| --- | --- | --- |
| `observation.state`，`action` | 17（`follower.torso_yaw`，`follower.head_yaw`，`follower.head_pitch`，右腕 `follower.r_arm_sh_pitch1` … `follower.r_arm_grip`，左腕 `follower.l_arm_sh_pitch1` … `follower.l_arm_grip`） | Dynamixelの位置カウント |
| `observation.effort` | 17（同じ並び．テンプレートの `record_effort: true`） | mA（電流） |
| `observation.leader` | 17（leaderの関節位置．同じ並び．名前は接頭辞なしの `torso_yaw` … `l_arm_grip`．leaderを使わないオプション `policy` では記録しない） | Dynamixelの位置カウント |
| `observation.images.camera` | 480×640×3（RGB） | [storage](../reference/configuration.md#image-storage) |
| `observation.images.digit_left`，`observation.images.digit_right` | 320×240×3（RGB．オプション `digit`） | [storage](../reference/configuration.md#image-storage) |
| `observation.meta.<node>.valid`，`capture_age_ms`，`ready_age_ms` | 各1（float32）．記録するノードごと：`leader`，`follower`，`camera`，`digit` のときは `digit_left`，`digit_right` も | `valid` は0/1，経過時間はms |
| `observation.meta.<node>.seq`，`capture_ns`，`ready_ns`，`receive_ns` | 各1（int64）．同じノード | 通し番号，単調時計のns |
| `action.valid`，`action.clamped` | 各1（float32） | 0/1 |
| `action.meta.follower.valid`，`clamped`，`seq`，`sent_ns` | 各1（`valid`，`clamped` はfloat32，`seq`，`sent_ns` はint64） | 0/1，指令の番号，単調時計のns |

- `observation.leader`，`observation.meta.<node>.*`，`action.valid`，`action.clamped`，`action.meta.follower.*` の意味，欠測の記録のしかた，指令のなかった行の `action` の中身は，[設定](../reference/configuration.md) の「記録と再開」で説明しています．どのロボットでも同じです．
- 方策（オプション `policy`）は，`camera` と左右のDIGITを観測し（`nodes/policy.yaml` の `observe`），`infer` は17関節の目標をカウントで返します．1手 `[17]` か，まとめた行動 `[H, 17]` です．
- `max_speed` はカウント/sです（テンプレートは `{follower: 1024}`）．
- テンプレートの既定の方策 `roboloom.policy:hold` は，腕をその場に留めます．方策の書き方は [方策で動かす](../controllers/policy.md) にあります．

## 起動オプションと組み合わせ

設定は `.roboloom/rakuda2/config.yaml` の1つです．オプションを何も有効にしない構成は，通常leader・`joint` controller・RealSenseです．テンプレートは次の起動オプションを持ちます（既定はすべて無効）．選び方は [CLI](../reference/cli.md)，規則は [設定](../reference/configuration.md) の「起動オプション」を参照してください．

| オプション | 内容 | 必要 / 競合 | データセット名 |
| --- | --- | --- | --- |
| `digit` | 左右DIGITを記録する | | `-digit` を付ける |
| `gravity` | leaderの左右腕を重力補償する（`nodes/leader_gravity.yaml`） | | 変えない |
| `bilateral` | 力の逆送（実機未検証）．leader・controller・robotを置き換え，推定器 `effort` を足す | `gravity` が必要 | `-bilateral` を付ける |
| `policy` | 学習した方策がfollowerを動かす．leaderとcontrollerを外し，`controllers.policy` を足す．`roboloom infer` が自動で有効にする | `digit` が必要，`gravity` と競合 | `-eval` を付ける |

| 有効なオプション | Leader | Sensors | `repo_id` |
| --- | --- | --- | --- |
| なし | 通常 | RealSense | `local/rakuda2` |
| `digit` | 通常 | RealSense + 左右DIGIT | `local/rakuda2-digit` |
| `gravity` | 重力補償付き | RealSense | `local/rakuda2` |
| `gravity`，`digit` | 重力補償付き | RealSense + 左右DIGIT | `local/rakuda2-digit` |
| `gravity`，`bilateral` | 重力補償付き＋力の逆送（実機未検証） | RealSense | `local/rakuda2-bilateral` |
| `digit`，`policy` | なし（方策） | RealSense + 左右DIGIT | `local/rakuda2-digit-eval` |

制約：

- `gravity` は，[Quick start](../quick-start/rakuda2.md) の測定（`calibrate-joints`，`measure-travel`，`identify-gravity`，`tune-gravity`）を済ませてから使います．測定値が `SET_...` のままだと読み込みを拒否します．
- `gravity` の有無でleaderのOperating Modeが変わります．端末から実機で起動するとき，CLIはEEPROMの差分を表示し，確認してから書きます．
- `policy` の方策（`nodes/policy.yaml`）はDIGITの画像を観測するので，`digit` が必要です．leaderを使わないため `gravity` とは同時に使えません．`gravity` を必要とする `bilateral` とも併用できません．
- `gravity` はデータセット名を変えません．記録するfeatureが通常leaderと同じためです．通常leaderと重力補償付きleaderのエピソードは同じデータセットに入ります．
- 画像featureが変わるため，`digit` の有無でデータセットが分かれます．RealSenseだけの既存データセットへDIGITのエピソードは追記しません．

## バイラテラル（実機未検証）

オプション `bilateral` は，followerが受けた外力をleaderへ返す組み合わせです．実機では確かめていません．模擬の試験だけを通しています．

| ノード | 設定 | 内容 |
| --- | --- | --- |
| robot | `nodes/follower_bilateral.yaml` | 腕を電流制限つき位置制御（Operating Mode 5，`current_position`）にする．`goal_current_mA` が接触時の力の上限．`SET_FOLLOWER_ARM_GOAL_CURRENT_mA` を決め，`roboloom commission` でModeとCurrent Limitを書く |
| leader | `nodes/leader_bilateral.yaml` | 重力補償付きleaderの腕グループに `feedback:` を足したもの |
| controller | `nodes/controller_bilateral.yaml` | `feedback:` で推定器と返す関節（初期値は右肘1関節，小さいゲイン）を指定 |
| estimator | `nodes/effort.yaml` | followerの外力の推定器（`model_residual`）．followerで同定した重力モデル `calibration/effort_gravity_<side>.yaml` を使う．接触の閾値は実測前の仮の値 |

制約：

- `goal_current_mA` は，EEPROMの `current_limit` 以下でなければ起動を拒否します．
- Mode 5へ書き換えた後のモーターでは，通常の `nodes/follower.yaml`（Mode 3）は起動時の検査で拒否されます．戻すときは `commission follower` で書き戻します．端末から実機で起動する場合は，CLIが起動前に差分を表示し，確認してから書き戻します．
- `bilateral` を有効にしたコマンド（`roboloom commission follower --with bilateral` など）は，設定全体を読み込みます．そのため，followerの重力モデル（`calibration/effort_gravity_<side>.yaml`）が無いと止まります．重力の同定はModeを書き換える前（Mode 3のまま）にできるので，先に同定してから `commission` します．
- 設定キーは [設定](../reference/configuration.md) の「力の逆送」にあります．

## 起動前の確認

ポート，モーターID，モデル，EEPROM，関節範囲，速度・電流上限を実機で確認します．テンプレートの `torque` は `true` なので，初回にfollowerを動かさず経路を確かめる場合は **起動前に `nodes/follower.yaml` を `torque: false` に変更** してください．leader側の制御は独立しており，トリガーや重力補償は通電します．

制御周期はテンプレートで120 Hzです．前提条件と下げ方は [設定](../reference/configuration.md) の「制御周期」を参照してください．

セットアップから収集までの手順は [Rakuda2 Quick start](../quick-start/rakuda2.md)，制御値の意味は [Gravity tuning](../reference/gravity-tuning.md) を参照してください．

## Web camera

`camera` の RealSense YAML を [Web camera](../sensors/webcam.md) の `opencv_rgb` 設定に差し替えられます。OpenCV は共通依存に含まれます。leader・controller・DIGIT と組み合わせる経路は共通ですが、Web カメラ実機との組み合わせは未検証です。`policy` は学習時と同じ画像内容・解像度に合わせてください。
