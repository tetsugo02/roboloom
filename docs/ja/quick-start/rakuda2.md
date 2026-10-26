# Rakuda2 Quick start

[インストール](installation.md) の実機収集用extras（`record` / `hardware`）が入っている前提です．設定ファイルはリポジトリルートからの相対パスで示します．対応機器と構成は [Rakuda2](../robots/rakuda2.md) を参照してください．

## 1. 機体設定と読み取り確認

```bash
uv run roboloom init rakuda2
ls /dev/serial/by-id/
```

既に `.roboloom/rakuda2/` がある場合，`init` は上書きしません．既存の機体設定を確認して使います．

leader / followerのU2D2ポートを識別し，別のプロセスが使っていない状態で読み取ります．次の `<...>` は実際のポートに置き換えます．

```bash
uv run roboloom probe /dev/serial/by-id/<follower-U2D2>
uv run roboloom probe /dev/serial/by-id/<leader-U2D2>
```

| ファイル（`.roboloom/rakuda2/` 内） | 設定・照合する内容 |
| --- | --- |
| `nodes/robot.yaml` | followerの `port`，ID・モデル，`registers`，実測した安全な `limits`，速度・電流・温度上限 |
| `nodes/leader.yaml`, `nodes/leader_gravity.yaml` | leaderの `port`，ID・モデル，`registers`，制御則 |
| `nodes/camera.yaml` | RealSenseの `serial` |
| `nodes/digit_left.yaml`, `nodes/digit_right.yaml` | 左右DIGITの `serial` |
| `calibration/leader_right.yaml`, `calibration/leader_left.yaml` | leaderの `port`，関節とURDFの対応，零点，方向 |

`probe` の結果から，各関節の `homing_offset` などを設定へ反映します．重力補償では動作モードとCurrent Limitを意図的に変えるので，現在のEEPROMをそのままコピーせず，後述の `commission` で設定との差を確認します．

テンプレートの値は機体に対する安全保証ではありません．とくにfollowerの `limits.min/max` は広い初期値です．実測した安全な範囲へ狭め，停止・脱力方法も機体ごとに確かめます．通常leaderでもトリガーには通電します．

初回の経路確認では **`nodes/robot.yaml` の `torque: true` を `torque: false` に変更** します．followerのトルクを切った状態で腕を支持してください．この設定はleader側の通電を止めません．

## 2. 通常leaderで収集経路を確認

最初はRealSenseのみの構成を使えます．DIGITをまだ接続しない場合も，この実験なら参照しません．

```bash
uv run roboloom validate rakuda2/experiment_camera
```

参照する設定に `SET_...` が残っていれば，場所が表示されます．埋めてから再検証します．`validate` はデバイスを開かないので，実機のEEPROMや停止挙動の照合は別途必要です．

EEPROMが意図した設定と違う場合は，dataflowを止め，両腕を支えた状態で `commission` を実行します．表示された変更を確認してから承認します．EEPROMを書き込み，読み戻す操作です．

```bash
uv run roboloom commission rakuda2/experiment_camera robot --hardware
uv run roboloom commission rakuda2/experiment_camera leader --hardware
uv run roboloom run rakuda2/experiment_camera --hardware
```

起動時にもID・モデル・EEPROMを照合し，不一致なら拒否します．画面で全ノードの状態とセンサーの取得周期を確認します．leaderをfollowerの姿勢へ揃え，controllerが `following` になったら，次を順に入力します．

```text
start pipeline check
stop
save
release
quit
```

`release` の確認時はfollowerの腕を支えます．`quit` でleaderも脱力するため，leaderの腕も支えてから終了します．この段階ではfollowerの `torque: false` を維持し，観測・記録経路を確認します．

## 3. 重力補償用の零点・方向・可動域を設定

以降はdataflowを止め，他のツールがleaderのバスを開いていない状態で行います．腕を支持し，トルクオフを確認してください．左右のcalibration YAMLのモーターIDとURDF関節の対応を確認し，URDF零姿勢に置いて測定します．

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_right.yaml
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_left.yaml
```

保存された `zero` と各関節の `direction`（`1` または `-1`）を確認し，対応・零点・方向を検証できたら各ファイルの `confirmed: true` を設定します．テンプレートの零点や符号を未確認のまま承認しないでください．

脱力したleaderを手でゆっくり動かし，左右の可動域を測定します．

```bash
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/travel_left.yaml
```

この操作はバスから位置を読むだけですが，結果をYAMLに保存します．この範囲はleaderの暴走検知に使い，followerの安全限界の代用にはしません．

## 4. 重力モデルを同定

`identify-gravity --collect` は保持電流を測るため **モーターに通電** します．周囲と支持方法を確認し，画面の姿勢配置・手を離す指示に従います．

```bash
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect --hardware
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/gravity_left.yaml --collect --hardware
```

出力の適合度と警告を確認します．関節方向や計測品質が不適切だと保存を拒否します．原因を直して再計測し，未生成のモデルで次へ進まないでください．設定・測定した姿勢によって誤差が残るため，次にgainとholdを調整します．

## 5. 重力補償モードを設定・調整

`nodes/leader_gravity.yaml` が左右の `gravity_<side>.yaml`，`travel_<side>.yaml`，`gravity_tuning_<side>.yaml` を参照します．電流上限・watchdog・可動域を確認した上で設定を検証し，EEPROMの変更を確認します．

```bash
uv run roboloom validate rakuda2/experiment_gravity
uv run roboloom commission rakuda2/experiment_gravity leader --hardware
uv run roboloom tune-gravity rakuda2/experiment_gravity leader right_arm --hardware
uv run roboloom tune-gravity rakuda2/experiment_gravity leader left_arm --hardware
```

調整開始時は両腕を支えます．調整対象でない側は脱力しています．

| 操作 | 内容 |
| --- | --- |
| `↑` / `↓` | 関節を選ぶ |
| `[` / `]` | 重さを打ち消すgainを下げる / 上げる |
| `-` / `=` | 動き始めの保持力 `hold_mA` を下げる / 上げる |
| `0` | 選択関節の重力補償を切り替えて比較する |
| `s` | 調整値を保存する |
| `q` | 終了する |

腕が下がるならgainを上げ，上がるなら下げます．動かし始めが重い場合はholdを下げます．電流が上限に張り付く場合は調整を止めて設定を見直します．詳細と制約は [Gravity tuning](../reference/gravity-tuning.md) にあります．Current Limitとwatchdogは別の保護であり，XC330のwatchdog作動だけで電流がゼロになるとは想定しません．

## 6. Teleoperationでデータ収集

収集前に，必要なら [leaderの関節固定と腰yaw相殺](../controllers/leader.md) を設定します．使用する `leader*.yaml` の `control` と `controller.yaml` の `couplings` を変更します．固定するleader関節は起動前にfollowerへ揃えます．通常・重力補償付き構成のどちらでも使える設定ですが，組み合わせの実機動作は未検証です．

重力補償付き構成の既定は **RealSenseのみ** です．DIGITも記録するときは [Rakuda2の構成例](../robots/rakuda2.md) に従いセンサーと保存先を変更します．通常leader + RealSense + DIGITなら `rakuda2` を指定します．

followerを動かす前に，機体の安全範囲・低速での追従・停止・脱力を確認し，`nodes/robot.yaml` を `torque: true` に変更します．両腕を支え，dataflow停止状態でEEPROMの確認を済ませてから起動します．

```bash
uv run roboloom validate rakuda2/experiment_gravity
uv run roboloom run rakuda2/experiment_gravity --hardware
```

1. robotの状態，センサー取得周期，recorderを確認します．
2. leaderをfollowerに揃え，controllerの `following` を確認します．`aligning` の警告中は，姿勢を合わせてから開始を再試行します．
3. `start pick up the cup` で追従・記録を始め，leaderで操作します．
4. `stop` で止めます．`stop` はfollowerを保持し，脱力はしません．
5. `save` で保存，または `discard` で破棄します．保存結果の欠損率・指令の有効率・制御周期の警告を確認します．
6. 次の `start <task>` で別エピソードを収集できます．
7. 終了時は `stop` → 保存または破棄 → 腕を支えて `release` → leaderも支えて `quit` の順にします．

異常時の `estop` はラッチされ，自動復帰しません．物理的な支持・停止手段を使える状態で操作してください．

一定時間の収集は次でも行えます．controllerの準備後，画面の指示に従いEnterで開始します．

```bash
uv run roboloom record rakuda2/experiment_gravity --task "pick up the cup" --seconds 30 --episodes 3 --hardware
```

Pythonからは同じdataflowを使えます．

```python
from roboloom import Session

with Session.launch("rakuda2/experiment_gravity", hardware=True) as session:
    session.wait_ready()
    result = session.record("pick up the cup", seconds=30)
    print(result.index, result.frames, result.warnings)
```

スクリプト終了時も腕の支持が必要です．手動の停止・解放を組み込む場合は [Python API](../reference/python-api.md) を参照してください．

既定の保存先は `.roboloom/rakuda2/datasets/rakuda2-camera` です（`output` は実験YAMLからの相対パス）．ログは `.roboloom/rakuda2/logs/` に残ります．設定・校正・調整のYAMLを管理し，同じ設定・FPS・featureのデータセットへ収集を再開できます．
