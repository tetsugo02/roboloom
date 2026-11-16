# Policy

!!! note "Status: hardware-verified"
    <span class="status status--verified">Hardware-verified</span> Policy inference and interventions (`policy`, `policy_teleop`) are checked on the real Rakuda2. Asynchronous inference, replaying a recording and a policy in another process are <span class="status status--mock">Mock only</span>.

A `type: policy` controller turns a learned policy's actions into follower targets. The policy is an object with `reset()` and `infer(observation)`: it gets the same observation as the recording and returns absolute joint targets. The controller takes care of the rate, interpolation, speed limits and safety checks.

```yaml
# nodes/policy.yaml (excerpt)
type: policy
followers: [follower]
factory: roboloom.policy:hold  # "module:callable"
observe: [camera]
rate_hz: 15
action_horizon: 8
```

```bash
uv run roboloom infer --seconds 20 --policy my_lab.policies:load
```

With `teleop:`, the leader can drive the follower before and during an episode ([Teleoperation and interventions](../policy/intervention.md)).

## Supported robots { #supported-robots }

| Robot | Options | Status | Example |
| --- | --- | --- | --- |
| Rakuda2 | `policy`, `policy_teleop` | <span class="status status--verified">Hardware-verified</span> | [Rakuda2 controllers](../robots/rakuda2/controllers.md#policy) |
| PiPER + Pika Gripper | `policy` | <span class="status status--dev">In development</span> | [PiPER controllers](../robots/piper/controllers.md#policy) |
| Your own robot | depends on the configuration | <span class="status status--mock">Mock only</span> | [Adding your own robot](../tutorials/own-robot.md) |

## In detail { #details }

How to write a policy, LeRobot policies, rates and interpolation, and evaluation are in the [Policies and inference](../policy/index.md) chapter. The keys are listed in [Policy configuration](../reference/configuration/policy.md).
