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

## 実験の組み合わせ

| 実験 | Leader | Sensors |
| --- | --- | --- |
| `rakuda2` / `rakuda2/experiment` | 通常 | RealSense + 左右DIGIT |
| `rakuda2/experiment_camera` | 通常 | RealSense |
| `rakuda2/experiment_gravity` | 重力補償付き | RealSense |
| `rakuda2/experiment_bilateral` | 重力補償付き＋力の逆送（実機未検証） | なし |

重力補償とDIGITを併用するときは，生成した `experiment_gravity.yaml` の `sensors` に次を追加します．

```yaml
sensors:
  camera: nodes/camera.yaml
  digit_left: nodes/digit_left.yaml
  digit_right: nodes/digit_right.yaml
```

追加時には `repo_id` と `output` も，例として `local/rakuda2-gravity-digit` と `datasets/rakuda2-gravity-digit` に変更してください．画像featureが変わるため，RealSenseだけの既存データセットへは追記できません．

## バイラテラル（実機未検証）

`experiment_bilateral` は，followerが受けた外力をleaderへ返す組み合わせです．実機では確かめていません．模擬の試験だけを通しています．

| ノード | 設定 | 内容 |
| --- | --- | --- |
| robot | `nodes/robot_bilateral.yaml` | 腕を電流制限つき位置制御（Operating Mode 5，`current_position`）にする．`goal_current_mA` が接触時の力の上限．`SET_FOLLOWER_ARM_GOAL_CURRENT_mA` を決め，`roboloom commission` でModeとCurrent Limitを書く |
| leader | `nodes/leader_bilateral.yaml` | 重力補償付きleaderの腕グループに `feedback:` を足したもの |
| controller | `nodes/controller_bilateral.yaml` | `feedback:` で推定器と返す関節（初期値は右肘1関節，小さいゲイン）を指定 |
| estimator | `nodes/effort.yaml` | followerの外力の推定器（`model_residual`）．followerで同定した重力モデル `calibration/effort_gravity_<side>.yaml` を使う．接触の閾値は実測前の仮の値 |

制約：

- `goal_current_mA` は，EEPROMの `current_limit` 以下でなければ起動を拒否します．
- Mode 5へ書き換えた後のモーターでは，通常の `nodes/robot.yaml`（Mode 3）は起動時の検査で拒否されます．戻すときは `commission` で書き戻します．
- 設定キーは [設定](../reference/configuration.md) の「力の逆送」にあります．

## 起動前の確認

ポート，モーターID，モデル，EEPROM，関節範囲，速度・電流上限を実機で確認します．テンプレートの `torque` は `true` なので，初回にfollowerを動かさず経路を確かめる場合は **起動前に `nodes/robot.yaml` を `torque: false` に変更** してください．leader側の制御は独立しており，トリガーや重力補償は通電します．

制御周期はテンプレートで120 Hzです．前提条件と下げ方は [設定](../reference/configuration.md) の「制御周期」を参照してください．

セットアップから収集までの手順は [Rakuda2 Quick start](../quick-start/rakuda2.md)，制御値の意味は [Gravity tuning](../reference/gravity-tuning.md) を参照してください．
