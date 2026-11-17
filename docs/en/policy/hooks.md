# Hooks

<span class="status status--mock">Mock only</span>

A hook is a local extension of a policy node: gate releases, correct residual actions, or observe lifecycle events without changing the policy implementation. Hooks are **mock only**; this example is not a validated tactile detector.

## 1. Write a local hook { #write }

Save this file next to the robot configuration, or in an installed package. The example assumes gripper counts increase toward open. Replace its image-mean condition with a task-specific detector before hardware validation. `step` may return `None` for unchanged input.

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

Enable both DIGIT sensors in the robot configuration, then add the hook to the policy node. `observe` keys must come from followers or the node’s `observe:` sources. For policy-only operation, narrow `sources` to `[policy]` and omit `teleop:`.

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

An optional `policy.hooks() -> Sequence[Hook]` is called after `policy.bind(spec)`. Return your hook instances there. A writing contribution requires the explicit YAML claim below; missing claims refuse loading and print these two entry lines. Contributions occupy that slot; without it, observe-only contributions go first.

```yaml
hooks:
  - from: policy
    writes: [follower.r_arm_grip, follower.l_arm_grip]
```

## 4. Check the mock run { #verify }

1. Validate the configuration with `roboloom validate <robot> --with policy --with policy_teleop --mock`.
2. Launch a mock policy episode and try takeover and handback. Steps run only during an episode; plain joint teleop/record nodes keep hooks disabled.
3. Inspect `hook_ms`, `hook_max_ms`, `hook_errors`, `hook_over`, `filtered` and the per-hook episode-end log (`ms`, `max_ms`, `errors`, `over`, `changed`, `notes`).
4. Check `action.filtered` in the dataset. It is float32 `[1]`, OR over all commands/followers in a row, and exists only when YAML has nonempty hook `writes`.

See [configuration tables](../reference/configuration/policy.md#hooks), [Python API](../reference/python-api/policy.md#hooks), and [where hooks run](../explanation/hooks.md).
