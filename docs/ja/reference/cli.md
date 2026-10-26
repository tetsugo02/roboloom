# CLI

以下では `roboloom` と略記します．uv環境では先頭に `uv run` を付けます．各コマンドの引数は `roboloom <command> --help` でも確認できます．

| コマンド | 用途 |
| --- | --- |
| `init rakuda2` | 機体設定を生成する |
| `probe <port>` | DynamixelのID・モデル・レジスタを読み取る |
| `validate <experiment>` | デバイスを開かず設定とdataflowを検証する |
| `calibrate-joints <calibration>` | URDF零姿勢の実測カウントをcalibrationに保存する |
| `measure-travel <calibration> --out <path>` | 手で動かした可動域を保存する |
| `identify-gravity <calibration> --out <path> --collect --hardware` | 保持電流を測定して重力モデルを同定する |
| `commission <experiment> <node> --hardware` | 差分と操作者の確認を経てEEPROMを書き，読み戻す |
| `tune-gravity <experiment> leader <group> --hardware` | gainとholdを対話調整する |
| `gravity-check <experiment> leader <group> --hardware` | 補償の有無による姿勢の変化を測る |
| `run <experiment> --hardware` | 操作画面で収集する |
| `record <experiment> --task <text> --seconds <n> --hardware` | 一定時間のエピソードを収集する（`--episodes` で回数指定） |
| `session <experiment> <operation> [task]` | 起動済みの実験へ操作を送る |

`calibrate-joints` / `measure-travel` はバスには書き込みませんが，ローカルYAMLを保存します．腕のトルクが切れていることが必要です．`identify-gravity --collect`，`tune-gravity`，`gravity-check` はモーターに通電します．dataflowと同時に同じバスを開かないでください．

## runの操作

| 入力 | 動作 |
| --- | --- |
| `start <task>` | 準備状態を確認し追従・記録を始める |
| `stop` | 追従・記録を止める（保存は別操作） |
| `save` | エピソードを保存する |
| `discard` | エピソードを破棄する |
| `release` | HOLD中のfollowerを，腕を支えた確認後に脱力する |
| `estop` | 非常停止する |
| `quit` | 腕を支えた確認後にdataflowを終了する．Enterでfollowerも脱力，`hold` でfollowerは保持 |

`stop` は脱力操作ではありません．`FAULT` / `ESTOP` / `RELEASED` は自動復帰しません．実機の開始・終了手順は [Quick start](../quick-start/rakuda2.md) にあります．既存の方策APIなど，leader以外の詳細は [Python API](python-api.md) を参照してください．
