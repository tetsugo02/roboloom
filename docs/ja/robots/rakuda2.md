# Rakuda2

Rakuda2は，胴体・頭部3関節，左右それぞれ腕6関節とグリッパー1関節の **17関節** を持つ構成です．関節値はDynamixelの生の位置カウント，電流はmAで扱います．

followerは `type: rakuda2_follower`，操作入力は `type: rakuda2_leader` です．leaderとfollowerは別のDynamixelバスを使い，それぞれのノードが専有します．設定は `roboloom init rakuda2` で作成します．

## 対応controller

現在の操作ガイドは [Leader](../controllers/leader.md) を対象にします．`inputs.leader` で関節位置を読み，`type: joint` のcontrollerがfollowerへ変換します．

- 通常のleader：腕・胴体・頭部は脱力，トリガーはばねとして制御します．
- 重力補償付きleader：左右腕を `gravity_comp` で制御し，同定した重力モデル・可動域・調整値を使います．
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

重力補償とDIGITを併用するときは，生成した `experiment_gravity.yaml` の `sensors` に次を追加します．

```yaml
sensors:
  camera: nodes/camera.yaml
  digit_left: nodes/digit_left.yaml
  digit_right: nodes/digit_right.yaml
```

追加時には `repo_id` と `output` も，例として `local/rakuda2-gravity-digit` と `datasets/rakuda2-gravity-digit` に変更してください．画像featureが変わるため，RealSenseだけの既存データセットへは追記できません．

## 起動前の確認

ポート，モーターID，モデル，EEPROM，関節範囲，速度・電流上限を実機で確認します．テンプレートの `torque` は `true` なので，初回にfollowerを動かさず経路を確かめる場合は **起動前に `nodes/robot.yaml` を `torque: false` に変更** してください．leader側の制御は独立しており，トリガーや重力補償は通電します．

セットアップから収集までの手順は [Rakuda2 Quick start](../quick-start/rakuda2.md)，制御値の意味は [Gravity tuning](../reference/gravity-tuning.md) を参照してください．
