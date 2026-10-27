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

leaderノードの `control` は，`free`（脱力），`position`（leaderでは通電時の姿勢を保持），`spring`，`gravity_comp` などを関節グループごとに選びます．全関節をちょうど1回ずつ指定します．`joint` controllerの `couplings`（既定 `[]`）は，`{joint, source, scale, reference}`（任意で `lead_ms`） のリストで，他のfollower関節の `reference` からの実測変位を目標へ加えます．両者は独立した設定です．[Leaderの設定例](../controllers/leader.md)を参照してください．

## 制御周期

`robot.yaml` の `control_hz` と，leaderの `poll_hz` は，そのノードがバスを読み書きする周期です．1周期の仕事（状態の読み出し，制御則の計算，目標値の書き込み）が周期に収まる必要があります．周期を上げると，leaderの電流制御とfollowerの追従が細かくなります．

周期は次の手順で決めます．

1. `roboloom probe <port>` を各ポートで実行します．状態の読み出し時間と，目安の周期上限（読み出しと書き込みに周期の70%を使う値）を表示します．`probe` は書き込みません．
2. `control_hz` と `poll_hz` を設定し，`run` の画面で確かめます．robotとleaderの行の `work … ms (max …)` が1周期の仕事の時間です．最大値が周期の70%程度以下で，`tick` が周期どおりなら，その周期で動いています．
3. 超える場合は周期を下げます．

Dynamixelのバスは，全モーターのファームウェアがv45以上なら，起動時にFast Sync Read（全モーターの応答を1パケットで返す読み出し）へ切り替えます．使えないときは通常の読み出しのまま動き，起動時に理由を表示します．

Rakuda2での実測値です（2026-10-27，17モーター，1 Mbps，FTDI latency timer 1 ms）．

| 読み出し | 時間 |
| --- | --- |
| 状態（位置・速度・電流），通常のSync Read | 5.0 ms |
| 状態，Fast Sync Read | 4.0 ms |
| Bus Watchdog（1レジスタ），Fast Sync Read | 2.0 ms |

また，Dynamixel SDKが送信のたびに行う出力の待ち（`flush`）を省いています．leaderの1周期では，これだけで約1.9 msかかっていました．パケットの順序は変わりません．

時間を節約するため，次の読み出しは毎周期は行いません．

- leaderのBus Watchdog：目標値の書き込みが `bus_watchdog_ms` の半分以上途切れたときと，100 msごとに読みます．作動していたら，今までどおり電流制御の関節を脱力します．
- followerの `health`：`every_ticks` 周期ごとに，Bus Watchdog・ハードウェアエラー・温度を1つずつ順に読みます．各値は `every_ticks` の3倍の周期ごとに更新されます．

テンプレートは120 Hzです．Rakuda2の実機で確かめた結果です（2026-10-27，121秒）．

| | 1周期の仕事（平均，最大） | 周期の間隔 |
| --- | --- | --- |
| leader（重力補償） | 4.3 ms，6.8 ms | 中央値 8.0 ms，p99.9 10.1 ms |
| follower | 3.7 ms，6.1 ms | 7.7 ms |

この間に1回，約120 msの停止がありました．60 Hzでも同じ程度の停止が起きており，周期とは関係ありません．120 HzはFTDIのlatency timerが1 msで，Fast Sync Readが使えることを前提にしています．`probe` の目安がこれを下回る場合や，`work` の最大が周期の70%を超える場合は，`control_hz` と `poll_hz` を下げてください（例：60）．

## 記録と再開

`record` extraでLeRobotDataset 0.6.1に保存します．取得・利用可能・受信・指令送信の単調時計時刻を区別して整列し，欠損はゼロ値と有効フラグで表します．`task` はフレームに記録されます．

同じデータセットに次のエピソードを追記できます．再開時はFPSとfeatureの互換性を検査します．センサー構成を変更したら `repo_id` / `output` を分けてください．

`recorder.quality` の `max_missing_rate`，`min_action_valid_rate`，`max_interval_ms` で品質警告の閾値を指定できます．保存結果のmetricsとwarningsを確認します．

## ログと設定の管理

ログは実験ファイルの隣の `logs/<実験名>-<時刻>/` に置きます．YAMLの設定・重力モデル・可動域・調整値・保存した初期姿勢（`poses/`）はGitで管理し，生データ `*.npz`・ログ・dataset・FIFOは生成した `.roboloom/.gitignore` で除外します．

APIの詳細は [Python API](python-api.md)，コマンドは [CLI](cli.md) にあります．
