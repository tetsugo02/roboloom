# Configuration

## 実験の指定

`roboloom init rakuda2` が `.roboloom/rakuda2/` に実験・ノード・calibration YAMLを作ります．既存のディレクトリを上書きしません．実験名 `rakuda2` は `experiment.yaml`，`rakuda2/experiment_gravity` は `experiment_gravity.yaml` を指します．ファイルパスでも指定できます．

## 実験YAML

```yaml
robot_id: rakuda2
repo_id: local/rakuda2
output: datasets/rakuda2
mode: hardware
dataset_fps: 15
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
robots:
  robot: nodes/robot.yaml
sensors:
  camera: nodes/camera.yaml
  digit_left: nodes/digit_left.yaml
  digit_right: nodes/digit_right.yaml
recorder: nodes/recorder.yaml
session: nodes/session.yaml
```

ノードYAMLのパスと `output` は実験ファイルのディレクトリが基準です．上の保存先は `.roboloom/rakuda2/datasets/rakuda2` です．ノード名はdoraのIDとデータセットのfeature名に使われます．現在は1実験につきrobotが1台，対応するcontrollerが1個です．

各ノードの `type` が実装を選びます．`SET_...` は機体固有の未設定値で，参照する設定に残っていると実行が拒否されます．`validate` は設定とdataflowの整合性を調べ，デバイスは開きません．EEPROMの実機との一致，画像取得，停止挙動までは確認しません．

## 関節固定と相殺

leaderノードの `control` は，`free`（脱力），`position`（leaderでは通電時の姿勢を保持），`spring`，`gravity_comp` などを関節グループごとに選びます．全関節をちょうど1回ずつ指定します．`joint` controllerの `couplings`（既定 `[]`）は，`{joint, source, scale, reference}` のリストで，他のfollower関節の `reference` からの実測変位を目標へ加えます．両者は独立した設定です．[Leaderの設定例](../controllers/leader.md)を参照してください．

## 記録と再開

`record` extraでLeRobotDataset 0.6.1に保存します．取得・利用可能・受信・指令送信の単調時計時刻を区別して整列し，欠損はゼロ値と有効フラグで表します．`task` はフレームに記録されます．

同じデータセットに次のエピソードを追記できます．再開時はFPSとfeatureの互換性を検査します．センサー構成を変更したら `repo_id` / `output` を分けてください．

`recorder.quality` の `max_missing_rate`，`min_action_valid_rate`，`max_interval_ms` で品質警告の閾値を指定できます．保存結果のmetricsとwarningsを確認します．

## ログと設定の管理

ログは実験ファイルの隣の `logs/<実験名>-<時刻>/` に置きます．YAMLの設定・重力モデル・可動域・調整値はGitで管理し，生データ `*.npz`・ログ・dataset・FIFOは生成した `.roboloom/.gitignore` で除外します．

APIの詳細は [Python API](python-api.md)，コマンドは [CLI](cli.md) にあります．
