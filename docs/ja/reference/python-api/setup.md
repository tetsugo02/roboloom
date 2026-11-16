# Setup

`roboloom.setup` は，計測と設定の手順（EEPROM，零点，可動域，重力，姿勢，卓上試験）を Python から呼ぶ API です．使い方の例のあとに，docstring から生成した説明（英語）を載せます．

## 使い方 { #usage }

- 計測の本体は，結果を dataclass で返し，失敗を例外で知らせます．
  - `ConfigError`：設定の誤り．
  - `SetupError`：計測の前提を満たさない，精度が足りない．
  - `HardwareError`：トルクが入っているなど，機器の状態が合わない．
  - `Cancelled`：確認が拒否された．何も書いていない．
- 人の操作が要る場面は，`Operator` に問い合わせます．
  - 腕を支える，姿勢を置く，Enter を押す，など．
  - CLI は `TerminalOperator` を渡します．
  - スクリプトや試験では `ScriptedOperator` に答えを並べて渡せます．
- 設定を取る関数は，パス，機体名，読み込み済みの `RobotConfig` のどれでも受け取ります．オプションやモードを選ぶときは，`load_config(..., options=..., mock=...)` で読み込んでから渡します．
- `plan_commission`，`watchdog_test`，`gravity_check` は，mockの設定を拒否します．

各手順に対応するコマンドは [CLI](../cli.md#commands) にあります．

```python
from roboloom import setup
from roboloom.operator import TerminalOperator

op = TerminalOperator()
from roboloom import load_config

gravity = load_config("rakuda2", options=["gravity"])
plan = setup.plan_commission(gravity, "leader")
for line in plan.lines():
    print(line)
setup.apply_commission(plan, op)  # 確認してから書く

fit = setup.identify_gravity(
    ".roboloom/rakuda2/calibration/leader_right.yaml",
    ".roboloom/rakuda2/calibration/gravity_right.yaml",
    op,
    collect=True,
)
for joint in fit.joints:
    print(joint.joint, f"{joint.explained:.0%}")
```

```python
# 重力補償の調整を，画面なしで（例：値を順に試す自動化）
tuning = setup.open_tuning(gravity, "leader", "right_arm")
try:
    tuning.start()
    tuning.key("]")  # 選んだ関節の gain +0.1
    for _ in range(120):
        tuning.step()
        time.sleep(tuning.period_s)
    print([(r.joint, r.gain, r.sent_mA) for r in tuning.rows()])
finally:
    tuning.close()
```

## EEPROM { #commission }

::: roboloom.setup.plan_commission
    options:
      heading_level: 3

::: roboloom.setup.apply_commission
    options:
      heading_level: 3

::: roboloom.setup.CommissionPlan
    options:
      heading_level: 3

## 零点と可動域 { #calibration }

::: roboloom.setup.calibrate_joints
    options:
      heading_level: 3

::: roboloom.setup.Calibration
    options:
      heading_level: 3

::: roboloom.setup.measure_travel
    options:
      heading_level: 3

::: roboloom.setup.Travel
    options:
      heading_level: 3

## 重力 { #gravity }

::: roboloom.setup.identify_gravity
    options:
      heading_level: 3

::: roboloom.setup.collect_holding_currents
    options:
      heading_level: 3

::: roboloom.setup.fit_gravity
    options:
      heading_level: 3

::: roboloom.setup.GravityFit
    options:
      heading_level: 3

::: roboloom.setup.gravity_check
    options:
      heading_level: 3

::: roboloom.setup.release_trial
    options:
      heading_level: 3

::: roboloom.setup.GravityCheck
    options:
      heading_level: 3

::: roboloom.setup.open_tuning
    options:
      heading_level: 3

::: roboloom.setup.TuningSession
    options:
      heading_level: 3

## 姿勢 { #poses }

::: roboloom.setup.capture_pose
    options:
      heading_level: 3

## 卓上試験 { #bench-tests }

::: roboloom.setup.check_hold
    options:
      heading_level: 3

::: roboloom.setup.hold_trial
    options:
      heading_level: 3

::: roboloom.setup.HoldResult
    options:
      heading_level: 3

::: roboloom.setup.watchdog_test
    options:
      heading_level: 3

::: roboloom.setup.watchdog_trial
    options:
      heading_level: 3

::: roboloom.setup.WatchdogResult
    options:
      heading_level: 3

## 操作者 { #operator }

::: roboloom.operator.Operator
    options:
      heading_level: 3

::: roboloom.operator.TerminalOperator
    options:
      heading_level: 3

::: roboloom.operator.ScriptedOperator
    options:
      heading_level: 3
