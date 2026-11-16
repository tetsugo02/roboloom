# Policy

`roboloom.policy` defines what the policy node runs and the functions that load a policy. How to use them is in the [Policies and inference](../../policy/index.md) chapter (in particular [Custom policies](../../policy/custom.md)); this page holds the descriptions generated from the docstrings.

## The policy contract { #contract }

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

## A policy that holds { #hold }

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

## Another process { #remote }

<span class="status status--mock">Mock only</span>

::: roboloom.policy.remote
    options:
      heading_level: 3
      members:
        - connect
        - serve
        - RemotePolicy
        - RemotePolicyError

## Replay { #replay }

<span class="status status--mock">Mock only</span>

::: roboloom.policy.replay
    options:
      heading_level: 3
      members:
        - load
        - Replay
