# Policy

`roboloom.policy` は，方策nodeが動かす方策の形と，方策を読み込む関数です．使い方は [方策と推論](../../policy/index.md) の章（特に [自作方策](../../policy/custom.md)）にあり，このページは docstring から生成した説明（英語）を載せます．

## 方策の形 { #contract }

::: roboloom.policy
    options:
      heading_level: 3
      show_root_heading: false
      members: false

::: roboloom.policy.Policy
    options:
      heading_level: 3

::: roboloom.policy.PolicySpec
    options:
      heading_level: 3

::: roboloom.policy.load_policy
    options:
      heading_level: 3

## 姿勢を保つ方策 { #hold }

::: roboloom.policy.hold
    options:
      heading_level: 3

::: roboloom.policy.Hold
    options:
      heading_level: 3

## LeRobot { #lerobot }

::: roboloom.policy.lerobot
    options:
      heading_level: 3
      members:
        - load
        - LeRobotPolicy

## 別のprocess { #remote }

<span class="status status--mock">模擬のみ</span>

::: roboloom.policy.remote
    options:
      heading_level: 3
      members:
        - connect
        - serve
        - RemotePolicy
        - RemotePolicyError

## 再生 { #replay }

<span class="status status--mock">模擬のみ</span>

::: roboloom.policy.replay
    options:
      heading_level: 3
      members:
        - load
        - Replay
