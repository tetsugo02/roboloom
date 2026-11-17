# Hooks

<span class="status status--mock">Mock only</span>

hook は policy node のlocalな extension です．policy を変えずに release gate，residual action の補正，lifecycle event の記録を追加できます．hooks は **mock only** です．以下の例は検証済みの tactile detector ではありません．

## 1. Write a local hook { #write }

robot configuration の隣か installed package に保存します．この例は gripper の counts が open 側に増える前提です．hardware validation の前に image mean の条件を task-specific な detector に置き換えます．`step` は変更しない場合に `None` を返せます．

```python
# .roboloom/<robot>/release_gate.py
from collections.abc import Sequence

import numpy as np

from roboloom.errors import ConfigError
from roboloom.hooks import Hook, HookSpec, Requirements, StepContext


class ReleaseGate(Hook):
    def __init__(self, joints: Sequence[str], max_image_mean: float = 80):
        self.joints = tuple(joints)
        self.max_image_mean = max_image_mean

    def requirements(self) -> Requirements:
        return Requirements(
            observe=(
                "observation.state",
                "observation.images.digit_left",
                "observation.images.digit_right",
            ),
            writes=self.joints,
            sources=("policy", "teleop"),
            on_error="hold",
        )

    def bind(self, spec: HookSpec) -> None:
        if any(
            spec.units[spec.names.index(j)] != "dynamixel_count" for j in self.joints
        ):
            raise ConfigError("this example assumes counts increasing toward open")

    def step(self, action: np.ndarray, ctx: StepContext) -> np.ndarray:
        observed_state = ctx.observation["observation.state"]
        left = ctx.observation["observation.images.digit_left"]
        right = ctx.observation["observation.images.digit_right"]
        # Mock demonstration only: replace with your validated tactile detector.
        allow = (
            bool(np.isfinite(observed_state).all())
            and max(float(left.mean()), float(right.mean())) < self.max_image_mean
        )
        for joint in self.joints:
            if joint not in ctx.names:
                continue
            i = ctx.index(joint)
            if not allow and action[i] > ctx.state[i]:
                action[i] = ctx.held[i]
        ctx.note(allow_release=allow)
        return action


def make(joints: Sequence[str], max_image_mean: float = 80) -> ReleaseGate:
    return ReleaseGate(joints, max_image_mean)
```

## 2. Claim writes in YAML { #configure }

robot configuration で両方の DIGIT sensor を有効にし，policy node に hook を追加します．`observe` key は follower または node の `observe:` にある source の feature に限ります．policy だけで使う場合は `sources` を `[policy]` に狭め，`teleop:` を省略できます．

```yaml
# Add to nodes/policy_teleop.yaml (its teleop: controllers stay configured).
observe: [camera, digit_left, digit_right]
hooks:
  - factory: release_gate:make
    kwargs:
      joints: [follower.r_arm_grip, follower.l_arm_grip]
      max_image_mean: 80
    writes: [follower.r_arm_grip, follower.l_arm_grip]
    sources: [policy, teleop]
    on_error: hold
    budget_ms: 3
    name: release_gate
```

## 3. Contribute a hook from a policy { #policy-hooks }

任意の `policy.hooks() -> Sequence[Hook]` は `policy.bind(spec)` の後で呼ばれます．`Hook` instance を返します．書き込む hook には以下の YAML claim が必須です．省略すると load を拒否し，追加する entry の 2 行を表示します．policy の hook はこの slot に入ります．slot がない observe-only の hook は先頭に入ります．

```yaml
hooks:
  - from: policy
    writes: [follower.r_arm_grip, follower.l_arm_grip]
```

## 4. Check the mock run { #verify }

1. `roboloom validate <robot> --with policy --with policy_teleop --mock` で configuration を確かめます．
2. mock の policy episode を起動し，takeover と handback を試します．step は episode 中だけです．通常の joint teleop/record node では無効です．
3. `hook_ms`，`hook_max_ms`，`hook_errors`，`hook_over`，`filtered` と，episode-end log の hook 別 `ms`，`max_ms`，`errors`，`over`，`changed`，`notes` を確かめます．
4. dataset の `action.filtered` を確かめます．float32 `[1]` で，行内の全 command/follower の OR です．YAML に空でない hook `writes` がある場合だけ column が存在します．

[configuration table](../reference/configuration/policy.md#hooks)，[Python API](../reference/python-api/policy.md#hooks)，[hook の実行位置](../explanation/hooks.md)を参照してください．
